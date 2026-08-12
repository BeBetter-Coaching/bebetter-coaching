"""Masterbrein v2 — Fase A testmatrix (source health, truth/provenance, complaints,
load, good-is-good, relaties, contradictions, projections, snapshot, performance).

De intelligentie (L2–L6) is puur → deterministisch testbaar zonder FinalSurge/AI:
we voeden `assemble()` met een raw-bundle + SourceHealth en asserten de state.
"""
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pwa"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import brain
from brain import models as M
from brain import projections, snapshot
from brain import sources as B_sources
from brain import state as B_state

TODAY = date(2026, 8, 12)
_SRC = ["intake", "coach_notes", "fs.training_log", "fs.zones", "fs.labels",
        "belasting", "on_hold", "garmin", "coach_memory"]


def H(fail=()):
    return [M.SourceHealth(source=s, available=(s not in fail),
                           error=("fout" if s in fail else "")) for s in _SRC]


def d(n):
    return (TODAY - timedelta(days=n)).isoformat()


def run(days, km=10, felt=2, effort=5, name="Duurloop", desc="rustige duurloop Z2",
        pace=None, planned=None, wk=None, completed=True, is_race=False, post=""):
    return {"date": d(days), "workout_key": wk or f"w{days}", "completed": completed,
            "actual_km": km, "planned_km": planned, "actual_min": km * 6,
            "felt": felt, "effort": effort, "activity_type": "Hardlopen",
            "name": name, "description": desc, "pace": pace, "hr_avg": None,
            "is_race": is_race, "post_notes": post}


ZONES_TEMPO = {"zones_text": "Z1 5:00-8:00", "zone_type": "tempo",
               "zones": [{"num": 1, "naam": "rustig", "low": 400, "high": 600},
                         {"num": 4, "naam": "drempel", "low": 240, "high": 270}]}


def raw_base(**kw):
    r = {"intake": {}, "intake_ts": "", "notes": [], "training_log": [], "labels": [],
         "zones": {}, "belasting": None, "on_hold": None, "garmin": "", "profiel": ""}
    r.update(kw)
    return r


def build(raw, health=None, prev=None):
    return B_state.assemble("A", "Anna", raw, health or H(), TODAY, prev)


def _grp(st, area):
    return next((e for e in st.evidence if e.key == f"complaint.{area}"), None)


def _key(st, key):
    return next((e for e in st.evidence if e.key == key), None)


# ══ SOURCE HEALTH ══════════════════════════════════════════════════════════
def test_01_gezonde_bron_leeg_is_known_empty():
    st = build(raw_base(training_log=[run(2)]))
    assert st.source("fs.training_log").available and not st.source("fs.training_log").stale
    assert "fs.training_log" not in st.source_gaps

def test_02_bron_faalt_is_unavailable():
    st = build(raw_base(), health=H(fail=("fs.training_log",)))
    assert st.source("fs.training_log").available is False
    assert "fs.training_log" in st.source_gaps

def test_03_stale_last_known_good():
    prev = build(raw_base(training_log=[run(i * 3, km=10, planned=10) for i in range(12)]))
    assert _key(prev, "load.km_per_week")
    now = build(raw_base(training_log=[]), health=H(fail=("fs.training_log",)), prev=prev)
    carried = _key(now, "load.km_per_week")
    assert carried is not None and carried.status == M.STALE
    assert carried.detail.get("last_known_good") is True

def test_04_partial_outage():
    st = build(raw_base(training_log=[run(2)]), health=H(fail=("fs.zones",)))
    assert "fs.zones" in st.source_gaps and "fs.training_log" not in st.source_gaps

def test_05_geen_false_geen_klacht_bij_outage():
    st = build(raw_base(training_log=[]), health=H(fail=("fs.training_log", "coach_notes")))
    assert st.overall == M.INSUFFICIENT_DATA
    assert "fs.training_log" in st.source_gaps

# ══ TRUTH / PROVENANCE ═════════════════════════════════════════════════════
def test_06_hard_fact_zones():
    st = build(raw_base(zones=ZONES_TEMPO))
    z = _key(st, "zones.personal")
    assert z and z.truth_type == M.FACT and z.strength == M.HIGH

def test_07_athlete_reported():
    st = build(raw_base(intake={"doel": "10 km"}, intake_ts=d(20)))
    assert _key(st, "goal.doel").truth_type == M.ATHLETE_REPORTED

