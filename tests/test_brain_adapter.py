"""Masterbrein V2 Fase B — compatibility-adapter + feature-gate.

Bewijst dat Schema zijn atleetcontext uit V2 kan krijgen via de bestaande publieke
`athlete_context`-API, dat de bekende sportmixbug in de UITEINDELIJKE Schema-context
verdwenen is (niet alleen in brain.derive), dat SourceHealth eerlijk doorwerkt,
en dat last-known-good / outage / gating correct zijn.

    python3 -m pytest tests/test_brain_adapter.py -q
"""
import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import athlete_context as AC
from brain import adapter, sources, snapshot, shadow
from brain.models import SourceHealth, STALE

TODAY = date(2026, 8, 11)


def _d(n):
    return (TODAY - timedelta(days=n)).isoformat()


# ── Synthetische raw + health-fabriek (geen FinalSurge/IO) ───────────────────
def _health(*, training_log=True, zones=True, intake=True):
    h = []
    for src, ok in (("intake", intake), ("coach_notes", True), ("coach_memory", True),
                    ("on_hold", True), ("garmin", True), ("belasting", True),
                    ("fs.training_log", training_log), ("fs.labels", True), ("fs.zones", zones)):
        h.append(SourceHealth(source=src, available=ok, last_success=(TODAY.isoformat() if ok else ""),
                              error=("" if ok else "geen bron")))
    return h


def _raw(log=None, intake=None, notes=None, **extra):
    r = {"intake": intake or {"doel": "10km sub 50", "trainingsdagen": "di/do"},
         "intake_ts": _d(30), "notes": notes or [], "profiel": "", "on_hold": None,
         "garmin": "", "belasting": None, "training_log": log or [], "labels": [],
         "zones": {}}
    r.update(extra)
    return r


def _gather_stub(raw, health):
    def _g(user_key, today=None):
        return raw, health
    return _g


def _ctx(raw, health, prev=None, save=False):
    """Bouw de V2-legacy-ctx uit synthetische raw/health (puur, geen snapshot-IO)."""
    from brain import state as _state
    ik = raw.get("intake") or {}
    naam = ik.get("athlete_name") or ik.get("naam") or "T"
    st = _state.assemble("T", naam, raw, health, TODAY, prev=prev)
    return adapter.to_legacy_context(st, raw, TODAY), st


# cross-trainer: 4 wk, per week 1 run 9km + 1 fiets 80km
def _crosstrainer_log():
    log = []
    for wi in range(4):
        log.append({"date": _d(wi * 7 + 1), "actual_km": 9.0, "completed": True, "activity_type": "Run"})
        log.append({"date": _d(wi * 7 + 3), "actual_km": 80.0, "completed": True, "activity_type": "Bike"})
    return log


def _pure_runner_log():
    log = []
    for wi in range(4):
        log.append({"date": _d(wi * 7 + 1), "actual_km": 8.0, "completed": True, "activity_type": "Run"})
        log.append({"date": _d(wi * 7 + 4), "actual_km": 6.0, "completed": True, "activity_type": "Run"})
    return log


# ════════════════════════════════════════════════════════════════════════════
# CONTRACT — legacy shape blijft bruikbaar door bestaande pure consumers
# ════════════════════════════════════════════════════════════════════════════
class TestContract:
    def test_shape_and_keys(self):
        ctx, _ = _ctx(_raw(_pure_runner_log()), _health())
        for k in ("profile", "training", "recovery", "health", "feedback", "goals", "coach",
                  "user_key", "naam", "missing"):
            assert k in ctx

    def test_pure_functions_consume_v2_ctx(self):
        ctx, _ = _ctx(_raw(_pure_runner_log()), _health())
        proj = AC.schema_projection(ctx)          # bestaande pure fn
        txt = AC.to_prompt_text(proj)             # bestaande pure fn
        u = AC.used_summary(ctx)                  # bestaande pure fn
        secties = AC.ui_sections(ctx)             # bestaande pure fn
        assert isinstance(txt, str) and "ATLEETCONTEXT" in txt
        assert all(isinstance(v, (bool, int)) for v in u.values())
        assert isinstance(secties, list) and secties

    def test_empty_athlete_does_not_crash(self):
        ctx, _ = _ctx(_raw([]), _health(training_log=True))
        AC.to_prompt_text(AC.schema_projection(ctx))
        AC.ui_sections(ctx)
        assert ctx["naam"]

    def test_naam_override(self):
        state, raw = None, _raw(_pure_runner_log())
        from brain import state as _state
        st = _state.assemble("T", "Origineel", raw, _health(), TODAY)
        ctx = adapter.to_legacy_context(st, raw, TODAY)
        assert ctx["naam"] == "Origineel"


