"""Weekbriefing — het maandagochtend-overzicht voor de coach.

Eén keer per week (of op verzoek) verzamelt de app wat er de afgelopen week
gebeurde en wat er deze week aandacht vraagt, en vat dat samen in een korte
briefing. Bronnen: FinalSurge (trainingen, races), de belasting-dagstand,
het schema-verloop en (indien gekoppeld) de facturatie uit Rompslomp.

Gedeeld opgeslagen (weekbriefing.json) zodat beide coaches dezelfde zien.
"""

from __future__ import annotations

from datetime import date, timedelta

import fs_client
import intake_store
from ai_client import create_message
from ai_feedback import _clean_text
from belasting import _entry_van_workout, _veilig
from dossier import _run_km

_FELT_NL = {1: "geweldig", 2: "goed", 3: "normaal", 4: "slecht", 5: "vreselijk"}


def week_label(vandaag: date | None = None) -> str:
    """ISO-weeklabel, bijv. '2026-W27'."""
    v = vandaag or date.today()
    jaar, week, _ = v.isocalendar()
    return f"{jaar}-W{week:02d}"


def aggregeer_week(per_atleet: list[dict]) -> dict:
    """
    Aggregeer de week-entries van alle atleten tot kerncijfers.
    per_atleet: [{"naam", "group", "entries": [...], "races": [str]}]
    """
    n_trainingen = 0
    km_totaal = 0.0
    felt_scores: list[float] = []
    stil: list[str] = []
    races: list[str] = []
    groepen: dict[str, dict] = {}

    for a in per_atleet:
        n_eigen = 0
        for e in a.get("entries", []):
            if not e.get("completed"):
                continue
            n_eigen += 1
            n_trainingen += 1
            km_totaal += _run_km(e)
            try:
                v = float(e.get("felt"))
                if v > 0:
                    felt_scores.append(v)
            except (TypeError, ValueError):
                pass
        g = groepen.setdefault(a.get("group") or "Overig", {"n": 0, "atleten": 0})
        g["n"] += n_eigen
        g["atleten"] += 1
        if n_eigen == 0:
            stil.append(a["naam"])
        for r in a.get("races", []):
            races.append(f"{a['naam']} — {r}" if r else a["naam"])

    gevoel = round(sum(felt_scores) / len(felt_scores), 1) if felt_scores else None
    return {
        "n_trainingen": n_trainingen,
        "km_totaal": round(km_totaal),
        "n_atleten": len(per_atleet),
        "n_actief": len(per_atleet) - len(stil),
        "stil": sorted(stil),
        "races_gedaan": races,
        "gevoel_gem": gevoel,
        "groepen": {k: v for k, v in sorted(groepen.items())},
    }


def verzamel_week(athletes: list[dict]) -> dict:
    """Haal de afgelopen 7 dagen op voor alle relevante atleten (parallel)."""
    on_hold = _veilig(intake_store.load_on_hold)
    admin_clients = _veilig(intake_store.load_admin_clients)
    vandaag = date.today()
    start = vandaag - timedelta(days=7)

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
        return {
            "naam": a["name"],
            "group": a.get("group", ""),
            "entries": [_entry_van_workout(w) for w in workouts],
            "races": [(w.get("name") or "").strip() for w in workouts
                      if w.get("is_race") and fs_client.is_executed_workout(w)],
        }

    per_atleet = [r for r in fs_client._parallel_per_athlete(todo, _fetch) if r]
    return aggregeer_week(per_atleet)


_BRIEFING_SYSTEM = """Je schrijft de wekelijkse maandagochtend-briefing voor twee hardloopcoaches (Jip en Remco) over hun eigen atleten.

REGELS:
- 6 tot 10 korte zinnen, zakelijk maar warm, alsof een collega je bijpraat bij de koffie
- Begin met het grote beeld (hoe draaide de groep), daarna wat aandacht vraagt deze week
- Noem atleten alleen bij naam als er iets mee moet (belasting, stilte, race, aflopend schema)
- Alleen feiten uit de aangeleverde data, verzin niets, geen aannames over oorzaken
- Gebruik NOOIT een streepje (-, – of —); schrijf vloeiende zinnen met komma's
- Geen kopjes, geen opsommingstekens, gewoon doorlopende alinea's. Nederlands."""


def genereer_briefing_tekst(stats: dict, aandacht: list[dict],
                            schema_urgent: list[str], races_komend: list[str],
                            facturatie: list[str]) -> str:
    """Laat Sonnet de weekcijfers + actielijsten samenvatten tot een briefing."""
    groepregels = "\n".join(f"  {g}: {v['n']} trainingen ({v['atleten']} atleten)"
                            for g, v in stats.get("groepen", {}).items())
    aandachtregels = "\n".join(
        f"  {r['naam']} ({r['ernst']}): " + "; ".join(r["signalen"])
        for r in aandacht) or "  (geen)"
    inhoud = f"""AFGELOPEN WEEK:
Trainingen uitgevoerd: {stats['n_trainingen']} (totaal ±{stats['km_totaal']} hardloop-km)
Actieve atleten: {stats['n_actief']} van {stats['n_atleten']}
Gemiddeld gevoel (1=geweldig, 5=vreselijk): {stats.get('gevoel_gem') or 'onbekend'}
Per groep:
{groepregels}
Zonder enige training deze week: {', '.join(stats['stil']) or 'niemand'}
Races gelopen: {', '.join(stats['races_gedaan']) or 'geen'}

DEZE WEEK AANDACHT:
Belasting-signalen:
{aandachtregels}
Schema loopt af of ontbreekt: {', '.join(schema_urgent) or 'niemand'}
Races komende 7 dagen: {', '.join(races_komend) or 'geen'}
Nog niet gefactureerd dit jaar: {', '.join(facturatie) or 'niemand of onbekend'}

Schrijf de briefing."""
    response = create_message(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=_BRIEFING_SYSTEM,
        messages=[{"role": "user", "content": inhoud}],
    )
    return _clean_text(response.content[0].text.strip())


def weekbriefing(athletes: list[dict], belasting_resultaten: list[dict],
                 schema_urgent: list[str], races_komend: list[str],
                 facturatie: list[str], forceer: bool = False) -> dict:
    """
    Geef de briefing van deze week; herberekent alleen bij een nieuwe week
    of forceer=True. Structuur: {week, gemaakt, tekst, stats}.
    """
    try:
        data = intake_store.load_weekbriefing()
    except Exception:
        data = {}
    wk = week_label()
    if not forceer and data.get("week") == wk:
        return data

    stats = verzamel_week(athletes)
    tekst = genereer_briefing_tekst(stats, belasting_resultaten,
                                    schema_urgent, races_komend, facturatie)
    data = {"week": wk, "gemaakt": date.today().isoformat(),
            "tekst": tekst, "stats": stats}
    try:
        intake_store.save_weekbriefing(data)
    except Exception:
        pass
    return data
