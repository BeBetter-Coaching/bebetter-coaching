"""Schemabouwer voor de PWA — intake -> AI-plan -> CSV (download).

Hergebruikt schema_builder.py (dezelfde AI-prompts en -logica als Streamlit) op
de GEDEELDE opslag. Vereist ANTHROPIC_API_KEY (staat op Render). De FinalSurge-
push (import_to_finalsurge) slaan we bewust over — dat is de rode stap; in de PWA
lever je het schema als CSV-download die je in FinalSurge importeert.

V1 hergebruikt de intake die de coach al per atleet in de bouwer opsloeg
(save_laatste_intake / load_laatste_intakes), zodat je niet 33 velden opnieuw
hoeft in te vullen: kies een atleet met opgeslagen intake -> plan -> CSV. Het
volledige intake-formulier in de PWA volgt later.

BELANGRIJK: schema_builder wordt LUI geïmporteerd (binnen de functies), want het
importeert ai_client -> anthropic.Anthropic() dat zonder key al bij import crasht.
Zo blijft het laden van deze module (en dus de app-boot) veilig, ook zonder key.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

_HIER = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HIER)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import intake_store                                    # veilig: geen AI-import


def heeft_key() -> bool:
    """Staat de Anthropic-sleutel gezet? Zonder key kan er geen plan gemaakt worden."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _intakes() -> dict:
    try:
        return intake_store.load_laatste_intakes() or {}
    except Exception:
        return {}


def bouwbare_atleten() -> list[dict]:
    """Atleten met een opgeslagen bouwer-intake (klaar om een plan te maken)."""
    out = []
    for key, intake in _intakes().items():
        if not isinstance(intake, dict):
            continue
        out.append({
            "key": key,
            "naam": intake.get("athlete_name") or intake.get("naam") or key,
            "doel": intake.get("doel", ""),
            "weken": intake.get("weken", ""),
            "trainingsdagen": intake.get("trainingsdagen", ""),
        })
    out.sort(key=lambda a: str(a["naam"]).lower())
    return out


def get_intake(key: str):
    intake = _intakes().get(key)
    if not isinstance(intake, dict):
        return None
    intake = dict(intake)
    intake.setdefault("athlete_key", key)
    return intake


def context(key: str) -> dict:
    """Compacte workbench-context (header) voor één atleet — puur uit de intake.

    Geen nieuwe waarheid: leest de reeds opgeslagen bouwer-intake. Zonebron is
    afgeleid van zone_type (zones-tekst blijft de enige intensiteitswaarheid).
    """
    intake = get_intake(key) or {}
    _zt = intake.get("zone_type", "tempo")
    return {
        "naam": intake.get("athlete_name") or intake.get("naam") or key,
        "voornaam": intake.get("naam", ""),
        "doel": intake.get("doel", ""),
        "weken": intake.get("weken", ""),
        "trainingsdagen": intake.get("trainingsdagen", ""),
        "startdatum": intake.get("startdatum", ""),
        "zone_bron": "hartslag" if _zt in ("hartslag", "heart_rate") else "tempo",
        "mode": intake.get("mode", "nieuw"),
    }


def _startweek_maandag(startdatum_str: str):
    """Maandag van de startweek (of None). Basis van de maandag-uitlijning."""
    try:
        d = datetime.strptime(startdatum_str, "%Y-%m-%d")
        return d - timedelta(days=d.weekday())
    except Exception:
        return None


