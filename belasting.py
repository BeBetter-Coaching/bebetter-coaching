"""Belasting-signalering — wie loopt uit de pas qua volume, gevoel of klachten.

Vier gratis rekenregels bepalen wie gevlagd wordt (geen AI):
  1. Volumesprong   — deze week fors meer km dan het 4-weekse gemiddelde ervoor
  2. Gevoel zakt    — gevoel-score structureel slechter dan de periode ervoor
  3. RPE-drift      — trainingen voelen zwaarder terwijl het volume gelijk blijft
  4. Klachtwoorden  — pijn/blessure/ziek e.d. in recente notities

Alleen voor gevlagde atleten schrijft Haiku één duidende coach-zin.
Resultaat wordt 1x per dag berekend en gedeeld opgeslagen (belasting.json),
zodat beide coaches dezelfde stand zien zonder herberekening.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import fs_client
import intake_store
from dossier import _is_run, _run_km

# Drempels (praktijkwaarden; bijstellen op basis van ervaring)
VOLUME_RATIO_LET_OP = 1.30   # +30% t.o.v. 4-weeks gemiddelde
VOLUME_RATIO_HOOG = 1.50     # +50%
BASIS_MIN_KM_WEEK = 10.0     # onder deze basis geen volume-signaal (opbouwers/starters)
GEVOEL_DREMPEL = 0.8         # punten verslechtering (1=geweldig … 5=vreselijk)
RPE_DREMPEL = 1.5            # punten zwaarder (schaal 1-10)
RPE_VOLUME_MAX = 1.15        # RPE-drift telt alleen als volume NIET fors steeg
MIN_DATAPUNTEN = 3           # minimaal aantal scores per venster

# Fysieke-klacht-patronen (bewust alleen negatief — geen PR/record zoals de
# dossier-signaallijst, die vangt ook positieve uitschieters)
_KLACHT_PATRONEN = [
    r"blessure", r"geblesseerd", r"\bpijn", r"pijnlijk", r"fysio", r"\bziek\b",
    r"griep", r"koorts", r"overtraind", r"uitgeput", r"doodmoe", r"geen energie",
    r"kramp", r"scheen", r"achilles", r"hamstring", r"\bkuit", r"\blies\b",
    r"\benkel", r"\bknie", r"\brug\b",
]


def _gem(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def analyse_belasting(entries: list[dict], vandaag: date | None = None) -> dict | None:
    """
    Analyseer trainingslog-entries (dicts met date, actual_km, activity_type,
    completed, felt, effort, post_notes) op belasting-signalen.
    Geeft None als er niets aan de hand is of te weinig data, anders:
    {"ernst": "let_op"|"hoog", "signalen": [tekst], "codes": [code], "metrics": {...}}
    """
    vandaag = vandaag or date.today()
    grens_7d = vandaag - timedelta(days=7)
    grens_14d = vandaag - timedelta(days=14)
    grens_basis = grens_7d - timedelta(days=28)      # volume-basis: 28d vóór de recente week
    grens_basis_scores = grens_14d - timedelta(days=28)  # score-basis: 28d vóór de recente 14d

    km_recent = 0.0
    km_basis = 0.0
    n_runs_basis = 0
    felt_recent, felt_basis = [], []
    rpe_recent, rpe_basis = [], []
    klachten: list[str] = []

    for e in entries:
        try:
            d = date.fromisoformat((e.get("date") or "")[:10])
        except ValueError:
            continue
        if d > vandaag or not e.get("completed"):
            continue

        km = _run_km(e)
        if d > grens_7d:
            km_recent += km
        elif d > grens_basis:
            km_basis += km
            if _is_run(e) and km > 0:
                n_runs_basis += 1

        # Gevoel (1=geweldig … 5=vreselijk) en RPE (1-10)
        for veld, recent, basis in (("felt", felt_recent, felt_basis),
                                    ("effort", rpe_recent, rpe_basis)):
            try:
                v = float(e.get(veld))
            except (TypeError, ValueError):
                continue
            if v <= 0:
                continue
            if d > grens_14d:
                recent.append(v)
            elif d > grens_basis_scores:
                basis.append(v)

        # Klachtwoorden in recente notities
        if d > grens_14d and e.get("post_notes"):
            tekst = e["post_notes"].lower()
            for pat in _KLACHT_PATRONEN:
                m = re.search(pat, tekst)
                if m and m.group(0).strip() not in klachten:
                    klachten.append(m.group(0).strip())

    signalen: list[str] = []
    codes: list[str] = []
    basis_week = km_basis / 4 if km_basis else 0.0
    ratio = (km_recent / basis_week) if basis_week else None

    # 1. Volumesprong — alleen bij een serieuze basis (geen starters flaggen)
    if (ratio is not None and basis_week >= BASIS_MIN_KM_WEEK
            and n_runs_basis >= 4 and ratio >= VOLUME_RATIO_LET_OP):
        signalen.append(f"Volume +{(ratio - 1) * 100:.0f}% deze week "
                        f"({km_recent:.0f} km vs gem. {basis_week:.0f} km/wk)")
        codes.append("volume")

    # 2. Gevoel zakt (hogere score = slechter)
    g_rec, g_bas = _gem(felt_recent), _gem(felt_basis)
    if (g_rec is not None and g_bas is not None
            and len(felt_recent) >= MIN_DATAPUNTEN and len(felt_basis) >= MIN_DATAPUNTEN
            and g_rec - g_bas >= GEVOEL_DREMPEL):
        signalen.append(f"Gevoel zakt: gem. {g_rec:.1f} laatste 2 wkn vs {g_bas:.1f} ervoor")
        codes.append("gevoel")

    # 3. RPE-drift: zwaarder bij gelijk werk
    r_rec, r_bas = _gem(rpe_recent), _gem(rpe_basis)
    if (r_rec is not None and r_bas is not None
            and len(rpe_recent) >= MIN_DATAPUNTEN and len(rpe_basis) >= MIN_DATAPUNTEN
            and r_rec - r_bas >= RPE_DREMPEL
            and (ratio is None or ratio < RPE_VOLUME_MAX)):
        signalen.append(f"Trainingen voelen zwaarder: RPE {r_rec:.1f} vs {r_bas:.1f} "
                        f"bij vergelijkbaar volume")
        codes.append("rpe")

    # 4. Klachtwoorden
    if klachten:
        signalen.append("Noemt in notities: " + ", ".join(klachten[:4]))
        codes.append("klachten")

    if not signalen:
        return None

    hoog = len(codes) >= 2 or (ratio is not None and ratio >= VOLUME_RATIO_HOOG)
    return {
        "ernst": "hoog" if hoog else "let_op",
        "signalen": signalen,
        "codes": codes,
        "metrics": {
            "km_recent": round(km_recent, 1), "km_basis_week": round(basis_week, 1),
            "ratio": round(ratio, 2) if ratio is not None else None,
            "gevoel_recent": g_rec, "gevoel_basis": g_bas,
            "rpe_recent": r_rec, "rpe_basis": r_bas,
            "klachten": klachten,
        },
    }


def _entry_van_workout(w: dict) -> dict:
    """Zet een ruwe FinalSurge-workout om naar een analyse-entry."""
    acts = w.get("Activities") or []
    act = acts[0] if acts else {}
    return {
        "date": (w.get("workout_date") or "")[:10],
        "activity_type": (w.get("activity_type_name")
                          or act.get("activity_type_name") or ""),
        "actual_km": fs_client._norm_km(act.get("amount"), act.get("amount_type")),
        "completed": fs_client.is_executed_workout(w),
        "felt": w.get("felt"),
        "effort": w.get("effort"),
        "post_notes": (w.get("post_workout_notes") or "").strip(),
    }


def check_alle(athletes: list[dict], on_hold: dict | None = None,
               admin_clients: dict | None = None) -> list[dict]:
    """
    Draai de belasting-analyse voor alle relevante atleten (parallel).
    Uitgesloten: los schema, on hold, opgezegd. Geeft alleen gevlagde atleten.
    """
    on_hold = on_hold or {}
    admin_clients = admin_clients or {}
    vandaag = date.today()
    start = vandaag - timedelta(days=43)

    todo = []
    for a in athletes:
        groepen = a.get("all_groups") or [a.get("group")]
        if any(fs_client.group_is_excluded(g, {"los schema"}) for g in groepen):
            continue
        if a["user_key"] in on_hold:
            continue
        if admin_clients.get(a["user_key"], {}).get("status") == "Opgezegd":
            continue
        todo.append(a)

    def _fetch(a):
        workouts = fs_client.get_workouts_deduped(a["user_key"], start, vandaag)
        entries = [_entry_van_workout(w) for w in workouts]
        res = analyse_belasting(entries, vandaag)
        if not res:
            return None
        notities = " | ".join(e["post_notes"] for e in entries
                              if e["post_notes"] and e["date"] >= (vandaag - timedelta(days=14)).isoformat())
        return {"user_key": a["user_key"], "naam": a["name"],
                "group": a.get("group", ""), "notities": notities[:800], **res}

    resultaten = [r for r in fs_client._parallel_per_athlete(todo, _fetch) if r]
    # Hoog eerst, dan alfabetisch
    return sorted(resultaten, key=lambda r: (r["ernst"] != "hoog", r["naam"]))


def dagelijkse_check(athletes: list[dict], forceer: bool = False) -> dict:
    """
    Geef de belasting-stand van vandaag. Herberekent alleen als de opgeslagen
    stand niet van vandaag is (of forceer=True); anders 1 goedkope opslag-load.
    Structuur: {"datum": iso, "resultaten": [...], "afgehandeld": {user_key: {...}}}
    """
    import ai_feedback

    try:
        data = intake_store.load_belasting()
    except Exception:
        data = {}
    vandaag = date.today().isoformat()
    if not forceer and data.get("datum") == vandaag:
        return data

    resultaten = check_alle(
        athletes,
        on_hold=_veilig(intake_store.load_on_hold),
        admin_clients=_veilig(intake_store.load_admin_clients),
    )
    for r in resultaten:
        try:
            r["duiding"] = ai_feedback.belasting_duiding(
                r["naam"], r["signalen"], r.get("notities", ""))
        except Exception:
            r["duiding"] = ""
        r.pop("notities", None)  # niet nodig in de opslag

    data = {"datum": vandaag, "resultaten": resultaten,
            "afgehandeld": data.get("afgehandeld", {})}
    try:
        intake_store.save_belasting(data)
    except Exception:
        pass  # niet-opslaan = morgen opnieuw berekenen, geen blokkade
    return data


def zichtbare_resultaten(data: dict) -> list[dict]:
    """Filter de resultaten op 'gezien' (7 dagen gedempt, behalve bij escalatie)."""
    vandaag = date.today().isoformat()
    afg = data.get("afgehandeld", {})
    zichtbaar = []
    for r in data.get("resultaten", []):
        a = afg.get(r["user_key"])
        if a and a.get("tot", "") >= vandaag and not (
                r["ernst"] == "hoog" and a.get("ernst") == "let_op"):
            continue  # gezien en niet geëscaleerd
        zichtbaar.append(r)
    return zichtbaar


def markeer_gezien(data: dict, user_key: str, ernst: str) -> dict:
    """Demp een atleet 7 dagen; bij escalatie naar 'hoog' komt hij eerder terug."""
    afg = data.setdefault("afgehandeld", {})
    afg[user_key] = {"tot": (date.today() + timedelta(days=7)).isoformat(),
                     "ernst": ernst}
    # Verlopen vermeldingen opruimen
    vandaag = date.today().isoformat()
    for k in list(afg.keys()):
        if afg[k].get("tot", "") < vandaag:
            del afg[k]
    try:
        intake_store.save_belasting(data)
    except Exception:
        pass
    return data


def _veilig(fn):
    try:
        return fn()
    except Exception:
        return {}
