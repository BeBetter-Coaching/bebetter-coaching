"""Masterbrein — deterministische relatieve event/tijd-semantiek (FC-3).

Eén centrale bron voor 'over N dagen'-achtige aanduidingen, zodat Feedback niet zelf de
tijd tot een bekende afspraak hoeft te raden en geen event verzint. Parseert UITSLUITEND een
BETROUWBARE datum (met expliciet jaartal); ontbreekt die, dan blijft het status UNKNOWN —
we gokken nooit een jaar of een 'over N dagen' zonder betrouwbare datum.
"""
from __future__ import annotations

import re
from datetime import date


def parse_reliable_date(value) -> date | None:
    """Betrouwbare kalenderdatum uit een (mogelijk vrije-tekst) waarde, of None.
    Accepteert ISO `YYYY-MM-DD` en `DD-MM-YYYY` / `DD/MM/YYYY` met EXPLICIET jaartal.
    Geen jaartal / ambigu (bv. '20 sep', 'halve marathon') → None (UNKNOWN, geen gok)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", s)             # ISO
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", s)       # DD-MM-YYYY
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def relative_event(value, today: date) -> dict:
    """Relatieve event-projectie: `{status, days, date, label}`.

    status: TODAY | TOMORROW | IN_N_DAYS | PAST | UNKNOWN.
    - UNKNOWN: geen betrouwbare datum in de waarde → geen 'over N dagen', geen vooruitblik.
    - PAST: datum ligt vóór vandaag (days negatief) → nooit als toekomst framen.
    `label` is een NL-aanduiding ('vandaag'/'morgen'/'over N dagen'/'N dagen geleden'); leeg bij UNKNOWN.
    """
    d = parse_reliable_date(value)
    if d is None:
        return {"status": "UNKNOWN", "days": None, "date": None, "label": ""}
    delta = (d - today).days
    iso = d.isoformat()
    if delta < 0:
        return {"status": "PAST", "days": delta, "date": iso, "label": f"{-delta} dagen geleden"}
    if delta == 0:
        return {"status": "TODAY", "days": 0, "date": iso, "label": "vandaag"}
    if delta == 1:
        return {"status": "TOMORROW", "days": 1, "date": iso, "label": "morgen"}
    return {"status": "IN_N_DAYS", "days": delta, "date": iso, "label": f"over {delta} dagen"}