# ════════════════════════════════════════════════════════════════════════════
# RUN-ONLY — sportmixbug moet uit de UITEINDELIJKE Schema-context verdwenen zijn
# ════════════════════════════════════════════════════════════════════════════
class TestRunOnlyInSchemaContext:
    def test_1_run_plus_cycling_run_only_km(self):
        ctx, _ = _ctx(_raw(_crosstrainer_log()), _health())
        assert ctx["training"]["km_per_week"] == 9.0          # niet 69 (incl. fiets)
        assert ctx["training"]["runs_per_week"] == 1.0        # niet 1.8 (fiets als run)

    def test_2_only_cycling_no_running_load(self):
        log = [{"date": _d(wi * 7 + 1), "actual_km": 60.0, "completed": True, "activity_type": "Bike"}
               for wi in range(4)]
        ctx, _ = _ctx(_raw(log), _health())
        assert not ctx["training"].get("km_per_week")
        assert not ctx["training"].get("runs_per_week")

    def test_3_running_plus_walking(self):
        log = []
        for wi in range(4):
            log.append({"date": _d(wi * 7 + 1), "actual_km": 10.0, "completed": True, "activity_type": "Run"})
            log.append({"date": _d(wi * 7 + 2), "actual_km": 5.0, "completed": True, "activity_type": "Walk"})
        ctx, _ = _ctx(_raw(log), _health())
        assert ctx["training"]["km_per_week"] == 10.0

    def test_4_running_plus_strength_hyrox_with_distance(self):
        log = []
        for wi in range(4):
            log.append({"date": _d(wi * 7 + 1), "actual_km": 12.0, "completed": True, "activity_type": "Run"})
            log.append({"date": _d(wi * 7 + 2), "actual_km": 3.0, "completed": True, "activity_type": "Strength"})
            log.append({"date": _d(wi * 7 + 3), "actual_km": 4.0, "completed": True, "activity_type": "HYROX"})
        ctx, _ = _ctx(_raw(log), _health())
        assert ctx["training"]["km_per_week"] == 12.0

    def test_5_running_gap_with_cycling_during_gap(self):
        # runs alleen in oude weken (5–8), fietsen in recente weken → geen 'run' recent,
        # onderbreking moet run-only zijn (fietsen vult het gat niet op)
        log = []
        for wi in range(4):
            log.append({"date": _d(wi * 7 + 1), "actual_km": 50.0, "completed": True, "activity_type": "Bike"})
        for wi in range(4, 8):
            log.append({"date": _d(wi * 7 + 1), "actual_km": 10.0, "completed": True, "activity_type": "Run"})
        ctx, _ = _ctx(_raw(log), _health())
        # recente run-km = 0 → geen positieve run-load
        assert not ctx["training"].get("km_per_week")
        assert ctx["training"].get("onderbreking")            # run-only onderbreking herkend

    def test_6_running_return_after_real_run(self):
        log = [{"date": _d(1), "actual_km": 8.0, "completed": True, "activity_type": "Run"},
               {"date": _d(3), "actual_km": 8.0, "completed": True, "activity_type": "Run"}]
        ctx, _ = _ctx(_raw(log), _health())
        assert ctx["training"]["km_per_week"] and ctx["training"]["runs_per_week"]

    def test_7_cycling_increase_complaint_stable_running(self):
        # klacht + fietsvolume stijgt, running stabiel → geen possible_relation op running
        log = []
        for wi in range(4):
            log.append({"date": _d(wi * 7 + 1), "actual_km": 8.0, "completed": True, "activity_type": "Run"})
            log.append({"date": _d(wi * 7 + 2), "actual_km": 40.0 + wi * 20, "completed": True, "activity_type": "Bike"})
        notes = [{"datum": _d(3), "tekst": "achilles zeurt weer opnieuw"}]
        ctx, st = _ctx(_raw(log, notes=notes), _health())
        assert not any(e.key == "load.possible_relation" for e in st.evidence)

    def test_8_running_increase_complaint(self):
        log = []
        for wi in range(8):
            km = 12.0 if wi < 4 else 6.0                      # recent hoger → opbouwend
            log.append({"date": _d(wi * 7 + 1), "actual_km": km, "completed": True, "activity_type": "Run"})
            log.append({"date": _d(wi * 7 + 4), "actual_km": km, "completed": True, "activity_type": "Run"})
        notes = [{"datum": _d(3), "tekst": "achilles zeurt weer opnieuw"}]
        ctx, st = _ctx(_raw(log, notes=notes), _health())
        assert any(e.key == "load.possible_relation" for e in st.evidence)

    def test_9_pure_runner_no_nonrun(self):
        raw = _raw(_pure_runner_log())
        ctx, _ = _ctx(raw, _health())
        # pure runner: run-only == all-activity (geen correctie t.o.v. sportmix-som)
        assert ctx["training"]["km_per_week"] == AC.training_summary(raw["training_log"], TODAY)["km_per_week"]

    def test_10_unknown_empty_activity_type(self):
        # leeg activity_type volgt de canonieke _is_run-semantiek (default = run)
        log = [{"date": _d(wi * 7 + 1), "actual_km": 7.0, "completed": True} for wi in range(4)]
        ctx_default, _ = _ctx(_raw(log), _health())
        assert ctx_default["training"]["km_per_week"] == 7.0


