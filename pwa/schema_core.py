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


def coachbare_atleten() -> list[dict]:
    """Volledige coachbare FinalSurge-roster voor Schema bouwen (modus NIEUW).

    Een bestaande intake is een PREFILL-bron, GEEN toelatingsvoorwaarde: atleten
    zónder intake staan er óók in. Gegroepeerd per coachgroep in de CENTRALE
    FinalSurge-volgorde (get_athletes_by_group), binnen elke groep alfabetisch.
    'Los trainingsschema' hoort hier WEL zichtbaar te zijn (geen Feedback-uitsluiting)."""
    try:
        import fs_client as FS
        groepen = FS.get_athletes_by_group()     # {groep: [atleet...]}, FS-volgorde
    except Exception:
        groepen = {}
    if not groepen:
        return bouwbare_atleten()                # FS niet gekoppeld → nooit een lege pagina
    try:
        module_intakes = intake_store.load_intakes() or {}
    except Exception:
        module_intakes = {}
    laatste = _intakes()
    out = []
    for groep, leden in groepen.items():
        for a in sorted(leden, key=lambda x: str(x.get("name") or "").lower()):
            key = a.get("user_key", "")
            if not key:
                continue
            ik = intake_store.nieuwste_intake(module_intakes.get(key), laatste.get(key))
            ik = ik if isinstance(ik, dict) else {}
            out.append({
                "key": key,
                "naam": a.get("name") or key,
                "groep": groep,
                "doel": ik.get("doel", ""),
                "weken": ik.get("weken", ""),
                "trainingsdagen": ik.get("trainingsdagen", ""),
                "heeft_intake": bool(ik),        # alleen een hint; geen filter
            })
    return out


def bouwbare_atleten() -> list[dict]:
    """Atleten met een opgeslagen bouwer-intake (prefill-hint / FS-loze fallback)."""
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
            "heeft_intake": True,
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
        "mode": (config or {}).get("mode", "nieuw"),
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
    naam_vol = base.get("athlete_name") or base.get("naam")
    voornaam = base.get("naam")
    if not naam_vol or not voornaam:         # atleet zonder intake → identity uit de roster
        try:
            import fs_core
            for a in fs_core.roster():
                if a.get("user_key") == key:
                    naam_vol = naam_vol or a.get("naam") or key
                    voornaam = voornaam or a.get("voornaam") or (a.get("naam", "").split()[0] if a.get("naam") else "")
                    break
        except Exception:
            pass
    naam_vol = naam_vol or key
    voornaam = voornaam or (naam_vol.split()[0] if naam_vol and naam_vol != key else "")
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
    intake["mode"] = cfg.get("mode", "nieuw") if cfg.get("mode") in ("nieuw", "verlengen", "bijsturen") else "nieuw"
    weken_int, einddatum = _bereken_periode(
        intake.get("startdatum", ""), cfg.get("weken") or intake.get("weken"),
        cfg.get("schema_einddatum") or "")
    intake["weken"] = str(weken_int)
    intake["schema_einddatum"] = einddatum
    if cfg.get("_context"):
        intake["uploaded_summary"] = cfg["_context"]
    return intake


def _actuele_context(key: str, intake: dict) -> str:
    """Compacte, taakgerichte atleetcontext via het gedeelde masterbrein
    (athlete_context): recency/relevantie-gefilterd, geen alles-ooit. Faalt stil."""
    try:
        import athlete_context as AC
        ctx = AC.build_athlete_context(key, intake.get("athlete_name") or intake.get("naam") or "")
        return AC.to_prompt_text(AC.schema_projection(ctx))
    except Exception:
        return ""


