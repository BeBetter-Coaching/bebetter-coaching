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
# Login-tokens ("onthoud mij") — alleen SHA256-hashes, nooit het token zelf
# ---------------------------------------------------------------------------

_AUTH_TOKENS_LOCAL = os.path.join(_BASE_DIR, ".auth_tokens.json")


def load_auth_tokens() -> dict:
    """Laad geldige login-tokens. Dict: sha256(token) → {created}."""
    return _load_json("auth_tokens.json", _AUTH_TOKENS_LOCAL)


def save_auth_tokens(tokens: dict) -> tuple[bool, str]:
    """Sla login-token-hashes op. Lege dict = alle apparaten uitgelogd."""
    return _save_json("auth_tokens.json", _AUTH_TOKENS_LOCAL, tokens,
                      "Update login-tokens via app")


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
# Afgehandelde afhaker-meldingen
# ---------------------------------------------------------------------------

_ALERTS_LOCAL = os.path.join(_BASE_DIR, ".alerts_handled.json")


def load_alerts_handled() -> dict:
    """Afgehandelde afhakers. Dict: user_key → {datum, coach}."""
    return _load_json("alerts_handled.json", _ALERTS_LOCAL)


def save_alerts_handled(handled: dict) -> tuple[bool, str]:
    """Sla afgehandelde afhakers op. Geeft (gelukt, foutmelding) terug."""
    return _save_json("alerts_handled.json", _ALERTS_LOCAL, handled, "Update alerts_handled via app")


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
# Administratie — handmatige klantvelden (status, pakket, coach, cyclus, notitie)
# ---------------------------------------------------------------------------

_ADMIN_LOCAL = os.path.join(_BASE_DIR, ".admin_clients.json")


def load_admin_clients() -> dict:
    """Handmatige admin-velden per klant. Dict: user_key → veld-dict."""
    return _load_json("admin_clients.json", _ADMIN_LOCAL)


def save_admin_clients(data: dict) -> tuple[bool, str]:
    """Sla handmatige admin-velden op. Geeft (gelukt, foutmelding) terug."""
    return _save_json("admin_clients.json", _ADMIN_LOCAL, data, "Update admin_clients via app")


# ---------------------------------------------------------------------------
# Administratie — pakketprijzen (instelbaar)
# ---------------------------------------------------------------------------

_PRIJZEN_LOCAL = os.path.join(_BASE_DIR, ".pakket_prijzen.json")


def load_pakket_prijzen() -> dict:
    """Prijs per pakket (per 4 weken). Dict: pakketnaam → bedrag."""
    return _load_json("pakket_prijzen.json", _PRIJZEN_LOCAL)


def save_pakket_prijzen(data: dict) -> tuple[bool, str]:
    """Sla pakketprijzen op. Geeft (gelukt, foutmelding) terug."""
    return _save_json("pakket_prijzen.json", _PRIJZEN_LOCAL, data, "Update pakket_prijzen via app")


# ---------------------------------------------------------------------------
# Administratie — KOR-correctie (overige omzet, niet in verkoopfacturen)
# ---------------------------------------------------------------------------

_KOR_CORR_LOCAL = os.path.join(_BASE_DIR, ".kor_correctie.json")


def load_kor_correctie() -> float:
    """Overige omzet (niet-factuur) die bij de factuuromzet wordt opgeteld."""
    d = _load_json("kor_correctie.json", _KOR_CORR_LOCAL)
    try:
        return float(d.get("overige_omzet", 0) or 0)
    except (ValueError, TypeError):
        return 0.0


def save_kor_correctie(bedrag: float) -> tuple[bool, str]:
    """Sla de overige-omzet-correctie op."""
    return _save_json("kor_correctie.json", _KOR_CORR_LOCAL,
                      {"overige_omzet": float(bedrag)}, "Update kor_correctie via app")


# ---------------------------------------------------------------------------
# Administratie — KOR-omzetcijfers (cumulatief per maand)
# ---------------------------------------------------------------------------

_REVENUE_LOCAL = os.path.join(_BASE_DIR, ".revenue.json")


def load_revenue() -> dict:
    """Cumulatieve omzet per maand. Dict: 'YYYY-MM' → bedrag (float)."""
    return _load_json("revenue.json", _REVENUE_LOCAL)


