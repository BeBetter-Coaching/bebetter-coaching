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
import feedback_core as feedback
import schema_core
import races_core as races
import schema_verloop_core as schema_verloop
import teampuls_core as teampuls
import admin_core
import home_core
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
# Twee coaches, gedeeld wachtwoord (voorlopig). Je kiest wie je bent i.p.v. een
# gebruikersnaam te typen; de sessie onthoudt het, zodat acties toegeschreven
# kunnen worden (bv. wie welke notitie schreef).
_COACHES = ["Jip", "Remco"]


def _b64nopad(raw: bytes) -> str:
    # GEEN '=' opvulling: anders wordt de cookie-waarde gequote en verhaspelen
    # sommige clients (o.a. geïnstalleerde iOS-PWA's) 'm → sessie niet herkend.
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64nopad(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign_session(user: str) -> str:
    body = _b64nopad(json.dumps({"u": user, "exp": time.time() + _SESSION_DAGEN * 86400}).encode())
    sig = hmac.new(_SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _valid_session(token: str) -> bool:
    try:
        body, sig = token.rsplit(".", 1)
        verwacht = hmac.new(_SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, verwacht):
            return False
        data = json.loads(_unb64nopad(body))
        return float(data.get("exp", 0)) > time.time()
    except Exception:
        return False


def _token_of(request: Request) -> str:
    """Sessie-token uit de Authorization-header (robuust in geïnstalleerde iOS-PWA's,
    waar cookies onbetrouwbaar bewaard worden) of anders uit de cookie (browser)."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get(_COOKIE, "")


def _session_user(request: Request):
    """Welke coach is ingelogd (uit de geldige sessie), of None."""
    token = _token_of(request)
    if not _valid_session(token):
        return None
    try:
        return json.loads(_unb64nopad(token.rsplit(".", 1)[0])).get("u")
    except Exception:
        return None


def _is_public(path: str) -> bool:
    """Paden zonder login: de app-schil zelf (het inlogscherm zit erín), het
    publieke intakeformulier + assets, de login-API en health/manifest/sw."""
    if path in ("/", "/manifest.webmanifest", "/sw.js", "/healthz",
                "/api/login", "/api/me", "/api/coaches", "/api/webauthn/available",
                "/api/webauthn/auth/options", "/api/webauthn/auth/verify"):
        return True
    return (path == "/intake"
            or path.startswith("/api/intake/public")
            or path.startswith("/static/"))


@app.middleware("http")
async def _login(request: Request, call_next):
    if _APP_PASSWORD and not _is_public(request.url.path):
        if not _valid_session(_token_of(request)):
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
    wie: str = ""
    password: str = ""


def _login_resp(wie: str):
    token = _sign_session(wie)
    # token ook in de body: de app bewaart 'm in localStorage en stuurt 'm als
    # Authorization-header mee (cookie blijft voor browser-gebruik).
    resp = JSONResponse({"ok": True, "wie": wie, "token": token})
    resp.set_cookie(_COOKIE, token, max_age=_SESSION_DAGEN * 86400,
                    httponly=True, secure=True, samesite="lax", path="/")
    return resp


@app.get("/api/coaches")
def api_coaches():
    """De keuze-knoppen op het inlogscherm (publiek)."""
    return {"coaches": _COACHES}


@app.get("/api/me")
def api_me(request: Request):
    """Ingelogd? En als wie? Het inlogscherm/app checkt dit bij het opstarten."""
    if not _APP_PASSWORD:                                   # lokaal: geen slot
        return {"ingelogd": True, "wie": ""}
    wie = _session_user(request)
    return {"ingelogd": bool(wie), "wie": wie or ""}


@app.post("/api/login")
def api_login(body: Login):
    if not _APP_PASSWORD:                                   # lokaal: geen slot
        return _login_resp(body.wie or _COACHES[0])
    if body.wie in _COACHES and secrets.compare_digest(body.password or "", _APP_PASSWORD):
        return _login_resp(body.wie)
    return JSONResponse({"ok": False, "err": "Onjuist wachtwoord."}, status_code=401)


@app.post("/api/logout")
def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(_COOKIE, path="/")
    return resp


# ── Face ID / passkeys (WebAuthn) — additief; wachtwoord blijft de fallback ──
_WA_CHAL = "bb_wa_chal"


def _sign_chal(chal_b64: str, wie: str) -> str:
    body = _b64nopad(json.dumps({"c": chal_b64, "w": wie, "exp": time.time() + 300}).encode())
    sig = hmac.new(_SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _read_chal(token: str):
    """(challenge_bytes, wie) of (None, None)."""
    try:
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(_SESSION_SECRET, body.encode(), hashlib.sha256).hexdigest()):
            return None, None
        data = json.loads(_unb64nopad(body))
        if float(data.get("exp", 0)) < time.time():
            return None, None
        return _unb64nopad(data["c"]), data.get("w", "")
    except Exception:
        return None, None


def _wa_ctx(request: Request):
    host = request.headers.get("host", "")
    return webauthn_core.rp_id_from_host(host), f"https://{host}"


def _chal_cookie(resp, chal: bytes, wie: str):
    b64 = base64.urlsafe_b64encode(chal).decode().rstrip("=")
    resp.set_cookie(_WA_CHAL, _sign_chal(b64, wie), max_age=300,
                    httponly=True, secure=True, samesite="lax", path="/")


@app.get("/api/webauthn/available")
def wa_available(wie: str = ""):
    """Heeft deze coach een passkey? (Login-scherm toont dan de biometrie-knop.)"""
    return {"aan": bool(_APP_PASSWORD) and wie in _COACHES and webauthn_core.has_credentials(wie)}


@app.post("/api/webauthn/register/options")     # vereist login (biometrie inschakelen)
def wa_reg_opts(request: Request):
    wie = _session_user(request)
    if wie not in _COACHES:
        return JSONResponse({"ok": False, "err": "Niet ingelogd."}, status_code=401)
    rp_id, _ = _wa_ctx(request)
    try:
        opts_json, chal = webauthn_core.registration_options(wie, rp_id)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Biometrie niet beschikbaar: {e}"}, status_code=500)
    resp = Response(opts_json, media_type="application/json")
    _chal_cookie(resp, chal, wie)
    return resp


@app.post("/api/webauthn/register/verify")      # vereist login
async def wa_reg_verify(request: Request):
    chal, wie = _read_chal(request.cookies.get(_WA_CHAL, ""))
    if not chal or wie != _session_user(request):
        return JSONResponse({"ok": False, "err": "Verlopen, probeer opnieuw."}, status_code=400)
    rp_id, origin = _wa_ctx(request)
    try:
        ok = webauthn_core.verify_registration(wie, await request.json(), chal, rp_id, origin)
    except Exception as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    return {"ok": ok}


@app.post("/api/webauthn/auth/options")         # PUBLIEK (ontgrendelen vóór login)
def wa_auth_opts(request: Request, wie: str = ""):
    if wie not in _COACHES or not webauthn_core.has_credentials(wie):
        return JSONResponse({"ok": False, "err": "Geen passkey op dit account."}, status_code=404)
    rp_id, _ = _wa_ctx(request)
    try:
        opts_json, chal = webauthn_core.authentication_options(wie, rp_id)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Biometrie niet beschikbaar: {e}"}, status_code=500)
    resp = Response(opts_json, media_type="application/json")
    _chal_cookie(resp, chal, wie)
    return resp


@app.post("/api/webauthn/auth/verify")          # PUBLIEK — bij succes: sessie-cookie
async def wa_auth_verify(request: Request):
    chal, wie = _read_chal(request.cookies.get(_WA_CHAL, ""))
    if not chal or wie not in _COACHES:
        return JSONResponse({"ok": False, "err": "Verlopen, probeer opnieuw."}, status_code=400)
    rp_id, origin = _wa_ctx(request)
    try:
        ok = webauthn_core.verify_authentication(wie, await request.json(), chal, rp_id, origin)
    except Exception as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    if not ok:
        return JSONResponse({"ok": False, "err": "Ontgrendelen mislukt."}, status_code=401)
    resp = _login_resp(wie)
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


# ── API: feedback (AI-concept op trainingen; FinalSurge + Anthropic) ─────────
class FeedbackGen(BaseModel):
    id: str = ""
    tekst: str = ""


@app.get("/api/feedback")
def feedback_lijst(dagen: int = 7):
    return feedback.te_beoordelen(days_back=dagen)


@app.get("/api/feedback/queue")          # lichte gecachete inbox-queue (stale-while-revalidate)
def feedback_queue(refresh: bool = False):
    # Server-Timing: laat de client (Feedback-debuglog) de servertijd afsplitsen
    # van de netwerktijd — zo weten we waar de refresh-latency zit.
    t0 = time.perf_counter()
    data = feedback.queue(refresh=refresh)
    dur = int((time.perf_counter() - t0) * 1000)
    return JSONResponse(data, headers={"Server-Timing": f"queue;dur={dur}"})


@app.get("/api/home/stats")
def home_stats(refresh: bool = False):
    """Home-cockpit: team-status, feedback-voortgang, info én de Prioriteit-
    vandaag-lijst. Standaard uit de opgeslagen snapshot (direct); refresh=1
    herberekent op de achtergrond + werkt de snapshot bij (stale-while-revalidate)."""
    return home_core.cockpit(refresh=refresh)


class HomeHandled(BaseModel):
    user_key: str = ""
    status: str = "gezien"        # "gezien" | "later"
    snooze_dagen: int = 7
    undo: bool = False
    soort: Optional[str] = None   # None = bulk (alle signalen); anders één signaaltype


@app.post("/api/home/handled")           # werklijst-status (Gezien/Later), per atleet of per signaal
def home_handled(body: HomeHandled, request: Request):
    wie = _session_user(request) or ""
    ok, msg = home_core.handled(body.user_key, status=body.status,
                                snooze_dagen=body.snooze_dagen, undo=body.undo,
                                by=wie, soort=body.soort)
    if not ok:
        return JSONResponse({"ok": False, "err": msg}, status_code=500)
    return {"ok": True}


@app.get("/api/home/prio/{user_key}/trainingen")   # lazy: gemiste sessies van één afhaker
def home_prio_trainingen(user_key: str):
    return home_core.prio_trainingen(user_key)


@app.post("/api/feedback/generate")
def feedback_gen(body: FeedbackGen):
    try:
        tekst = feedback.genereer(body.id)
    except ValueError as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Genereren mislukt: {e}"}, status_code=500)
    return {"ok": True, "tekst": tekst}


@app.post("/api/feedback/post")          # WRITE: post de reactie in FinalSurge
def feedback_post(body: FeedbackGen):
    try:
        feedback.plaats(body.id, body.tekst)
    except ValueError as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Posten mislukt: {e}"}, status_code=500)
    return {"ok": True}


@app.get("/api/feedback/thread")         # volledige conversatie (atleet + coach)
def feedback_thread(id: str = ""):
    try:
        return {"ok": True, "thread": feedback.thread(id)}
    except ValueError as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=500)


@app.post("/api/feedback/skip")          # overslaan (tot de atleet weer reageert)
def feedback_skip(body: FeedbackGen):
    try:
        feedback.overslaan(body.id)
    except ValueError as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Overslaan mislukt: {e}"}, status_code=500)
    return {"ok": True}


# NB: deze pad-parameter-route staat BEWUST ná /queue, /generate, /post, /thread,
# /skip zodat die literals niet als workout_key worden opgevat.
@app.get("/api/feedback/{workout_key}")  # lazy focus-detail (samenvatting/zones/afwijking)
def feedback_detail(workout_key: str):
    t0 = time.perf_counter()
    data = feedback.detail(workout_key)
    dur = int((time.perf_counter() - t0) * 1000)
    return JSONResponse(data, headers={"Server-Timing": f"detail;dur={dur}"})


# ── API: races (aankomende races + race-wens posten) ──────────────────────────
class RaceWens(BaseModel):
    id: str = ""
    tekst: str = ""


@app.get("/api/races")
def races_lijst(dagen: int = 42):
    return races.komende(days_ahead=dagen)


@app.post("/api/races/wens")             # WRITE: plaats race-wens als coach-comment
def races_wens(body: RaceWens):
    try:
        races.plaats_wens(body.id, body.tekst)
    except ValueError as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Posten mislukt: {e}"}, status_code=500)
    return {"ok": True}


# ── API: schema-verloop (wie loopt bijna af — puur lezend) ─────────────────────
@app.get("/api/schema-verloop")
def schema_verloop_lijst(horizon: int = 60):
    return schema_verloop.verloop(horizon_days=horizon)


# ── API: teampuls (belasting-signalen + AI-weekbriefing) ───────────────────────
class PulsGezien(BaseModel):
    user_key: str = ""
    ernst: str = ""
    undo: bool = False


@app.get("/api/teampuls/signalen")
def teampuls_signalen(force: bool = False):
    return teampuls.signalen(force=force)


@app.post("/api/teampuls/gezien")        # demp een atleet 7 dagen (gedeeld)
def teampuls_gezien(body: PulsGezien):
    try:
        teampuls.markeer_gezien(body.user_key, body.ernst, undo=body.undo)
    except Exception as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=500)
    return {"ok": True}


@app.get("/api/teampuls/briefing")
def teampuls_briefing(force: bool = False):
    return teampuls.briefing(force=force)


# ── API: administratie (financiële cockpit — pincode, puur lezend) ─────────────
class AdminPin(BaseModel):
    pin: str = ""


@app.get("/api/admin/status")
def admin_status():
    return admin_core.status()


@app.post("/api/admin/overzicht")
def admin_overzicht(body: AdminPin):
    try:
        data = admin_core.overzicht(body.pin)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Cockpit laden mislukt: {e}"}, status_code=500)
    if not data.get("ok"):
        return JSONResponse({"ok": False, "err": "pin"}, status_code=403)
    return data


# ── API: schema bouwen (intake -> AI-plan -> CSV; Anthropic + gedeelde intake) ─
class SchemaGen(BaseModel):
    key: str = ""
    plan: str = ""
    csv: str = ""


@app.get("/api/schema/atleten")
def schema_atleten():
    return {"atleten": schema_core.bouwbare_atleten(), "ai": schema_core.heeft_key()}


@app.post("/api/schema/plan")
def schema_plan(body: SchemaGen):
    try:
        plan = schema_core.genereer_plan(body.key)
    except ValueError as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Plan mislukt: {e}"}, status_code=500)
    return {"ok": True, "plan": plan}


@app.post("/api/schema/csv")
def schema_csv(body: SchemaGen):
    try:
        csv_tekst, rijen = schema_core.genereer_csv(body.key, body.plan)
    except ValueError as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"CSV mislukt: {e}"}, status_code=500)
    return {"ok": True, "csv": csv_tekst, "rijen": rijen}


@app.post("/api/schema/push")            # WRITE: zet de trainingen op de FS-kalender
def schema_push(body: SchemaGen):
    try:
        res = schema_core.push(body.key, body.csv)
    except ValueError as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "err": f"Pushen mislukt: {e}"}, status_code=500)
    return {"ok": True, **res}


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
