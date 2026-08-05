"""BeBetter PWA — proto-backend (FastAPI) voor de strippenkaart.

Serveert de PWA-frontend (static/) en een kleine JSON-API die op DEZELFDE
opslag werkt als de Streamlit-app (via strippen_core -> intake_store). Zo zie je
een wijziging in de app terug in Streamlit en andersom: één bron, twee voordeuren.

Lokaal draaien:
    cd pwa
    python3 -m pip install -r requirements.txt
    uvicorn api:app --reload --port 8000
Open daarna http://localhost:8000
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import strippen_core as core

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC = os.path.join(_HERE, "static")

app = FastAPI(title="BeBetter PWA (proto)")


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


# ── API ─────────────────────────────────────────────────────────────────────
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


# ── PWA-shell + static ──────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(os.path.join(_STATIC, "index.html"))


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(os.path.join(_STATIC, "manifest.webmanifest"),
                        media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    # service worker moet vanaf de root geserveerd worden om de hele app te dekken
    return FileResponse(os.path.join(_STATIC, "sw.js"), media_type="application/javascript")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