# ════════════════════════════════════════════════════════════════════════════
# PROJECTIE — adapter gebruikt for_schema; resolved klachten niet als actueel
# ════════════════════════════════════════════════════════════════════════════
class TestProjection:
    def test_resolved_complaint_not_active(self):
        notes = [{"datum": _d(40), "tekst": "achilles pijn"},
                 {"datum": _d(3), "tekst": "achilles is helemaal hersteld"}]
        ctx, _ = _ctx(_raw(_pure_runner_log(), notes=notes), _health())
        aks = (ctx["health"] or {}).get("actuele_klachten") or []
        assert not any("achilles" in (k["tekst"].lower()) for k in aks)

    def test_active_complaint_present(self):
        notes = [{"datum": _d(3), "tekst": "achilles zeurt weer opnieuw"}]
        ctx, _ = _ctx(_raw(_pure_runner_log(), notes=notes), _health())
        aks = ctx["health"]["actuele_klachten"]
        assert any("achilles" in k["tekst"].lower() for k in aks)

    def test_recurring_complaint_terugkerend(self):
        notes = [{"datum": _d(3), "tekst": "achilles zeurt"},
                 {"datum": _d(40), "tekst": "weer achilles gevoelig"}]
        ctx, _ = _ctx(_raw(_pure_runner_log(), notes=notes), _health())
        assert "achilles" in (ctx["health"].get("terugkerend") or [])

    def test_belasting_signaal_via_v2(self):
        raw = _raw(_pure_runner_log())
        raw["belasting"] = {"ernst": "hoog", "signalen": ["omvang +40%"],
                            "_stand_datum": _d(0), "_afgehandeld": False}
        ctx, _ = _ctx(raw, _health())
        assert ctx["feedback"]["belasting_signaal"]["ernst"] == "hoog"


