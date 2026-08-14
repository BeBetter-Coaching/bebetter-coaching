"""Masterbrein v2 — Dossier Fase A: append-only history-store.

Deep-store náást de hot `brain_snapshot.json`. Bewaart per atleet een
append-only lijst `HistoryEvent`-dicts. Hergebruikt het BEWEZEN intake_store
JSON-patroon (GitHub-backed + lokale fallback) — GEEN database.

Invarianten (zie dossier-architecture-design.md §M + opdracht §6/§8/§23):
  • append-only: nooit een bestaand event overschrijven of verwijderen;
  • idempotent: dedupe op deterministische `id` → herbouwen/dubbele hook =
    0 duplicaten;
  • deterministische ordening (op effective_at, dan recorded_at, dan id);
  • lost-update-safe: op een GitHub-SHA-conflict (409) opnieuw laden en
    idempotent samenvoegen (CAS-retry). In-proces lock serialiseert threads.
  • consumers lezen NOOIT het JSON-bestand direct — alleen via deze API
    (zodat latere per-atleet sharding zonder consumer-wijziging kan).
  • corruptie/leeg bestand → veilige lege state, breekt nooit een request.

Store-vorm (v1, één bestand): {"schema_version": 1, "events": {athlete_key: [event,...]}}
"""
from __future__ import annotations

import os
import threading
from datetime import date

import intake_store

from .events import HistoryEvent

_REMOTE = "athlete_history.json"
_LOCAL = os.path.join(os.path.dirname(os.path.abspath(intake_store.__file__)),
                      ".athlete_history.json")

STORE_SCHEMA_VERSION = 1

# ── O4 — store-granulariteit (BESLIST Fase A) ────────────────────────────────
# v1 = één centraal bestand zolang het volume klein is. De read/write-API
# hieronder abstraheert de fysieke opslag, zodat per-atleet sharding later kan
# worden ingezet ZONDER consumer-wijziging. Split pas op bewijs, niet vroeg:
SHARD_THRESHOLD_ATHLETES = 40      # > dit aantal atleten → overweeg per-atleet shards
SHARD_THRESHOLD_EVENTS = 750       # > dit aantal events voor één atleet → overweeg shard
SHARD_THRESHOLD_TOTAL = 6000       # > dit totaal events → overweeg splitsen

# CAS-retry op write-conflict (GitHub 409). Idempotente merge maakt retry veilig.
_MAX_WRITE_RETRIES = 5
_lock = threading.RLock()          # serialiseert appends binnen één proces


def _load_all() -> dict:
    """Rauwe store-dict, veilig (nooit exception naar de caller)."""
    try:
        data = intake_store._load_json(_REMOTE, _LOCAL)
        if not isinstance(data, dict):
            return {"schema_version": STORE_SCHEMA_VERSION, "events": {}}
        ev = data.get("events")
        if not isinstance(ev, dict):
            data["events"] = {}
        data.setdefault("schema_version", STORE_SCHEMA_VERSION)
        return data
    except Exception:
        return {"schema_version": STORE_SCHEMA_VERSION, "events": {}}


def _sort_key(e: dict) -> tuple:
    return (str(e.get("effective_at") or ""), str(e.get("recorded_at") or ""),
            str(e.get("id") or ""))


def _athlete_events(all_data: dict, athlete_key: str) -> list:
    lst = (all_data.get("events") or {}).get(athlete_key)
    return list(lst) if isinstance(lst, list) else []


def _is_conflict(err: str) -> bool:
    e = (err or "").lower()
    return "409" in e or "conflict" in e or "sha" in e


