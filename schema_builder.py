"""Schema bouwen — AI trainingsplan generator voor BeBetter Coaching."""

from __future__ import annotations

import re
import io
import csv
import math
import base64
import time
from datetime import date, datetime
from typing import Optional

import intake_store
from ai_client import create_message


# ---------------------------------------------------------------------------
# VDOT berekening (Jack Daniels)
# ---------------------------------------------------------------------------

def _vo2_at_velocity(v: float) -> float:
    """VO2 vereist voor snelheid v (m/min)."""
    return -4.60 + 0.182258 * v + 0.000104 * v ** 2


def _pct_vo2max_at_time(t_min: float) -> float:
    """Fractie van VO2max vol te houden gedurende t minuten."""
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def _velocity_at_pct_vo2max(pct: float, vdot: float) -> float:
    """Snelheid (m/min) bij gegeven percentage van VO2max."""
    target = pct * vdot
    # Kwadratische formule: 0.000104*v² + 0.182258*v + (-4.60 - target) = 0
    a, b, c = 0.000104, 0.182258, -4.60 - target
    disc = b ** 2 - 4 * a * c
    if disc < 0:
        return 0.0
    return (-b + math.sqrt(disc)) / (2 * a)


def _sec_to_pace(v_m_per_min: float) -> str:
    """Zet snelheid (m/min) om naar min:sec/km string."""
    if v_m_per_min <= 0:
        return "—"
    sec_per_km = 1000 / v_m_per_min * 60
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}"


def calculate_vdot(distance_m: float, time_sec: float) -> float:
    """Bereken VDOT op basis van een wedstrijd- of testresultaat."""
    t_min = time_sec / 60
    v = distance_m / t_min  # m/min
    return _vo2_at_velocity(v) / _pct_vo2max_at_time(t_min)


def vdot_to_zones_text(vdot: float) -> str:
    """
    Genereer een zones-tekst (min/km) op basis van VDOT.
    Mapping naar Jack Daniels trainingsintensiteiten:
      Z1 Herstel/Easy  : 59-65% VO2max
      Z2 Aeroob/Easy   : 65-74% VO2max
      Z3 Marathon/Tempo : 80-88% VO2max
      Z4 Interval (I)  : 95-100% VO2max
      Z5 Snelheid (R)  : 105-112% VO2max
    Hogere % = sneller = lagere pace-waarde.
    """
    z1_slow = _velocity_at_pct_vo2max(0.59, vdot)
    z1_fast = _velocity_at_pct_vo2max(0.65, vdot)
    z2_slow = z1_fast
    z2_fast = _velocity_at_pct_vo2max(0.74, vdot)
    z3_slow = _velocity_at_pct_vo2max(0.80, vdot)
    z3_fast = _velocity_at_pct_vo2max(0.88, vdot)
    z4_slow = _velocity_at_pct_vo2max(0.95, vdot)
    z4_fast = _velocity_at_pct_vo2max(1.00, vdot)
    z5_slow = _velocity_at_pct_vo2max(1.05, vdot)
    z5_fast = _velocity_at_pct_vo2max(1.12, vdot)

    return (
        f"Z1 (Herstel): >{_sec_to_pace(z1_slow)} min/km\n"
        f"Z2 (Easy/Aeroob): {_sec_to_pace(z2_fast)}-{_sec_to_pace(z2_slow)} min/km\n"
        f"Z3 (Marathon/Tempo): {_sec_to_pace(z3_fast)}-{_sec_to_pace(z3_slow)} min/km\n"
        f"Z4 (Interval/VO2max): {_sec_to_pace(z4_fast)}-{_sec_to_pace(z4_slow)} min/km\n"
        f"Z5 (Snelheid/Repetitie): {_sec_to_pace(z5_fast)}-{_sec_to_pace(z5_slow)} min/km"
    )


# ---------------------------------------------------------------------------
# Bestandsextractie — PDF, DOCX, XLSX, afbeeldingen
# ---------------------------------------------------------------------------

def _detect_workout_type(name: str, description: str) -> str:
    """Geeft een label terug op basis van naam/beschrijving, voor de AI-context."""
    text = (name + " " + description).lower()
    if any(x in text for x in ["interval", "x 400", "x 800", "x 1000", "x 1200", "x 1600", "herhaling"]):
        return "INTERVAL"
    if any(x in text for x in ["tempo", "drempel", "lactaat", "threshold"]):
        return "TEMPO"
    if any(x in text for x in ["fartlek"]):
        return "FARTLEK"
    if any(x in text for x in ["progressi"]):
        return "PROGRESSIEF"
    if any(x in text for x in ["lange duurloop", "long run", "llr"]):
        return "LANGE DUURLOOP"
    if any(x in text for x in ["herstel", "recovery", "rustig"]):
        return "HERSTEL"
    return "DUURLOOP"


def _summarize_laps(laps: list) -> str:
    """
    Maak een leesbare samenvatting van lapdata.
    Detecteert of het interval-splits zijn op basis van pace-variatie.
    """
    if not laps:
        return ""

    paces = []
    for lap in laps:
        p = lap.get("pace")
        if p and ":" in str(p):
            try:
                parts = str(p).split(":")
                paces.append(int(parts[0]) * 60 + int(parts[1]))
            except Exception:
                pass

    if len(paces) < 2:
        return ""

    pace_min = min(paces)
    pace_max = max(paces)
    spread = pace_max - pace_min

    def _fmt(sec):
        return f"{sec // 60}:{sec % 60:02d}"

    # Als de spreiding groot is (>45 sec/km) → interval-patroon zichtbaar
    if spread > 45:
        return (
            f"  ⚡ Splits tonen interval-patroon: snelste {_fmt(pace_min)}/km, "
            f"traagste {_fmt(pace_max)}/km (verschil {spread}s/km — "
            f"NIET verwarren met gemiddelde pace)"
        )
    # Kleine spreiding → consistente run
    elif len(paces) >= 3:
        avg = sum(paces) // len(paces)
        return f"  → Splits consistent: gemiddeld {_fmt(avg)}/km, range {_fmt(pace_min)}-{_fmt(pace_max)}/km"

    return ""


def format_training_log(workouts: list[dict]) -> str:
    """
    Zet een lijst workout-dicts om naar compacte tekst voor de AI.
    Groepeert per week, toont geplande vs voltooide waarden, beschrijving en lapdata.

    BELANGRIJK voor de AI: de 'pace' in de summary is de GEMIDDELDE pace voor de
    HELE training. Bij intervaltrainingen is dit misleidend — de werkelijke
    intervaltempos zijn veel sneller. Gebruik de beschrijving + lap-splits om
    het echte niveau te bepalen.
    """
    if not workouts:
        return ""

    from collections import defaultdict

    by_week: dict[str, list] = defaultdict(list)
    for w in workouts:
        try:
            dt = datetime.strptime(w["date"], "%Y-%m-%d")
            week_key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
        except Exception:
            week_key = "onbekend"
        by_week[week_key].append(w)

    total = len(workouts)
    completed = sum(1 for w in workouts if w["completed"])
    races = [w for w in workouts if w.get("is_race") and w["completed"]]

    lines = [
        "TRAININGSLOG LAATSTE 3 MAANDEN (automatisch opgehaald uit FinalSurge)",
        f"Periode: {workouts[0]['date']} t/m {workouts[-1]['date']} | "
        f"{completed}/{total} trainingen voltooid ({round(completed/total*100) if total else 0}%)",
        "",
        "⚠️  LET OP — PACE INTERPRETATIE:",
        "De 'pace' per training is het GEMIDDELDE over de gehele run.",
        "Bij interval- en tempotrainingen is dit ALTIJD lager dan de werkelijke inspanning.",
        "Een 'gem. 6:00/km' bij een intervaltraining kan betekenen dat de intervals op 4:20-4:40/km liepen.",
        "Gebruik de NAAM, BESCHRIJVING en SPLITS om het echte trainingsniveau te bepalen.",
        "Ga NOOIT uit van het gemiddelde als basis voor intensiteitsplanning.",
        "",
    ]

    if races:
        lines.append("Wedstrijden/races: " + ", ".join(
            f"{r['date']} {r['name']}" + (f" ({r['actual_km']} km)" if r.get('actual_km') else "")
            for r in races
        ))
        lines.append("")

    all_week_keys = sorted(by_week.keys())
    recent_week_keys = all_week_keys[-6:]  # laatste 6 weken
    older_week_keys = all_week_keys[:-6]   # alles daarvoor

    def _render_week_full(week_key):
        """Render een week volledig (met alle details)."""
        result = []
        week_workouts = by_week[week_key]
        week_done = sum(1 for w in week_workouts if w["completed"])
        vol_km = sum(w["actual_km"] or 0 for w in week_workouts)
        vol_str = f" | {vol_km:.0f} km" if vol_km else ""
        result.append(f"[{week_key} — {week_done}/{len(week_workouts)} voltooid{vol_str}]")

        for w in week_workouts:
            status = "✓" if w["completed"] else "✗"
            wtype = _detect_workout_type(w.get("name", ""), w.get("description", ""))
            row = f"  {status} {w['date']} | [{wtype}] {w['name']}"

            plan_parts = []
            if w.get("planned_km"):
                plan_parts.append(f"{w['planned_km']} km")
            elif w.get("planned_min"):
                plan_parts.append(f"{int(w['planned_min'])} min")
            if plan_parts:
                row += f" | gepland: {', '.join(plan_parts)}"

            if w["completed"]:
                actual_parts = []
                if w.get("actual_km"):
                    actual_parts.append(f"{w['actual_km']} km")
                if w.get("actual_min"):
                    actual_parts.append(f"{int(w['actual_min'])} min")
                if w.get("pace"):
                    actual_parts.append(f"gem. {w['pace']}/km")
                if w.get("hr_avg"):
                    actual_parts.append(f"gem. HF {w['hr_avg']} bpm")
                if actual_parts:
                    row += f" | gedaan: {', '.join(actual_parts)}"
                if w.get("felt"):
                    row += f" | gevoel: {w['felt']}"
                if w.get("effort"):
                    row += f" | RPE: {w['effort']}"
            else:
                row += " | NIET VOLTOOID"

            result.append(row)

            # Beschrijving tonen (bevat de geplande structuur)
            desc = w.get("description", "").strip()
            if desc:
                desc_short = desc.split("---")[0].strip()[:300]
                result.append(f"    📋 Plan: {desc_short}")

            # Lap-splits voor recente workouts
            laps = w.get("laps") or []
            lap_summary = _summarize_laps(laps)
            if lap_summary:
                result.append(lap_summary)

            if w.get("post_notes"):
                result.append(f"    💬 Atleet: {w['post_notes'][:250]}")

        result.append("")
        return result

    def _render_week_compact(week_key):
        """Render een week als één compacte samenvattingsregel."""
        week_workouts = by_week[week_key]
        vol_km = sum(w["actual_km"] or 0 for w in week_workouts)
        types = list(dict.fromkeys(
            _detect_workout_type(w.get("name", ""), w.get("description", ""))
            for w in week_workouts
        ))
        vol_str = f"{vol_km:.0f}km" if vol_km else "0km"
        types_str = ", ".join(types) if types else "—"
        return f"[{week_key}] | {vol_str} | {types_str}"

    # RECENTE WEKEN — meest recent eerst, volledig uitgeschreven
    lines.append("── RECENTE WEKEN (meest relevant) ──")
    lines.append("")
    for week_key in reversed(recent_week_keys):
        lines.extend(_render_week_full(week_key))

    # VOORGAANDE WEKEN — compact, meest recent eerst
    if older_week_keys:
        lines.append("── VOORGAANDE WEKEN (context) ──")
        lines.append("")
        for week_key in reversed(older_week_keys):
            lines.append(_render_week_compact(week_key))
        lines.append("")

    return "\n".join(lines)