# ════════════════════════════════════════════════════════════════════════════
# SOURCE-HEALTH — geen platgestreken "stabiel"/"geen klachten" bij bronuitval
# ════════════════════════════════════════════════════════════════════════════
class TestSourceHealth:
    def test_training_log_gap_no_false_stable(self):
        ctx, _ = _ctx(_raw([]), _health(training_log=False))
        assert "fs.training_log" in ctx["_brain"]["schema_relevant_gaps"]
        assert ctx["training"].get("databron_onzeker")
        assert not ctx["training"].get("km_per_week")

    def test_gap_visible_in_prompt(self):
        ctx, _ = _ctx(_raw([]), _health(training_log=False))
        txt = AC.to_prompt_text(AC.schema_projection(ctx))
        assert "niet beschikbaar" in txt.lower()

    def test_healthy_but_empty_is_not_a_gap(self):
        ctx, _ = _ctx(_raw([]), _health(training_log=True))
        assert "fs.training_log" not in ctx["_brain"]["schema_relevant_gaps"]


# ════════════════════════════════════════════════════════════════════════════
# LAST-KNOWN-GOOD — gefaalde bron → prev evidence STALE, nooit vers HIGH
# ════════════════════════════════════════════════════════════════════════════
class TestLastKnownGood:
    def test_prev_load_carried_stale(self):
        healthy = _raw(_pure_runner_log())
        _, prev = _ctx(healthy, _health())            # gezonde state als prev
        # nu training_log-uitval, geen nieuwe log
        ctx, st = _ctx(_raw([]), _health(training_log=False), prev=prev)
        km_ev = next((e for e in st.evidence if e.key == "load.km_per_week"), None)
        assert km_ev is not None and km_ev.status == STALE
        assert (km_ev.detail or {}).get("last_known_good") is True
        # in de ctx zichtbaar als 'laatst bekend', niet als vers getal
        assert "laatst bekend" in str(ctx["training"].get("km_per_week"))

    def test_no_prev_no_invented_load(self):
        ctx, st = _ctx(_raw([]), _health(training_log=False), prev=None)
        assert not ctx["training"].get("km_per_week")
        assert st.overall in ("INSUFFICIENT_DATA", "ATTENTION", "STABLE")
        # geen vals GOOD zonder trainingsdata
        assert st.overall != "GOOD"


# ════════════════════════════════════════════════════════════════════════════
# GATING — legacy/shadow/v2 via env, default veilig
# ════════════════════════════════════════════════════════════════════════════
class TestGating:
    def test_default_is_legacy(self, monkeypatch):
        monkeypatch.delenv("BEBETTER_SCHEMA_BRAIN", raising=False)
        assert AC.schema_brain_mode() == "legacy"

    def test_unknown_mode_falls_back_legacy(self, monkeypatch):
        monkeypatch.setenv("BEBETTER_SCHEMA_BRAIN", "banaan")
        assert AC.schema_brain_mode() == "legacy"

    def test_v2_mode_routes_through_adapter(self, monkeypatch):
        monkeypatch.setenv("BEBETTER_SCHEMA_BRAIN", "v2")
        raw, health = _raw(_crosstrainer_log()), _health()
        monkeypatch.setattr(sources, "gather", _gather_stub(raw, health))
        monkeypatch.setattr(snapshot, "load_snapshot", lambda k: None)
        monkeypatch.setattr(snapshot, "save_snapshot", lambda s: (True, ""))
        ctx = AC.build_athlete_context("T", today=TODAY)
        assert ctx["training"]["km_per_week"] == 9.0          # run-only correctie actief
        assert "_brain" in ctx

    def test_v2_failure_raises_no_silent_fallback(self, monkeypatch):
        monkeypatch.setenv("BEBETTER_SCHEMA_BRAIN", "v2")

        def _boom(user_key, naam="", today=None):
            raise RuntimeError("v2 kapot")
        monkeypatch.setattr(adapter, "build_context", _boom)
        import pytest
        with pytest.raises(RuntimeError):
            AC.build_athlete_context("T", today=TODAY)

    def test_shadow_output_stays_v1(self, monkeypatch):
        monkeypatch.setenv("BEBETTER_SCHEMA_BRAIN", "shadow")
        raw, health = _raw(_crosstrainer_log()), _health()
        monkeypatch.setattr(sources, "gather", _gather_stub(raw, health))
        monkeypatch.setattr(snapshot, "load_snapshot", lambda k: None)
        monkeypatch.setattr(snapshot, "save_snapshot", lambda s: (True, ""))
        # v1 _gather patchen zodat legacy dezelfde synthetische bron ziet
        monkeypatch.setattr(AC, "_gather", lambda k: {**raw, "labels": []})
        ctx = AC.build_athlete_context("T", today=TODAY)
        # production-output = v1 (sportmix), maar diagnostics kennen de correctie
        assert "_shadow" in ctx
        cls = ctx["_shadow"]["running_load"]["classification"]
        assert cls in ("EXPECTED_CORRECTION", "SOURCE_HEALTH_DIFFERENCE")


