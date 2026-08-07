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
import os
import secrets
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import strippen_core as core
import dossier_core as dossier
import intake_core as intake
import documenten_core as docs

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "static")

app = FastAPI(title="BeBetter PWA (proto)")


# ── Simpel inlogslot (gedeeld wachtwoord voor Jip & Remco) ──────────────────
# Actief zodra APP_PASSWORD als omgevingsvariabele is gezet (op de hosting).
# Lokaal (geen APP_PASSWORD) staat het uit, zodat ontwikkelen frictieloos blijft.
_APP_USER = os.environ.get("APP_USER", "bebetter")
_APP_PASSWORD = os.environ.get("APP_PASSWORD", "")


def _is_public(path: str) -> bool:
    """Paden die de klant zonder login moet kunnen bereiken.

    Het publieke intakeformulier (klant vult in, installeert niets) plus de
    statische assets die het nodig heeft. De token in de link beschermt het
    formulier tegen willekeurige bezoekers; er staat geen coach-data achter.
    """
    if path in ("/manifest.webmanifest", "/sw.js", "/healthz"):
        return True
    return (path == "/intake"
            or path.startswith("/api/intake/public")
            or path.startswith("/static/"))


@app.middleware("http")
async def _login(request, call_next):
    if _APP_PASSWORD and not _is_public(request.url.path):
        hdr = request.headers.get("authorization", "")
        ok = False
        if hdr.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(hdr[6:]).decode("utf-8").partition(":")
                ok = (secrets.compare_digest(user, _APP_USER)
                      and secrets.compare_digest(pw, _APP_PASSWORD))
            except Exception:
                ok = False
        if not ok:
            return Response("Inloggen vereist.", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="BeBetter Coaching"'})
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
