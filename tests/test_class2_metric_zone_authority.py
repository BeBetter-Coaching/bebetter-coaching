"""Correctness Round 2 — Class 2: Deterministic metric & zone authority.

Feedback mag geen eigen zone-/metric-conclusies meer trekken uit ruwe tempo-/HR-waarden naast
ruwe zonegrenzen wanneer de code dat deterministisch kan vaststellen. De AI ontvangt per lap het
resultaat van de bestaande canonical classifier (`fs_client.classify_pace_hr_zone`) als FEIT, en
de EXPLICIET geplande metric is leidend (planned metric → athlete zone type fallback). Geen tweede
zone-engine, `fs_client` byte-identiek, PF-4 intact.

    python3 -m pytest tests/test_class2_metric_zone_authority.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback
import fs_client


# ── Zonetabellen (native eenheid: tempo = seconden/km, HF = bpm) ─────────────
# Tempo: lagere seconden = sneller = zwaarder.
TEMPO_ZONES = [
    {"num": 1, "naam": "Herstel", "low": 310, "high": 360},   # 5:10–6:00
    {"num": 2, "naam": "Duur",    "low": 256, "high": 310},   # 4:16–5:10
    {"num": 3, "naam": "Tempo",   "low": 230, "high": 256},   # 3:50–4:16
    {"num": 4, "naam": "Drempel", "low": 210, "high": 230},   # 3:30–3:50
]
# Scenario B — Z2 snelle grens exact 5:14 (314s).
TEMPO_ZONES_B = [
    {"num": 2, "naam": "Duur",  "low": 314, "high": 345},     # 5:14–5:45
    {"num": 3, "naam": "Tempo", "low": 290, "high": 314},     # 4:50–5:14
]
HR_ZONES = [
    {"num": 1, "naam": "Herstel", "low": 110, "high": 130},
    {"num": 2, "naam": "Duur",    "low": 130, "high": 145},
    {"num": 3, "naam": "Tempo",   "low": 145, "high": 160},
    {"num": 4, "naam": "Drempel", "low": 160, "high": 175},
]


def _lap(pace=None, hr=None, dist=None, dur=None):
    d = {}
    if pace is not None:
        d["pace_display"] = pace
    if hr is not None:
        d["hr_avg"] = hr
    if dist is not None:
        d["amount"] = dist
    if dur is not None:
        d["duration"] = dur
    return d


# ════════════════════════════════════════════════════════════════════════════
# 1-4, 9 — per-lap deterministische classificatie via _format_laps
# ════════════════════════════════════════════════════════════════════════════
def test_1_per_lap_pace_classificatie():
    out = ai_feedback._format_laps([_lap(pace="4:12"), _lap(pace="4:25")],
                                   zones=TEMPO_ZONES, is_pace=True)
    regels = out.strip().split("\n")
    assert "→ Z3" in regels[0]       # 4:12 = 252s → Z3 (sneller dan Z2-grens 4:16)
    assert "→ Z2" in regels[1]       # 4:25 = 265s → Z2


def test_2_per_lap_hr_classificatie():
    out = ai_feedback._format_laps([_lap(hr=150), _lap(hr=138)],
                                   zones=HR_ZONES, is_pace=False)
    regels = out.strip().split("\n")
    assert "→ Z3" in regels[0]       # 150 bpm → Z3
    assert "→ Z2" in regels[1]       # 138 bpm → Z2


def test_3_pace_range_over_edge_individuele_labels():
    # Range 4:12–4:25 rond de Z2-grens 4:16 → NIET één label voor de hele range.
    out = ai_feedback._format_laps(
        [_lap(pace="4:12"), _lap(pace="4:18"), _lap(pace="4:25")],
        zones=TEMPO_ZONES, is_pace=True)
    regels = out.strip().split("\n")
    assert "→ Z3" in regels[0]       # 4:12 (252s) sneller dan Z2 → Z3
    assert "→ Z2" in regels[1]       # 4:18 (258s) → Z2
    assert "→ Z2" in regels[2]       # 4:25 (265s) → Z2
    labels = {r.split("→")[1].strip() for r in regels}
    assert len(labels) > 1           # niet de hele range in één zone


def test_4_5_25_langzamer_dan_5_14():
    # 5:25 (325s) MOET langzamer dan 5:14 (314s) zijn → Z2, nooit Z3.
    out = ai_feedback._format_laps([_lap(pace="5:25")], zones=TEMPO_ZONES_B, is_pace=True)
    assert "→ Z2" in out
    assert "Z3" not in out           # nooit '5:25 sneller dan 5:14 → Z3'


def test_9_geen_ruwe_pace_zonder_label():
    # Elke classificeerbare lap krijgt een deterministisch label (→). Rauwe pace staat
    # nooit zonder label naast de zonegrenzen.
    out = ai_feedback._format_laps([_lap(pace="4:12"), _lap(pace="4:25"), _lap(pace="4:05")],
                                   zones=TEMPO_ZONES, is_pace=True)
    regels = [r for r in out.strip().split("\n") if r.strip()]
    assert all("→" in r for r in regels)              # geen lap zonder deterministisch label
    assert "tempo 4:12" in out                        # ruw getal blijft als feit staan


def test_out_of_range_is_geen_valse_membership():
    # 3:20 (200s) sneller dan de snelste zone (Z4 low=210) → BUITEN de zones, geen 'Z4'-membership.
    out = ai_feedback._format_laps([_lap(pace="3:20")], zones=TEMPO_ZONES, is_pace=True)
    assert "BUITEN de zones" in out and "sneller dan Z4" in out
    assert "→ Z4 (door de app" not in out             # geen valse membership


def test_zonder_classificatiecontext_ongewijzigd():
    # Geen zones/is_pace → ongewijzigd gedrag: ruwe getallen, geen '→'-label.
    out = ai_feedback._format_laps([_lap(pace="4:12", hr=150)])
    assert "tempo 4:12" in out and "HF 150 bpm" in out
    assert "→" not in out


# ════════════════════════════════════════════════════════════════════════════
# _build_workout_context helpers (5,6,7,8,10) — echte FC-2 classifier draait mee
# ════════════════════════════════════════════════════════════════════════════
def _zones_result(zone_type, struct):
    return {"zones_text": "\n".join(f"Z{z['num']} ({z['naam']})" for z in struct),
            "zone_type": zone_type, "zones": struct}


def _step(target_type, zone, dist=None, dur=None):
    s = {"intensity": "ACTIVE", "target": [{"targetType": target_type, "zone": zone}]}
    if dist is not None:
        s["durationType"] = "DISTANCE"; s["durationDist"] = dist; s["distUnit"] = "km"
    if dur is not None:
        s["duration"] = dur
    return s


def _ctx(monkeypatch, zone_type, struct, steps, activity):
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda *a, **k: steps, raising=False)
    monkeypatch.setattr(fs_client, "get_athlete_zones",
                        lambda *a, **k: _zones_result(zone_type, struct), raising=False)
    monkeypatch.setattr(ai_feedback.intake_store, "garmin_context_text", lambda *a, **k: "", raising=False)
    wd = {
        "athlete_first_name": "Lisa", "athlete_name": "Lisa Test",
        "workout_name": "Interval", "post_notes": "", "athlete_comments": [],
        "workout_key": "WK", "athlete_key": "AK", "workout_date": "2026-08-20",
        "felt": None, "effort": None, "coach_profiel": "", "brein_context": "",
        "details": {"description": "", "has_structured_workout": True,
                    "is_race": False, "Activities": [activity]},
    }
    ctx, _ = ai_feedback._build_workout_context(wd)
    return ctx


def test_5_pace_target_hr_athlete_is_pace_led(monkeypatch):
    steps = [_step("pacezone", 2, dist=2)]                 # geplande metric = tempo
    act = {"pace_display": "4:20", "hr_avg": 150,
           "Laps": [_lap(pace="4:20", hr=150, dist=2)]}
    ctx = _ctx(monkeypatch, "hartslag", HR_ZONES, steps, act)   # atleet heeft HR-zones
    assert "GEPLANDE target-metric is TEMPO" in ctx
    assert "Beoordeel PRIMAIR via tempo" in ctx
    assert "nooit maken dat je tempo niet beoordeelt" in ctx
    assert "UITSLUITEND via hartslag" not in ctx           # oude HR-led gedrag weg


def test_6_hr_target_pace_athlete_is_hr_led(monkeypatch):
    steps = [_step("hrzone", 2, dist=2)]                   # geplande metric = hartslag
    act = {"pace_display": "4:20", "hr_avg": 150, "Laps": [_lap(pace="4:20", hr=150, dist=2)]}
    ctx = _ctx(monkeypatch, "tempo", TEMPO_ZONES, steps, act)   # atleet heeft tempo-zones
    assert "GEPLANDE target-metric is HARTSLAG" in ctx
    assert "Beoordeel PRIMAIR via hartslag" in ctx
    assert "UITSLUITEND via tempo" not in ctx


def test_7_geen_planned_metric_zonetype_fallback(monkeypatch):
    steps = [{"intensity": "ACTIVE", "target": [{"targetType": "open"}],
              "durationType": "DISTANCE", "durationDist": 5, "distUnit": "km"}]
    act = {"pace_display": "4:20", "hr_avg": 150,
           "Laps": [_lap(pace="4:12", hr=150, dist=1), _lap(pace="4:25", hr=150, dist=1)]}
    ctx = _ctx(monkeypatch, "tempo", TEMPO_ZONES, steps, act)   # geen planned metric → tempo-fallback
    assert "TEMPO-ZONES VAN LISA" in ctx
    assert "PRIMAIR via tempo" in ctx
    assert "DETERMINISTISCH geclassificeerd" in ctx
    assert "→ Z3" in ctx and "→ Z2" in ctx                 # per-lap labels aanwezig


def test_8_ambiguous_blocks_geen_verzonnen_per_block_truth(monkeypatch):
    # 3 geplande blokken vs 2 laps → AMBIGUOUS (count mismatch): geen per-blok-waarheid,
    # maar per-lap labels mogen wel, met expliciete 'per lap, niet per blok'-waarschuwing.
    steps = [_step("pacezone", 3, dist=1), _step("pacezone", 3, dist=1), _step("pacezone", 3, dist=1)]
    act = {"pace_display": "4:12", "hr_avg": 150,
           "Laps": [_lap(pace="4:12", dist=1), _lap(pace="4:14", dist=1)]}
    ctx = _ctx(monkeypatch, "tempo", TEMPO_ZONES, steps, act)
    assert "NIET betrouwbaar" in ctx                       # blok-analyse eerlijk AMBIGUOUS
    assert "PER LAP, niet per blok" in ctx                 # per-lap labels, geen blok-generalisatie
    assert "→ Z3" in ctx                                    # 4:12 en 4:14 zijn Z3 als losse laps


def test_10_pf4_interval_hr_guard_intact(monkeypatch):
    # Gestructureerd (≥2 blokken) + AMBIGUOUS + HR-athlete/HR-target → PF-4-OORDEEL blijft:
    # het gemiddelde bewijst NIET dat de werkblokken hun target haalden.
    steps = [_step("hrzone", 3, dist=1), _step("hrzone", 3, dist=1), _step("hrzone", 3, dist=1)]
    act = {"pace_display": "4:20", "hr_avg": 150,
           "Laps": [_lap(hr=150, dist=1), _lap(hr=152, dist=1)]}
    ctx = _ctx(monkeypatch, "hartslag", HR_ZONES, steps, act)
    assert "bewijst NIET" in ctx
    assert "NIET vast te stellen" in ctx                   # AMBIGUOUS-tak van PF-4
    assert "correct uitgevoerd" in ctx                     # (in de 'NOOIT ... correct uitgevoerd'-zin)


# ════════════════════════════════════════════════════════════════════════════
# 12,13 — één canonical engine + zonegrenzen/math ongewijzigd
# ════════════════════════════════════════════════════════════════════════════
def test_12_enige_zone_engine_is_fs_classifier():
    # ai_feedback classificeert NIET zelf: _lap_zone_label mapt ALLEEN de classifier-status
    # (num/nearest_num), raakt nooit de zonegrens-velden aan; de enige engine die grenzen
    # vergelijkt is fs_client.classify_pace_hr_zone (in _format_laps + berekende_zone_regel).
    src = open(os.path.join(_ROOT, "ai_feedback.py")).read()
    assert src.count("classify_pace_hr_zone(") >= 2         # per-lap + gemiddelde via de canonical engine
    body = src.split("def _lap_zone_label")[1].split("def _format_laps")[0]
    for grens in ("low", "high", "onder", "boven"):
        assert grens not in body                            # geen eigen grens-arithmetiek
    assert 'cls.get("status")' in body                      # mapt uitsluitend de deterministische status


# ════════════════════════════════════════════════════════════════════════════
# Round-2 regressie B — inclusieve zonegrenzen (5:34 bij zone 5:14–5:34 = IN de zone)
# ════════════════════════════════════════════════════════════════════════════
# FinalSurge-stijl: 1-seconde gat tussen aangrenzende zones (Z2.high=334, Z1.low=335).
GAP_PACE = [{"num": 1, "naam": "Herstel", "low": 335, "high": 390},   # 5:35–6:30
            {"num": 2, "naam": "Duur",    "low": 314, "high": 334},   # 5:14–5:34
            {"num": 3, "naam": "Tempo",   "low": 290, "high": 313}]   # 4:50–5:13
GAP_HR = [{"num": 1, "low": 111, "high": 130},
          {"num": 2, "low": 131, "high": 145},                        # gat: 130↔131
          {"num": 3, "low": 146, "high": 160}]


def test_B_exacte_snelle_grens_in_zone():
    assert fs_client.classify_pace_hr_zone(GAP_PACE, 314, is_pace=True)["num"] == 2   # 5:14


def test_B_exacte_langzame_grens_in_zone():
    r = fs_client.classify_pace_hr_zone(GAP_PACE, 334, is_pace=True)                  # 5:34
    assert r["status"] == "IN_ZONE" and r["num"] == 2                                 # NIET BETWEEN


def test_B_een_sec_sneller_in_zone():
    assert fs_client.classify_pace_hr_zone(GAP_PACE, 333, is_pace=True)["num"] == 2   # 5:33


def test_B_een_sec_langzamer_volgende_zone():
    assert fs_client.classify_pace_hr_zone(GAP_PACE, 335, is_pace=True)["num"] == 1   # 5:35 → Z1


def test_B_hr_exacte_bovengrens_in_zone():
    r = fs_client.classify_pace_hr_zone(GAP_HR, 145, is_pace=False)                   # exact Z2.high
    assert r["status"] == "IN_ZONE" and r["num"] == 2


def test_B_ai_context_behoudt_exact_label_geen_erbuiten():
    # de per-lap AI-context krijgt het deterministische IN_ZONE-label; nooit 'BUITEN de banden'.
    out = ai_feedback._format_laps([_lap(pace="5:34")], zones=GAP_PACE, is_pace=True)
    assert "→ Z2" in out
    assert "BUITEN" not in out and "tussen zones" not in out                          # geen 'net erbuiten'


def test_B_contigue_tabel_ongewijzigd():
    # regressiebescherming: bij een CONTIGUE tabel blijft de bovengrens naar de langzamere zone
    # gaan (geen overlap-verandering) — bewijs dat B alleen gaten/laatste-zone-randen dicht.
    contig = [{"num": 3, "low": 247, "high": 270}, {"num": 4, "low": 227, "high": 247}]
    assert fs_client.classify_pace_hr_zone(contig, 247, is_pace=True)["num"] == 3     # 4:07 → Z3 (ongewijzigd)


def test_13_zonegrenzen_math_ongewijzigd():
    # De canonical classifier blijft exact hetzelfde rekenen (geen zonegrens-wijziging).
    assert fs_client.classify_pace_hr_zone(TEMPO_ZONES, 252, is_pace=True)["num"] == 3    # 4:12 → Z3
    assert fs_client.classify_pace_hr_zone(TEMPO_ZONES, 265, is_pace=True)["num"] == 2    # 4:25 → Z2
    assert fs_client.classify_pace_hr_zone(HR_ZONES, 150, is_pace=False)["num"] == 3      # 150 → Z3
    slow = fs_client.classify_pace_hr_zone(TEMPO_ZONES, 200, is_pace=True)                # 3:20 sneller dan Z4
    assert slow["status"] == "ABOVE_HARDEST_ZONE" and slow["num"] is None