# ════════════════════════════════════════════════════════════════════════════
# OUTAGE — end-to-end fault injection op fs.training_log (Sectie 8)
# ════════════════════════════════════════════════════════════════════════════
class TestOutageEndToEnd:
    def _fault_gather(self, base_raw, fail_training_log):
        """Simuleer sources.gather met een gecontroleerde fs.training_log-fout."""
        def _g(user_key, today=None):
            health = _health(training_log=not fail_training_log)
            raw = dict(base_raw)
            if fail_training_log:
                raw = {**raw, "training_log": []}
            return raw, health
        return _g

    def test_scenario_A_snapshot_present(self, monkeypatch):
        base = _raw(_pure_runner_log())
        # 1. gezonde build → snapshot
        store = {}
        monkeypatch.setattr(snapshot, "load_snapshot", lambda k: store.get(k))
        monkeypatch.setattr(snapshot, "save_snapshot",
                            lambda s: (store.__setitem__(s.athlete_key, s), (True, ""))[1])
        monkeypatch.setattr(sources, "gather", self._fault_gather(base, fail_training_log=False))
        st1, _ = adapter.build_state("T", TODAY)
        assert st1.overall in ("STABLE", "GOOD")
        assert store.get("T") is not None
        # 2. nu fs.training_log-uitval, prev aanwezig
        monkeypatch.setattr(sources, "gather", self._fault_gather(base, fail_training_log=True))
        st2, raw2 = adapter.build_state("T", TODAY)
        sh = next(s for s in st2.sources if s.source == "fs.training_log")
        assert sh.available is False
        assert "fs.training_log" in st2.source_gaps
        km = next((e for e in st2.evidence if e.key == "load.km_per_week"), None)
        assert km is not None and km.status == STALE
        assert (km.detail or {}).get("last_known_good") is True
        ctx = adapter.to_legacy_context(st2, raw2, TODAY)
        assert "laatst bekend" in str(ctx["training"].get("km_per_week"))

    def test_scenario_B_no_snapshot(self, monkeypatch):
        base = _raw(_pure_runner_log())
        monkeypatch.setattr(snapshot, "load_snapshot", lambda k: None)
        monkeypatch.setattr(snapshot, "save_snapshot", lambda s: (True, ""))
        monkeypatch.setattr(sources, "gather", self._fault_gather(base, fail_training_log=True))
        st, raw = adapter.build_state("T", TODAY)
        assert "fs.training_log" in st.source_gaps
        assert st.overall != "GOOD"                          # geen vals GOOD zonder data
        ctx = adapter.to_legacy_context(st, raw, TODAY)
        assert not ctx["training"].get("km_per_week")        # geen verzonnen running load
        assert ctx["training"].get("databron_onzeker")

    def test_recovery_after_outage(self, monkeypatch):
        base = _raw(_pure_runner_log())
        store = {}
        monkeypatch.setattr(snapshot, "load_snapshot", lambda k: store.get(k))
        monkeypatch.setattr(snapshot, "save_snapshot",
                            lambda s: (store.__setitem__(s.athlete_key, s), (True, ""))[1])
        # outage
        monkeypatch.setattr(sources, "gather", self._fault_gather(base, fail_training_log=True))
        adapter.build_state("T", TODAY)
        # herstel
        monkeypatch.setattr(sources, "gather", self._fault_gather(base, fail_training_log=False))
        st, raw = adapter.build_state("T", TODAY)
        km = next((e for e in st.evidence if e.key == "load.km_per_week"), None)
        assert km is not None and km.status != STALE          # weer live
        assert "fs.training_log" not in st.source_gaps
        ctx = adapter.to_legacy_context(st, raw, TODAY)
        assert "laatst bekend" not in str(ctx["training"].get("km_per_week"))


