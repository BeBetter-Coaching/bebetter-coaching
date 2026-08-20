"""Feedback-core correctness — Fase 1 (echte gebruikstestbevindingen).

Dekt de deterministische lagen die vóór de AI kloppen moeten:
  • afstandsafwijking-banden (geünificeerd met brain.derive) + <10% lekt niet naar AI;
  • zone-classificatie op exacte grenzen (incl. de gemelde 3:48 → Z4 case);
  • queue↔detail consistentie: 'reactie' in de lijst ⇒ detail toont het atleetbericht.

    python3 -m pytest tests/test_feedback_core.py -q
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import fs_client
import feedback_core as FC


# ════════════════════════════════════════════════════════════════════════════
# Blocker 1 — niet-run context moet gemeten data bevatten (geen vage AI)
# ════════════════════════════════════════════════════════════════════════════
class TestNonRunContextData:
    def _wd(self, **over):
        wd = {"athlete_name": "Test", "athlete_first_name": "Test", "athlete_key": "A",
              "workout_key": "W", "workout_name": "MTB", "workout_date": "2026-08-10",
              "workout_type": "bike", "post_notes": "Voelde enorm zwaar. Terug te zien in de data?",
              "details": {"description": "Duurrit", "Activities": [
                  {"amount": 15.3, "planned_amount": 15.0, "duration": 2706,
                   "pace_display": "20.3", "pace_display_type": "km/u", "hr_avg": 123, "hr_max": 155}]}}
        wd.update(over)
        return wd

    def test_metrics_in_context(self):
        import ai_feedback
        ctx, _ = ai_feedback._build_nonrun_context(self._wd())
        assert "123" in ctx and "155" in ctx          # hartslag
        assert "15.3" in ctx                            # afstand
        assert "45:" in ctx                             # duur
        assert "20.3" in ctx                            # tempo/snelheid

    def test_geen_running_zone_classificatie(self):
        import ai_feedback
        ctx, _ = ai_feedback._build_nonrun_context(self._wd())
        # geen hardloop-zone-INDELING (Z1..Z5 / "Zone 3") op een fietstraining
        for z in ("Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5", "BEREKENDE ZONE"):
            assert z not in ctx

    def test_systeemprompt_verbiedt_vage_hedge(self):
        import ai_feedback
        assert "hangt af van wat ik" in ai_feedback._NONRUN_SYSTEM
        assert "gebruik die dan concreet" in ai_feedback._NONRUN_SYSTEM.lower()

    def test_geen_activities_geen_crash(self):
        import ai_feedback
        wd = self._wd(details={"description": "x", "Activities": []})
        ctx, _ = ai_feedback._build_nonrun_context(wd)
        assert "Gemeten gegevens" not in ctx           # geen lege metrics-sectie
        assert isinstance(ctx, str)

    def test_metrics_formatter_partial(self):
        import ai_feedback
        # alleen HR aanwezig → alleen die regel, geen crash
        out = ai_feedback._format_nonrun_metrics({"hr_avg": 140})
        assert "140 bpm" in out and "Afstand" not in out


# ════════════════════════════════════════════════════════════════════════════
# Fase 2 — Masterbrein feedback-gate (legacy/shadow/v2)
# ════════════════════════════════════════════════════════════════════════════
class TestFeedbackBrainGate:
    def test_default_legacy(self, monkeypatch):
        monkeypatch.delenv("BEBETTER_FEEDBACK_BRAIN", raising=False)
        assert FC.feedback_brain_mode() == "legacy"

    def test_unknown_falls_back(self, monkeypatch):
        monkeypatch.setenv("BEBETTER_FEEDBACK_BRAIN", "banaan")
        assert FC.feedback_brain_mode() == "legacy"

    def _stub_block(self, monkeypatch):
        from brain import adapter
        monkeypatch.setattr(adapter, "feedback_context_block",
                            lambda ak, wk="", today=None: {
                                "prompt_block": "BREIN: ~30 km/week", "source_gaps": [],
                                "has_load": True, "complaint_areas": [], "overall": "STABLE"})

    def test_legacy_no_injection(self, monkeypatch):
        monkeypatch.setenv("BEBETTER_FEEDBACK_BRAIN", "legacy")
        self._stub_block(monkeypatch)
        assert FC._brein_context({"athlete_key": "A", "workout_key": "W"}) == ""

    def test_shadow_builds_but_no_injection(self, monkeypatch):
        monkeypatch.setenv("BEBETTER_FEEDBACK_BRAIN", "shadow")
        self._stub_block(monkeypatch)
        w = {"athlete_key": "A", "workout_key": "W"}
        assert FC._brein_context(w) == ""              # niet geïnjecteerd
        assert w.get("_brein_diag", {}).get("has_load") is True   # wel gebouwd voor diag

    def test_v2_injects_block(self, monkeypatch):
        monkeypatch.setenv("BEBETTER_FEEDBACK_BRAIN", "v2")
        self._stub_block(monkeypatch)
        assert "BREIN" in FC._brein_context({"athlete_key": "A", "workout_key": "W"})

    def test_v2_failure_is_safe(self, monkeypatch):
        monkeypatch.setenv("BEBETTER_FEEDBACK_BRAIN", "v2")
        from brain import adapter

        def _boom(ak, wk="", today=None):
            raise RuntimeError("brain kapot")
        monkeypatch.setattr(adapter, "feedback_context_block", _boom)
        # nooit fataal: lege context, geen crash in de generatie-flow
        assert FC._brein_context({"athlete_key": "A", "workout_key": "W"}) == ""


# ════════════════════════════════════════════════════════════════════════════
# E — afstandsafwijking: banden + boundary-matrix
# ════════════════════════════════════════════════════════════════════════════
class TestAfwijkingBanden:
    def _rel(self, planned, actual):
        return FC.afwijking(planned, actual)["relevance"]

    def test_gelijk_is_ignore(self):
        assert self._rel(10, 10) == "ignore"

    def test_boundary_matrix(self):
        p = 10.0
        cases = [
            (10.5, "ignore"),    # +5%
            (9.5, "ignore"),     # -5%
            (10.99, "ignore"),   # +9.9%
            (9.01, "ignore"),    # -9.9%
            (11.0, "notable"),   # +10.0%
            (9.0, "notable"),    # -10.0%
            (11.49, "notable"),  # +14.9%
            (11.5, "notable"),   # +15.0%
            (11.99, "notable"),  # +19.9%
            (12.0, "clear"),     # +20.0%
            (13.0, "clear"),     # +30.0%
        ]
        for actual, verwacht in cases:
            assert self._rel(p, actual) == verwacht, f"{actual} → {self._rel(p, actual)} != {verwacht}"

    def test_onder_10_report_false(self):
        assert FC.afwijking(10, 10.5)["report"] is False

    def test_geen_geplande_afstand_na(self):
        assert FC.afwijking(0, 10)["relevance"] == "n/a"
        assert FC.afwijking(None, 10)["relevance"] == "n/a"


# ════════════════════════════════════════════════════════════════════════════
# E — <10% mag NOOIT als feedbackpunt naar de AI; 10–20/>=20 wél, gestuurd
# ════════════════════════════════════════════════════════════════════════════
class TestDeviationPromptInjection:
    def _context(self, monkeypatch, planned, actual):
        import ai_feedback
        import intake_store
        monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda *a, **k: None)
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda *a, **k: {})
        monkeypatch.setattr(fs_client, "get_workout_builder", lambda *a, **k: [])
        monkeypatch.setattr(intake_store, "garmin_context_text", lambda *a, **k: "")
        wd = {
            "athlete_name": "Test Atleet", "athlete_first_name": "Test",
            "athlete_key": "A", "workout_key": "W", "workout_name": "Duurloop",
            "workout_date": "2026-08-10", "post_notes": "lekker gelopen",
            "workout_type": "run",
            "details": {"has_structured_workout": False,
                        "Activities": [{"planned_amount": planned, "amount": actual,
                                        "pace_display": "5:30", "hr_avg": 150}]},
        }
        ctx, _ = ai_feedback._build_workout_context(wd)
        return ctx

    def test_onder_10_niet_benoemen(self, monkeypatch):
        ctx = self._context(monkeypatch, 10.0, 9.3)   # -7%
        assert "AFSTANDSAFWIJKING" in ctx
        assert "NIET" in ctx and "binnen 10%" in ctx

    def test_10_tot_20_neutraal(self, monkeypatch):
        ctx = self._context(monkeypatch, 10.0, 11.5)  # +15%
        assert "AFSTANDSAFWIJKING" in ctx
        assert "GEEN probleem" in ctx

    def test_boven_20_niet_automatisch_negatief(self, monkeypatch):
        ctx = self._context(monkeypatch, 10.0, 13.0)  # +30%
        assert "AFSTANDSAFWIJKING" in ctx
        assert "automatisch negatief" in ctx

    def test_deviation_op_canonieke_activiteit_niet_swap(self, monkeypatch):
        # regressie: een snellere activiteit (race-swap) mag de AFSTANDSafwijking niet
        # veranderen — die blijft op de primaire activiteit (== detail()).
        import ai_feedback, intake_store
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda *a, **k: {})
        monkeypatch.setattr(fs_client, "get_workout_builder", lambda *a, **k: [])
        monkeypatch.setattr(intake_store, "garmin_context_text", lambda *a, **k: "")
        # snelste activiteit zou een +20%-afwijking geven als hij gebruikt werd
        monkeypatch.setattr(fs_client, "get_fastest_activity_on_day",
                            lambda *a, **k: {"pace_display": "4:00", "planned_amount": 10.0, "amount": 12.0})
        wd = {"athlete_name": "T", "athlete_first_name": "T", "athlete_key": "A",
              "workout_key": "W", "workout_name": "Duurloop", "workout_date": "2026-08-10",
              "post_notes": "x", "workout_type": "run",
              "details": {"has_structured_workout": False,
                          "Activities": [{"planned_amount": 12.0, "amount": 12.02,
                                          "pace_display": "5:30", "hr_avg": 150}]}}
        ctx, _ = ai_feedback._build_workout_context(wd)
        # primaire activiteit = 0.2% → ignore; niet de +20% van de snelste activiteit
        assert "binnen 10%" in ctx and "20%" not in ctx.split("AFSTANDSAFWIJKING", 1)[-1][:200]


# ════════════════════════════════════════════════════════════════════════════
# D — zone-classificatie op exacte grenzen (tempo, seconden/km)
# ════════════════════════════════════════════════════════════════════════════
class TestZoneBoundaries:
    # tempo-zones in seconden/km (lager = sneller = hogere zone)
    PACE = [
        {"num": 1, "naam": "Rustig", "low": 300, "high": 600},   # 5:00–10:00
        {"num": 2, "naam": "Duur", "low": 270, "high": 300},     # 4:30–5:00
        {"num": 3, "naam": "Tempo", "low": 247, "high": 270},    # 4:07–4:30
        {"num": 4, "naam": "Drempel", "low": 227, "high": 247},  # 3:47–4:07
        {"num": 5, "naam": "VO2", "low": 180, "high": 227},      # 3:00–3:47
    ]

    def _z(self, sec):
        z = fs_client.zone_van_waarde(self.PACE, sec, is_pace=True)
        return z["num"] if z else None

    def test_gemelde_case_3_48_is_z4(self):
        # coach-notitie: Z4 = 3:47–4:07, uitgevoerd 3:48 → moet Z4 zijn
        assert self._z(228) == 4                      # 3:48 = 228s

    def test_exacte_ondergrens_inclusief_snelle_edge(self):
        assert self._z(227) == 4                      # 3:47 = onder-edge Z4 (incl.)

    def test_exacte_bovengrens_naar_langzamere_zone(self):
        assert self._z(247) == 3                      # 4:07 = boven-edge Z4 → Z3 (excl.)

    def test_midden_zone(self):
        assert self._z(237) == 4                      # ~3:57 midden Z4

    def test_net_buiten_snelste(self):
        # FC-2: sneller dan alle banden → GEEN valse Z5-membership (clamp verwijderd)
        assert self._z(179) is None
        cls = fs_client.classify_pace_hr_zone(self.PACE, 179, is_pace=True)
        assert cls["status"] == "ABOVE_HARDEST_ZONE" and cls["nearest_num"] == 5

    def test_display_afronding_blijft_zelfde_zone(self):
        # 3:47.4 (227.4s) en weergegeven '3:47' (227s) vallen beide in Z4
        assert self._z(227) == self._z(227.4) == 4


# ════════════════════════════════════════════════════════════════════════════
# F/G — queue↔detail consistentie (invariant)
# ════════════════════════════════════════════════════════════════════════════
class TestQueueDetailConsistency:
    def _workout(self, **over):
        w = {"athlete_key": "A", "athlete_name": "Youri Test",
             "athlete_first_name": "Youri", "workout_key": "W1",
             "workout_name": "Duurloop", "workout_date": "2026-08-10",
             "post_notes": "", "felt": None, "effort": None,
             "athlete_comments": [], "thread": []}
        w.update(over)
        return w

    def test_reactie_via_comment_zichtbaar_in_detail(self):
        # atleet reageerde via een comment → thread én categorie moeten dat tonen
        w = self._workout(
            athlete_comments=["Zwaar maar top gevoel!"],
            thread=[{"tekst": "Zwaar maar top gevoel!", "van": "atleet", "naam": "Youri"}])
        assert FC._categorie(w)[0] == "reactie"
        assert any(not m["coach"] and m["tekst"] for m in FC._gesprek(w))

    def test_reactie_via_postnotes_zichtbaar_in_detail(self):
        w = self._workout(
            post_notes="Voelde top",
            thread=[{"tekst": "Voelde top", "van": "atleet", "naam": "Youri", "_display": False}])
        assert FC._categorie(w)[0] == "reactie"
        assert any(not m["coach"] for m in FC._gesprek(w))

    def test_reactie_alleen_in_thread_niet_in_comments(self):
        # exacte F/G-scenario: atleetbericht zit in de thread maar athlete_comments is leeg
        w = self._workout(
            athlete_comments=[],
            thread=[{"tekst": "Ging top vandaag", "van": "atleet", "naam": "Youri"}])
        assert FC._categorie(w)[0] == "reactie"                 # queue herkent reactie
        assert any(not m["coach"] for m in FC._gesprek(w))      # detail toont hetzelfde bericht

    def test_geen_atleetbericht_is_geen_reactie(self):
        # alleen een coach-bericht in de thread → GEEN 'reactie'
        w = self._workout(thread=[{"tekst": "netjes!", "van": "coach", "naam": "jij"}])
        assert FC._categorie(w)[0] != "reactie"

    def test_invariant_reactie_impliceert_atleetbericht(self):
        # HARDE INVARIANT: als de queue 'reactie' zegt, moet detail een atleetbericht kunnen tonen
        for w in [
            self._workout(athlete_comments=["a"], thread=[{"tekst": "a", "van": "atleet"}]),
            self._workout(post_notes="p", thread=[{"tekst": "p", "van": "atleet", "_display": False}]),
        ]:
            if FC._categorie(w)[0] == "reactie":
                assert any(not m["coach"] for m in FC._gesprek(w)), \
                    "queue=reactie maar detail toont geen atleetbericht (F/G-inconsistentie)"