_INTAKE_VELDEN_SPEC = """{
  "naam": "roepnaam",
  "leeftijd": "getal of leeg",
  "horloge": "merk/type sporthorloge of leeg",
  "doel": "trainingsdoel",
  "referentie": "recente referentieprestatie (afstand + tijd) of leeg",
  "langste": "langste recent gelopen afstand of leeg",
  "volume": "huidig wekelijks volume (km/week) of leeg",
  "dagen": "trainingsdagen (bijv. ma/wo/vr/zo) of leeg",
  "tijd": "beschikbare tijd per training of leeg",
  "kwaliteit": "exact één van: Weinig/geen | Enige ervaring | Regelmatig",
  "op_tijd": "true als de atleet op tijd (minuten) traint i.p.v. km, anders false",
  "herstel": "exact één van: Langzaam | Normaal | Snel",
  "werkdruk": "exact één van: Laag | Normaal | Hoog",
  "ondergrond": "lijst met elementen uit: Weg, Trail, Baan, Loopband",
  "blessure": "blessurehistorie of leeg",
  "andere": "andere sporten/verplichtingen of leeg",
  "motivatie": "waarom dit doel, wat drijft de atleet, of leeg",
  "loopervaring": "hoe lang en hoe consistent loopt de atleet al, of leeg",
  "prs": "beste prestaties ooit (PR's) of leeg",
  "eerdere": "eerdere schema's/coach-ervaring of leeg",
  "slaap": "slaap en leefritme of leeg",
  "klachten": "huidige klachten of fysieke aandachtspunten of leeg",
  "leuk": "waar wordt de atleet blij van in training, of leeg",
  "niet_leuk": "waar ziet de atleet tegenop / wat haat hij, of leeg",
  "wat_werkte": "wat werkte goed in eerdere trainingen/schema's (aanpak, opbouw), of leeg",
  "wat_niet_werkte": "wat werkte NIET in eerdere trainingen/schema's, of leeg",
  "wedstrijd": "geprikte wedstrijd + datum, of leeg",
  "notities": "overige relevante info uit het gesprek die nergens anders past"
}"""


def extract_intake_fields(tekst: str) -> dict:
    """
    Haal uit een vrije intake-notule (willekeurige tekst) de gestructureerde
    intakevelden. Geeft een dict met dezelfde sleutels als de intakeformulier.
    Onbekende velden blijven leeg; selectievelden krijgen alleen toegestane
    waarden. Bij twijfel niets verzinnen.
    """
    import json as _json

    prompt = f"""Hieronder staat een vrije notitie van een intakegesprek met een hardloper.
Haal de informatie eruit en vul deze JSON-structuur. Gebruik EXACT deze sleutels:

{_INTAKE_VELDEN_SPEC}

Regels:
- Vul alleen in wat echt in de tekst staat. Verzin niets. Laat onbekend leeg ("" of [] of false).
- Voor de selectievelden (kwaliteit, herstel, werkdruk): gebruik UITSLUITEND een van de genoemde waarden, of laat leeg als het er niet uit blijkt.
- Antwoord met ALLEEN de JSON, geen uitleg eromheen.

NOTITIE:
{tekst[:8000]}"""

    response = create_message(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    out = response.content[0].text.strip()

    # JSON uit de respons vissen (eventueel binnen ```-blok)
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        return {}
    try:
        data = _json.loads(m.group(0))
    except Exception:
        return {}

    # Valideer selectievelden tegen de toegestane opties
    _opts = {
        "kwaliteit": {"Weinig/geen", "Enige ervaring", "Regelmatig"},
        "herstel": {"Langzaam", "Normaal", "Snel"},
        "werkdruk": {"Laag", "Normaal", "Hoog"},
    }
    for veld, toegestaan in _opts.items():
        if data.get(veld) not in toegestaan:
            data.pop(veld, None)
    # Ondergrond: alleen geldige elementen
    geldig_ond = {"Weg", "Trail", "Baan", "Loopband"}
    ond = data.get("ondergrond")
    if isinstance(ond, list):
        data["ondergrond"] = [o for o in ond if o in geldig_ond]
    else:
        data.pop("ondergrond", None)
    # op_tijd naar bool
    if "op_tijd" in data:
        data["op_tijd"] = bool(data["op_tijd"]) if isinstance(data["op_tijd"], bool) \
            else str(data["op_tijd"]).strip().lower() in ("true", "ja", "1", "yes")
    return data


def extract_file_content(uploaded_file) -> dict:
    """
    Verwerk een geüpload bestand naar tekst of een afbeelding voor Claude.
    Geeft een dict terug met 'type' ("text" of "image") en 'content'.
    """
    name = uploaded_file.name.lower()
    raw = uploaded_file.read()

    # Afbeeldingen → Claude Vision
    if name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        ext_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".gif": "image/gif", ".webp": "image/webp"}
        ext = "." + name.rsplit(".", 1)[-1]
        media_type = ext_map.get(ext, "image/png")
        return {
            "type": "image",
            "media_type": media_type,
            "data": base64.standard_b64encode(raw).decode("utf-8"),
            "label": uploaded_file.name,
        }

    # PDF → tekst extraheren, bij scan/afbeelding → Claude Vision
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            tekst = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
            if len(tekst) > 100:
                return {"type": "text", "content": f"[PDF: {uploaded_file.name}]\n{tekst}", "label": uploaded_file.name}
        except Exception:
            pass
        # Fallback: stuur als afbeelding (gescande PDF)
        return {
            "type": "image",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(raw).decode("utf-8"),
            "label": uploaded_file.name,
        }

    # Word DOCX → tekst
    if name.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(io.BytesIO(raw))
            tekst = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return {"type": "text", "content": f"[Word: {uploaded_file.name}]\n{tekst}", "label": uploaded_file.name}
        except Exception as e:
            return {"type": "text", "content": f"[Word: kon niet lezen: {e}]", "label": uploaded_file.name}

    # Excel XLSX → tabel als tekst
    if name.endswith((".xlsx", ".xls")):
        try:
            import pandas as pd
            df = pd.read_excel(io.BytesIO(raw))
            return {"type": "text", "content": f"[Excel: {uploaded_file.name}]\n{df.to_string(index=False)}", "label": uploaded_file.name}
        except Exception as e:
            return {"type": "text", "content": f"[Excel: kon niet lezen: {e}]", "label": uploaded_file.name}

    # CSV
    if name.endswith(".csv"):
        try:
            import pandas as pd
            df = pd.read_csv(io.StringIO(raw.decode("utf-8", errors="ignore")))
            return {"type": "text", "content": f"[CSV: {uploaded_file.name}]\n{df.to_string(index=False)}", "label": uploaded_file.name}
        except Exception as e:
            return {"type": "text", "content": f"[CSV: kon niet lezen: {e}]", "label": uploaded_file.name}

    # Fallback: probeer als tekst
    try:
        tekst = raw.decode("utf-8", errors="ignore")
        return {"type": "text", "content": f"[{uploaded_file.name}]\n{tekst}", "label": uploaded_file.name}
    except Exception:
        return {"type": "text", "content": f"[{uploaded_file.name}: onleesbaar bestand]", "label": uploaded_file.name}

# ---------------------------------------------------------------------------
# System prompt (aangeleverd door Jip van Lent)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Je bent een expert hardloopcoach-assistent voor BeBetter Coaching. Je maakt wetenschappelijk onderbouwde trainingsschema's op basis van bewezen trainingsleer.

━━━ TRAININGSLEER — METHODOLOGIE ━━━

JACK DANIELS (VDOT-SYSTEEM) — het fundament
Als een doeltijd + afstand bekend is bereken je het VDOT en leid je ALLE trainingstempo's daaruit af:
- E-tempo (Easy): aerobe basis, actief herstel. ~59-74% VO2max. Gesprekstempo.
- M-tempo (Marathon): ~75-84% VO2max. Gecontroleerd, lang vol te houden.
- T-tempo (Threshold): lactaatdrempel, comfortabel hard. ~83-88% VO2max. Max 20-30 min aaneengesloten.
- I-tempo (Interval): VO2max-ontwikkeling. ~95-100% VO2max. Intervallen van 600m-1600m. Herstel = actief, gelijke duur.
- R-tempo (Repetition): snelheid en loopeconomie. 105-120% VO2max. 200-400m. Volledig herstel (2-3x de inspanningstijd).

VDOT → TRAININGSTEMPO's (indicatief):
- 5km 19:30 (VDOT ~54): E=5:30-6:15, T=4:30, I=4:10, R=3:55/km
- 5km 22:00 (VDOT ~46): E=6:15-7:00, T=5:10, I=4:50, R=4:30/km
- 5km 25:00 (VDOT ~39): E=7:00-8:00, T=5:55, I=5:30, R=5:10/km
- 10km 45:00 (VDOT ~50): E=5:45-6:30, T=4:50, I=4:25, R=4:05/km
- 10km 55:00 (VDOT ~40): E=6:45-7:45, T=5:45, I=5:20, R=5:00/km
- HM 1:45 (VDOT ~50): E=5:45-6:30, M=5:00, T=4:50, I=4:25/km
- HM 2:00 (VDOT ~43): E=6:30-7:30, M=5:45, T=5:30, I=5:05/km

ARTHUR LYDIARD — periodisering
Fases in volgorde: Aerobe opbouw → Heuvelcircuit → Anaerobe ontwikkeling → Coördinatie/sprint → Competitie → Herstel.
Aerobe basis is nooit "af" — onderhoud altijd 80% E-volume, ook in intensieve fases.

PETE PFITZINGER — volume en specificiteit
- Middellange duurlopen (16-19km) op M-tempo zijn cruciaal voor 10km en langer.
- Progressieve lange duurlopen: begin E, eindig op M-tempo (laatste 30-40%).
- Wekelijkse "medium-long run" (60-70% van de lange duurloop) als extra aeroob fundament.

