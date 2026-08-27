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


def _stand_payload(data: dict, belasting) -> dict:
    """Bouw de signalen-payload uit een (opgeslagen of verse) belasting-stand, mét
    freshness volgens het gedeelde contract: datum==vandaag → FRESH (vers); een
    geldige oudere stand → STALE-but-valid (stale, direct bruikbaar + verversen);
    geen datum → UNKNOWN (pending). Zelfde stand als Home/Dossier."""
    from datetime import date as _d
    try:
        zichtbaar = belasting.zichtbare_resultaten(data)
    except Exception:
        zichtbaar = []
    items = [_norm(r) for r in zichtbaar]
    hoog = sum(1 for i in items if i["ernst"] == "hoog")
    datum = data.get("datum")
    vers = bool(datum) and datum == _d.today().isoformat()
    payload = {"fs": True, "items": items, "datum": datum, "hoog": hoog,
               "totaal": len(items), "vers": vers, "stale": bool(datum) and not vers}
    if data.get("_err"):
        payload["_err"] = data["_err"]
    return payload


def signalen(force: bool = False) -> dict:
    """Belasting-signalen (dagelijks gecachet, gedeeld met Streamlit/Home/Dossier).

    FAST READ (force=False): lees ALLEEN de opgeslagen stand — geen roster-fetch,
    geen recompute. Zo verschijnt Teampuls direct met de bestaande monitoringsstate
    (FRESH of STALE-but-valid), i.p.v. op de dag-eerste-open 30-45s te blokkeren op
    een volledige teamrecompute. De client triggert daarna zelf de achtergrond-refresh
    (force=True) en reconcilieert.

    REFRESH (force=True): herbereken de dagstand (belasting.dagelijkse_check) — de
    zware sweep, nu bewust achter de expliciete/achtergrond-actie i.p.v. page-open."""
    if not heeft_token():
        return {"fs": False, "items": [], "datum": None}
    import belasting                                # lui: trekt ai_client mee

    if not force:
        try:
            data = belasting.laad_stand() or {}
        except Exception:
            data = {}
        if data.get("datum"):
            return _stand_payload(data, belasting)
        # Nog geen stand (koud/eerste keer) → geen zware recompute in het renderpad;
        # client toont skeletons en triggert force-refresh op de achtergrond.
        return {"fs": True, "items": [], "datum": None, "hoog": 0, "totaal": 0,
                "vers": False, "stale": False, "pending": True}

    try:
        data = belasting.dagelijkse_check(_atleten(), forceer=True)
    except Exception as e:
        try:
            data = belasting.laad_stand()
        except Exception:
            data = {}
        data.setdefault("_err", str(e))
    return _stand_payload(data, belasting)


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
    # Zowel demp als undo lopen via belasting.markeer_gezien → coach-authority-veilig
    # onder de gedeelde stand-lock (her-leest de verse stand, overschrijft nooit een
    # gelijktijdige recompute of tweede coachactie).
    belasting.markeer_gezien(data, user_key, ernst, undo=undo)
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