def test_08_coach_reported():
    st = build(raw_base(notes=[{"datum": d(5), "tekst": "goede week gedraaid"}]))
    assert _key(st, "coach.observation").truth_type == M.COACH_REPORTED

def test_09_derivation_heeft_provenance():
    st = build(raw_base(training_log=[run(i * 2, planned=10) for i in range(10)]))
    km = _key(st, "load.km_per_week")
    assert km and km.truth_type == M.DERIVED and km.provenance

def test_10_stable_ids_bij_rebuild():
    r = raw_base(notes=[{"datum": d(3), "tekst": "pijn aan knie"}], training_log=[run(2)])
    a = build(r); b = build(r)
    assert sorted(e.id for e in a.evidence) == sorted(e.id for e in b.evidence)

# ══ COMPLAINTS ═════════════════════════════════════════════════════════════
def test_11_acute_complaint():
    st = build(raw_base(notes=[{"datum": d(3), "tekst": "pijn aan knie"}]))
    assert _grp(st, "knie").status == M.ACTIVE

def test_12_recurring_complaint():
    st = build(raw_base(notes=[{"datum": d(3), "tekst": "pijn aan achilles"},
                               {"datum": d(15), "tekst": "achilles zeurt weer opnieuw"}]))
    assert _grp(st, "achilles").status == M.RECURRING

def test_13_explicit_resolved():
    st = build(raw_base(notes=[{"datum": d(20), "tekst": "pijn aan knie"},
                               {"datum": d(3), "tekst": "knie is helemaal hersteld"}]))
    assert _grp(st, "knie").status == M.RESOLVED

def test_14_resolved_recurring_history_preserved():
    st = build(raw_base(notes=[{"datum": d(30), "tekst": "pijn aan achilles"},
                               {"datum": d(20), "tekst": "achilles zeurt weer"},
                               {"datum": d(2), "tekst": "achilles is nu over en hersteld"}]))
    g = _grp(st, "achilles")
    assert g.status == M.RESOLVED and g.detail["count"] == 2 and len(g.provenance) == 2

def test_15_stale_old_complaint():
    st = build(raw_base(notes=[{"datum": d(200), "tekst": "pijn aan hamstring"}]))
    assert _grp(st, "hamstring").status == M.HISTORICAL

def test_16_negated_complaint_geen_evidence():
    st = build(raw_base(notes=[{"datum": d(3), "tekst": "geen pijn aan de knie, ging prima"}]))
    assert _grp(st, "knie") is None

# ══ LOAD ═══════════════════════════════════════════════════════════════════
def test_17_stable_load():
    st = build(raw_base(training_log=[run(i * 2, km=10) for i in range(28)]))
    assert _key(st, "load.trend").value == "stabiel"

def test_18_rising_load():
    log = [run(i, km=12, wk=f"r{i}") for i in range(0, 28, 2)] + \
          [run(28 + i, km=4, wk=f"o{i}") for i in range(0, 28, 3)]
    assert _key(build(raw_base(training_log=log)), "load.trend").value == "opbouwend"

def test_19_interruption():
    st = build(raw_base(training_log=[run(21 + i * 2, km=10) for i in range(10)]))
    assert _key(st, "load.interruption") is not None

def test_20_return_after_gap():
    log = [run(i, km=10) for i in range(0, 18, 2)] + [run(60, km=10, wk="old")]
    assert _key(build(raw_base(training_log=log)), "load.trend").value == "hervat"

def test_21_duration_aggregate():
    st = build(raw_base(training_log=[run(i * 2, km=10) for i in range(12)]))
    assert _key(st, "load.min_per_week") is not None

# ══ GOOD-IS-GOOD ═══════════════════════════════════════════════════════════
def _rising_log():
    return [run(i, km=12, felt=2, effort=5, wk=f"r{i}") for i in range(0, 28, 2)] + \
           [run(28 + i, km=4, felt=2, effort=5, wk=f"o{i}") for i in range(0, 28, 3)]

def test_22_gezonde_atleet_good_of_stable():
    st = build(raw_base(training_log=[run(i * 2) for i in range(20)]))
    assert st.overall in (M.GOOD, M.STABLE)

def test_23_high_load_good_response_niet_problematiseren():
    st = build(raw_base(training_log=_rising_log()))
    assert _key(st, "load.well_tolerated") is not None and st.overall in (M.GOOD, M.STABLE)