# ════════════════════════════════════════════════════════════════════════════
# SEMANTISCHE VERGELIJKING — pure runner gelijk, cross-trainer gecorrigeerd
# ════════════════════════════════════════════════════════════════════════════
class TestFeedbackProjection:
    def test_load_reaches_feedback_projection(self):
        # obs C: Feedback moet km/runs/interruption uit de projectie kunnen halen
        _, st = _ctx(_raw(_pure_runner_log()), _health())
        from brain import projections
        fb = projections.for_feedback(st)
        keys = {e["key"] for e in fb["evidence"]}
        assert "load.km_per_week" in keys and "load.runs_per_week" in keys

    def test_context_block_bevat_km(self):
        _, st = _ctx(_raw(_pure_runner_log()), _health())
        block = adapter.feedback_context(st, "")
        assert block["has_load"] is True
        assert "km/week" in block["prompt_block"]
        assert "Vraag NIET" in block["prompt_block"]

    def test_context_block_gap_geen_valse_belasting(self):
        # obs source-health: bij trainingslog-uitval geen km-claim, wel expliciet onbekend
        _, st = _ctx(_raw([]), _health(training_log=False))
        block = adapter.feedback_context(st, "")
        assert block["has_load"] is False
        assert "onbekend" in block["prompt_block"].lower()
        assert "km/week" not in block["prompt_block"]

    def test_context_block_klacht_coachperspectief_zonder_diagnose(self):
        # FC-3: klacht komt door met coachperspectief (coachacties), nooit als diagnose
        notes = [{"datum": _d(3), "tekst": "achilles zeurt weer opnieuw"}]
        _, st = _ctx(_raw(_pure_runner_log(), notes=notes), _health())
        block = adapter.feedback_context(st, "")
        pb = block["prompt_block"].lower()
        assert "achilles" in pb
        assert "coachperspectief" in pb and "geen diagnose" in pb

    def test_empty_athlete_safe(self):
        _, st = _ctx(_raw([]), _health())
        block = adapter.feedback_context(st, "")
        assert block["prompt_block"] == "" or isinstance(block["prompt_block"], str)


class TestSemanticCompareClassification:
    def test_pure_runner_format_only(self):
        cls = shadow._classify_running(14.0, 14.0, 2.0, 2.0, 14.0, [])
        assert cls == "FORMAT_ONLY"

    def test_pure_runner_unexpected_change(self):
        # geen non-run sessies, maar v1 km wijkt af van v2 → verdacht
        cls = shadow._classify_running(14.0, 11.0, 2.0, 2.0, 11.0, [], n_nonrun=0)
        assert cls == "UNEXPECTED_SEMANTIC_CHANGE"

    def test_crosstrainer_km_correction(self):
        # all-activity 69 (incl. fiets), run-only/v2 = 9 → bedoelde km-correctie
        cls = shadow._classify_running(69.0, 9.0, 1.8, 1.0, 69.0, [], n_nonrun=6)
        assert cls == "EXPECTED_CORRECTION"

    def test_runs_only_sportmix_correction(self):
        # km identiek (non-run zonder afstand) maar v1 telde ze als runs → correctie
        cls = shadow._classify_running(35.6, 35.6, 7.2, 2.5, 35.6, [], n_nonrun=100)
        assert cls == "EXPECTED_CORRECTION"

    def test_training_log_gap_is_source_health(self):
        cls = shadow._classify_running(69.0, None, 1.8, None, None, ["fs.training_log"], n_nonrun=6)
        assert cls == "SOURCE_HEALTH_DIFFERENCE"
