"""BeBetter PWA — proto-backend (FastAPI) voor de strippenkaart.

Serveert de PWA-frontend (static/) en een kleine JSON-API die op DEZELFDE
opslag werkt als de Streamlit-app (via strippen_core -> intake_store). Zo zie je
een wijziging in de app terug in Streamlit en andersom: één bron, twee voordeuren.

Lokaal draaien:
    cd pwa
    python3 -m pip install -r requirements.txt
    python3 -m uvicorn api:app --reload --port 8000
Open daarna http://localhost:8000
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import strippen_core as core
import dossier_core as dossier
import intake_core as intake
import documenten_core as docs
import atleten_core as atleten
import webauthn_core

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "static")

app = FastAPI(title="BeBetter PWA (proto)")


# ── Inlog: eigen sessie-cookie i.p.v. de lelijke HTTP Basic-popup ───────────
# Actief zodra APP_PASSWORD als omgevingsvariabele staat (op de hosting). Na
# inloggen zetten we een ondertekende cookie (~90 dagen), zodat je NIET na elke
# update opnieuw hoeft in te loggen. De app toont een eigen (mooi) inlogscherm;
# geen browser-popup meer. Lokaal (geen APP_PASSWORD) staat het slot uit.
_APP_USER = os.environ.get("APP_USER", "bebetter")
_APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
_SESSION_SECRET = (os.environ.get("SESSION_SECRET") or _APP_PASSWORD or "dev-secret").encode()
_SESSION_DAGEN = 90
_COOKIE = "bb_session"


def _sign_session(user: str) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps({"u": user, "exp": time.time() + _SESSION_DAGEN * 86400}).encode()
    ).decode()
    sig = hmac.new(_SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _valid_session(token: str) -> bool:
    try:
        body, sig = token.rsplit(".", 1)
        verwacht = hmac.new(_SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, verwacht):
            return False
        data = json.loads(base64.urlsafe_b64decode(body))
        return float(data.get("exp", 0)) > time.time()
    except Exception:
        return False


def _is_public(path: str) -> bool:
    """Paden zonder login: de app-schil zelf (het inlogscherm zit erín), het
    publieke intakeformulier + assets, de login-API en health/manifest/sw."""
    if path in ("/", "/manifest.webmanifest", "/sw.js", "/healthz",
                "/api/login", "/api/me", "/api/webauthn/available",
                "/api/webauthn/auth/options", "/api/webauthn/auth/verify"):
        return True
    return (path == "/intake"
            or path.startswith("/api/intake/public")
            or path.startswith("/static/"))


@app.middleware("http")
async def _login(request: Request, call_next):
    if _APP_PASSWORD and not _is_public(request.url.path):
        if not _valid_session(request.cookies.get(_COOKIE, "")):
            # Geen browser-popup meer: nette 401; de app toont zelf het inlogscherm.
            return JSONResponse({"err": "auth"}, status_code=401)
    return await call_next(request)


# ── Verzoek-modellen ────────────────────────────────────────────────────────
class NieuweKaart(BaseModel):
    naam: str
    aantal: int = 10
    telefoon: str = ""


class ImportText(BaseModel):
    text: str = ""


class ImportCommit(BaseModel):
    rows: list[dict] = []
    aantal: int = 10


class Notitie(BaseModel):
    coach: str = "Coach"
    tekst: str = ""


class Profiel(BaseModel):
    tekst: str = ""


class PubliekeIntake(BaseModel):
    token: str = ""
    resume: str = ""
    velden: dict = {}


class DocGen(BaseModel):
    slug: str = ""
    user_key: Optional[str] = None
    answers: dict = {}


# ── Health: lichtgewicht, geen login, geen data — houdt Render Free wakker ───
@app.get("/healthz")
def healthz():
    return {"ok": True}


# ── Inlog-API (eigen scherm; zet/leest de sessie-cookie) ────────────────────
class Login(BaseModel):
    user: str = ""
    password: str = ""


@app.get("/api/me")
def api_me(request: Request):
    """Is er een geldige sessie? Het inlogscherm checkt dit bij het opstarten."""
    ingelogd = (not _APP_PASSWORD) or _valid_session(request.cookies.get(_COOKIE, ""))
    return {"ingelogd": ingelogd}


@app.post("/api/login")
def api_login(body: Login):
    if not _APP_PASSWORD:                                   # lokaal: geen slot
        return {"ok": True}
    ok = (secrets.compare_digest(body.user or "", _APP_USER)
          and secrets.compare_digest(body.password or "", _APP_PASSWORD))
    if not ok:
        return JSONResponse({"ok": False, "err": "Onjuiste gebruikersnaam of wachtwoord."},
                            status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(_COOKIE, _sign_session(body.user), max_age=_SESSION_DAGEN * 86400,
                    httponly=True, secure=True, samesite="lax", path="/")
    return resp


@app.post("/api/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(_COOKIE, path="/")
    return resp


# ── Face ID / passkeys (WebAuthn) — additief; wachtwoord blijft de fallback ──
_WA_CHAL = "bb_wa_chal"


def _sign_chal(chal_b64: str) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps({"c": chal_b64, "exp": time.time() + 300}).encode()).decode()
    sig = hmac.new(_SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _read_chal(token: str):
    try:
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()):
            return None
        data = json.loads(base64.urlsafe_b64decode(body))
        if float(data.get("exp", 0)) < time.time():
            return None
        c = data["c"]
        return base64.urlsafe_b64decode(c + "=" * (-len(c) % 4))
    except Exception:
        return None


def _wa_ctx(request: Request):
    host = request.headers.get("host", "")
    return webauthn_core.rp_id_from_host(host), f"https://{host}"


def _chal_cookie(resp, chal: bytes):
    b64 = base64.urlsafe_b64encode(chal).decode().rstrip("=")
    resp.set_cookie(_WA_CHAL, _sign_chal(b64), max_age=300,
                    httponly=True, secure=True, samesite="lax", path="/")


@app.get("/api/webauthn/available")
def wa_available():
    """Heeft dit account een passkey? (Login-scherm toont dan de Face ID-knop.)"""
    return {"aan": bool(_APP_PASSWORD) and webauthn_core.has_credentials(_APP_USER)}


@app.post("/api/webauthn/register/options")     # vereist login (Face ID inschakelen)
def wa_reg_opts(request: Request):
    rp_id, _ = _wa_ctx(request)
    try:
        opts_json, chal = webauthn_core.registration_options(_APP_USER, rp_id)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Face ID niet beschikbaar: {e}"}, status_code=500)
    resp = Response(opts_json, media_type="application/json")
    _chal_cookie(resp, chal)
    return resp


@app.post("/api/webauthn/register/verify")      # vereist login
async def wa_reg_verify(request: Request):
    chal = _read_chal(request.cookies.get(_WA_CHAL, ""))
    if not chal:
        return JSONResponse({"ok": False, "err": "Verlopen, probeer opnieuw."}, status_code=400)
    rp_id, origin = _wa_ctx(request)
    try:
        ok = webauthn_core.verify_registration(_APP_USER, await request.json(), chal, rp_id, origin)
    except Exception as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    return {"ok": ok}


@app.post("/api/webauthn/auth/options")         # PUBLIEK (ontgrendelen vóór login)
def wa_auth_opts(request: Request):
    if not webauthn_core.has_credentials(_APP_USER):
        return JSONResponse({"ok": False, "err": "Geen passkey op dit account."}, status_code=404)
    rp_id, _ = _wa_ctx(request)
    try:
        opts_json, chal = webauthn_core.authentication_options(_APP_USER, rp_id)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Face ID niet beschikbaar: {e}"}, status_code=500)
    resp = Response(opts_json, media_type="application/json")
    _chal_cookie(resp, chal)
    return resp


@app.post("/api/webauthn/auth/verify")          # PUBLIEK — bij succes: sessie-cookie
async def wa_auth_verify(request: Request):
    chal = _read_chal(request.cookies.get(_WA_CHAL, ""))
    if not chal:
        return JSONResponse({"ok": False, "err": "Verlopen, probeer opnieuw."}, status_code=400)
    rp_id, origin = _wa_ctx(request)
    try:
        ok = webauthn_core.verify_authentication(_APP_USER, await request.json(), chal, rp_id, origin)
    except Exception as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    if not ok:
        return JSONResponse({"ok": False, "err": "Ontgrendelen mislukt."}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(_COOKIE, _sign_session(_APP_USER), max_age=_SESSION_DAGEN * 86400,
                    httponly=True, secure=True, samesite="lax", path="/")
    resp.delete_cookie(_WA_CHAL, path="/")
    return resp


# ── API: documenten (template-PDF's; AI-intro's zodra de key gezet is) ───────
@app.get("/api/docs/templates")
def docs_templates():
    return {"templates": docs.templates(), "ai": docs.heeft_key(), "cloud": docs.cloud_backed()}


@app.post("/api/docs/generate")
def docs_generate(body: DocGen):
    try:
        data, fn = docs.genereer(body.slug, body.answers, body.user_key)
    except ValueError as e:
        return Response(str(e), status_code=400)
    except Exception as e:                                  # AI-fout, ontbrekend bestand, enz.
        return Response(f"Genereren mislukt: {e}", status_code=500)
    from urllib.parse import quote
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fn)}"})


# ── API: atleten (FinalSurge-roster verrijkt met store-data) ─────────────────
@app.get("/api/atleten")
def atleten_lijst():
    return atleten.verenigde_roster()


@app.get("/api/atleten/{ident:path}")
def atleten_detail(ident: str):
    d = atleten.detail(ident)
    if not d:
        return Response("Onbekende atleet.", status_code=404)
    return d


# ── API: strippenkaart ───────────────────────────────────────────────────────
@app.get("/api/kaarten")
def kaarten():
    return {"kaarten": core.list_kaarten(), "cloud": core.cloud_backed()}


@app.post("/api/kaarten")
def nieuwe_kaart(body: NieuweKaart):
    ok, err = core.add_kaart(body.naam, body.aantal, body.telefoon)
    return {"ok": ok, "err": err}


@app.post("/api/kaarten/{naam}/afboeken")
def afboeken(naam: str):
    ok, err, info = core.afboeken(naam)
    return {"ok": ok, "err": err, "info": info}


@app.post("/api/kaarten/{naam}/terug")
def terug(naam: str):
    ok, err = core.terug(naam)
    return {"ok": ok, "err": err}


@app.delete("/api/kaarten/{naam}")
def verwijder(naam: str):
    ok, err = core.verwijder(naam)
    return {"ok": ok, "err": err}


@app.post("/api/import/preview")
def import_preview(body: ImportText):
    return core.import_preview(body.text)


@app.post("/api/import")
def import_commit(body: ImportCommit):
    ok, err, telling = core.import_commit(body.rows, body.aantal)
    return {"ok": ok, "err": err, **telling}


# ── API: dossier (store-only, zelfde data als Streamlit) ─────────────────────
@app.get("/api/dossier/athletes")
def dossier_athletes():
    return {"athletes": dossier.list_athletes(), "cloud": dossier.cloud_backed()}


@app.get("/api/dossier/{key}")
def dossier_detail(key: str):
    d = dossier.get_dossier(key)
    if d is None:
        return {"ok": False, "err": "Onbekende atleet."}
    return {"ok": True, "dossier": d}


@app.post("/api/dossier/{key}/note")
def dossier_add_note(key: str, body: Notitie):
    ok, err = dossier.add_note(key, body.coach, body.tekst)
    return {"ok": ok, "err": err}


@app.delete("/api/dossier/{key}/note/{index}")
def dossier_del_note(key: str, index: int):
    ok, err = dossier.delete_note(key, index)
    return {"ok": ok, "err": err}


@app.post("/api/dossier/{key}/profiel")
def dossier_save_profiel(key: str, body: Profiel):
    ok, err = dossier.save_profiel(key, body.tekst)
    return {"ok": ok, "err": err}


# ── API: intake (coach-inbox, achter login) ──────────────────────────────────
@app.get("/api/intake/link")
def intake_link():
    return {"token": intake.link_token(), "cloud": intake.cloud_backed()}


@app.post("/api/intake/link")
def intake_new_link():
    return {"token": intake.new_link_token()}


@app.get("/api/intake/inbox")
def intake_inbox():
    return {"inbox": intake.inbox_list()}


@app.post("/api/intake/inbox/{iid}/take")
def intake_inbox_take(iid: str):
    ok, err, naam = intake.inbox_take(iid)
    return {"ok": ok, "err": err, "naam": naam}


@app.delete("/api/intake/inbox/{iid}")
def intake_inbox_del(iid: str):
    ok, err = intake.inbox_delete(iid)
    return {"ok": ok, "err": err}


# ── API: intake (publiek, ZONDER login — token beschermt) ────────────────────
@app.get("/api/intake/public/check")
def intake_public_check(token: str = "", resume: str = ""):
    if not intake.token_valid(token):
        return {"ok": False}
    return {"ok": True, "prefill": intake.get_submission(resume) if resume else {}}


@app.post("/api/intake/public/submit")
def intake_public_submit(body: PubliekeIntake):
    if not intake.token_valid(body.token):
        return {"ok": False, "err": "Deze link is niet (meer) geldig. Vraag je coach om een nieuwe."}
    ok, err = intake.public_submit(body.velden, body.resume)
    return {"ok": ok, "err": err}


# ── PWA-shell + static ──────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(os.path.join(_STATIC, "index.html"))


@app.get("/intake")
def publieke_intake():
    # Publiek klantformulier (geen login) — token in de link beschermt.
    return FileResponse(os.path.join(_STATIC, "intake_public.html"))


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(os.path.join(_STATIC, "manifest.webmanifest"),
                        media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    # service worker moet vanaf de root geserveerd worden om de hele app te dekken
    return FileResponse(os.path.join(_STATIC, "sw.js"), media_type="application/javascript")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
