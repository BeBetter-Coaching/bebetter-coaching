"""Masterbrein v2 — durable per-atleet snapshot (Fase A).

Hergebruikt het bewezen intake_store JSON-store-patroon (GitHub-backed + lokale
fallback), geen nieuwe database. Eén bestand `brain_snapshot.json` met
{athlete_key: state-dict}. Version-mismatch of corrupte data → veilige None
(nooit crashen, nooit halve state serveren).
"""
from __future__ import annotations

import os

import intake_store

from .models import SCHEMA_VERSION, AthleteState

_REMOTE = "brain_snapshot.json"
_LOCAL = os.path.join(os.path.dirname(os.path.abspath(intake_store.__file__)),
                      ".brain_snapshot.json")


def _load_all() -> dict:
    try:
        data = intake_store._load_json(_REMOTE, _LOCAL)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_snapshot(user_key: str):
    """Laad de opgeslagen AthleteState voor één atleet, of None (veilig)."""
    try:
        d = _load_all().get(user_key)
        if not isinstance(d, dict):
            return None
        if d.get("schema_version") != SCHEMA_VERSION:
            return None                              # versie-mismatch → geen risico
        return AthleteState.from_dict(d)
    except Exception:
        return None


def save_snapshot(state: AthleteState) -> tuple:
    """Sla de state op (load-modify-save). Best-effort, nooit corruptie bij fout."""
    try:
        alld = _load_all()
        alld[state.athlete_key] = state.to_dict()
        return intake_store._save_json(_REMOTE, _LOCAL, alld,
                                       f"brain snapshot {state.athlete_key}")
    except Exception as e:
        return False, str(e)[:120]