def save_revenue(data: dict) -> tuple[bool, str]:
    """Sla cumulatieve omzetcijfers op. Geeft (gelukt, foutmelding) terug."""
    return _save_json("revenue.json", _REVENUE_LOCAL, data, "Update revenue via app")


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


# ---------------------------------------------------------------------------
# Garmin athlete-state (gepubliceerd door de losse hardloopcoach-app)
# ---------------------------------------------------------------------------

_GARMIN_STATE_LOCAL = os.path.join(_BASE_DIR, ".garmin_state.json")


def load_garmin_state() -> dict:
    """Laad de Garmin athlete-state. Dict: user_key → {readiness, weekly, ...}.

    Wordt geschreven door de aparte hardloopcoach-app; alleen-lezen hier.
    Leeg dict als er (nog) geen data is.
    """
    return _load_json("garmin_state.json", _GARMIN_STATE_LOCAL)


def garmin_context_text(user_key: str) -> str:
    """Korte, AI-leesbare samenvatting van de Garmin-state voor deze atleet.

    Bedoeld om als achtergrond mee te geven aan de schema- en feedback-prompts.
    Geeft een lege string ('') terug als er geen Garmin-data is — dan verandert
    er niets aan de prompt en dus niets aan het gedrag voor die atleet.
    """
    if not user_key:
        return ""
    try:
        state = (load_garmin_state() or {}).get(user_key)
    except Exception:
        return ""
    if not state:
        return ""

    readiness = state.get("readiness") or {}
    sig = readiness.get("signals") or {}
    light_nl = {"green": "GROEN", "amber": "ORANJE", "red": "ROOD"}.get(
        readiness.get("light"), ""
    )

    lines: list[str] = []
    if light_nl:
        reasons = "; ".join((readiness.get("reasons") or [])[:2])
        lines.append(f"Readiness vandaag: {light_nl}" + (f" — {reasons}" if reasons else ""))

    hrv = sig.get("hrv") or {}
    nums: list[str] = []
    if hrv.get("current") is not None:
        nums.append(f"HRV {hrv['current']} (baseline {hrv.get('baseline_mean', '?')})")
    if sig.get("sleep_last_night_h") is not None:
        nums.append(f"slaap {sig['sleep_last_night_h']}u")
    if sig.get("resting_hr") is not None:
        nums.append(f"rust-HS {sig['resting_hr']}")
    if sig.get("body_battery_at_wake") is not None:
        nums.append(f"Body Battery bij ontwaken {sig['body_battery_at_wake']}")
    if nums:
        lines.append(", ".join(nums))

    if sig.get("acwr") is not None:
        zone = sig.get("acwr_zone", "")
        lines.append(f"belasting deze week {round(sig['acwr'] * 100)}% van normaal ({zone})")

    hard = sig.get("last_hard_session")
    if hard and hard.get("hours_ago") is not None and hard["hours_ago"] <= 48:
        lines.append(f"zware sessie {round(hard['hours_ago'])}u geleden ({hard.get('name', '')})")

    if not lines:
        return ""

    body = "\n".join(f"- {x}" for x in lines)
    return (
        "GARMIN-HERSTELSTATUS van deze atleet (momentopname uit de hardloopcoach-app; "
        "alleen als achtergrond — het plan, de doelen en de zones blijven leidend):\n"
        f"{body}\n"
        f"(bijgewerkt: {state.get('updated_at', '')})"
    )


def garmin_summary_line(user_key: str) -> str:
    """Korte one-liner voor in de UI (leeg als er geen Garmin-data is).

    Bv. 'readiness ORANJE · belasting 82% van normaal · zware sessie 19u geleden'.
    """
    if not user_key:
        return ""
    try:
        state = (load_garmin_state() or {}).get(user_key)
    except Exception:
        return ""
    if not state:
        return ""
    readiness = state.get("readiness") or {}
    sig = readiness.get("signals") or {}
    parts: list[str] = []
    light_nl = {"green": "GROEN", "amber": "ORANJE", "red": "ROOD"}.get(readiness.get("light"))
    if light_nl:
        parts.append(f"readiness {light_nl}")
    if sig.get("acwr") is not None:
        parts.append(f"belasting {round(sig['acwr'] * 100)}% van normaal")
    hard = sig.get("last_hard_session")
    if hard and hard.get("hours_ago") is not None and hard["hours_ago"] <= 48:
        parts.append(f"zware sessie {round(hard['hours_ago'])}u geleden")
    return " · ".join(parts)