STEPHEN SEILER — polariseerd trainen
- 80% van alle kilometers op Z1-Z2, 20% op Z4-Z5.
- Vermijd de grijze zone (Z3 als enige kwaliteit): levert weinig op en vermoeit te veel.
- Combineer lage-intensiteitsvolume met echte hoge-intensiteitsblokken.

BRAD HUDSON — adaptief trainen
- Begin conservatiever dan nodig. Observeer reactie, verhoog dan.
- Kwaliteitstrainingen eerst ontwerpen, dan de rustdagen eromheen.

━━━ TRAININGSVORMEN — GEBRUIK VARIATIE ━━━

Gebruik NOOIT steeds dezelfde trainingsvormen. Wissel af op basis van fase, niveau en doel:

RUSTIG (Z1-Z2, E-tempo):
- Herstelloop: 5-8km Z1, wandelpauzes toegestaan
- Rustige duurloop: 8-16km Z1-Z2, gesprekstempo
- Lange duurloop: 16-30km Z1, laatste deel optioneel M-tempo
- Medium-long run: 12-18km Z1-Z2
- Progressieve duurloop: begin Z1, verhoog elke 3km een zone, eindig Z3

DREMPEL (Z3, T-tempo):
- Tempo-blok: 1x 5-8km Z3 aaneengesloten (na opbouw)
- Cruise intervals: 3-5x 1.6km Z3 / 0.8km Z1 herstel
- Ladder-tempo: 1km / 2km / 3km / 2km / 1km Z3, 400m herstel tussendoor
- Vlotte duurloop: 10-14km Z2-Z3, gecontroleerd hard

INTERVAL / VO2MAX (Z4, I-tempo):
- Klassieke intervals: 5-8x 800m of 1000m Z4 / gelijke afstand Z1 herstel
- Lange intervals: 3-5x 1200m of 1600m Z4 / gelijke afstand Z1
- Piramide intervals: 400m-800m-1200m-1600m-1200m-800m-400m Z4 / halve afstand herstel
- Cutdown intervals: 5x 1000m Z4 met elk interval 5-10 sec sneller
- Heuvelintervals: 6-10x 300m heuvel Z4 (kracht + VO2max), looppas terug als herstel

SNELHEID / REPETITIES (Z5, R-tempo):
- Strides: 4-8x 100m vloeiend versnellen, geen max sprint, volledige rust
- Korte repetities: 8-12x 200m of 6-8x 400m Z5, volledig herstel (2-3x inspanningstijd)
- Flying 30's: 30m aanloop + 30m maximale sprint, 3-4x, volledig herstel

FARTLEK (vrije intensiteitswisseling):
- Gestructureerde fartlek: ALTIJD beschrijven als afstanden, NOOIT als tijden
  Goed: "200m snel (Z4) / 300m rustig (Z1), herhaal × 12, totaal 6km"
  FOUT: "60 sec snel / 90 sec rustig" — dit is niet bruikbaar voor de workout builder
- Ongestructureerde fartlek: alleen in vroege opbouwfase voor beginnende atleten

━━━ KRITIEKE REGEL — AFSTANDEN ALTIJD, NOOIT TIJD ━━━

ALLE trainingen beschrijf je in kilometers of meters — NOOIT in minuten of seconden.

AFSTANDEN — ALTIJD HELE KILOMETERS:
- De totale afstand van elke training is ALTIJD een heel getal kilometers (8km, 10km, 12km — nooit 9,22km of 11,5km)
- Individuele onderdelen mogen fractioneel zijn (1,2km interval, 800m herstel) — maar het totaal klopt op een heel kilometer
- Bouw de training op vanuit de onderdelen en rond het totaal af naar het dichtstbijzijnde hele km
- Schrijf altijd: "10km totaal" niet "9,8km" of "10,2km"
Dit geldt voor: warming-up, hoofdblok, intervallen, herstel, cooling-down.

CORRECT:
- "1.5km warming-up Z1"
- "5x 1000m Z4 / 500m Z1 herstel"
- "200m snel (Z4) / 300m rustig (Z1), herhaal × 10"
- "8km Z2"
- "1km cooling-down Z1"

FOUT (nooit gebruiken):
- "10 min warming-up"
- "5x 4 min Z4"
- "60 sec snel / 90 sec rustig"
- "30 min Z2"

Reden: de workout builder in FinalSurge werkt uitsluitend op afstand. Tijden worden niet overgenomen.

━━━ WERKWIJZE ━━━

Werk ALTIJD in deze volgorde:

━━━ HARTSLAGZONES vs TEMPOZONES — KRITIEKE REGEL ━━━

De intake vermeldt welk zone-type de atleet gebruikt: hartslag (bpm) of tempo (min/km).

ALS ZONE-TYPE = HARTSLAG:
- Schrijf trainingen ALTIJD in hartslagzones (bijv. "Z2", "zone 2", "130-145 bpm")
- Schrijf NOOIT min/km-tijden als sturing voor de training
- Gebruik tempo-aanduidingen ALLEEN als referentie ("dit loopt waarschijnlijk rond 6:30/km")
  maar als INSTRUCTIE altijd de hartslagzone
- Voorbeeldformulering: "45 min Z2 (verwacht tempo ~6:15-6:45/km — maar hartslag leidend)"

ALS ZONE-TYPE = TEMPO:
- Schrijf trainingen in min/km of E/M/T/I/R-tempo's (Jack Daniels)
- Hartslagwaarden zijn dan optioneel ter referentie

━━━ WERKWIJZE ━━━

Werk ALTIJD in deze volgorde:

1. SAMENVATTING ATLEET
   - Feiten uit intake + trainingslog + zones. VDOT berekening als doeltijd gegeven.
   - Zone-type bepaalt hoe je de trainingen formuleert (zie boven).
   - Schrijf afgeleide trainingsintensiteiten op in het juiste formaat (bpm of min/km).
   - Analyseer het trainingslog INHOUDELIJK: welke trainingsvormen heeft de atleet gedaan?
     Op welk WERKELIJK tempo liepen de intervals, tempo-blokken, fartleks?
     Let op splits en beschrijvingen — NIET op gemiddelde pace van de hele run.
   - Benoem concreet: "atleet heeft aangetoond 5x1000m op 4:30 te kunnen lopen" of
     "laatste 4 weken geen echte kwaliteitstraining — alleen duurlopen".
   - Risico's, ontbrekende info, sterke/zwakke punten.

2. AANSLUITANALYSE (verplicht — VOOR de macro-opbouw)
   Bereken concreet uit het trainingslog:
   a) VOLUME: gemiddeld weekvolume afgelopen 4 weken (of beschikbare weken als minder)
      → Dit is het startvolume voor week 1. Noteer dit letterlijk: "Gemiddeld: X km/week"
   b) TRAININGSVORMEN: welke typen training deed de atleet de laatste 4 weken?
      → Noteer: bijv. "2x duurloop, 1x interval, 0x tempo" per week
   c) KWALITEITSNIVEAU: wat is het aangetoonde niveau van kwaliteitstrainingen?
      → Bijv: "5x1000m @ 4:30/km" of "geen kwaliteitstraining de afgelopen 4 weken"
   d) TREND: was het volume stijgend, stabiel of dalend?
   e) STARTPUNT WEEK 1: noteer EXACT wat week 1 bevat (km + trainingsvormen)
      zodat het naadloos aansluit op de afgelopen periode.

3. MACRO-OPBOUW (periodisering)
   - Welke fases? Hoeveel weken? Waarom deze volgorde?
   - Taper: altijd 2-3 weken voor wedstrijd, volume -40-60%, intensiteit bewaren.
   - Wekelijks volumeritme: typisch 3 weken opbouw + 1 week deload (-30%).

4. SCHEMA TEKSTUEEL
   - Schrijf minimaal 2 weken volledig uit, daarna blokken van 2 weken.
   - Elke training: naam + afstand + zone/tempo + waarom + niet doen.
   - Gebruik variatie in trainingsvormen (zie boven) — nooit 3 weken dezelfde structuur.
   - Verwijs expliciet naar de VDOT-tempo's.

AANSLUITREGEL:
De eerste week van het schema start op het volume en de trainingsvormen die de atleet de afgelopen weken aantoonbaar deed.
Volume ±10% van het gemiddelde van de laatste 4 weken — nooit een plotselinge sprong omhoog of omlaag.
Introduceer geen nieuwe trainingsvormen in de eerste week.

━━━ DOELTIJD — KRITIEKE REGEL ━━━

Als een specifieke doeltijd + afstand opgegeven is:
- Bereken VDOT en schrijf dit EXPLICIET op in de samenvatting.
- Leid ALLE trainingstempo's af van dit VDOT — NOOIT generieke tempo's.
- Elke kwaliteitstraining moet tempo's bevatten die aansluiten bij het VDOT.
- Als de atleet op hartslag traint: vertaal VDOT-zones naar de opgegeven bpm-zones.
- Het doel stuurt ALLES. Een atleet die 19:30 wil lopen traint NIET op 25-min niveau.

━━━ KALENDER-LABELS ━━━

- Vakantie / afwezigheid: geen of minimale training. Benoem expliciet.
- Wedstrijd-labels: piekmoment — taper ervoor, herstel erna.
- Betalings-/verlenglabels: informatief, benoem in samenvatting.
- Alle overige labels: pas schema logisch aan.

━━━ TRAININGSLOG LEZEN — KRITIEKE INSTRUCTIES ━━━

Het trainingslog bevat automatisch opgehaalde data uit FinalSurge. Lees het zo:

1. PACE IN DE LOG = GEMIDDELDE OVER DE GEHELE TRAINING
   Dit is NIET de inspanningsintensiteit. Voorbeelden:
   - "[INTERVAL] Intervaltraining 5x1000m | gem. 5:50/km" → de intervals liepen op ~4:20-4:40/km,
     de 5:50 is het gemiddelde inclusief warming-up + herstelblokken.
   - "[TEMPO] Tempoloop 10km | gem. 5:10/km" → het tempogedeelte liep op ~4:45-5:00/km.
   Gebruik het gemiddelde NOOIT als indicatie van het maximale tempo of de intensiteit.

2. SPLITS/LAPS ZIJN DE WAARHEID
   Als er "⚡ Splits tonen interval-patroon" staat, gebruik die waarden als basis
   voor het werkelijke intensiteitsniveau van de atleet.

3. BESCHRIJVING (📋 Plan) VERTELT WAT GEPLAND WAS
   Gebruik dit om te zien of de atleet klaar was voor die intensiteit.
   Stond er "5x 1000m Z4" in het plan en heeft de atleet het uitgevoerd? Dan KAN die atleet Z4-intervals.

4. NAAM VAN DE WORKOUT [TYPE]
   [INTERVAL], [TEMPO], [FARTLEK] = kwaliteitstraining op hoge intensiteit
   [DUURLOOP], [HERSTEL] = lage intensiteit, hier is het gemiddelde betrouwbaarder
   [PROGRESSIEF] = begin laag, einde hoog — gemiddelde zit ertussenin

