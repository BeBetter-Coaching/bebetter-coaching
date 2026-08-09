"""Teampuls voor de PWA — belasting-signalen + AI-weekbriefing.

Hergebruikt exact de gedeelde kern (belasting.py, briefing.py, intake_store) die
ook de Streamlit-app voedt. Zo zijn de signalen, het 'gezien'-dempen (7 dagen,
gedeeld tussen beide coaches) en de weekbriefing 1-op-1 gelijk.

Lui importeren: belasting.dagelijkse_check en briefing importeren ai_client →
anthropic. Zonder ANTHROPIC_API_KEY crasht dat bij import. Daarom pas binnen de
functies die de AI echt nodig hebben.
"""
from __future__ import annotations

import os
import sys
import types

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# belasting → dossier importeert streamlit+pandas op moduleniveau; die staan niet
# in de PWA-omgeving (Render). We raken ze nooit aan (alleen de pure functies),
# dus stubben we ze zodat de import-keten laadt. Zelfde truc als admin_core.
for _m in ("streamlit", "pandas"):
    if _m not in sys.modules:
        try:
            __import__(_m)
        except Exception:
            sys.modules[_m] = types.ModuleType(_m)

import fs_client as FS

try:
    import intake_store
except Exception:
    intake_store = None


def heeft_token() -> bool:
    try:
        return bool(FS.get_token())
    except Exception:
        return False


def heeft_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _atleten() -> list:
    """Vlakke atletenlijst zoals main.py (_all_athletes) — voedt belasting/briefing."""
    groepen = FS.get_athletes_by_group()
    return [a for members in groepen.values() for a in members]


def _norm(r: dict) -> dict:
    mx = r.get("metrics") or {}
    return {
        "user_key": r.get("user_key", ""),
        "naam": r.get("naam", ""),
        "groep": r.get("group", ""),
        "ernst": r.get("ernst", ""),               # "hoog" | "let_op"
        "signalen": r.get("signalen") or [],
        "duiding": r.get("duiding") or "",
        "metrics": {
            "km_recent": mx.get("km_recent"),
            "km_basis": mx.get("km_basis_week"),
            "gevoel_recent": mx.get("gevoel_recent"),
            "gevoel_basis": mx.get("gevoel_basis"),
            "rpe_recent": mx.get("rpe_recent"),
            "rpe_basis": mx.get("rpe_basis"),
            "runs": mx.get("runs_recent") or [],
        },
    }


def signalen(force: bool = False) -> dict:
    """Belasting-signalen van vandaag (dagelijks gecachet, gedeeld met Streamlit)."""
    if not heeft_token():
        return {"fs": False, "items": [], "datum": None}
    import belasting                                # lui: trekt ai_client mee
    try:
        data = belasting.dagelijkse_check(_atleten(), forceer=force)
    except Exception as e:
        # Val terug op de laatst opgeslagen stand — nooit een leeg scherm
        try:
            data = belasting.laad_stand()
        except Exception:
            data = {}
        data.setdefault("_err", str(e))
    zichtbaar = []
    try:
        zichtbaar = belasting.zichtbare_resultaten(data)
    except Exception:
        pass
    items = [_norm(r) for r in zichtbaar]
    hoog = sum(1 for i in items if i["ernst"] == "hoog")
    return {"fs": True, "items": items, "datum": data.get("datum"),
            "hoog": hoog, "totaal": len(items)}


def stand_kort() -> dict:
    """Goedkope home-teller: alleen de opgeslagen belasting-stand lezen (géén
    FinalSurge-calls, géén AI). Voor het home-metertje 'belasting-signalen'."""
    import belasting
    try:
        data = belasting.laad_stand()
        zichtbaar = belasting.zichtbare_resultaten(data)
    except Exception:
        return {"totaal": 0, "hoog": 0, "datum": None, "vers": False}
    hoog = sum(1 for r in zichtbaar if r.get("ernst") == "hoog")
    from datetime import date as _d
    return {"totaal": len(zichtbaar), "hoog": hoog,
            "datum": data.get("datum"), "vers": data.get("datum") == _d.today().isoformat()}


def markeer_gezien(user_key: str, ernst: str, undo: bool = False) -> bool:
    """Demp een atleet 7 dagen (gedeeld met Streamlit). undo=True heft de demping
    op (voor de Ongedaan-toast): haalt de atleet uit 'afgehandeld' en bewaart."""
    import belasting
    try:
        data = belasting.laad_stand()
    except Exception:
        data = {}
    if undo:
        (data.get("afgehandeld") or {}).pop(user_key, None)
        try:
            intake_store.save_belasting(data)
        except Exception:
            pass
    else:
        belasting.markeer_gezien(data, user_key, ernst)
    return True


def briefing(force: bool = False) -> dict:
    """AI-weekbriefing (per week gecachet, gedeeld met Streamlit)."""
    if not heeft_token():
        return {"fs": False}
    import briefing as B
    # De briefing wil aandacht-lijsten; die halen we goedkoop uit de opgeslagen
    # stand + schema/races (net als de Streamlit-Teampuls). Ontbreekt iets, dan
    # blijft die lijst leeg — de briefing draait door.
    atleten = _atleten()
    bel_res = []
    try:
        bel_res = (intake_store.load_belasting() or {}).get("resultaten", []) if intake_store else []
    except Exception:
        pass
    schema_urgent, races_komend = [], []
    try:
        rows = FS.get_schema_end_dates(horizon_days=60)
        schema_urgent = [r["name"] for r in rows
                         if r.get("days_left") is None or r["days_left"] <= 7]
    except Exception:
        pass
    try:
        races_komend = [r["athlete_name"] for r in FS.get_upcoming_races(days_ahead=7)]
    except Exception:
        pass
    try:
        data = B.weekbriefing(atleten, bel_res, schema_urgent, races_komend, [], forceer=force)
    except Exception as e:
        return {"fs": True, "ai": heeft_key(), "err": f"Briefing maken mislukt: {e}"}
    return {"fs": True, "ai": heeft_key(), "week": data.get("week"),
            "gemaakt": data.get("gemaakt"), "tekst": data.get("tekst", ""),
            "stats": data.get("stats", {})}