# ── Write — idempotente, lost-update-safe append ─────────────────────────────
def append_events(athlete_key: str, events) -> tuple[bool, str, int]:
    """Voeg events idempotent toe. Geeft (ok, err, n_new_toegevoegd).

    Dedupe op `id`: al aanwezige events worden overgeslagen (0 duplicaten).
    Bij een schrijf-conflict (concurrente writer) wordt opnieuw geladen en
    opnieuw samengevoegd — geen verloren events. Nooit fataal voor de caller.
    """
    if not athlete_key:
        return False, "geen athlete_key", 0
    new = [e.to_dict() if isinstance(e, HistoryEvent) else dict(e) for e in (events or [])]
    new = [e for e in new if e.get("id")]
    if not new:
        return True, "", 0

    with _lock:
        for attempt in range(_MAX_WRITE_RETRIES):
            all_data = _load_all()
            cur = _athlete_events(all_data, athlete_key)
            have = {e.get("id") for e in cur}
            add = [e for e in new if e.get("id") not in have]
            if not add:
                return True, "", 0                       # alles al aanwezig → idempotent
            merged = cur + add
            merged.sort(key=_sort_key)
            all_data.setdefault("events", {})[athlete_key] = merged
            ok, err = intake_store._save_json(
                _REMOTE, _LOCAL, all_data,
                f"dossier history +{len(add)} {athlete_key}")
            if ok:
                return True, "", len(add)
            if not _is_conflict(err) or attempt == _MAX_WRITE_RETRIES - 1:
                return False, (err or "")[:160], 0
            # conflict → loop: herlaad (krijgt de events van de andere writer),
            # her-merge idempotent, probeer opnieuw.
    return False, "max retries", 0


def append_event(athlete_key: str, event) -> tuple[bool, str, int]:
    return append_events(athlete_key, [event])


# ── Read-API (consumers gebruiken UITSLUITEND deze functies) ─────────────────
def get_events(athlete_key: str, *, domain: str = "", event_type: str = "",
               status: str = "", since: str = "", until: str = "",
               limit: int = 0, newest_first: bool = False) -> list:
    """Events voor één atleet, gefilterd + deterministisch geordend.

    Filters zijn optioneel; `since`/`until` vergelijken op effective_at (ISO).
    Retourneert HistoryEvent-objecten (nooit rauwe dicts) — consumers hoeven
    het opslagformaat niet te kennen."""
    all_data = _load_all()
    rows = _athlete_events(all_data, athlete_key)
    rows.sort(key=_sort_key)
    out = []
    for e in rows:
        if domain and e.get("domain") != domain:
            continue
        if event_type and e.get("event_type") != event_type:
            continue
        if status and e.get("status") != status:
            continue
        eff = str(e.get("effective_at") or "")
        if since and eff and eff < since:
            continue
        if until and eff and eff > until:
            continue
        out.append(HistoryEvent.from_dict(e))
    if newest_first:
        out.reverse()
    if limit and limit > 0:
        out = out[:limit]
    return out


def get_recent_events(athlete_key: str, limit: int = 20) -> list:
    return get_events(athlete_key, newest_first=True, limit=limit)


def has_event(athlete_key: str, event_id: str) -> bool:
    return any(e.get("id") == event_id for e in _athlete_events(_load_all(), athlete_key))


def count_events(athlete_key: str) -> int:
    return len(_athlete_events(_load_all(), athlete_key))


# ── Lichte per-atleet index (§22 — geen full-history-scan voor roster/Teampuls) ──
def index() -> dict:
    """Compacte index per atleet: {athlete_key: {n, last_event_at, last_event_type}}.

    Bedoeld voor snelle roster-/Teampuls-tellers zonder de volle history te
    materialiseren. Puur afgeleid, geen aparte opslag."""
    all_data = _load_all()
    out = {}
    for ak, rows in (all_data.get("events") or {}).items():
        if not isinstance(rows, list) or not rows:
            out[ak] = {"n": 0, "last_event_at": "", "last_event_type": ""}
            continue
        srt = sorted(rows, key=_sort_key)
        last = srt[-1]
        out[ak] = {"n": len(rows),
                   "last_event_at": str(last.get("effective_at") or last.get("recorded_at") or ""),
                   "last_event_type": last.get("event_type") or ""}
    return out


def storage_health() -> dict:
    """Diagnostiek voor acceptance: totalen + of de shard-drempel is bereikt."""
    all_data = _load_all()
    ev = all_data.get("events") or {}
    total = sum(len(v) for v in ev.values() if isinstance(v, list))
    max_one = max((len(v) for v in ev.values() if isinstance(v, list)), default=0)
    n_ath = len(ev)
    return {
        "athletes": n_ath, "total_events": total, "max_events_one_athlete": max_one,
        "cloud_backed": intake_store.is_cloud_backed(),
        "shard_recommended": (n_ath > SHARD_THRESHOLD_ATHLETES
                              or max_one > SHARD_THRESHOLD_EVENTS
                              or total > SHARD_THRESHOLD_TOTAL),
        "as_of": date.today().isoformat(),
    }