def groepeer_weken(rijen: list, startdatum_str: str) -> list:
    """Groepeer canonieke rows deterministisch per maandag-week.

    Hergebruikt EXACT de bewezen Streamlit-weeklogica (builder stap 3):
    weeknummer = (datum - maandag_van_startweek) // 7 + 1. Geen tweede/andere
    weekberekening. Kent elke row een stabiele `id` toe (positie in de
    CSV-parse) zodat include/exclude en edits later betrouwbaar te koppelen zijn.
    Muteert de rows in-place met `id` — de platte `rijen` in de response delen
    dezelfde dicts, dus die krijgen ook een id.
    """
    start_monday = _startweek_maandag(startdatum_str)
    for i, w in enumerate(rijen):
        w.setdefault("id", f"r{i}")

    buckets: dict = defaultdict(list)
    for w in rijen:
        try:
            dt = datetime.strptime(w.get("date", ""), "%Y-%m-%d")
        except Exception:
            dt = None
        if start_monday and dt:
            wk = (dt - start_monday).days // 7 + 1
        elif dt:
            wk = dt.isocalendar()[1]        # geen startdatum → ISO-week (stabiel)
        else:
            wk = 0
        buckets[wk].append(w)

    weken = []
    for wk in sorted(buckets):
        rows = sorted(buckets[wk], key=lambda w: w.get("date", ""))
        total_km = round(sum((w.get("planned_km") or 0) for w in rows))
        if start_monday and wk >= 1:
            mon = start_monday + timedelta(weeks=wk - 1)
            sun = mon + timedelta(days=6)
            datumrange = f"{mon.day}/{mon.month} – {sun.day}/{sun.month}"
            week_start = mon.strftime("%Y-%m-%d")
            label = f"Week {wk}"
        else:
            datumrange = ""
            week_start = rows[0].get("date", "") if rows else ""
            label = f"Week {wk}" if wk else "Overig"
        weken.append({
            "week_index": wk,
            "week_start": week_start,
            "label": label,
            "datumrange": datumrange,
            "total_km": total_km,
            "rows": rows,
        })
    return weken


def genereer_plan(key: str) -> str:
    """Genereer de plan-tekst (AI). Vereist een opgeslagen intake + de sleutel."""
    intake = get_intake(key)
    if not intake:
        raise ValueError("Geen opgeslagen intake voor deze atleet. "
                         "Vul de bouwer-intake eerst in (Streamlit).")
    import schema_builder as SB                         # lui: pas hier is de key nodig
    return SB.generate_plan(intake)


def genereer_csv(key: str, plan_tekst: str):
    """Genereer de CSV op basis van het plan (AI). Geeft (csv_tekst, rijen) terug."""
    if not (plan_tekst or "").strip():
        raise ValueError("Geen plan om een CSV van te maken.")
    intake = get_intake(key)
    if not intake:
        raise ValueError("Geen opgeslagen intake voor deze atleet.")
    import schema_builder as SB                         # lui
    csv_tekst = SB.generate_csv(plan_tekst, intake)
    csv_clean = SB.extract_csv_block(csv_tekst)
    rijen = SB.parse_csv_text(csv_tekst)
    weken = groepeer_weken(rijen, intake.get("startdatum", ""))
    return csv_clean, rijen, weken


# ══════════════════════════════════════════════════════════════════════════════
# Slice 2 — PWA-configuratie (modus NIEUW) + AI plan-sparfase
# Eén assembled intake-dict uit de coach-config voedt generate_plan / chat_about_plan
# / generate_csv → alles blijft consistent (weekkalender, harde eisen, zones).
# Hergebruikt de bewezen Streamlit-kern; geen tweede chatprotocol of parser.
# ══════════════════════════════════════════════════════════════════════════════

def _nieuwste_intake(key: str) -> dict:
    """Nieuwste intake uit BEIDE bakjes (intake-module + bouwer-snapshot), net als de
    Streamlit-bouwer. Puur lezen; geen nieuw datamodel."""
    try:
        intakes = intake_store.load_intakes() or {}
    except Exception:
        intakes = {}
    try:
        laatste = intake_store.load_laatste_intakes() or {}
    except Exception:
        laatste = {}
    rec = intake_store.nieuwste_intake(intakes.get(key), laatste.get(key))
    return dict(rec) if isinstance(rec, dict) else {}


def _default_start() -> str:
    """Eerstvolgende maandag (zelfde default als de Streamlit-bouwer)."""
    v = date.today()
    return (v + timedelta(days=(7 - v.weekday()))).isoformat()


