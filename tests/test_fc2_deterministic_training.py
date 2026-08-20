"""FC-2 — Deterministische zoneclassificatie + per-blok HR/planned-intensity vóór AI.

Twee P0's uit System Coherence Gate v1:
  A. de pace-zoneclassifier voor Feedback mag out-of-range NOOIT als echte zonemembership
     presenteren (geen stille nearest-zone clamp) → `classify_pace_hr_zone` (eerlijk).
  D–G. interval-/blok-HR wordt deterministisch tegen planned intensity/HR-doel gezet, met
     expliciete mapping-confidence; een HR onder target betekent NOOIT deterministisch "harder".

`fs_client.zone_van_waarde` (met clamp) blijft bewust ONGEWIJZIGD voor Masterbrein/Schema;
Feedback gebruikt de nieuwe eerlijke classifier.

    python3 -m pytest tests/test_fc2_deterministic_training.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import fs_client
import ai_feedback


# Persoonlijke pacezones (sec/km) — FinalSurge-conventie: low = langzame edge (hoge sec),
# high = snelle edge (lage sec). Contigu Z1..Z5.
PACE = [
    {"num": 1, "naam": "Rustig", "low": 600, "high": 330},   # 5:30–10:00
    {"num": 2, "naam": "Duur", "low": 330, "high": 300},     # 5:00–5:30
    {"num": 3, "naam": "Tempo", "low": 300, "high": 270},    # 4:30–5:00
    {"num": 4, "naam": "Drempel", "low": 270, "high": 240},  # 4:00–4:30
    {"num": 5, "naam": "VO2", "low": 240, "high": 210},      # 3:30–4:00
]
HR = [
    {"num": 1, "naam": "Herstel", "low": 100, "high": 130},
    {"num": 2, "naam": "Duur", "low": 130, "high": 150},
    {"num": 3, "naam": "Tempo", "low": 150, "high": 165},
    {"num": 4, "naam": "Drempel", "low": 165, "high": 180},
]


def _c(zones, w, is_pace):
    return fs_client.classify_pace_hr_zone(zones, w, is_pace)


# ════════════════════════════════════════════════════════════════════════════
# A/B — pace-zoneclassificatie (geen stille clamp; alle Z1–Z5-grensgevallen)
# ════════════════════════════════════════════════════════════════════════════
class TestPaceZoneClassifier:
    def test_1_exact_binnen_iedere_zone(self):
        for sec, num in [(465, 1), (315, 2), (285, 3), (255, 4), (225, 5)]:
            r = _c(PACE, sec, True)
            assert r["status"] == "IN_ZONE" and r["num"] == num, (sec, r)

    def test_2_exacte_grenzen(self):
        # ondergrens (snelle edge) inclusief; bovengrens (langzame edge) → makkelijkere zone
        assert _c(PACE, 240, True)["num"] == 4          # Z4 snelle edge (incl.)
        assert _c(PACE, 270, True)["num"] == 3          # Z4 langzame edge → Z3
        assert _c(PACE, 210, True)["num"] == 5          # Z5 snelste edge (incl.)

    def test_3_een_sec_beide_kanten(self):
        assert _c(PACE, 241, True)["num"] == 4          # net langzamer dan Z4-snel → Z4
        assert _c(PACE, 239, True)["num"] == 5          # net sneller dan Z4-snel → Z5
        assert _c(PACE, 269, True)["num"] == 4
        assert _c(PACE, 271, True)["num"] == 3

    def test_4_sneller_dan_snelste_zone(self):
        r = _c(PACE, 200, True)                         # 3:20 — sneller dan Z5 (snelste)
        assert r["status"] == "ABOVE_HARDEST_ZONE" and r["edge"] == "harder"
        assert r["num"] is None and r["nearest_num"] == 5 and r["delta"] == 10

    def test_5_langzamer_dan_langzaamste_zone(self):
        r = _c(PACE, 650, True)                         # langzamer dan Z1
        assert r["status"] == "BELOW_EASIEST_ZONE" and r["edge"] == "easier"
        assert r["num"] is None and r["nearest_num"] == 1

    def test_6_gap_tussen_zones(self):
        gap = [{"num": 3, "naam": "Tempo", "low": 300, "high": 270},
               {"num": 4, "naam": "Drempel", "low": 260, "high": 240}]   # gat 260–270
        r = _c(gap, 265, True)
        assert r["status"] == "BETWEEN_ZONES" and r["num"] is None
        assert r["nearest_num"] in (3, 4)

    def test_7_malformed_en_overlap(self):
        assert _c([], 250, True)["status"] == "UNKNOWN"
        assert _c(PACE, None, True)["status"] == "UNKNOWN"
        assert _c([{"num": 1, "naam": "x", "low": None, "high": None}], 250, True)["status"] == "UNKNOWN"
        # overlap: deterministisch, geen crash, eerste membership wint
        ov = [{"num": 1, "naam": "a", "low": 300, "high": 250},
              {"num": 2, "naam": "b", "low": 280, "high": 240}]
        assert _c(ov, 260, True)["status"] in ("IN_ZONE", "BETWEEN_ZONES")

    def test_8_de_live_case_3_53_is_niet_z3(self):
        # Z3 = 3:55–4:15 als SNELSTE zone; 3:53 (233s) is sneller dan de snelle grens
        z = [{"num": 1, "naam": "Rustig", "low": 600, "high": 300},
             {"num": 2, "naam": "Duur", "low": 300, "high": 255},
             {"num": 3, "naam": "Tempo", "low": 255, "high": 235}]      # 3:55–4:15
        r = _c(z, 233, True)                            # 3:53
        assert r["status"] != "IN_ZONE"
        assert r["num"] is None                          # GEEN Z3-membership
        assert r["status"] == "ABOVE_HARDEST_ZONE" and r["nearest_num"] == 3
        assert r["delta"] == 2                            # 2 sec/km sneller dan de grens

    def test_9_out_of_range_nooit_in_zone(self):
        for w in (200, 650):
            r = _c(PACE, w, True)
            assert r["status"] != "IN_ZONE" and r["num"] is None

    def test_pace_richting_lager_is_harder(self):
        # lager sec = sneller = zwaardere zone; nooit numeriek "groter = harder"
        assert _c(PACE, 225, True)["num"] == 5           # 3:45 = zwaar (Z5)
        assert _c(PACE, 465, True)["num"] == 1           # 7:45 = licht (Z1)
        assert _c(PACE, 205, True)["edge"] == "harder"   # sneller dan snelste → harder-kant

    def test_hr_richting_en_grenzen(self):
        assert _c(HR, 140, False)["num"] == 2
        r_hi = _c(HR, 185, False)                        # boven hoogste → hardere kant
        assert r_hi["status"] == "ABOVE_HARDEST_ZONE" and r_hi["edge"] == "harder"
        r_lo = _c(HR, 90, False)                         # onder laagste → makkelijke kant
        assert r_lo["status"] == "BELOW_EASIEST_ZONE" and r_lo["edge"] == "easier"


# ════════════════════════════════════════════════════════════════════════════
# D–G — planned block ↔ executed lap assessment + confidence
# ════════════════════════════════════════════════════════════════════════════
def _step(intensity, zone=None, dur="03:00", ttype="hr_zone"):
    s = {"intensity": intensity, "durationType": "TIME", "duration": dur}
    if zone is not None:
        s["target"] = [{"targetType": ttype, "zone": zone}]
    return s


def _lap(pace="4:00", hr=None, dur=None):
    l = {"pace_display": pace, "hr_avg": hr}
    if dur:
        l["duration"] = dur                              # laps-per-blok: verifieerbare structuur
    return l


class TestBlockAssessment:
    STEPS = [_step("WARMUP", 1, "10:00"), _step("ACTIVE", 4), _step("REST", None, "02:00"),
             _step("ACTIVE", 4)]
    # laps met dezelfde duur als de geplande blokken → aantoonbaar 1-op-1 (MATCHED)
    LAPS = [_lap("6:00", 120, "10:00"), _lap("4:00", 158, "03:00"),
            _lap("7:00", 130, "02:00"), _lap("4:00", 172, "03:00")]

    def _assess(self, steps=None, laps=None):
        return fs_client.assess_workout_blocks(steps if steps is not None else self.STEPS,
                                               laps if laps is not None else self.LAPS,
                                               HR, "hartslag")

    def test_10_warmup_niet_als_active(self):
        a = self._assess()
        assert a["confidence"] == "MATCHED"
        b1 = a["blocks"][0]
        assert b1["type"] == "WARMUP" and b1["status"] == "NOT_EVALUATED"

    def test_11_rest_niet_als_targetblok(self):
        a = self._assess()
        b3 = a["blocks"][2]
        assert b3["type"] == "REST" and b3["status"] == "NOT_EVALUATED"

    def test_12_eerste_active_onder_target_is_feit_geen_conclusie(self):
        a = self._assess()
        b2 = a["blocks"][1]
        assert b2["type"] == "ACTIVE" and b2["target_zone"] == 4
        assert b2["observed_hr"] == 158 and b2["status"] == "BELOW_TARGET"
        # de rendering geeft feit + HR-lag-caveat, GEEN deterministische "harder" conclusie
        tekst = ai_feedback._format_block_assessment(a, "Lisa")
        assert "hartslag-lag" in tekst and "GEEN bewijs dat harder" in tekst
        assert "harder lopen" not in tekst.lower().split("blok-analyse")[0]  # geen kale conclusie

    def test_13_later_active_in_target_is_passend(self):
        a = self._assess()
        b4 = a["blocks"][3]
        assert b4["status"] == "ON_TARGET"

    def test_14_ambiguous_geen_harde_blokbeoordeling(self):
        a = self._assess(laps=[_lap("4:00", 160), _lap("4:00", 170)])   # 2 laps ≠ 4 blokken
        assert a["confidence"] == "AMBIGUOUS" and a["blocks"] == []
        tekst = ai_feedback._format_block_assessment(a, "Lisa")
        assert "niet betrouwbaar" in tekst.lower() and "niet hard per blok" in tekst.lower()

    def test_15_ontbrekende_hr_is_unknown(self):
        a = self._assess(laps=[_lap("6:00", 120, "10:00"), _lap("4:00", None, "03:00"),
                               _lap("7:00", 130, "02:00"), _lap("4:00", 172, "03:00")])
        assert a["blocks"][1]["status"] == "UNKNOWN"     # geen HF → geen vergelijking gokken

    def test_16_ontbrekende_planned_hr_geen_targetvergelijking(self):
        steps = [_step("WARMUP", 1, "10:00"), _step("ACTIVE", None), _step("REST", None, "02:00"),
                 _step("ACTIVE", 4)]
        a = self._assess(steps=steps)
        assert a["blocks"][1]["status"] == "UNKNOWN"     # geen doelzone → UNKNOWN

    def test_17_blokduur_als_context(self):
        a = self._assess()
        assert a["blocks"][0]["dur"] == "10:00 min" and a["blocks"][1]["dur"] == "03:00 min"

    def test_18_metric_volgt_zonesysteem(self):
        # tempo-atleet → observed = tempo; HF-atleet → observed = HF
        a_hr = self._assess()
        assert a_hr["blocks"][1]["metric"] == "hr"
        steps_p = [_step("WARMUP", 1, "10:00", "pace_zone"), _step("ACTIVE", 4, ttype="pace_zone")]
        laps_p = [_lap("6:00", None, "10:00"), _lap("4:15", None, "03:00")]
        a_p = fs_client.assess_workout_blocks(steps_p, laps_p, PACE, "tempo")
        assert a_p["confidence"] == "MATCHED" and a_p["blocks"][1]["metric"] == "tempo"

    def test_unavailable_zonder_plan_of_laps(self):
        assert fs_client.assess_workout_blocks([], self.LAPS, HR, "hartslag")["confidence"] == "UNAVAILABLE"
        assert fs_client.assess_workout_blocks(self.STEPS, [], HR, "hartslag")["confidence"] == "UNAVAILABLE"
        assert fs_client.assess_workout_blocks(self.STEPS, self.LAPS, [], "hartslag")["confidence"] == "UNAVAILABLE"


# ════════════════════════════════════════════════════════════════════════════
# C — downstream AI-contract (rendering-helpers)
# ════════════════════════════════════════════════════════════════════════════
class TestAIContract:
    def test_19_20_out_of_range_pace_nooit_als_zone(self):
        cls = _c([{"num": 1, "naam": "Rustig", "low": 600, "high": 300},
                  {"num": 2, "naam": "Duur", "low": 300, "high": 255},
                  {"num": 3, "naam": "Tempo", "low": 255, "high": 235}], 233, True)
        regel = ai_feedback._zone_regel_tekst("3:53 min/km", cls, is_pace=True)
        assert "BUITEN de persoonlijke zones" in regel
        assert "= Zone 3" not in regel and "= Zone" not in regel
        assert "SNELLER dan de snelste" in regel

    def test_in_zone_wel_membership(self):
        cls = _c(PACE, 285, True)                        # Z3
        regel = ai_feedback._zone_regel_tekst("4:45 min/km", cls, is_pace=True)
        assert "= Zone 3" in regel and "BINNEN de persoonlijke zone" in regel

    def test_21_blocktype_index_status_zichtbaar(self):
        a = TestBlockAssessment().  _assess()
        tekst = ai_feedback._format_block_assessment(a, "Lisa")
        assert "Warming-up" in tekst and "Werkblok 2" in tekst and "Herstel" in tekst
        assert "doel Z4" in tekst and "onder target" in tekst and "in target" in tekst

    def test_22_23_beide_generators_delen_dezelfde_context(self):
        src = open(os.path.join(_ROOT, "ai_feedback.py")).read()
        # generate_feedback en generate_reply bouwen beide op _build_workout_context
        assert src.count("_build_workout_context(") >= 2
        # de eerlijke classifier + blok-assessment zitten in de gedeelde context-bouw
        assert "classify_pace_hr_zone(" in src and "assess_workout_blocks(" in src


# ════════════════════════════════════════════════════════════════════════════
# L — production-equivalent acceptance (integratie via _build_workout_context)
# ════════════════════════════════════════════════════════════════════════════
def _patch_common(monkeypatch, zones_result):
    import intake_store
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: zones_result)
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda ak, d: None, raising=False)
    monkeypatch.setattr(intake_store, "garmin_context_text", lambda ak: "", raising=False)


class TestAcceptance:
    def test_scenario1_pace_out_of_range(self, monkeypatch):
        PACE3 = [{"num": 1, "naam": "Rustig", "low": 600, "high": 300},
                 {"num": 2, "naam": "Duur", "low": 300, "high": 255},
                 {"num": 3, "naam": "Tempo", "low": 255, "high": 235}]   # 3:55–4:15 top
        _patch_common(monkeypatch, {"zones_text": "Z3: 3:55-4:15", "zone_type": "tempo", "zones": PACE3})
        wd = {"athlete_name": "Lisa T", "athlete_first_name": "Lisa", "workout_name": "Tempoduurloop",
              "post_notes": "", "workout_key": "W", "athlete_key": "A", "workout_date": "2026-08-12",
              "details": {"Activities": [{"pace_display": "3:53", "hr_avg": 160, "amount": 10,
                                          "planned_amount": 10, "Laps": []}]}}
        ctx, _ = ai_feedback._build_workout_context(wd)
        assert "BUITEN de persoonlijke zones" in ctx
        assert "SNELLER dan de snelste" in ctx
        assert "3:53 min/km = Zone 3" not in ctx          # geen valse membership

    def test_scenario2_hr_interval_first_block_below(self, monkeypatch):
        _patch_common(monkeypatch, {"zones_text": "HR zones", "zone_type": "hartslag", "zones": HR})
        monkeypatch.setattr(fs_client, "get_workout_builder",
                            lambda wk, ak: [_step("WARMUP", 1, "10:00"), _step("ACTIVE", 4),
                                            _step("REST", None, "02:00"), _step("ACTIVE", 4)])
        wd = {"athlete_name": "Sem J", "athlete_first_name": "Sem", "workout_name": "Intervaltraining",
              "post_notes": "", "workout_key": "W", "athlete_key": "A", "workout_date": "2026-08-12",
              "details": {"has_structured_workout": True,
                          "Activities": [{"pace_display": "4:30", "hr_avg": 150, "amount": 8,
                                          "planned_amount": 8,
                                          "Laps": [_lap("6:00", 120, "10:00"), _lap("4:00", 158, "03:00"),
                                                   _lap("7:00", 130, "02:00"), _lap("4:00", 172, "03:00")]}]}}
        ctx, _ = ai_feedback._build_workout_context(wd)
        assert "BLOK-ANALYSE" in ctx
        assert "Warming-up" in ctx and "Werkblok" in ctx and "Herstel" in ctx
        assert "onder target" in ctx and "hartslag-lag" in ctx     # feit + voorzichtige caveat
        assert "in target" in ctx                                  # later blok apart beoordeeld


# ════════════════════════════════════════════════════════════════════════════
# Truth-contract-hardening (laatste FC-2 check)
# ════════════════════════════════════════════════════════════════════════════
class TestContract1OneCanonicalZone:
    """Dezelfde zones + dezelfde 3:53 → NERGENS echte Z3-membership (Feedback,
    zone_van_waarde-adapter én Masterbrein/brain.zones geven consistent geen Z3)."""
    Z3TOP = [{"num": 1, "naam": "Rustig", "low": 600, "high": 300},
             {"num": 2, "naam": "Duur", "low": 300, "high": 255},
             {"num": 3, "naam": "Tempo", "low": 255, "high": 235}]   # 3:55–4:15 = snelste zone

    def test_feedback_classifier_geen_z3(self):
        r = fs_client.classify_pace_hr_zone(self.Z3TOP, 233, True)
        assert r["status"] != "IN_ZONE" and r["num"] is None

    def test_legacy_adapter_geen_z3(self):
        # zone_van_waarde (Masterbrein/Schema-adapter) mag NOOIT nog een valse Z3 teruggeven
        assert fs_client.zone_van_waarde(self.Z3TOP, 233, True) is None

    def test_masterbrein_zone_of_geen_z3(self):
        import brain.zones as bz
        r = bz.zone_of(self.Z3TOP, pace="3:53", is_pace=True)
        assert r is not None and r.get("status") != "IN_ZONE" and r.get("num") is None

    def test_geen_enkele_consumer_liegt_z3(self):
        # cross-consumer invariant: geen enkele bron classificeert 3:53 als echte Z3
        import brain.zones as bz
        vals = [fs_client.classify_pace_hr_zone(self.Z3TOP, 233, True).get("num"),
                (fs_client.zone_van_waarde(self.Z3TOP, 233, True) or {}).get("num"),
                (bz.zone_of(self.Z3TOP, pace="3:53", is_pace=True) or {}).get("num")]
        assert all(v is None for v in vals)


class TestContract2MappingProof:
    """Gelijke aantallen is niet genoeg: MATCHED vereist aantoonbare structurele overeenkomst."""
    STEPS = [_step("WARMUP", 1, "10:00"), _step("ACTIVE", 4, "03:00"),
             _step("REST", None, "02:00"), _step("ACTIVE", 4, "03:00")]

    def test_gelijke_aantallen_incompatibele_structuur_geen_matched(self):
        # 4 laps == 4 blokken, maar per-km auto-laps (~1 km, geen blok-duur) → structure_mismatch
        laps = [_lap("6:00", 120), _lap("4:00", 158), _lap("7:00", 130), _lap("4:00", 172)]
        a = fs_client.assess_workout_blocks(self.STEPS, laps, HR, "hartslag")
        assert a["confidence"] == "AMBIGUOUS" and a.get("reason") == "structure_mismatch"

    def test_gelijke_aantallen_verkeerde_duur_geen_matched(self):
        # even veel laps, maar de duur past niet op de blokken (10min-blok vs 30s-lap) → AMBIGUOUS
        laps = [_lap("6:00", 120, "00:30"), _lap("4:00", 158, "00:30"),
                _lap("7:00", 130, "00:30"), _lap("4:00", 172, "00:30")]
        a = fs_client.assess_workout_blocks(self.STEPS, laps, HR, "hartslag")
        assert a["confidence"] == "AMBIGUOUS"

    def test_echte_een_op_een_fixture_wel_matched(self):
        laps = [_lap("6:00", 120, "10:00"), _lap("4:00", 158, "03:00"),
                _lap("7:00", 130, "02:00"), _lap("4:00", 172, "03:00")]
        a = fs_client.assess_workout_blocks(self.STEPS, laps, HR, "hartslag")
        assert a["confidence"] == "MATCHED" and len(a["blocks"]) == 4

    def test_afstandsblokken_matchen_op_afstand(self):
        steps = [{"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 0.4,
                  "distUnit": "km", "target": [{"targetType": "hr_zone", "zone": 4}]},
                 {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 0.4,
                  "distUnit": "km", "target": [{"targetType": "hr_zone", "zone": 4}]}]
        laps = [{"pace_display": "4:00", "hr_avg": 170, "amount": 0.41},
                {"pace_display": "4:00", "hr_avg": 172, "amount": 0.40}]
        assert fs_client.assess_workout_blocks(steps, laps, HR, "hartslag")["confidence"] == "MATCHED"


class TestContract3PlannedMetric:
    """De geplande target-metric leidt; het globale zonesysteem mag niet stil converteren."""
    def test_expliciete_planned_metric_wordt_gebruikt(self):
        steps = [_step("WARMUP", 1, "10:00", "pace_zone"), _step("ACTIVE", 4, "03:00", "pace_zone")]
        laps = [_lap("6:00", None, "10:00"), _lap("4:15", None, "03:00")]
        a = fs_client.assess_workout_blocks(steps, laps, PACE, "tempo")
        assert a["confidence"] == "MATCHED" and a["blocks"][1]["metric"] == "tempo"

    def test_planned_metric_wijkt_af_van_zonetabel_is_unknown(self):
        # geplande HF-target, maar alleen een TEMPO-zonetabel → niet stil omzetten → UNKNOWN
        steps = [_step("WARMUP", 1, "10:00", "hr_zone"), _step("ACTIVE", 4, "03:00", "hr_zone")]
        laps = [_lap("6:00", 120, "10:00"), _lap("4:00", 170, "03:00")]
        a = fs_client.assess_workout_blocks(steps, laps, PACE, "tempo")
        assert a["confidence"] == "MATCHED"
        assert a["blocks"][1]["status"] == "UNKNOWN"     # geen stille HF→tempo-conversie

    def test_geen_expliciete_metric_valt_terug_op_zonetabel(self):
        # target zonder metric-hint → veilige fallback op de enige persoonlijke zonebron
        steps = [{"intensity": "ACTIVE", "durationType": "TIME", "duration": "03:00",
                  "target": [{"targetType": "zone", "zone": 4}]}]
        laps = [_lap("4:00", 172, "03:00")]
        a = fs_client.assess_workout_blocks(steps, laps, HR, "hartslag")
        assert a["confidence"] == "MATCHED" and a["blocks"][0]["status"] == "ON_TARGET"