def test_24_source_outage_insufficient():
    st = build(raw_base(training_log=[]), health=H(fail=("fs.training_log",)))
    assert st.overall == M.INSUFFICIENT_DATA

def test_25_active_complaint_niet_good():
    st = build(raw_base(training_log=[run(i * 2) for i in range(20)],
                        notes=[{"datum": d(2), "tekst": "pijn aan knie"}]))
    assert st.overall == M.ATTENTION

# ══ RELATIONSHIPS ══════════════════════════════════════════════════════════
def test_26_load_up_good_response_well_tolerated():
    assert _key(build(raw_base(training_log=_rising_log())), "load.well_tolerated")

def test_27_load_up_recurring_complaint_possible_relation():
    log = _rising_log()
    st = build(raw_base(training_log=log, notes=[{"datum": d(3), "tekst": "pijn aan achilles"},
                                                 {"datum": d(15), "tekst": "achilles zeurt"}]))
    pr = _key(st, "load.possible_relation")
    assert pr and pr.value == "possible_relation" and pr.detail["note"].startswith("associatie")

def _easy_runs(n, pace):
    return [run(i * 3, km=10, pace=pace, name="Duurloop", desc="rustige duurloop Z2", wk=f"e{i}")
            for i in range(n)]

def test_28_one_over_zone_geen_structural_pattern():
    log = _easy_runs(2, "8:20") + [run(9, km=10, pace="5:00", desc="rustige duurloop Z2", wk="over")]
    soz = _key(build(raw_base(training_log=log, zones=ZONES_TEMPO)), "zones.structural_over")
    assert soz.value not in ("REPEATED_OVER", "ZONE_REVIEW_CANDIDATE")

def test_29_repeated_over_zone_pattern():
    # herhaald over + actieve klacht → blijft REPEATED_OVER (geen review candidate)
    st = build(raw_base(training_log=_easy_runs(4, "5:00"), zones=ZONES_TEMPO,
                        notes=[{"datum": d(2), "tekst": "pijn aan knie"}]))
    assert _key(st, "zones.structural_over").value == "REPEATED_OVER"

def test_30_repeated_over_good_feedback_review_candidate():
    st = build(raw_base(training_log=_easy_runs(4, "5:00"), zones=ZONES_TEMPO))
    assert _key(st, "zones.structural_over").value == "ZONE_REVIEW_CANDIDATE"

# ══ CONTRADICTIONS ═════════════════════════════════════════════════════════
def test_31_live_zone_beats_intake():
    st = build(raw_base(intake={"zones": "oude zones uit intake"}, zones=ZONES_TEMPO))
    assert _key(st, "precedence.zones").detail["winner"] == "fs.zones"

def test_32_resolved_beats_old_active_current():
    st = build(raw_base(notes=[{"datum": d(4), "tekst": "pijn aan knie"},
                               {"datum": d(2), "tekst": "knie helemaal hersteld"}]))
    assert _grp(st, "knie").status == M.RESOLVED

def test_33_coach_current_correction_history_preserved():
    st = build(raw_base(notes=[{"datum": d(6), "tekst": "pijn aan achilles na duurloop"},
                               {"datum": d(1), "tekst": "achilles is over en hersteld"}]))
    g = _grp(st, "achilles")
    assert g.status == M.RESOLVED and g.provenance   # mentions behouden

def test_34_on_hold_plus_training_conflict():
    st = build(raw_base(on_hold={"since": d(20), "reden": "vakantie"},
                        training_log=[run(5, km=10)]))
    c = _key(st, "conflict.on_hold_vs_activity")
    assert c and c.status == M.CONFLICT and c.id in st.conflicts

# ══ PROJECTIONS ════════════════════════════════════════════════════════════
def test_35_home_low_strength_weg():
    # één athlete-melding (post_notes) → strength LOW → hoort NIET op Home
    st = build(raw_base(training_log=[run(2, post="pijn aan knie")]))
    assert _grp(st, "knie").strength == M.LOW
    home = projections.for_home(st)
    assert not any(e["key"] == "complaint.knie" for e in home["evidence"])