def _bereken_periode(startdatum: str, weken, schema_einddatum: str) -> tuple:
    """Maandag-uitgelijnd, identiek aan de Streamlit-bouwer. Geeft (weken_int, einddatum_iso).
    Weken → einddatum → weken telt consistent terug (geen off-by-one)."""
    try:
        start = date.fromisoformat(startdatum)
    except Exception:
        return (int(weken or 8), schema_einddatum or "")
    sm = start - timedelta(days=start.weekday())
    end = None
    if schema_einddatum:
        try:
            end = date.fromisoformat(schema_einddatum)
        except Exception:
            end = None
    if end is None:
        wk = int(weken or 8)
        end = sm + timedelta(weeks=wk) - timedelta(days=1)
    es = end + timedelta(days=(6 - end.weekday()))
    weken_int = max(1, ((es - sm).days + 1) // 7)
    return (weken_int, end.isoformat())


def context_config(config: dict) -> dict:
    """Workbench-/header-context afgeleid van de (bewerkte) coach-config."""
    zt = (config or {}).get("zone_type")
    return {
        "naam": config.get("athlete_name") or config.get("naam") or "",
        "voornaam": config.get("naam", ""),
        "doel": config.get("doel", ""),
        "weken": config.get("weken", ""),
        "trainingsdagen": config.get("trainingsdagen", ""),
        "startdatum": config.get("startdatum", ""),
        "zone_bron": "hartslag" if zt in ("hartslag", "heart_rate") else "tempo",
        "mode": "nieuw",
    }


def afspraken(config: dict) -> list:
    """Deterministische 'Schema-afspraken' uit DEZELFDE bronvelden als
    _harde_eisen_secties (trainingsdagen, variatie, zones, mode). Geen parallelle regels."""
    import schema_builder as SB
    cfg = config or {}
    dagen = SB._parse_weekdagen(cfg.get("trainingsdagen", ""))
    out = []
    if cfg.get("doel"):
        out.append(f"Doel: {cfg['doel']}")
    if cfg.get("weken"):
        out.append(f"Periode: {cfg['weken']} weken · start {cfg.get('startdatum', '?')}")
    if dagen:
        namen = ", ".join(SB._WEEKDAG_NL[d] for d in dagen)
        out.append(f"Trainingsdagen ({len(dagen)}/week): {namen}")
    else:
        out.append("Trainingsdagen: nog niet gekozen — de AI kiest ze dan zelf")
    zt = "hartslag" if cfg.get("zone_type") in ("hartslag", "heart_rate") else "tempo"
    out.append(f"Zones ({zt}): {cfg.get('zones') or '—'}")
    if cfg.get("huidig_volume"):
        out.append(f"Huidig volume: {cfg['huidig_volume']}")
    if cfg.get("race_prioriteit"):
        out.append(f"Race: {cfg['race_prioriteit']}")
    if cfg.get("tussenraces"):
        out.append(f"Tussenraces: {cfg['tussenraces']}")
    if cfg.get("blessurehistorie"):
        out.append(f"Let op: {cfg['blessurehistorie']}")
    if cfg.get("coach_notitie"):
        out.append(f"Coachinstructie: {cfg['coach_notitie'].splitlines()[0]}")
    out.append("Variatie verplicht; op elke trainingsdag een training (bewezen harde eisen).")
    return out


def config_prefill(key: str) -> dict:
    """Slimme prefill voor modus NIEUW uit bestaande atleet-/intakecontext + FS-zones.
    Snel: geen zware sweep (trainingslog volgt pas bij plan-generatie)."""
    base = _nieuwste_intake(key)
    naam_vol = base.get("athlete_name") or base.get("naam") or key
    voornaam = base.get("naam") or (naam_vol.split()[0] if naam_vol else "")
    zones_text = base.get("zones", "")
    zone_type = base.get("zone_type", "tempo")
    try:
        import fs_client as FS
        fetched = FS.get_athlete_zones(key) or {}
        if fetched.get("zones_text"):
            zones_text = fetched["zones_text"]
            zone_type = fetched.get("zone_type", zone_type)
    except Exception:
        pass
    start = base.get("startdatum") or _default_start()
    weken_int, einddatum = _bereken_periode(start, base.get("weken") or "8",
                                             base.get("schema_einddatum", ""))
    config = {
        "athlete_key": key, "naam": voornaam, "athlete_name": naam_vol,
        "doel": base.get("doel", ""), "startdatum": start, "weken": str(weken_int),
        "schema_einddatum": einddatum, "wedstrijddatum": base.get("wedstrijddatum", ""),
        "trainingsdagen": base.get("trainingsdagen", ""),
        "huidig_volume": base.get("huidig_volume", ""),
        "tijd_per_training": base.get("tijd_per_training", ""),
        "zone_type": "hartslag" if zone_type in ("hartslag", "heart_rate") else "tempo",
        "zones": zones_text, "race_prioriteit": base.get("race_prioriteit", ""),
        "tussenraces": base.get("tussenraces", ""), "coach_notitie": base.get("coach_notitie", ""),
        "referentie_prestatie": base.get("referentie_prestatie", ""),
        "blessurehistorie": base.get("blessurehistorie", ""),
        "andere_sporten": base.get("andere_sporten", ""), "op_tijd": base.get("op_tijd", False),
        "_context": "",   # zware actuele context — pas bij plan-generatie gevuld
    }
    return {"config": config, "context": context_config(config), "afspraken": afspraken(config)}


def _intake_from_config(key: str, config: dict) -> dict:
    """Assembleer de bewezen intake-dict uit de (bewerkte) coach-config, aangevuld met
    de opgeslagen intake voor niet-bewerkte velden. Dit is de ENIGE planbron."""
    intake = _nieuwste_intake(key)
    cfg = config or {}
    for f in ("naam", "athlete_name", "doel", "startdatum", "trainingsdagen",
              "huidig_volume", "tijd_per_training", "zone_type", "zones",
              "race_prioriteit", "tussenraces", "coach_notitie", "wedstrijddatum",
              "referentie_prestatie", "blessurehistorie", "andere_sporten", "op_tijd"):
        if f in cfg and cfg.get(f) not in (None, ""):
            intake[f] = cfg[f]
    intake["athlete_key"] = key
    intake["athlete_name"] = cfg.get("athlete_name") or intake.get("athlete_name") or key
    intake["mode"] = "nieuw"
    weken_int, einddatum = _bereken_periode(
        intake.get("startdatum", ""), cfg.get("weken") or intake.get("weken"),
        cfg.get("schema_einddatum") or "")
    intake["weken"] = str(weken_int)
    intake["schema_einddatum"] = einddatum
    if cfg.get("_context"):
        intake["uploaded_summary"] = cfg["_context"]
    return intake


def _actuele_context(key: str, intake: dict) -> str:
    """Bounded, best-effort recente atleetcontext via BEWEZEN datapaden: Garmin-herstel
    + kalenderlabels + trainingslog (4 mnd). Recency/relevantie i.p.v. alles-ooit; faalt
    stil. Later verplaatsbaar naar een gedeelde athlete-context (masterbrein-richting)."""
    try:
        import fs_client as FS
        import schema_builder as SB
    except Exception:
        return ""
    delen = []
    try:
        g = intake_store.garmin_context_text(key)
        if g:
            delen.append(g)
    except Exception:
        pass
    try:
        start = date.fromisoformat(intake.get("startdatum", ""))
        weken = int(intake.get("weken") or 8)
        labels = FS.get_calendar_labels(key, start - timedelta(days=7),
                                        start + timedelta(days=weken * 7 + 7))
        if labels:
            regels = [f"  - {l['start_date']}"
                      f"{(' t/m ' + l['end_date']) if l.get('end_date') and l['end_date'] != l['start_date'] else ''}"
                      f": {l['name']}" for l in labels]
            delen.append("KALENDER-LABELS (verplicht verwerken):\n" + "\n".join(regels))
    except Exception:
        pass
    try:
        log = FS.get_training_log(key, months=4)
        if log:
            delen.append(SB.format_training_log(log)[:9000])
    except Exception:
        pass
    return "\n\n".join(delen)


def genereer_plan_config(key: str, config: dict) -> dict:
    """Conceptplan (AI) uit de coach-config. Vult eenmalig de zware actuele context en
    geeft die als context_blob terug zodat de chat 'm hergebruikt (geen refetch)."""
    intake = _intake_from_config(key, config)
    context_blob = (config or {}).get("_context", "")
    if not context_blob:
        context_blob = _actuele_context(key, intake)
        if context_blob:
            intake["uploaded_summary"] = context_blob
    import schema_builder as SB
    plan = SB.generate_plan(intake)
    return {"plan": plan, "context_blob": context_blob,
            "afspraken": afspraken(config), "context": context_config(config)}


_PU_START = "===PLAN UPDATE==="
_PU_END = "===EINDE PLAN==="


def _split_plan_update(reply: str) -> dict:
    """Bewezen Streamlit-protocol: markers → volledig bijgewerkt plan (atomair).
    Zonder markers = gewone sparreactie (plan onveranderd). Half → truncated."""
    r = reply or ""
    if _PU_START in r and _PU_END in r:
        new_plan = r.split(_PU_START, 1)[1].split(_PU_END, 1)[0].strip()
        display = r.split(_PU_START, 1)[0].strip() or "Plan bijgewerkt."
        return {"reply": display, "plan_updated": bool(new_plan), "plan": new_plan, "truncated": False}
    if _PU_START in r:
        partial = r.split(_PU_START, 1)[1].strip()
        display = r.split(_PU_START, 1)[0].strip() or "Plan deels bijgewerkt (respons afgekapt)."
        return {"reply": display, "plan_updated": bool(partial), "plan": partial, "truncated": True}
    return {"reply": r.strip(), "plan_updated": False, "plan": "", "truncated": False}


def chat_plan(key: str, config: dict, plan: str, history: list) -> dict:
    """Spar over het actieve plan (hergebruikt schema_builder.chat_about_plan)."""
    if not (plan or "").strip():
        raise ValueError("Geen actief plan om over te sparren.")
    intake = _intake_from_config(key, config)
    import schema_builder as SB
    reply = SB.chat_about_plan(plan, intake, history or [])
    return _split_plan_update(reply)


def genereer_csv_config(key: str, config: dict, plan_tekst: str):
    """Bouw het schema (CSV→rows→weken) uit de ACTUELE planversie + de coach-config."""
    if not (plan_tekst or "").strip():
        raise ValueError("Geen plan om een schema van te maken.")
    intake = _intake_from_config(key, config)
    import schema_builder as SB
    csv_tekst = SB.generate_csv(plan_tekst, intake)
    csv_clean = SB.extract_csv_block(csv_tekst)
    rijen = SB.parse_csv_text(csv_tekst)
    weken = groepeer_weken(rijen, intake.get("startdatum", ""))
    return csv_clean, rijen, weken


def push(key: str, csv_tekst: str) -> dict:
    """Zet de trainingen uit de CSV op de FinalSurge-kalender van de atleet.

    WRITE-actie. Hergebruikt exact `schema_builder.import_to_finalsurge` (beproefd
    in de Streamlit-bouwer): zelfde zone_type-mapping, fill_builder en op_tijd.
    Voegt trainingen TOE (wist bestaande niet). Geeft een resultaat-dict terug.
    """
    intake = get_intake(key)
    if not intake:
        raise ValueError("Geen opgeslagen intake voor deze atleet.")
    ak = intake.get("athlete_key", "")
    if not ak:
        raise ValueError("Geen FinalSurge-koppeling (athlete_key) voor deze atleet.")
    import schema_builder as SB
    rijen = SB.parse_csv_text(csv_tekst or "")
    if not rijen:
        raise ValueError("Geen trainingen in de CSV om te pushen.")
    _zt = intake.get("zone_type", "tempo")
    zone_type = "heart_rate" if _zt in ("hartslag", "heart_rate") else "pace"
    ok, fouten, builder_fouten = SB.import_to_finalsurge(
        athlete_key=ak, workouts=rijen, zone_type=zone_type,
        fill_builder=True, op_tijd=intake.get("op_tijd", False))
    return {"ok_aantal": ok, "totaal": len(rijen),
            "fouten": fouten or [], "builder_fouten": builder_fouten or []}
