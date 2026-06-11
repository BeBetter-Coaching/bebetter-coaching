"""Intake-opslag — GitHub-backed (privé repo) met lokale fallback.

Op Streamlit Cloud is het bestandssysteem vluchtig: bij elke redeploy
verdwijnen lokale bestanden. Daarom worden intakes opgeslagen in de
privé repo BeBetter-Coaching/bebetter-data via de GitHub API.
Lokaal (zonder GH_TOKEN) wordt een JSON-bestand naast de app gebruikt.
"""

import base64
import json
import os

import requests

_REPO = "BeBetter-Coaching/bebetter-data"
_FILE_PATH = "intakes.json"
_API_URL = f"https://api.github.com/repos/{_REPO}/contents/{_FILE_PATH}"
_LOCAL_FILE = os.path.join(os.path.dirname(__file__), ".intakes.json")


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


def load_intakes() -> dict:
    """Laad alle intakes. Dict: athlete_key → intake-dict."""
    token = _gh_token()
    if token:
        try:
            resp = requests.get(_API_URL, headers=_gh_headers(token), timeout=10)
            if resp.status_code == 200:
                content = base64.b64decode(resp.json()["content"]).decode("utf-8")
                return json.loads(content)
            if resp.status_code == 404:
                return {}  # bestand bestaat nog niet
        except Exception:
            pass
    # Lokale fallback
    try:
        if os.path.exists(_LOCAL_FILE):
            with open(_LOCAL_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_intakes(intakes: dict) -> tuple[bool, str]:
    """Sla alle intakes op. Geeft (gelukt, foutmelding) terug."""
    payload_json = json.dumps(intakes, ensure_ascii=False, indent=2)

    token = _gh_token()
    if token:
        try:
            # Huidige SHA ophalen (nodig voor update)
            sha = None
            resp = requests.get(_API_URL, headers=_gh_headers(token), timeout=10)
            if resp.status_code == 200:
                sha = resp.json().get("sha")

            body = {
                "message": "Update intakes via app",
                "content": base64.b64encode(payload_json.encode("utf-8")).decode("ascii"),
            }
            if sha:
                body["sha"] = sha

            put = requests.put(_API_URL, headers=_gh_headers(token), json=body, timeout=15)
            if put.status_code in (200, 201):
                return True, ""
            return False, f"GitHub API: {put.status_code} — {put.text[:200]}"
        except Exception as e:
            return False, str(e)

    # Lokale fallback
    try:
        with open(_LOCAL_FILE, "w") as f:
            f.write(payload_json)
        return True, ""
    except Exception as e:
        return False, str(e)


def is_cloud_backed() -> bool:
    """True als intakes in GitHub worden opgeslagen (permanent)."""
    return bool(_gh_token())