5. BOUW VOORT OP WERKELIJK AANGETOOND NIVEAU
   Als een atleet aantoonbaar 5x 1000m op 4:30/km heeft gelopen, is dat het startpunt.
   Niet 5:50 (het gemiddelde van die run). Bouw de volgende fase hierop.
   Verhoog geleidelijk: meer herhalingen, iets sneller, of langere intervallen.

6. WEEKVOLUME LAATSTE 4 WEKEN = STARTPUNT SCHEMA
   Bereken het GEMIDDELDE weekvolume van de laatste 4 weken uit het log.
   Week 1 van het schema start op dit volume — NOOIT meer dan 10% hoger of lager.
   Als de laatste 4 weken gemiddeld 35 km/week waren, start week 1 op 33-37 km.
   Maak geen plotselinge sprong, ook niet als het doel dat technisch zou toestaan.

7. TRAININGSVORMEN CONTINUÏTEIT
   Kijk naar welke trainingsvormen de atleet de afgelopen 4 weken deed.
   Week 1 bevat DEZELFDE typen (of minder) als de atleet al deed — introduceer niets nieuws in week 1.
   Als de atleet al intervals deed: continueer. Als niet: introduceer ze pas in week 2-3.

━━━ GEÜPLOADE BESTANDEN ━━━

- Verwerk trainingslog VOLLEDIG. Benoem: volume, consistentie, zwakke/sterke punten.
- Pas schema aan op basis van wat de atleet werkelijk aankan — niet wat hij zegt.
- Zones uit upload zijn leidend als ze concreter zijn dan de intake.

━━━ CSV-REGELS ━━━

Kolommen: Date (MM/DD/YYYY), ActivityType, WorkoutName, PlannedTimeMinutes, PlannedDistance, mi/km/m/y, WorkoutDescription
Gebruik plain ASCII. Geen em-dashes. Gebruik - in plaats van --.
ActivityType: Run, CrossTraining, Bike, Swim, Rest. Altijd Engels.
PlannedTimeMinutes: altijd 0 of leeg. PlannedDistance: altijd invullen in km.