def bekende_context(key: str) -> dict:
    """'Bekende atleetcontext' voor de UI + traceability (booleans/tellingen)."""
    try:
        import athlete_context as AC
        ctx = AC.build_athlete_context(key)
        return {"secties": AC.ui_sections(ctx), "used": AC.used_summary(ctx)}
    except Exception as e:
        return {"secties": [], "used": {}, "err": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# VERLENGEN — slimme herijking (geen nieuwe intake). Vorige blok + actuele
# werkelijkheid worden vergeleken; alleen verandering/onzekerheid gaat terug naar
# de coach. Hergebruikt het masterbrein (athlete_context) + bewezen FS-planning.
# ══════════════════════════════════════════════════════════════════════════════
_MIN_BLOK_WORKOUTS = 4        # < dit = 'los schema', niet betrouwbaar als blok (spiegelt fs_client)


def _planned_window(key: str) -> list:
    """Geplande (structured, niet-race) FS-trainingen rond heden (−120..+180 dagen),
    gesorteerd op datum. Basis om het lopende/laatste blok betrouwbaar te herkennen."""
    try:
        import fs_client as FS
        van = date.today() - timedelta(days=120)
        lijst = FS.get_planned_workouts_from(key, van, horizon_days=300)
        return sorted(lijst or [], key=lambda x: str(x.get("date"))[:10])
    except Exception:
        return []


def vorig_blok(key: str) -> dict:
    """Identificeer het lopende/laatste blok betrouwbaar. Bronvolgorde:
    (1) daadwerkelijke geplande FS-workouts (heden ± venster) → hardste bron;
    (2) opgeslagen schema-intake (laatste_intakes) als er geen FS-planning is.
    Geeft periode, laatste geplande datum, frequentie en of het blok nog loopt."""
    planned = _planned_window(key)
    intake = _nieuwste_intake(key)
    today = date.today()
    eerste = planned[0]["date"] if planned else ""
    laatste = planned[-1]["date"] if planned else ""
    n = len(planned)
    freq = None
    if n >= 2 and eerste and laatste:
        weken = max(1, ((date.fromisoformat(laatste) - date.fromisoformat(eerste)).days // 7) + 1)
        freq = round(n / weken, 1)
    # Betrouwbaar = genoeg echte geplande trainingen, óf een opgeslagen schema-intake.
    # Zonder FS-planning is er GEEN overlaprisico (niets om mee te botsen).
    betrouwbaar = (n >= _MIN_BLOK_WORKOUTS) or bool(intake.get("startdatum") or intake.get("doel"))
    loopt_nog, afgelopen_dagen = False, None
    if laatste:
        ld = date.fromisoformat(laatste)
        if ld >= today:
            loopt_nog = True
        else:
            afgelopen_dagen = (today - ld).days
    return {
        "betrouwbaar": bool(betrouwbaar),
        "bron": "finalsurge" if n else ("intake" if betrouwbaar else "onbekend"),
        "periode": {"van": eerste, "tot": laatste},
        "laatste_datum": laatste,
        "aantal_gepland": n,
        "frequentie": freq,
        "trainingsdagen_intake": intake.get("trainingsdagen", ""),
        "doel": intake.get("doel", ""),
        "loopt_nog": loopt_nog,
        "afgelopen_dagen": afgelopen_dagen,
    }


def _verleng_start(vb: dict) -> str:
    """Nieuwe start = dag ná de laatste geplande training (bewezen Streamlit-regel).
    Nooit vóór het einde van het vorige blok. Geen FS-planning → default (eerstvolgende
    maandag), coach bevestigt dan zelf."""
    laatste = vb.get("laatste_datum") or ""
    if laatste:
        try:
            return (date.fromisoformat(laatste) + timedelta(days=1)).isoformat()
        except Exception:
            pass
    return _default_start()


def _dagen_aantal(trainingsdagen: str) -> int:
    try:
        import schema_builder as SB
        return len(SB._parse_weekdagen(trainingsdagen or ""))
    except Exception:
        return 0


def _herijking(key: str, config: dict, vb: dict) -> tuple:
    """Vergelijk oud (intake/vorig blok) met actueel (athlete_context + live FS-zones).
    Produceert herijkings-items met status/zekerheid/bron. FEITEN mogen automatisch
    actualiseren (config muteren); COACHBESLUITEN nooit stil (alleen 'controleren').
    Geeft (items, ctx) terug; ctx is de al-gebouwde masterbreincontext (hergebruik)."""
    import athlete_context as AC
    ctx = AC.build_athlete_context(key, config.get("athlete_name") or config.get("naam") or "")
    tr = ctx.get("training") or {}
    health = ctx.get("health") or {}
    fb = ctx.get("feedback") or {}
    intake = _nieuwste_intake(key)
    items = []

    def add(sleutel, label, status, zekerheid, oud="", actueel="", bron="", kritiek=False):
        items.append({"sleutel": sleutel, "label": label, "status": status,
                      "zekerheid": zekerheid, "oud": str(oud), "actueel": str(actueel),
                      "bron": bron, "kritiek": bool(kritiek)})

    # 1. ZONES — feit uit FinalSurge (config_prefill zette al de live zones in config)
    oud_zones = (intake.get("zones") or "").strip()
    live_zones = (config.get("zones") or "").strip()
    if live_zones and oud_zones and live_zones != oud_zones:
        add("zones", "Zones", "veranderd", "hoog", oud_zones[:60], live_zones[:60],
            "FinalSurge (live)")
    elif live_zones:
        add("zones", "Zones", "geldig", "hoog", actueel=live_zones[:60], bron="FinalSurge")

    # 2. VOLUME — actueel gemeten volume mag als FEIT worden geactualiseerd
    km = tr.get("km_per_week")
    oud_vol = (intake.get("huidig_volume") or "").strip()
    if km:
        config["huidig_volume"] = f"{km} km/week (recent gemeten)"
        status = "veranderd" if oud_vol and str(km) not in oud_vol else "geldig"
        add("volume", "Volume", status, "hoog", oud_vol or "onbekend",
            f"{km} km/week", "trainingslog")

    # 3. FREQUENTIE — actueel = observatie (feit); GEWENST = coachbesluit (niet stil wijzigen)
    gewenst = _dagen_aantal(config.get("trainingsdagen", ""))
    runs = tr.get("runs_per_week")
    if runs and gewenst and abs(round(runs) - gewenst) >= 1:
        add("frequentie", "Gewenste frequentie", "controleren", "middel",
            f"vorig schema {gewenst}×/week", f"recent ~{round(runs)}×/week uitgevoerd",
            "trainingslog", kritiek=False)
    elif gewenst:
        add("frequentie", "Frequentie", "geldig", "middel",
            actueel=f"{gewenst}×/week", bron="vorig schema")

    # 4. TRAININGSDAGEN — welke dagen blijft een coach-check (haalbaarheid), niet stil wijzigen
    if config.get("trainingsdagen"):
        add("trainingsdagen", "Trainingsdagen nog haalbaar?", "controleren", "middel",
            actueel=config.get("trainingsdagen"), bron="vorig schema")
    else:
        add("trainingsdagen", "Trainingsdagen onbekend", "controleren", "laag",
            bron="—")

    # 5. DOEL
    if config.get("doel"):
        add("doel", "Doel blijft hoofddoel?", "controleren", "middel",
            actueel=config.get("doel"), bron="vorig schema")

    # 6. ONDERBREKING — actief aandachtspunt (belastbaarheid), kritiek
    if tr.get("onderbreking"):
        add("onderbreking", "Onderbreking", "aandacht", "hoog",
            actueel=tr["onderbreking"], bron="trainingslog", kritiek=True)

    # 7. KLACHTEN — recente/actuele klachten, kritiek
    for k in (health.get("actuele_klachten") or []):
        add("klacht", "Actuele klacht", "aandacht", "hoog",
            actueel=f"{k.get('tekst','')} ({k.get('bron','')}, {k.get('datum','')})",
            bron=k.get("bron", ""), kritiek=True)

    # 8. BELASTING-SIGNAAL — verse hoge belasting, kritiek
    bs = fb.get("belasting_signaal")
    if bs:
        add("belasting", "Belastingsignaal", "aandacht", "hoog",
            actueel=f"{bs.get('ernst','')}: " + "; ".join(bs.get("signalen") or []),
            bron="belasting-stand", kritiek=True)

    # 9. BEPERKTE RECENTE DATA — context, geen blokkade
    if not km and not runs:
        add("data", "Beperkte recente trainingsdata", "aandacht", "middel",
            actueel="weinig/geen recente uitvoering — herijk belastbaarheid conservatief",
            bron="trainingslog", kritiek=False)

    return items, ctx


def _verleng_vragen(key: str, config: dict, ctx: dict) -> list:
    """Mini-update: alléén vragen waarvan BeBetter het antwoord NIET al kent.
    In deze slice in-app door de coach te beantwoorden (niet extern verstuurd)."""
    vragen = []
    if not (config.get("trainingsdagen") or "").strip():
        vragen.append({"sleutel": "trainingsdagen",
                       "vraag": "Op welke dagen kan de atleet de komende weken trainen?"})
    if not (ctx.get("recovery")):
        vragen.append({"sleutel": "werk_slaap",
                       "vraag": "Is het werk-/slaapritme de afgelopen weken veranderd?"})
    # Vakantie/afwezigheid kunnen we nooit uit data weten → altijd zinvol, maar optioneel.
    vragen.append({"sleutel": "afwezig",
                   "vraag": "Zijn er vakanties of periodes met minder trainingsruimte?"})
    return vragen[:4]


def _verleng_readiness(config: dict, vb: dict, items: list) -> dict:
    """Rijk readiness-model: klaar / controle / geblokkeerd. Blokkeer alléén op een
    echte harde voorwaarde (geen doel/zones, ongeldige atleet). Weinig data, net
    afgelopen blok of een onderbreking blokkeren NIET — die zijn juist context."""
    if not config.get("athlete_key"):
        return {"status": "geblokkeerd", "reden": "Ongeldige atleet.", "ontbreekt": ["atleet"]}
    ontbreekt = []
    if not (config.get("doel") or "").strip():
        ontbreekt.append("doel")
    if not (config.get("zones") or "").strip():
        ontbreekt.append("zones")
    if ontbreekt:
        return {"status": "geblokkeerd",
                "reden": "Kernconfig ontbreekt: " + ", ".join(ontbreekt), "ontbreekt": ontbreekt}
    kritiek = [i for i in items if i["status"] == "aandacht" and i.get("kritiek")]
    controle = [i for i in items if i["status"] == "controleren"]
    if kritiek or controle:
        return {"status": "controle", "kritiek": len(kritiek), "controle": len(controle),
                "te_controleren": len(kritiek) + len(controle)}
    return {"status": "klaar"}


def verleng_prefill(key: str) -> dict:
    """Verlengen-ingang: oud (intake) als basis → herijkt met actuele werkelijkheid.
    Geeft config (mode=verlengen, start ná laatste geplande training) + vorig_blok +
    herijking + readiness + mini-update-vragen. Eén assembled config voedt daarna de
    bewezen Nieuw-flow (plan→chat→workbench→publish) ongewijzigd."""
    prefill = config_prefill(key)                 # basis: intake + live FS-zones
    config = prefill["config"]
    config["mode"] = "verlengen"
    vb = vorig_blok(key)
    config["startdatum"] = _verleng_start(vb)
    config["_verleng_laatste"] = vb.get("laatste_datum", "")
    weken_int, einddatum = _bereken_periode(config["startdatum"], config.get("weken") or "8", "")
    config["weken"] = str(weken_int)
    config["schema_einddatum"] = einddatum
    items, ctx = _herijking(key, config, vb)      # kan config muteren (feiten actualiseren)
    vragen = _verleng_vragen(key, config, ctx)
    readiness = _verleng_readiness(config, vb, items)
    return {
        "config": config, "context": context_config(config), "afspraken": afspraken(config),
        "vorig_blok": vb, "herijking": items, "readiness": readiness, "vragen": vragen,
    }


def _overlap_errors(key: str, config: dict, inc: list) -> list:
    """Verlengen: alleen TOEVOEGEN ná het bestaande blok. Een included row op/vóór de
    laatste geplande datum = blokkerende overlap (geen delete/overwrite)."""
    if (config or {}).get("mode") != "verlengen" or not inc:
        return []
    laatste = (config or {}).get("_verleng_laatste") or ""
    if not laatste:
        laatste = vorig_blok(key).get("laatste_datum") or ""
    if not laatste:
        return []                                 # geen bestaand blok → geen overlaprisico
    bad = [str(r["date"])[:10] for r in inc
           if _valid_date(r.get("date")) and str(r["date"])[:10] <= laatste]
    if bad:
        return [f"Overlap met het bestaande blok: {len(bad)} training(en) op/vóór de laatste "
                f"geplande datum ({laatste}). Een verlenging voegt alléén ná het bestaande "
                f"blok toe — verzet de startdatum."]
    return []


def genereer_plan_config(key: str, config: dict) -> dict:
    """Conceptplan (AI) uit de coach-config. Bouwt eenmalig de gedeelde atleetcontext
    (masterbrein) en geeft die als context_blob + traceability terug zodat de chat
    'm hergebruikt (geen refetch)."""
    intake = _intake_from_config(key, config)
    context_blob = (config or {}).get("_context", "")
    context_used = {}
    if not context_blob:
        try:
            import athlete_context as AC
            actx = AC.build_athlete_context(key, intake.get("athlete_name") or intake.get("naam") or "")
            context_blob = AC.to_prompt_text(AC.schema_projection(actx))
            context_used = AC.used_summary(actx)
        except Exception:
            context_blob = ""
        if context_blob:
            intake["uploaded_summary"] = context_blob
    import schema_builder as SB
    plan = SB.generate_plan(intake)
    return {"plan": plan, "context_blob": context_blob, "context_used": context_used,
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


# ══════════════════════════════════════════════════════════════════════════════
# Slice 3 — veilige publicatie naar FinalSurge (preview → expliciete write)
# Enige write-input = de canonieke workbench-rows (included + edits). Hergebruikt
# de bewezen import_to_finalsurge PER RIJ → exacte per-rij-status, echte partial-
# failure en retry-alleen-mislukte. Geen tweede importer, geen optimistic success.
# ══════════════════════════════════════════════════════════════════════════════

def _included(rows: list) -> list:
    return [r for r in (rows or []) if r.get("included", True)]


def _valid_date(s) -> bool:
    try:
        date.fromisoformat(str(s)[:10]); return True
    except Exception:
        return False


def validate_rows(key: str, rows: list) -> list:
    """Deterministische server-side validatie vóór ELKE externe write. Backend is
    beslissend (frontend-validatie is alleen UX)."""
    errs = []
    if not key:
        errs.append("Geen atleet gekoppeld.")
    if not rows:
        errs.append("Geen trainingen in het schema.")
    inc = _included(rows)
    if rows and not inc:
        errs.append("Geen enkele training geselecteerd.")
    seen = set()
    for r in inc:
        rid = r.get("id")
        if rid in seen:
            errs.append(f"Dubbele training-id in de payload ({rid}).")
        seen.add(rid)
        d = r.get("date")
        if not _valid_date(d):
            errs.append(f"Ongeldige datum: {d}")
        if not (r.get("name") or "").strip():
            errs.append(f"Naam ontbreekt ({d}).")
        at = (r.get("activity_type") or "").strip()
        if not at:
            errs.append(f"Trainingstype ontbreekt ({d}).")
        for val, lbl in ((r.get("planned_km"), "afstand"), (r.get("planned_min"), "duur")):
            if val in (None, ""):
                continue
            try:
                if float(val) < 0:
                    errs.append(f"Negatieve {lbl} ({d}).")
            except (TypeError, ValueError):
                errs.append(f"Ongeldige {lbl} ({d}).")
    return errs


def _to_write_row(r: dict) -> dict:
    """Canonieke row → import_to_finalsurge-vorm (edits zitten al in de row)."""
    return {
        "date": r.get("date"),
        "name": r.get("name") or r.get("activity_type") or "Training",
        "description": r.get("description", ""),
        "activity_type": r.get("activity_type", "Run"),
        "planned_km": r.get("planned_km"),
        "planned_min": r.get("planned_min"),
    }


def _dup_status(inc: list, bestaand: list) -> dict:
    """Classificeer per included-row t.o.v. bestaande geplande FS-workouts:
    nieuw / bestaande_op_datum / mogelijk_duplicaat. Geen agressieve fuzzy match."""
    per_datum = {}
    for b in bestaand or []:
        per_datum.setdefault(str(b.get("date"))[:10], []).append(b)
    out = {}
    for r in inc:
        d = str(r.get("date"))[:10]
        ex = per_datum.get(d, [])
        if not ex:
            out[r.get("id")] = "nieuw"
            continue
        nm = (r.get("name") or "").strip().lower()
        match = any(nm and nm == (str(b.get("name") or "").strip().lower()) for b in ex)
        out[r.get("id")] = "mogelijk_duplicaat" if match else "bestaande_op_datum"
    return out


def _bestaande_in_range(key: str, van: str, tot: str) -> list:
    """Eén read van bestaande geplande FS-workouts in de datumrange (read-before-write)."""
    try:
        import fs_client as FS
        lijst = FS.get_planned_workouts_from(key, date.fromisoformat(van))
        return [b for b in (lijst or []) if str(b.get("date"))[:10] <= tot]
    except Exception:
        return []


def _n_builder(inc: list) -> int:
    return sum(1 for r in inc
              if r.get("activity_type") in ("Run", "Bike", "Swim") and (r.get("description") or "").strip())


def publish_preview(key: str, config: dict, rows: list) -> dict:
    """Write-preview: validatie + read-before-write duplicaatcheck. GEEN write."""
    errs = validate_rows(key, rows)
    inc = _included(rows)
    errs = errs + _overlap_errors(key, config, inc)   # verlengen: overlap = blokkerend
    dup, date_range, conflicts = {}, None, 0
    if inc and not errs:
        dates = sorted(str(r["date"])[:10] for r in inc if _valid_date(r.get("date")))
        if dates:
            date_range = {"van": dates[0], "tot": dates[-1]}
            bestaand = _bestaande_in_range(key, dates[0], dates[-1])
            dup = _dup_status(inc, bestaand)
            conflicts = sum(1 for s in dup.values() if s in ("mogelijk_duplicaat", "bestaande_op_datum"))
    items = [{
        "id": r.get("id"), "date": r.get("date"), "activity_type": r.get("activity_type", "Run"),
        "name": r.get("name", ""), "planned_km": r.get("planned_km"), "planned_min": r.get("planned_min"),
        "status": dup.get(r.get("id"), "nieuw"),
    } for r in inc]
    return {
        "valid": not errs, "errors": errs, "date_range": date_range,
        "counts": {"included": len(inc), "excluded": len(rows or []) - len(inc),
                   "edited": sum(1 for r in inc if r.get("edited")),
                   "conflicts": conflicts, "builder": _n_builder(inc)},
        "items": items,
    }


# Idempotency: per write_id onthouden welke rij-signatures al succesvol geschreven
# zijn (dubbelklik/retry/timeout → nooit dubbel schrijven). In-memory volstaat voor
# de sessie; de read-before-write preview vangt reeds bestaande duplicaten los daarvan.
_WRITE_RECEIPTS: dict = {}


def _row_sig(r: dict) -> str:
    return f"{str(r.get('date'))[:10]}|{(r.get('name') or '').strip().lower()}|{r.get('planned_km')}|{r.get('planned_min')}"


def _audit(key: str, mode: str, attempted: int, ok: int, fail: int, builderfail: int, date_range) -> None:
    """Compacte write-receipt in de log — GEEN workoutbeschrijvingen/gevoelige tekst."""
    try:
        print("[schema_write]", {
            "athlete": key, "ts": datetime.now().isoformat(timespec="seconds"),
            "mode": mode or "nieuw",
            "attempted": attempted, "success": ok, "failed": fail, "builder_failed": builderfail,
            "range": date_range,
        })
    except Exception:
        pass


def publish(key: str, config: dict, rows: list, write_id: str = "") -> dict:
    """Publiceer included rows naar FinalSurge. Per rij via import_to_finalsurge →
    exacte status. success=blijvend (nooit opnieuw), builder_failed=workout bestaat
    (nooit opnieuw aanmaken), failed=retry-eligible. Backend is de waarheid."""
    inc = _included(rows)
    errs = validate_rows(key, rows) + _overlap_errors(key, config, inc)
    if errs:
        raise ValueError("; ".join(errs))
    intake = _intake_from_config(key, config)
    _zt = intake.get("zone_type", "tempo")
    zone_type = "heart_rate" if _zt in ("hartslag", "heart_rate") else "pace"
    op_tijd = bool(intake.get("op_tijd"))
    import schema_builder as SB
    receipt = _WRITE_RECEIPTS.setdefault(write_id or "anon", {"success": set()})
    done = receipt["success"]

    results, ok, fail, builderfail, skipped = [], 0, 0, 0, 0
    for r in inc:
        sig = _row_sig(r)
        if sig in done:                                   # idempotent: al geschreven
            results.append({"id": r.get("id"), "status": "success", "skipped": True}); ok += 1; skipped += 1
            continue
        try:
            o, e, be = SB.import_to_finalsurge(
                athlete_key=key, workouts=[_to_write_row(r)], zone_type=zone_type,
                fill_builder=True, op_tijd=op_tijd)
        except Exception as ex:
            results.append({"id": r.get("id"), "status": "failed", "err": str(ex)[:200]}); fail += 1
            continue
        if o == 1 and not be:
            done.add(sig); results.append({"id": r.get("id"), "status": "success"}); ok += 1
        elif o == 1:                                      # workout ok, builder faalde → nooit opnieuw aanmaken
            done.add(sig); builderfail += 1
            results.append({"id": r.get("id"), "status": "builder_failed", "err": (be[0] if be else "")[:200]}); ok += 1
        else:
            results.append({"id": r.get("id"), "status": "failed", "err": (e[0] if e else "onbekend")[:200]}); fail += 1

    dates = sorted(str(r["date"])[:10] for r in inc if _valid_date(r.get("date")))
    dr = {"van": dates[0], "tot": dates[-1]} if dates else None
    _audit(key, (config or {}).get("mode", "nieuw"), len(inc), ok, fail, builderfail, dr)
    return {
        "results": results,
        "counts": {"attempted": len(inc), "success": ok, "failed": fail,
                   "builder_failed": builderfail, "skipped": skipped},
        "state": "success" if fail == 0 else "partial_failure",
    }


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