def test_36_home_medium_recurring_zichtbaar():
    st = build(raw_base(notes=[{"datum": d(3), "tekst": "pijn aan achilles"},
                               {"datum": d(15), "tekst": "achilles zeurt weer"}]))
    home = projections.for_home(st)
    assert any(e["key"] == "complaint.achilles" for e in home["evidence"])

def test_37_feedback_oude_klacht_weg():
    st = build(raw_base(notes=[{"datum": d(240), "tekst": "pijn aan hamstring"}],
                        training_log=[run(2)]))
    fb = projections.for_feedback(st)
    assert not any(e["key"] == "complaint.hamstring" for e in fb["evidence"])

def test_38_schema_planning_context_aanwezig():
    st = build(raw_base(intake={"doel": "10 km"}, training_log=[run(i * 2) for i in range(10)]))
    sc = projections.for_schema(st)
    keys = {e["key"] for e in sc["evidence"]}
    assert "goal.doel" in keys and any(k.startswith("load.") for k in keys)

def test_39_dossier_historie_behouden():
    st = build(raw_base(notes=[{"datum": d(200), "tekst": "pijn aan hamstring"}]))
    dos = projections.for_dossier(st)
    assert any(e["key"] == "complaint.hamstring" for e in dos["evidence"])
    assert any(e["key"].startswith("complaint.mention.") for e in dos["evidence"])

# ══ SNAPSHOT ═══════════════════════════════════════════════════════════════
@pytest.fixture
def local_store(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot.intake_store, "_gh_token", lambda: "")
    monkeypatch.setattr(snapshot, "_LOCAL", str(tmp_path / "bs.json"))

def test_40_snapshot_save_load(local_store):
    st = build(raw_base(training_log=[run(2)]))
    ok, _ = snapshot.save_snapshot(st)
    assert ok
    got = snapshot.load_snapshot("A")
    assert got and got.athlete_key == "A" and len(got.evidence) == len(st.evidence)

def test_41_snapshot_source_stale_metadata(local_store):
    st = build(raw_base(), health=H(fail=("fs.zones",)))
    snapshot.save_snapshot(st)
    got = snapshot.load_snapshot("A")
    assert got.source("fs.zones").available is False

def test_42_snapshot_missing_safe(local_store):
    assert snapshot.load_snapshot("ONBEKEND") is None

def test_43_snapshot_version_mismatch_safe(local_store, monkeypatch):
    st = build(raw_base(training_log=[run(2)]))
    snapshot.save_snapshot(st)
    monkeypatch.setattr(snapshot, "SCHEMA_VERSION", 999)
    assert snapshot.load_snapshot("A") is None

# ══ PERFORMANCE / CALLS ════════════════════════════════════════════════════
class _FSCounter:
    def __init__(self):
        self.calls = {}
    def _bump(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

@pytest.fixture
def fs_stub(monkeypatch):
    import fs_client as FS
    c = _FSCounter()
    monkeypatch.setattr(B_sources, "_fs_ready", lambda: True)
    monkeypatch.setattr(FS, "get_training_log", lambda *a, **k: (c._bump("training_log") or [run(2)]))
    monkeypatch.setattr(FS, "get_calendar_labels", lambda *a, **k: (c._bump("labels") or []))
    monkeypatch.setattr(FS, "get_athlete_zones", lambda *a, **k: (c._bump("zones") or ZONES_TEMPO))
    def _boom(*a, **k):
        c._bump("FANOUT"); raise AssertionError("fan-out niet toegestaan in Fase A")
    monkeypatch.setattr(FS, "get_comments", _boom)
    monkeypatch.setattr(FS, "get_workouts_needing_feedback", _boom)
    return c

def test_44_hot_read_geen_fs_call(local_store, monkeypatch):
    st = build(raw_base(training_log=[run(2)]))
    snapshot.save_snapshot(st)
    import fs_client as FS
    monkeypatch.setattr(FS, "get_training_log", lambda *a, **k: (_ for _ in ()).throw(AssertionError("FS bij hot read")))
    got = snapshot.load_snapshot("A")
    assert got is not None       # geen FS-call nodig

def test_45_refresh_geen_duplicate_same_source(fs_stub):
    B_sources.gather("A", TODAY)
    assert fs_stub.calls.get("training_log") == 1
    assert fs_stub.calls.get("zones") == 1

def test_46_geen_comment_fanout(fs_stub):
    B_sources.gather("A", TODAY)
    assert "FANOUT" not in fs_stub.calls
