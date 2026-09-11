"""/healthz draagt een buildmarker (11 sep 2026).

`build` is de commit van de draaiende release (Render: RENDER_GIT_COMMIT), zodat een
server-only release van buiten te verifiëren is. Het contract `ok: true` blijft staan.

    python3 -m pytest tests/test_healthz_build.py -q
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

from fastapi.testclient import TestClient              # noqa: E402

import api                                              # noqa: E402

_SHA = "11802a3f0c9d8e7b6a5f4e3d2c1b0a9f8e7d6c5b"


def _healthz():
    r = TestClient(api.app).get("/healthz")
    assert r.status_code == 200
    return r.json()


def test_ok_blijft_true_en_build_bestaat(monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    body = _healthz()
    assert body["ok"] is True and "build" in body


def test_met_commit_env_exact_die_waarde(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", _SHA)
    assert _healthz() == {"ok": True, "build": _SHA}


def test_zonder_commit_env_unknown(monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    assert _healthz()["build"] == "unknown"
    monkeypatch.setenv("RENDER_GIT_COMMIT", "  ")
    assert _healthz()["build"] == "unknown"


def test_publiek_ook_met_login_aan(monkeypatch):
    # Render's healthcheck en een externe controle hebben geen sessie.
    monkeypatch.setattr(api, "_APP_PASSWORD", "geheim")
    monkeypatch.setenv("RENDER_GIT_COMMIT", _SHA)
    assert _healthz()["build"] == _SHA