BESCHRIJVING FORMAT (exact zo, elke training):
Regel 1: Trainingstype + totale afstand + zone-label (GEEN specifieke tempo's of bpm — alleen zonenummer)
Regel 2: Warming-up: Xkm Z1  (of "inbegrepen in de loop" als er geen aparte warmup-stap is)
Regel 3: Hoofdblok: exacte structuur in km/m (zie voorbeelden hieronder)
Regel 4: Cooling-down: Xkm Z1  (of "niet van toepassing" als er geen aparte cooldown-stap is)
---
Regel 5+: Coaching-tekst — wat / waarom / niet doen (max 3 zinnen)

AFSTANDS-BALANS — KRITIEKE REGEL:
De SOM van warmup-km + hoofdblok-km + cooldown-km MOET EXACT gelijk zijn aan de km in Regel 1.
Bijv: "Vlotte duurloop 8km" → warmup + hoofdblok + cooldown = 8km.
Als er geen aparte warmup/cooldown is: schrijf "inbegrepen" of "niet van toepassing" en bereken het hoofdblok dienovereenkomstig.

COOLING-DOWN REGEL:
- ALTIJD als km-afstand (bijv. "1km Z1") of "niet van toepassing"
- NOOIT als minuten of tijd — "5 min wandelen na" is FOUT
- Minimum 1km als er wél een cooldown-stap is
- Als "niet van toepassing": de workout builder voegt GEEN cooldown-stap toe

ZONE-AANDUIDINGEN IN BESCHRIJVING:
Schrijf ALLEEN het zonenummer: "Z2", "Z3", "Z4" — NOOIT "(5:25-5:50/km)" of "(140-155 bpm)" erbij.
De zone-definitie staat al in FinalSurge — extra tempo's/bpm in de beschrijving zijn altijd fout of conflicterend.

BESCHRIJVINGSVOORBEELDEN:

Interval 400m:
"Intervaltraining 10km | Z4
Warming-up: 2km Z1
Hoofdblok: 8x 400m Z4 / 400m Z1 herstel
Cooling-down: 1.6km Z1
---
Ontwikkelt VO2max en loopeconomie. Loop de eerste helft gecontroleerd — niet uitpakken. Herstel is actief joggen, niet wandelen."

Fartlek:
"Fartlek 10km | Z1-Z4
Warming-up: 1.5km Z1
Hoofdblok: 200m Z4 / 300m Z1, herhaal x14 (7km totaal)
Cooling-down: 1.5km Z1
---
Wisselend tempo traint het vermogen om van intensiteit te wisselen. De 200m hard zijn echt hard (Z4), de 300m zijn rustig herstel (Z1). Geen grijze zone."

Tempo-blok:
"Tempoloop 10km | Z3
Warming-up: 2km Z1
Hoofdblok: 6km Z3 aaneengesloten
Cooling-down: 2km Z1
---
Verhoogt lactaatdrempel. Comfortabel hard tempo — je kunt nog spreken maar niet uitgebreid. Nooit harder dan Z3."

Progressieve duurloop:
"Progressieve duurloop 12km | Z1-Z3
Warming-up: inbegrepen in de loop (de eerste km's zijn de warmup)
Hoofdblok: 4km Z1 / 4km Z2 / 4km Z3
Cooling-down: niet van toepassing — loop de laatste 500m rustig uit
---
Leert het lichaam versnellen op vermoeidheid. Begin rustig — de eerste 4km moeten aanvoelen als te makkelijk."

ZONES in beschrijvingen altijd als label: "Z1", "Z2", "Z3" — nooit met tempo of bpm erbij.

━━━ ANDERE SPORTEN ━━━

HYROX / kracht: RPE-schaal 1-10. Nooit zwaar kracht vóór kwaliteitslooptraining.
Plan zodat spierpijn weg is voor looptraining-dagen.

━━━ BLESSUREBELEID ━━━

Actieve risicopunten altijd in samenvatting. Bij twijfel: conservatiever.
Bij blessurehistorie: introduceer kwaliteitstraining 1 week later dan normaal."""


# ---------------------------------------------------------------------------
# Intake → prompt bouwen
# ---------------------------------------------------------------------------

def build_prompt(intake: dict) -> str:
    """Zet intake-formulier om naar een Claude-prompt."""
    naam = intake.get("naam", "de atleet")
    doel = intake.get("doel", "")
    wedstrijddatum = intake.get("wedstrijddatum", "")
    weken = intake.get("weken", "")
    startdatum = intake.get("startdatum", "")
    trainingsdagen = intake.get("trainingsdagen", "")
    huidig_volume = intake.get("huidig_volume", "")
    zone_type = intake.get("zone_type", "tempo")
    zones = intake.get("zones", "")
    andere_sporten = intake.get("andere_sporten", "")
    blessurehistorie = intake.get("blessurehistorie", "")
    extra = intake.get("extra", "")
    uploaded_summary = intake.get("uploaded_summary", "")

    # Nieuwe velden — trainingsprofiel
    referentie_prestatie = intake.get("referentie_prestatie", "")
    tijd_per_training = intake.get("tijd_per_training", "")
    langste_afstand = intake.get("langste_afstand", "")
    kwaliteitservaring = intake.get("kwaliteitservaring", "")
    herstelcapaciteit = intake.get("herstelcapaciteit", "")
    werkdruk = intake.get("werkdruk", "")
    loopondergrond = intake.get("loopondergrond", "")
    race_prioriteit = intake.get("race_prioriteit", "")
    tussenraces = intake.get("tussenraces", "")
    coach_notitie = intake.get("coach_notitie", "")
    wat_werkte = intake.get("wat_werkte", "")
    wat_niet_werkte = intake.get("wat_niet_werkte", "")
    op_tijd = intake.get("op_tijd", False)

    schema_einddatum = intake.get("schema_einddatum", "")

    regels = [
        f"Atleet: {naam}",
        f"Doelstelling: {doel}",
    ]
    if schema_einddatum and wedstrijddatum and schema_einddatum != wedstrijddatum:
        regels.append(f"Wedstrijddatum (hoofddoel): {wedstrijddatum}")
        regels.append(f"Dit schema loopt tot: {schema_einddatum} ({weken} weken)")
        regels.append("Let op: na dit schema volgt een vervolgschema richting het hoofddoel.")
    elif wedstrijddatum:
        regels.append(f"Wedstrijddatum: {wedstrijddatum}")
    if not (schema_einddatum and wedstrijddatum and schema_einddatum != wedstrijddatum) and weken:
        regels.append(f"Schemalengte: {weken} weken")
    if startdatum:
        regels.append(f"Startdatum schema: {startdatum}")
    regels.append(f"Trainingsdagen per week: {trainingsdagen}")
    regels.append(f"Huidig wekelijks volume: {huidig_volume}")
    zone_instructie = (
        "HARTSLAG — gebruik ALLEEN hartslagzones als sturing (geen min/km als instructie)"
        if zone_type == "hartslag" else
        "TEMPO — gebruik min/km of E/M/T/I/R-aanduidingen als sturing"
    )
    regels.append(f"Zone-type: {zone_instructie}")
    regels.append(f"Zones: {zones}")
    if andere_sporten:
        regels.append(f"Andere sporten / vaste verplichtingen: {andere_sporten}")
    if blessurehistorie:
        regels.append(f"Blessurehistorie: {blessurehistorie}")
    if extra:
        regels.append(f"Extra informatie: {extra}")

    # Nieuwe velden toevoegen aan prompt
    if referentie_prestatie:
        regels.append(f"Recente referentieprestatie (HUIDIG niveau): {referentie_prestatie}")
    if tijd_per_training:
        regels.append(f"Beschikbare tijd per training: {tijd_per_training}")
    if langste_afstand:
        regels.append(f"Langste recent gelopen afstand: {langste_afstand}")
    if kwaliteitservaring:
        regels.append(f"Ervaring kwaliteitstraining: {kwaliteitservaring}")
    if herstelcapaciteit:
        regels.append(f"Herstelcapaciteit: {herstelcapaciteit}")
    if werkdruk:
        regels.append(f"Werkdruk/stress buiten sport: {werkdruk}")
    if loopondergrond:
        regels.append(f"Loopondergrond: {loopondergrond}")
    if race_prioriteit:
        regels.append(f"Race prioriteit: {race_prioriteit}")
    if tussenraces:
        regels.append(f"Tussenraces: {tussenraces}")
    if coach_notitie:
        regels.append(f"⭐ Coach notitie (BELANGRIJK — specifieke coaching kennis): {coach_notitie}")
    if wat_werkte:
        regels.append(f"Wat werkte goed in vorige schema's: {wat_werkte}")
    if wat_niet_werkte:
        regels.append(f"Wat NIET werkte / viel zwaar: {wat_niet_werkte}")

    intake_tekst = "\n".join(regels)

    upload_sectie = ""
    if uploaded_summary:
        upload_sectie = f"\n\nGEÜPLOADE DOCUMENTEN (trainingslog, zones, printscreens):\n{uploaded_summary}"

    tijd_override_sectie = _TIJD_OVERRIDE if op_tijd else ""

    return f"""Hier is de intake voor een nieuw trainingsschema:

{intake_tekst}{upload_sectie}

━━━ PRE-FLIGHT CHECK (verplicht VOOR je het schema schrijft) ━━━

Schrijf eerst een gestructureerde pre-flight check met exact deze 7 punten:

1. HUIDIG NIVEAU: Wat is het aantoonbare huidige niveau? Welk VDOT correspondeert hiermee? (gebruik referentieprestatie, NIET de doeltijd)
2. DOELNIVEAU: Welk VDOT heeft de atleet nodig voor de doelstelling? Hoe groot is de gap?
3. WEEKSTRUCTUUR: Hoe ziet een standaard trainingsweek eruit gegeven de beschikbare dagen + tijd per training? (maak een concrete weekschema-template)
4. PERIODISERING: Welke fases? Hoeveel weken per fase? Waar zit de taper?
5. RISICO'S: Noem 3 concrete risico's voor DEZE atleet (op basis van herstelcapaciteit, blessurehistorie, werkdruk, ervaring)
6. AANNAMES: Wat neem je aan omdat het niet in de intake staat? Wees expliciet.
7. CONTINUÏTEIT (verplicht als trainingslog beschikbaar is):
   - Gemiddeld weekvolume laatste 4 weken: X km
   - Meest recente trainingsvormen: [lijst]
   - Meest recente kwaliteitstraining: [wat / wanneer / op welk niveau]
   - Week 1 van het schema start op: X km met Y trainingsvormen
   - Toelichting: hoe sluit dit exact aan op de afgelopen periode?

━━━ DAN PAS het schema ━━━

Na de pre-flight check: genereer het volledige schema.

BELANGRIJK: Als het doel een specifieke tijd bevat, bereken dan eerst het VDOT op basis van de REFERENTIEPRESTATIE (huidig niveau) en leid ALLE trainingstempo's af van dat VDOT. De doeltijd bepaalt de periodisering, niet de startintensiteit.

Volg de werkwijze:
1. Pre-flight check (zie boven) — dit is verplicht, inclusief punt 7 CONTINUÏTEIT
2. Aansluitanalyse (zie werkwijze punt 2) — bereken concreet het startpunt
3. Macro-opbouw (periodisering in grote lijnen, welke fases en waarom)
4. Schema tekstueel (begin met aansluitparagraaf, daarna eerste 2 weken volledig, daarna blokken van 2 weken)

Genereer de CSV nog NIET — die vraag ik apart op als het plan goed is.{tijd_override_sectie}"""


# Time-based override die aan het einde van build_prompt() wordt toegevoegd
_TIJD_OVERRIDE = """
━━━ SCHEMA OP TIJD — OVERRIDE (heeft voorrang op alle andere regels) ━━━

Voor deze atleet werken we op TIJD (minuten), niet op afstand (km).

PLAN SCHRIJVEN:
- Beschrijf alle trainingen in minuten: "45 min Z2", "60 min Z1", "8x 3 min Z4 / 2 min Z1 herstel"
- NOOIT km of meters gebruiken (ook niet "8km" of "400m")
- Afstanden in de aansluitanalyse/pre-flight mag je wel noemen als context (uit trainingslog)
- Schemaoverzicht per week ook in minuten: bijv. "Week 1: 3x 45 min + 1x 60 min = ~195 min totaal"

CSV REGELS (OVERRIDE):
- PlannedTimeMinutes: invullen met de duur in minuten (bijv. 45 voor 45 minuten)
- PlannedDistance: leeg laten (0 of leeg)
- WorkoutDescription: trainingen beschrijven in minuten

WORKOUT BUILDER REGELS (OVERRIDE):
- durationType: "TIME" (niet "DISTANCE")
- duration: "MM:SS" formaat voor tijden onder 60 min (bijv. "45:00" voor 45 min, "03:00" voor 3 min, "10:00" voor 10 min)
- duration: "H:MM:SS" formaat alleen als de tijd 60 min of meer is (bijv. "1:30:00" voor 90 min)
- durationDist: null
- targetIsTimeBased: true (in elk target-object)

Voorbeelden tijdgebaseerde beschrijvingen:
"Rustige duurloop 45 min | Z2
Warming-up: inbegrepen
Hoofdblok: 45 min Z2 aaneengesloten
Cooling-down: niet van toepassing
---
Comfortabel tempo, je kunt een gesprek voeren."

"Intervaltraining 60 min | Z4
Warming-up: 10 min Z1
Hoofdblok: 8x 3 min Z4 / 2 min Z1 herstel (40 min totaal)
Cooling-down: 10 min Z1
---
Scherpe intervallen, ga vol voor de 3 minuten. Herstel is actief joggen."
"""


CHAT_SYSTEM_PROMPT = """Je bent een expert hardloopcoach-assistent (BeBetter Coaching) die sparrt over een trainingsschema.

Je hebt het trainingsplan al gegenereerd. De coach (Jip) kan nu vragen stellen, aanpassingen voorstellen of discussiëren over keuzes.

REGELS:
- Beantwoord vragen bondig en direct. Geen onnodige uitleg.
- Als de coach om aanpassingen vraagt aan het plan: voer ze uit en geef het VOLLEDIGE bijgewerkte plan terug.
- Schrijf in het Nederlands.

━━━ KRITIEKE REGEL — PLAN UPDATES ━━━

Als je het plan aanpast (ook kleine aanpassingen), doe dan ALTIJD het volgende:

1. Schrijf EERST een korte bevestiging van wat je aanpast (1-2 zinnen).
2. Schrijf dan EXACT op een eigen regel:
===PLAN UPDATE===
3. Schrijf daarna het VOLLEDIGE bijgewerkte plan — alle weken, niets weglaten.
4. Sluit af met EXACT op een eigen regel:
===EINDE PLAN===

NOOIT zeggen "ik heb het aangepast" zonder de markers te gebruiken.
NOOIT alleen de gewijzigde weken teruggeven — altijd het VOLLEDIGE plan.
NOOIT stoppen halverwege het plan — schrijf het volledig af, ook als het lang is.

Als je een vraag beantwoordt zonder het plan te wijzigen: gewone tekst, geen markers.
Als iets niet mogelijk is: zeg dat eerlijk zonder markers te gebruiken."""


def chat_about_plan(
    plan: str,
    intake: dict,
    history: list[dict],
) -> str:
    """
    Spar met de AI over het trainingsplan.
    history: lijst van {"role": "user"/"assistant", "content": "..."}
    Geeft de AI-respons terug (kan een plan-update bevatten).
    """
    naam = intake.get("naam", "de atleet")
    doel = intake.get("doel", "")
    zones = intake.get("zones", "")
    zone_type = intake.get("zone_type", "tempo")
    uploaded_summary = intake.get("uploaded_summary", "")

    context = f"""ATLEET: {naam}
DOEL: {doel}
ZONES ({zone_type}): {zones}"""
    if uploaded_summary:
        context += f"\nEXTRA CONTEXT: {uploaded_summary[:1000]}"

    context += f"\n\nHET HUIDIGE PLAN:\n{plan}"

    messages = [{"role": "user", "content": context}, {"role": "assistant", "content": "Begrepen. Ik ken het plan en ben klaar om te sparren. Wat wil je bespreken of aanpassen?"}]

    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    response = create_message(
        model="claude-opus-4-5",
        max_tokens=10000,
        system=CHAT_SYSTEM_PROMPT,
        messages=messages,
    )
    return response.content[0].text.strip()


_WEEKDAG_MAP = {
    "maandag": 0, "ma": 0, "dinsdag": 1, "di": 1, "woensdag": 2, "wo": 2, "woe": 2,
    "donderdag": 3, "do": 3, "don": 3, "vrijdag": 4, "vr": 4, "vrij": 4,
    "zaterdag": 5, "za": 5, "zat": 5, "zondag": 6, "zo": 6, "zon": 6,
}
_WEEKDAG_NL = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]


def _parse_weekdagen(tekst: str) -> list[int]:
    """Vind de trainingsdagen (0=maandag … 6=zondag) in vrije tekst, op volgorde."""
    t = (tekst or "").lower()
    hits = []
    for naam, num in _WEEKDAG_MAP.items():
        for m in re.finditer(rf"\b{naam}\b", t):
            hits.append((m.start(), num))
    # Weekdag-volgorde (maandag → zondag), ontdubbeld
    return sorted({num for _, num in hits})


def build_csv_prompt(plan_tekst: str, intake: dict) -> str:
    """Vraag de CSV op basis van het goedgekeurde plan."""
    naam = intake.get("naam", "de atleet")
    op_tijd = intake.get("op_tijd", False)
    vandaag = date.today().strftime("%d-%m-%Y")

    # Bereken de exacte maandagdatum per week op basis van de startdatum
    startdatum_str = intake.get("startdatum", "")
    week_datums_tekst = ""
    try:
        from datetime import datetime as _dt2, timedelta as _td2
        start_dt = _dt2.strptime(startdatum_str, "%Y-%m-%d").date()
        # Zorg dat startdatum altijd een maandag is (naar vorige maandag afronden indien nodig)
        start_monday = start_dt - timedelta(days=start_dt.weekday())
        weken_aantal = int(intake.get("weken") or 8)
        # Gekozen trainingsdagen → exacte datum per training, zodat de AI de
        # dagen niet zelf verzint (di/zo werd anders ma/wo).
        _dagen = _parse_weekdagen(intake.get("trainingsdagen", ""))
        week_lines = []
        for w in range(weken_aantal):
            mon = start_monday + timedelta(weeks=w)
            sun = mon + timedelta(days=6)
            if _dagen:
                _paren = ", ".join(
                    f"{_WEEKDAG_NL[dg]} {(mon + timedelta(days=dg)).strftime('%m/%d/%Y')}"
                    for dg in _dagen)
                week_lines.append(f"  Week {w+1} ({mon.strftime('%m/%d')} t/m "
                                  f"{sun.strftime('%m/%d')}): trainingen op → {_paren}")
            else:
                week_lines.append(
                    f"  Week {w+1}: maandag {mon.strftime('%m/%d/%Y')} t/m zondag {sun.strftime('%m/%d/%Y')}")
        week_datums_tekst = "\n".join(week_lines)
    except Exception:
        pass

    if op_tijd:
        regels = """KRITIEKE REGELS (SCHEMA OP TIJD):
1. PlannedTimeMinutes: invullen met de duur in MINUTEN (bijv. 45 voor 45 min). PlannedDistance: leeg laten (0).
2. Beschrijvingen in MINUTEN, niet in km/m.
3. WorkoutDescription formaat voor tijdgebaseerde trainingen:

FORMAT VOOR ELKE TRAINING (tijdgebaseerd):
[Trainingstype] [totale duur] min | [zone]
Warming-up: [X] min Z1  (of "inbegrepen")
Hoofdblok: [exacte structuur in minuten]
Cooling-down: [X] min Z1  (of "niet van toepassing")
---
[Coaching tekst: wat/waarom/niet doen, max 2 zinnen]

VOORBEELDEN tijdgebaseerde hoofdblok-beschrijvingen:
- Interval: "8x 3 min Z4 / 2 min Z1 herstel"
- Fartlek: "1 min Z4 / 2 min Z1, herhaal x10"
- Tempo aaneengesloten: "20 min Z3 aaneengesloten"
- Progressief: "15 min Z1 / 15 min Z2 / 15 min Z3"
- Rustige duurloop: "45 min Z2 aaneengesloten"

NOOIT km, m of afstand gebruiken in de beschrijvingen."""
    else:
        regels = """KRITIEKE REGELS:
1. PlannedTimeMinutes: altijd 0. PlannedDistance: altijd in km.
2. Beschrijvingen ALTIJD in km/m, NOOIT in minuten of seconden.
3. WorkoutDescription moet exact het formaat volgen dat de workout builder kan lezen:

FORMAT VOOR ELKE TRAINING:
[Trainingstype] [totale afstand]km | [zone]
Warming-up: [X]km Z1
Hoofdblok: [exacte structuur]
Cooling-down: [X]km Z1
---
[Coaching tekst: wat/waarom/niet doen, max 2 zinnen]

VOORBEELDEN van correcte hoofdblok-beschrijvingen:
- Interval: "8x 400m Z4 / 400m Z1 herstel"
- Fartlek: "200m Z4 / 300m Z1, herhaal x14"
- Tempo aaneengesloten: "6km Z3 aaneengesloten"
- Progressief: "4km Z1 / 4km Z2 / 4km Z3"
- Lange duurloop: "14km Z1 / 4km Z2"

FOUT (gebruik NOOIT):
- "60 sec snel / 90 sec rustig"
- "5x 4 min Z4"
- "10 min warming-up\""""

    week_datums_sectie = f"""
WEEKKALENDER — gebruik EXACT deze datums:
{week_datums_tekst}

DATUMREGELS (niet onderhandelbaar):
- Weken lopen altijd van MAANDAG t/m ZONDAG
- Staan er per week "trainingen op → <dagen met datums>", gebruik dan UITSLUITEND
  die exacte datums. Elke training valt op één van de genoemde trainingsdagen;
  verzin geen andere weekdagen. Het aantal trainingen per week is gelijk aan het
  aantal genoemde trainingsdagen (tenzij het plan expliciet minder/meer voorschrijft).
- Geen enkele training mag vóór de startdatum van week 1 vallen
- Datumformaat in de CSV: MM/DD/YYYY
""" if week_datums_tekst else f"""
DATUMREGEL: Weken lopen altijd van MAANDAG t/m ZONDAG. Startdatum schema: {startdatum_str}.
"""

    return f"""Het schema voor {naam} is goedgekeurd. Genereer nu de volledige CSV voor het hele schema.

Vandaag is het {vandaag}.
{week_datums_sectie}
HARDE REGELS VOOR DE CSV (niet onderhandelbaar):
- GEEN rustdagen als CSV-regel. Zet ALLEEN de daadwerkelijke trainingen als rijen.
  Rustdagen laat je gewoon weg (geen ActivityType "Rest", geen lege dagen).
- ELKE WorkoutDescription is VOLLEDIG en meerregelig volgens het format hieronder
  (naam+afstand+zone, Warming-up, Hoofdblok, Cooling-down, ---, 1-2 coaching-zinnen).
  Een losse regel als "Duurloop met strides" is FOUT: onbruikbaar voor de builder.
- WorkoutDescription bevat komma's en meerdere regels, dus zet dat veld ALTIJD
  tussen dubbele aanhalingstekens ("...") in de CSV, anders breekt de kolom.

Gebruik exact dit formaat — geen uitleg, alleen de CSV:
Date,ActivityType,WorkoutName,PlannedTimeMinutes,PlannedDistance,mi/km/m/y,WorkoutDescription

{regels}

Het goedgekeurde schema:
{plan_tekst[:4000]}"""


# ---------------------------------------------------------------------------
# Claude API aanroepen
# ---------------------------------------------------------------------------

def generate_plan(intake: dict) -> str:
    """Genereer een trainingsplan tekstueel (stap 1-3)."""
    prompt = build_prompt(intake)

    # Garmin-herstelstatus meegeven als achtergrond (alleen als de hardloopcoach-app
    # die publiceerde voor deze atleet; anders leeg -> prompt en gedrag ongewijzigd).
    _garmin = intake_store.garmin_context_text(intake.get("athlete_key", ""))
    if _garmin:
        prompt += (
            "\n\n" + _garmin + "\nWeeg deze actuele herstel- en belastingstatus mee bij "
            "het opbouwtempo en de intensiteit van de eerste weken (bijvoorbeeld "
            "voorzichtiger starten na onderherstel of een recente zware sessie). Het "
            "doel, de wedstrijddatum en de zones blijven leidend."
        )

    # Bouw de message content op: tekst + eventuele afbeeldingen
    content = [{"type": "text", "text": prompt}]

    for item in intake.get("uploaded_images", []):
        # item = {"media_type": "image/png", "data": "<base64>", "label": "..."}
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": item["media_type"],
                "data": item["data"],
            },
        })
        content.append({
            "type": "text",
            "text": f"[Bovenstaande afbeelding: {item['label']}]",
        })

    response = create_message(
        model="claude-opus-4-5",
        max_tokens=6000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    text = response.content[0].text if response.content else None
    if not text:
        raise ValueError("Lege respons van AI bij plan-generatie — probeer opnieuw.")
    return text.strip()


def generate_csv(plan_tekst: str, intake: dict) -> str:
    """Genereer de CSV op basis van het goedgekeurde schema (stap 4)."""
    if not plan_tekst:
        raise ValueError("Geen plan beschikbaar om CSV van te genereren.")
    prompt = build_csv_prompt(plan_tekst, intake)

    response = create_message(
        model="claude-opus-4-5",
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text if response.content else None
    if not text:
        raise ValueError("Lege respons van AI bij CSV-generatie — probeer opnieuw.")
    return text.strip()


# ---------------------------------------------------------------------------
# CSV verwerken
# ---------------------------------------------------------------------------

def extract_csv_block(text: str) -> str:
    """Haal de CSV-inhoud uit een markdown-codeblok of plain text."""
    # Zoek ```csv ... ``` blok
    match = re.search(r"```(?:csv)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Zoek op header-regel
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if "Date" in line and "ActivityType" in line:
            start = i
            break
    if start is not None:
        return "\n".join(lines[start:]).strip()
    return text.strip()


def parse_csv_text(csv_text: str) -> list[dict]:
    """
    Verwerk CSV-tekst naar een lijst van workout-dicts.
    Kolommen: Date, ActivityType, WorkoutName, PlannedTimeMinutes,
              PlannedDistance, mi/km/m/y, WorkoutDescription
    """
    csv_clean = extract_csv_block(csv_text)
    rows = []

    reader = csv.DictReader(io.StringIO(csv_clean))
    for row in reader:
        # csv.DictReader vult ontbrekende kolommen met None → altijd via (… or "")
        date_str = (row.get("Date") or "").strip()
        activity_type = (row.get("ActivityType") or "Run").strip() or "Run"
        workout_name = (row.get("WorkoutName") or "").strip()
        time_min = (row.get("PlannedTimeMinutes") or "").strip()
        distance = (row.get("PlannedDistance") or "").strip()
        dist_unit = (row.get("mi/km/m/y") or "km").strip() or "km"
        description = (row.get("WorkoutDescription") or "").strip()

        # Datum naar YYYY-MM-DD omzetten (input MM/DD/YYYY)
        try:
            dt = datetime.strptime(date_str, "%m/%d/%Y")
            date_iso = dt.strftime("%Y-%m-%d")
        except ValueError:
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                date_iso = date_str
            except ValueError:
                continue  # Sla ongeldige rijen over

        # Numerieke waarden
        try:
            planned_min = float(time_min) if time_min else None
        except ValueError:
            planned_min = None

        try:
            planned_dist = float(distance) if distance else None
            # Alles omzetten naar km
            if dist_unit in ("mi", "miles"):
                planned_dist = planned_dist * 1.60934 if planned_dist else None
        except ValueError:
            planned_dist = None

        # Rustdagen horen NIET in het schema — sla elke Rest-rij over, ongeacht
        # of de AI er een naam bij zette. Ook lege rijen (geen naam/tijd/afstand).
        if activity_type.strip().lower() in ("rest", "rustdag", "rust"):
            continue
        if not workout_name and not time_min and not distance:
            continue

        # Afronden naar heel kilometer
        if planned_dist is not None:
            planned_dist = round(planned_dist)

        rows.append({
            "date": date_iso,
            "activity_type": activity_type,
            "name": workout_name or activity_type,
            "planned_min": planned_min,
            "planned_km": planned_dist,
            "description": description,
        })

    return rows


# ---------------------------------------------------------------------------
# Workout Builder structuur genereren (zones/stappen via AI)
# ---------------------------------------------------------------------------

BUILDER_SYSTEM_PROMPT = """Je converteert workout-beschrijvingen naar FinalSurge WorkoutBuilder JSON.

Geef ALLEEN geldige JSON terug — geen uitleg, geen markdown, geen ```json blokken.

KRITIEKE REGEL: De workout builder moet EXACT overeenkomen met de beschrijving.
- Als de beschrijving zegt "8x 400m Z4 / 400m Z1 herstel" → bouw een repeat-blok met 8 herhalingen van 0.4km Z4 + 0.4km Z1
- Als de beschrijving zegt "200m Z4 / 300m Z1, herhaal x14" → bouw een repeat-blok met 14 herhalingen van 0.2km Z4 + 0.3km Z1
- Als de beschrijving zegt "6km Z3 aaneengesloten" → bouw één ACTIVE stap van 6km Z3
- Als de beschrijving zegt "4km Z1 / 4km Z2 / 4km Z3" → bouw 3 losse ACTIVE stappen van elk 4km
Wees letterlijk — vertaal exact wat er staat, niet wat je denkt dat bedoeld wordt.

Structuur: warmup → hoofdblok (repeat of losse stap(pen)) → cooldown.

━━━ STAP-OBJECT (type: "step") ━━━
Verplichte velden:
  type: "step"
  id: oplopend integer (begin bij 101)
  name: null
  name_original: null
  comments: null
  comments_original: null
  durationType: "DISTANCE"  ← ALTIJD DISTANCE, NOOIT TIME
  duration: "00:00"  ← altijd "00:00" want durationType is altijd DISTANCE
  durationDist: afstand in km (bijv. 1.0 voor warming-up, 0.8 voor 800m, 1.5 voor cooling-down)
  distUnit: "km"
  target: [zone-object, open-object]  (zie hieronder)
  data: []
  repeats: null
  skip_last_rest: false
  intensity: "WARMUP" | "ACTIVE" | "REST" | "COOLDOWN"

KRITIEKE REGEL: durationType is ALTIJD "DISTANCE". Gebruik NOOIT "TIME". Ook voor warming-up, cooling-down en rusttussenpauzes bij intervallen altijd afstand in km opgeven.

TOTALE AFSTAND — KRITIEKE REGEL:
De SOM van alle stap-afstanden (WARMUP + ACTIVE stappen + COOLDOWN) MOET EXACT gelijk zijn aan de km vermeld in regel 1 van de beschrijving.
Bijv: beschrijving begint met "Vlotte duurloop 8km" → alle stappen samen = precies 8km.

COOLING-DOWN / WARMING-UP REGELS:
- Als beschrijving zegt "Cooling-down: niet van toepassing" of geen km-afstand geeft → voeg GEEN cooldown stap toe
- Als beschrijving zegt "Warming-up: inbegrepen in de loop" → voeg GEEN aparte warmup stap toe
- Als er wél een warmup of cooldown stap is: minimum 1km, nooit fracties zoals 0.5km
- Tijdsgebaseerde aanwijzingen ("5 min wandelen na") zijn coachingstekst, GEEN stap in de builder

━━━ TARGET ARRAY ━━━
Altijd 2 objecten. Object 1 is de zone, object 2 is altijd "open".

Bij pace-zones (target="pace"):
  Object 1: {"targetType":"pace_zone","zoneBased":true,"zone":<1-5>,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false}

Bij hartslagzones (target="hr"):
  Object 1: {"targetType":"hr_zone","zoneBased":true,"zone":<1-5>,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false}

Object 2 (altijd hetzelfde):
  {"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}

━━━ REPEAT-BLOK (type: "repeat") ━━━
Gebruik dit voor intervallen met herhaling (bijv. 5x 800m, 4x 4km):
  type: "repeat"
  id: integer vanaf 5001
  name: null, name_original: null, comments: null, comments_original: null
  durationType: "DISTANCE", duration: "00:00", durationDist: null, distUnit: "km"
  target: [zone-object van de actieve inner step, open-object]  ← NOOIT een lege array []
  data: []
  steps: [ <inner stappen: ACTIVE + optioneel REST> ]   (wordt automatisch omgezet naar "data" voor FinalSurge)
  repeats: <aantal herhalingen als integer>
  skip_last_rest: false
  intensity: "ACTIVE"

Inner steps van een repeat-blok krijgen id's vanaf 201, 202, etc.
Inner REST-stap: gebruik DISTANCE in km (bijv. 0.4 voor 400m herstel). NOOIT TIME.

━━━ ZONE MAPPING ━━━
Z1 = zone 1, Z2 = zone 2, Z3 = zone 3, Z4 = zone 4, Z5 = zone 5

Expliciete zonenummers in de beschrijving altijd respecteren: "Z3" → zone 3, "Z4" → zone 4, etc.

Als de beschrijving geen expliciet zonenummer geeft:
- Warming-up / cooling-down / herstel → zone 1
- Rustige duurloop (hoofdblok) → zone 2
- Vlotte duurloop / comfortabel hard → zone 3
- Intervalblokken / tempoblokken / hard → zone 4
- Sprint / maximaal / VO2max → zone 5

KRITIEK voor warming-up en cooling-down: gebruik ALTIJD zone 1, ook als het hoofdblok een hogere zone heeft.
KRITIEK voor repeat-blokken: gebruik de zone van de ACTIEVE intervallen (niet zone 1) tenzij expliciet anders staat.

━━━ WANDELEN ━━━
Als de beschrijving "wandelen" of "walk" noemt (bijv. wandelherstel tussen intervallen):
- geef die stap het veld "name": "wandelen" en intensity "REST"
- gebruik GEEN loopzone (geen zone 1) voor die stap; de app vult zelf een wandel-pace in
- behoud de afstand/tijd zoals beschreven (bijv. 1 min of 200m wandelen)

━━━ VOORBEELDEN ━━━

VOORBEELD 1 — Intervaltraining (5x 800m Z4, herstel 400m Z1):
{
  "target_options": [{
    "name": "Intervaltraining",
    "description": null,
    "sport": "running",
    "target": "hr",
    "target_override": null,
    "steps": [
      {"type":"step","id":101,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":1.5,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"WARMUP"},
      {"type":"repeat","id":5001,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":null,"distUnit":"km","target":[],"data":[],"steps":[
        {"type":"step","id":201,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":0.8,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":4,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"ACTIVE"},
        {"type":"step","id":202,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":0.4,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"REST"}
      ],"repeats":5,"skip_last_rest":false,"intensity":"ACTIVE"},
      {"type":"step","id":102,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":1.5,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"COOLDOWN"}
    ]
  }]
}

VOORBEELD 2 — Rustige duurloop (10 km Z2, pace zones):
{"target_options":[{"name":"Rustige duurloop","description":null,"sport":"running","target":"pace","target_override":null,"steps":[{"type":"step","id":101,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":1.5,"distUnit":"km","intensity":"WARMUP","target":[{"targetType":"pace_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false},{"type":"step","id":102,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":7.0,"distUnit":"km","intensity":"ACTIVE","target":[{"targetType":"pace_zone","zoneBased":true,"zone":2,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false},{"type":"step","id":103,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":1.5,"distUnit":"km","intensity":"COOLDOWN","target":[{"targetType":"pace_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false}]}]}

VOORBEELD 3 — Fartlek (200m Z4 / 300m Z1, herhaal x14, totaal 10km):
Beschrijving: "Fartlek 10km | Warming-up: 1.5km Z1 | Hoofdblok: 200m Z4 / 300m Z1, herhaal x14 | Cooling-down: 1.5km Z1"
→ repeat-blok met 14 herhalingen, inner stap 1 = 0.2km Z4 ACTIVE, inner stap 2 = 0.3km Z1 REST
{"target_options":[{"name":"Fartlek","description":null,"sport":"running","target":"hr","target_override":null,"steps":[{"type":"step","id":101,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":1.5,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"WARMUP"},{"type":"repeat","id":5001,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":null,"distUnit":"km","target":[],"data":[],"steps":[{"type":"step","id":201,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":0.2,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":4,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"ACTIVE"},{"type":"step","id":202,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":0.3,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"REST"}],"repeats":14,"skip_last_rest":false,"intensity":"ACTIVE"},{"type":"step","id":102,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":1.5,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"COOLDOWN"}]}]}

VOORBEELD 4 — Progressieve duurloop (4km Z1 / 4km Z2 / 4km Z3, totaal 12km):
Beschrijving: "Progressieve duurloop 12km | Hoofdblok: 4km Z1 / 4km Z2 / 4km Z3"
→ 3 losse ACTIVE stappen, elk met eigen zone. Geen repeat-blok. Geen aparte warmup/cooldown (zit in de loop).
{"target_options":[{"name":"Progressieve duurloop","description":null,"sport":"running","target":"hr","target_override":null,"steps":[{"type":"step","id":101,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":4.0,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"WARMUP"},{"type":"step","id":102,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":4.0,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":2,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"ACTIVE"},{"type":"step","id":103,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":4.0,"distUnit":"km","target":[{"targetType":"hr_zone","zoneBased":true,"zone":3,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"COOLDOWN"}]}]}

VOORBEELD 5 — Tempo-blok (6km Z3 aaneengesloten):
Beschrijving: "Tempoloop | Warming-up: 2km Z1 | Hoofdblok: 6km Z3 aaneengesloten | Cooling-down: 2km Z1"
→ één losse ACTIVE stap voor het hoofdblok, geen repeat-blok
{"target_options":[{"name":"Tempoloop","description":null,"sport":"running","target":"pace","target_override":null,"steps":[{"type":"step","id":101,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":2.0,"distUnit":"km","target":[{"targetType":"pace_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"WARMUP"},{"type":"step","id":102,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":6.0,"distUnit":"km","target":[{"targetType":"pace_zone","zoneBased":true,"zone":3,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"ACTIVE"},{"type":"step","id":103,"name":null,"name_original":null,"comments":null,"comments_original":null,"durationType":"DISTANCE","duration":"00:00","durationDist":2.0,"distUnit":"km","target":[{"targetType":"pace_zone","zoneBased":true,"zone":1,"targetLow":null,"targetHigh":null,"targetOption":null,"targetTypeOriginal":null,"targetOptionOriginal":null,"targetIsTimeBased":false},{"targetType":"open","targetOption":"","zoneBased":false,"targetLow":"0","targetHigh":"0","zone":0,"targetIsTimeBased":false,"targetTypeOriginal":null,"targetOptionOriginal":null}],"data":[],"repeats":null,"skip_last_rest":false,"intensity":"COOLDOWN"}]}]}

━━━ BESLISREGELS ━━━

1. Staat er "Xkm aaneengesloten" of "Xkm Z?" zonder herhaling → losse ACTIVE stap
2. Staat er "Nx Ym Z? / Zm Z?" → repeat-blok met N herhalingen, ACTIVE + REST inner stap
3. Staat er "Xkm Z1 / Ykm Z2 / Zkm Z3" (oplopende zones) → 3 losse stappen (progressieve loop)
4. Staat er "herhaal x N" of "×N" → repeat-blok met dat aantal
5. Warming-up staat ALTIJD als aparte stap met intensity WARMUP, zone 1
6. Cooling-down staat ALTIJD als aparte stap met intensity COOLDOWN, zone 1
7. Als er geen aparte warmup/cooldown in de beschrijving staat: voeg 1.5km Z1 warmup en 1km Z1 cooldown toe

━━━ OUTPUT STRUCTUUR ━━━
{
  "target_options": [
    {
      "name": "<workout naam>",
      "description": null,
      "sport": "running",
      "target": "pace" | "hr",
      "target_override": null,
      "steps": [ ... ALLE stappen inclusief hoofdblok ... ]
    }
  ]
}"""


def generate_builder_steps(
    workout_name: str,
    description: str,
    zone_type: str = "pace",  # "pace" of "heart_rate"
    activity_type: str = "Run",
    op_tijd: bool = False,
) -> list:
    """
    Zet een workout-beschrijving om naar FinalSurge WorkoutBuilder stappen.
    Geeft de target_options lijst terug (klaar voor WorkoutBuilderSave).
    Alleen voor hardloop-workouts; cross training en rest worden overgeslagen.
    """
    if activity_type not in ("Run", "Bike", "Swim"):
        return []
    if not description or not description.strip():
        return []

    # Alleen het inhoudelijke deel (voor de ---) meegeven
    desc_main = description.split("---")[0].strip() if "---" in description else description.strip()
    if not desc_main:
        return []

    sport_map = {"Run": "running", "Bike": "cycling", "Swim": "swimming"}
    sport = sport_map.get(activity_type, "running")
    # FinalSurge gebruikt intern "hr" voor hartslag (niet "heart_rate")
    target = "hr" if zone_type in ("heart_rate", "hartslag", "hr") else "pace"

    tijdnotitie = (
        "\n\nLET OP — SCHEMA OP TIJD: gebruik durationType 'TIME'. "
        "duration formaat: MM:SS voor tijden onder 60 min (bijv. '45:00', '03:00', '10:00'). "
        "Alleen H:MM:SS als de tijd 60 min of meer is. durationDist = null."
        if op_tijd else ""
    )

    prompt = f"""Workout naam: {workout_name}
Sport: {sport}
Zone-type: {target} ({'min/km' if target == 'pace' else 'bpm'}){tijdnotitie}

Beschrijving:
{desc_main[:1500]}

Genereer de FinalSurge WorkoutBuilder JSON voor deze workout."""

    import json, tempfile, os
    try:
        response = create_message(
            model="claude-opus-4-5",
            max_tokens=3000,
            system=BUILDER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Schrijf raw output naar debug-bestand (best-effort — werkt niet op cloud)
        try:
            debug_path = os.path.join(os.path.dirname(__file__), "builder_debug.txt")
            with open(debug_path, "w") as f:
                f.write(f"=== PROMPT ===\n{prompt}\n\n=== RAW OUTPUT ===\n{raw}\n")
        except Exception:
            pass

        # Strip markdown als die er toch omheen zit
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        parsed = json.loads(raw)

        # Bepaal het target-type (hr of pace) voor default target-objecten
        tgt_type = "hr_zone" if target == "hr" else "pace_zone"

        def _default_target(zone: int = 1) -> list:
            """Geeft een geldige 2-element target array terug (vereist door FinalSurge UI)."""
            return [
                {
                    "targetType": tgt_type,
                    "zoneBased": True,
                    "zone": zone,
                    "targetLow": None,
                    "targetHigh": None,
                    "targetOption": None,
                    "targetTypeOriginal": None,
                    "targetOptionOriginal": None,
                    "targetIsTimeBased": False,
                },
                {
                    "targetType": "open",
                    "targetOption": "",
                    "zoneBased": False,
                    "targetLow": "0",
                    "targetHigh": "0",
                    "zone": 0,
                    "targetIsTimeBased": False,
                    "targetTypeOriginal": None,
                    "targetOptionOriginal": None,
                },
            ]

        def _fix_duration(step: dict) -> None:
            """Zet 'HH:MM:SS' om naar 'MM:SS' voor tijden onder 60 min (FinalSurge toont anders '00:MM:SS')."""
            if step.get("durationType") != "TIME":
                return
            dur = step.get("duration") or ""
            parts = dur.split(":")
            if len(parts) == 3 and parts[0] == "00":
                step["duration"] = f"{parts[1]}:{parts[2]}"

        def _is_wandel(step: dict) -> bool:
            blob = " ".join(
                str(step.get(k) or "") for k in ("name", "name_original", "comments", "comments_original")
            ).lower()
            return "wandel" in blob or "walk" in blob

        def _wandel_target(step: dict) -> bool:
            """
            Zet een wandel-stap op een pace-target van 10:00-12:00 min/km i.p.v. een zone.
            10:00/km = 600 sec, 12:00/km = 720 sec. Geeft True terug als toegepast.
            """
            if target != "pace" or not _is_wandel(step):
                return False
            step["target"] = [
                {
                    "targetType": "pace",
                    "zoneBased": False,
                    "zone": 0,
                    "targetLow": "10:00",   # min/km (sneller)
                    "targetHigh": "12:00",  # min/km (langzamer)
                    "targetOption": None,
                    "targetTypeOriginal": None,
                    "targetOptionOriginal": None,
                    "targetIsTimeBased": False,
                },
                _default_target()[1],
            ]
            return True

        def _fix_step_targets(step: dict) -> None:
            """Zorg dat elke stap een geldige niet-lege target array heeft."""
            t = step.get("target")
            if not t:  # None of []  → FinalSurge UI crasht anders
                # Bepaal zone van de stap zelf of gebruik zone 1 als fallback
                zone = 1
                step["target"] = _default_target(zone)
            elif len(t) == 1:
                # Voeg het verplichte open-object toe als het ontbreekt
                step["target"].append(_default_target()[1])

        for opt in parsed.get("target_options", []):
            for step in opt.get("steps", []):
                # Verplaats inner steps van "steps" naar "data" (FinalSurge API-vereiste)
                if step.get("type") == "repeat" and step.get("steps"):
                    step["data"] = step.pop("steps")
                # Fix targets op repeat-blok zelf
                _wandel_target(step)
                _fix_step_targets(step)
                _fix_duration(step)
                # Fix targets op alle inner steps
                for inner in step.get("data", []):
                    _wandel_target(inner)
                    _fix_step_targets(inner)
                    _fix_duration(inner)

        return parsed.get("target_options", [])
    except Exception as e:
        try:
            debug_path = os.path.join(os.path.dirname(__file__), "builder_debug.txt")
            with open(debug_path, "a") as f:
                f.write(f"\n=== PARSE ERROR ===\n{e}\n")
        except Exception:
            pass
        return []


# ---------------------------------------------------------------------------
# FinalSurge import
# ---------------------------------------------------------------------------

def _parse_duration_to_min(dur: str) -> float:
    """'MM:SS' of 'H:MM:SS' → minuten (float)."""
    parts = (dur or "").split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
        if len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 60
    except ValueError:
        return 0.0
    return 0.0


def _calc_builder_duration_min(target_options: list):
    """
    Bereken de totale tijd in minuten vanuit de WorkoutBuilder target_options.
    Telt alle TIME-stappen op (inclusief repeat-blokken × herhalingen), zodat de
    geplande totaaltijd exact gelijk loopt met wat in de builder staat.
    """
    total = 0.0
    found = False

    def _step_min(step: dict) -> float:
        if step.get("durationType") == "TIME":
            return _parse_duration_to_min(step.get("duration") or "")
        return 0.0

    for opt in target_options:
        for step in opt.get("steps", []):
            if step.get("type") == "repeat":
                reps = step.get("repeats") or 1
                for inner in (step.get("data") or step.get("steps") or []):
                    m = _step_min(inner)
                    if m > 0:
                        total += m * reps
                        found = True
            else:
                m = _step_min(step)
                if m > 0:
                    total += m
                    found = True

    return round(total) if found else None


def _calc_builder_distance_km(target_options: list):
    """
    Bereken de totale afstand in km vanuit WorkoutBuilder target_options.
    Telt alle DISTANCE-stappen op (inclusief repeat-blokken × aantal herhalingen).
    """
    total = 0.0
    found_any = False

    def _step_km(step: dict) -> float:
        if step.get("durationType") == "DISTANCE":
            dist = step.get("durationDist") or 0
            return float(dist)
        return 0.0

    for opt in target_options:
        for step in opt.get("steps", []):
            if step.get("type") == "repeat":
                reps = step.get("repeats") or 1
                inner = step.get("data") or step.get("steps") or []
                for inner_step in inner:
                    km = _step_km(inner_step)
                    if km > 0:
                        total += km * reps
                        found_any = True
            else:
                km = _step_km(step)
                if km > 0:
                    total += km
                    found_any = True

    return round(total) if found_any else None  # afronden naar heel kilometer


def import_to_finalsurge(
    athlete_key: str,
    workouts: list[dict],
    zone_type: str = "pace",
    progress_callback=None,
    fill_builder: bool = True,
    op_tijd: bool = False,
) -> tuple[int, list[str], list[str]]:
    """
    Importeer een lijst van workout-dicts naar FinalSurge.
    fill_builder: als True, vult ook de WorkoutBuilder met zone-stappen.
    op_tijd: als True, wordt geplande tijd gebruikt i.p.v. afstand.
    Geeft (aantal_gelukt, workout_fouten, builder_fouten) terug.
    """
    import fs_client
    import time

    ok = 0
    errors = []
    builder_errors = []

    for i, w in enumerate(workouts):
        if progress_callback:
            progress_callback(i, len(workouts), w.get("name", ""))

        try:
            desc = w.get("description", "")
            activity_type = w.get("activity_type", "Run")

            # Stap 1: genereer WorkoutBuilder stappen eerst zodat we de exacte afstand weten
            builder_steps = []
            planned_km = w.get("planned_km")

            if fill_builder and desc.strip() and activity_type in ("Run", "Bike", "Swim"):
                try:
                    builder_steps = generate_builder_steps(
                        workout_name=w["name"],
                        description=desc,
                        zone_type=zone_type,
                        activity_type=activity_type,
                        op_tijd=op_tijd,
                    )
                    # Bij afstandsschema: gebruik builder-km als geplande afstand
                    if builder_steps and not op_tijd:
                        builder_km = _calc_builder_distance_km(builder_steps)
                        if builder_km:
                            planned_km = builder_km
                except Exception as be:
                    builder_errors.append(f"{w['date']} {w['name']} (builder generatie): {be}")

            # Stap 2: sla de workout op
            planned_min = w.get("planned_min") if op_tijd else None
            # Bij tijdsschema: gebruik de builder-totaaltijd als geplande tijd,
            # zodat de geplande totaaltijd exact matcht met de WorkoutBuilder.
            if op_tijd and builder_steps:
                builder_min = _calc_builder_duration_min(builder_steps)
                if builder_min:
                    planned_min = builder_min
            result = fs_client.save_workout(
                user_key=athlete_key,
                workout_date=w["date"],
                name=w["name"],
                description=desc,
                activity_type=activity_type,
                planned_distance_km=None if op_tijd else planned_km,
                planned_duration_min=planned_min,
            )

            # Haal de workout_key op uit de API-respons
            workout_key = (
                result.get("new_workout_key")
                or (result.get("data") or {}).get("key")
                or (result.get("data") or {}).get("workout_key")
            )

            # Stap 3: sla de WorkoutBuilder op
            if fill_builder and builder_steps:
                if not workout_key:
                    builder_errors.append(
                        f"{w['date']} {w['name']}: geen workout_key in respons — "
                        f"respons was: {str(result)[:200]}"
                    )
                else:
                    try:
                        fs_client.save_workout_builder(
                            user_key=athlete_key,
                            workout_key=workout_key,
                            target_options=builder_steps,
                            workout_name=w.get("name", ""),
                        )
                    except Exception as be:
                        builder_errors.append(f"{w['date']} {w['name']} (builder opslaan): {be}")
            elif fill_builder and desc.strip() and activity_type in ("Run", "Bike", "Swim") and not builder_steps:
                builder_errors.append(
                    f"{w['date']} {w['name']}: geen stappen gegenereerd (lege beschrijving?)"
                )

            ok += 1

            # Kleine pauze om rate limiting te voorkomen
            if fill_builder:
                time.sleep(0.3)

        except Exception as e:
            errors.append(f"{w['date']} {w['name']}: {e}")

    return ok, errors, builder_errors
