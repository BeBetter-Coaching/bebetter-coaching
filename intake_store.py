"""Gedeelde opslag — GitHub-backed (privé repo) met lokale fallback.

Op Streamlit Cloud is het bestandssysteem vluchtig: bij elke redeploy
verdwijnen lokale bestanden. Daarom wordt alle gedeelde/persistente data
opgeslagen in de privé repo BeBetter-Coaching/bebetter-data via de
GitHub API. Lokaal (zonder GH_TOKEN) wordt een JSON-bestand naast de
app gebruikt.

Stores:
  intakes.json        — intake per atleet
  on_hold.json        — atleten op hold
  skipped.json        — overgeslagen feedback-workouts
  builder_state.json  — half afgemaakt schema in de builder
"""

from __future__ import annotations

import base64
import json
import os

import requests

_REPO = "BeBetter-Coaching/bebetter-data"
_BASE_DIR = os.path.dirname(__file__)


def _gh_token() -> str:
    """GitHub token uit Streamlit secrets of omgevingsvariabele."""
    try:
        import streamlit as st
        token = st.secrets.get("GH_TOKEN", "")
        if token:
            return token.strip()
    except Exception:
        pass
    return os.environ.get("GH_TOKEN", "").strip()


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


def _api_url(file_path: str) -> str:
    return f"https://api.github.com/repos/{_REPO}/contents/{file_path}"


def _load_json(file_path: str, local_file: str) -> dict:
    """Laad een JSON-dict uit GitHub, met lokale fallback. Leeg = {}."""
    token = _gh_token()
    if token:
        try:
            resp = requests.get(_api_url(file_path), headers=_gh_headers(token), timeout=10)
            if resp.status_code == 200:
                content = base64.b64decode(resp.json()["content"]).decode("utf-8")
                return json.loads(content)
            if resp.status_code == 404:
                return {}  # bestand bestaat nog niet
        except Exception:
            pass
    try:
        if os.path.exists(local_file):
            with open(local_file) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_json(file_path: str, local_file: str, data: dict, message: str) -> tuple[bool, str]:
    """Sla een JSON-dict op in GitHub, met lokale fallback. Geeft (gelukt, fout)."""
    payload_json = json.dumps(data, ensure_ascii=False, indent=2)

    token = _gh_token()
    if token:
        try:
            # Huidige SHA ophalen (nodig voor update van bestaand bestand)
            sha = None
            resp = requests.get(_api_url(file_path), headers=_gh_headers(token), timeout=10)
            if resp.status_code == 200:
                sha = resp.json().get("sha")

            body = {
                "message": message,
                "content": base64.b64encode(payload_json.encode("utf-8")).decode("ascii"),
            }
            if sha:
                body["sha"] = sha

            put = requests.put(_api_url(file_path), headers=_gh_headers(token), json=body, timeout=15)
            if put.status_code in (200, 201):
                return True, ""
            return False, f"GitHub API: {put.status_code} — {put.text[:200]}"
        except Exception as e:
            return False, str(e)

    # Lokale fallback
    try:
        with open(local_file, "w") as f:
            f.write(payload_json)
        return True, ""
    except Exception as e:
        return False, str(e)


def is_cloud_backed() -> bool:
    """True als data in GitHub wordt opgeslagen (permanent)."""
    return bool(_gh_token())


# ---------------------------------------------------------------------------
# Intakes
# ---------------------------------------------------------------------------

_INTAKES_LOCAL = os.path.join(_BASE_DIR, ".intakes.json")


def load_intakes() -> dict:
    """Laad alle intakes. Dict: athlete_key → intake-dict."""
    return _load_json("intakes.json", _INTAKES_LOCAL)


def save_intakes(intakes: dict) -> tuple[bool, str]:
    """Sla alle intakes op. Geeft (gelukt, foutmelding) terug."""
    return _save_json("intakes.json", _INTAKES_LOCAL, intakes, "Update intakes via app")


# ---------------------------------------------------------------------------
# On-hold
# ---------------------------------------------------------------------------

_ON_HOLD_LOCAL = os.path.join(_BASE_DIR, ".on_hold.json")


def load_on_hold() -> dict:
    """Laad on-hold atleten. Dict: user_key → {naam, reden, since}."""
    return _load_json("on_hold.json", _ON_HOLD_LOCAL)


def save_on_hold(on_hold: dict) -> tuple[bool, str]:
    """Sla on-hold atleten op. Geeft (gelukt, foutmelding) terug."""
    return _save_json("on_hold.json", _ON_HOLD_LOCAL, on_hold, "Update on_hold via app")


# ---------------------------------------------------------------------------
# Overgeslagen feedback-workouts
# ---------------------------------------------------------------------------

_SKIPPED_LOCAL = os.path.join(_BASE_DIR, ".feedback_skipped.json")


def load_skipped() -> dict:
    """Laad overgeslagen workouts. Dict: workout_key → skip-datum (ISO)."""
    return _load_json("skipped.json", _SKIPPED_LOCAL)


def save_skipped(skipped: dict) -> tuple[bool, str]:
    """Sla overgeslagen workouts op. Geeft (gelukt, foutmelding) terug."""
    return _save_json("skipped.json", _SKIPPED_LOCAL, skipped, "Update skipped via app")


# ---------------------------------------------------------------------------
# Coach-notities per atleet
# ---------------------------------------------------------------------------

_NOTES_LOCAL = os.path.join(_BASE_DIR, ".notes.json")


def load_notes() -> dict:
    """Laad coach-notities. Dict: user_key → lijst van {datum, coach, tekst}."""
    return _load_json("notes.json", _NOTES_LOCAL)


def save_notes(notes: dict) -> tuple[bool, str]:
    """Sla coach-notities op. Geeft (gelukt, foutmelding) terug."""
    return _save_json("notes.json", _NOTES_LOCAL, notes, "Update notes via app")


# ---------------------------------------------------------------------------
# Builder-state (half afgemaakt schema)
# ---------------------------------------------------------------------------

_BUILDER_LOCAL = os.path.join(_BASE_DIR, ".builder_state.json")


def load_builder_state() -> dict:
    """Laad de opgeslagen builder-state. Leeg dict = geen opgeslagen schema."""
    return _load_json("builder_state.json", _BUILDER_LOCAL)


def save_builder_state(state: dict) -> tuple[bool, str]:
    """Sla de builder-state op. Geeft (gelukt, foutmelding) terug."""
    return _save_json("builder_state.json", _BUILDER_LOCAL, state, "Update builder_state via app")


def clear_builder_state() -> tuple[bool, str]:
    """Wis de opgeslagen builder-state."""
    return _save_json("builder_state.json", _BUILDER_LOCAL, {}, "Reset builder_state via app")
