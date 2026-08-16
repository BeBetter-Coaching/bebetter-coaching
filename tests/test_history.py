"""Dossier Fase A — history-foundation testmatrix.

Bewijst de harde invarianten uit de opdracht (§8/§9/§10/§11/§19/§23/§24):
model-roundtrip + deterministische ids, append-only store met idempotente dedupe
en CAS-veilige write, snapshot-diff (unchanged→0, klacht-lifecycle, interruption/
return, prev=None→0, bronuitval→geen fake events, cross-training-veiligheid) en de
niet-fatale Feedback-hook. Alles puur/deterministisch — geen FinalSurge/AI.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pwa"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from brain import events as E
from brain import history, history_store as HS
from brain.models import (ACTIVE, ATHLETE_REPORTED, DERIVED, HISTORICAL, MEDIUM,
                          RECENT, RECURRING, RESOLVED, AthleteState, Evidence,
                          SourceHealth, derived_evidence)

TODAY = date(2026, 8, 14)


# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Isoleer de history-store in een tmp-bestand + forceer shadow-modus."""
    monkeypatch.delenv("GH_TOKEN", raising=False)     # forceer lokale fallback
    monkeypatch.setattr(HS, "_LOCAL", str(tmp_path / ".athlete_history.json"))
    monkeypatch.setenv("BEBETTER_DOSSIER_HISTORY", "shadow")
    yield


def _state(ak="ath1", evidence=None, gaps=None):
    st = AthleteState(athlete_key=ak, naam=ak, built_at="2026-08-14T10:00:00",
                      evidence=list(evidence or []))
    st.source_gaps = list(gaps or [])
    st.sources = [SourceHealth(source="fs.training_log", available=("fs.training_log" not in (gaps or [])))]
    return st


def _complaint(area, status, dates, resolved_at="", strength=MEDIUM, ak="ath1"):
    """Bouw een afgeleide klacht-GROEP-evidence (zoals complaints.build produceert)."""
    ev = derived_evidence(
        key=f"complaint.{area}", domain="health", value=area, status=status,
        strength=strength, provenance=[f"m.{area}.{d}" for d in dates],
        window="complaint", athlete_key=ak,
        detail={"area": area, "count": len(dates), "dates": dates,
                "resolved": bool(resolved_at), "resolved_at": resolved_at})
    ev.observed_at = dates[-1] if dates else ""
    return ev


def _interruption(ak="ath1"):
    return derived_evidence("load.interruption", "load", "3 weken niet gettraind",
                            status=ACTIVE, strength=MEDIUM, provenance=["fs.training_log"],
                            window="10w", athlete_key=ak)


def _km(ak="ath1", km=40.0):
    return derived_evidence("load.km_per_week", "load", km, status=ACTIVE,
                            strength=MEDIUM, provenance=["fs.training_log"],
                            window="4w", athlete_key=ak, unit="km/week")


# ── Model ────────────────────────────────────────────────────────────────────
def test_event_roundtrip_and_required_fields():
    ev = E.HistoryEvent(athlete_key="a", event_type=E.COMPLAINT_STARTED,
                        domain="health", entity="kuit", effective_at="2026-08-01")
    d = ev.to_dict()
    back = E.HistoryEvent.from_dict(d)
    assert back.to_dict() == d
    assert back.id == ev.id and back.id.startswith("e_")
    assert back.event_type in E.EVENT_TYPES


def test_event_id_deterministic_and_semantic():
    a = E.event_id("a", E.COMPLAINT_STARTED, "health", "kuit", "2026-08-01")
    b = E.event_id("a", E.COMPLAINT_STARTED, "health", "kuit", "2026-08-01")
    assert a == b                                      # zelfde semantiek → zelfde id
    assert a != E.event_id("a", E.COMPLAINT_STARTED, "health", "knie", "2026-08-01")
    assert a != E.event_id("a", E.COMPLAINT_RESOLVED, "health", "kuit", "2026-08-01")


def test_event_id_independent_of_provenance_and_runtime():
    e1 = E.HistoryEvent(athlete_key="a", event_type=E.COMPLAINT_STARTED, domain="health",
                        entity="kuit", effective_at="2026-08-01", provenance_ids=["m1"],
                        recorded_at="2026-08-10")
    e2 = E.HistoryEvent(athlete_key="a", event_type=E.COMPLAINT_STARTED, domain="health",
                        entity="kuit", effective_at="2026-08-01", provenance_ids=["m1", "m2"],
                        recorded_at="2026-08-14")
    assert e1.id == e2.id                              # provenance/recorded_at ⊄ identiteit


# ── Store ────────────────────────────────────────────────────────────────────
def test_store_append_and_read(store):
    ev = E.HistoryEvent(athlete_key="a", event_type=E.COMPLAINT_STARTED,
                        domain="health", entity="kuit", effective_at="2026-08-01")
    ok, err, n = HS.append_event("a", ev)
    assert ok and n == 1 and err == ""
    got = HS.get_events("a")
    assert len(got) == 1 and got[0].id == ev.id


def test_store_duplicate_append_is_idempotent(store):
    ev = E.HistoryEvent(athlete_key="a", event_type=E.COMPLAINT_STARTED,
                        domain="health", entity="kuit", effective_at="2026-08-01")
    HS.append_event("a", ev)
    ok, err, n = HS.append_event("a", ev)             # exact hetzelfde event
    assert ok and n == 0                              # 0 duplicaten
    assert HS.count_events("a") == 1


def test_store_batch_and_filters(store):
    evs = [
        E.HistoryEvent(athlete_key="a", event_type=E.COMPLAINT_STARTED, domain="health",
                       entity="kuit", effective_at="2026-08-01"),
        E.HistoryEvent(athlete_key="a", event_type=E.COMPLAINT_RESOLVED, domain="health",
                       entity="kuit", effective_at="2026-08-10", status=E.RESOLVED),
        E.HistoryEvent(athlete_key="a", event_type=E.TRAINING_INTERRUPTION_STARTED,
                       domain="load", entity="training", effective_at="2026-08-05"),
    ]
    ok, err, n = HS.append_events("a", evs)
    assert ok and n == 3
    assert len(HS.get_events("a", domain="health")) == 2
    assert len(HS.get_events("a", event_type=E.TRAINING_INTERRUPTION_STARTED)) == 1
    assert len(HS.get_events("a", status=E.RESOLVED)) == 1
    assert len(HS.get_events("a", since="2026-08-04", until="2026-08-31")) == 2
    # deterministische ordening op effective_at
    order = [e.effective_at for e in HS.get_events("a")]
    assert order == sorted(order)


def test_store_persists_across_reload(store):
    ev = E.HistoryEvent(athlete_key="a", event_type=E.COMPLAINT_STARTED, domain="health",
                        entity="kuit", effective_at="2026-08-01")
    HS.append_event("a", ev)
    # nieuwe "sessie": _load_all leest opnieuw van schijf
    assert HS.has_event("a", ev.id)
    assert HS.count_events("a") == 1


def test_store_malformed_file_is_safe(store, tmp_path, monkeypatch):
    p = tmp_path / ".athlete_history.json"
    p.write_text("{ this is not valid json ]")
    monkeypatch.setattr(HS, "_LOCAL", str(p))
    assert HS.get_events("a") == []                   # geen crash → veilige lege state
    ok, err, n = HS.append_event("a", E.HistoryEvent(
        athlete_key="a", event_type=E.COMPLAINT_STARTED, domain="health",
        entity="kuit", effective_at="2026-08-01"))
    assert ok and n == 1                              # herstelt zichzelf


def test_store_cas_retry_on_conflict(store, monkeypatch):
    """Simuleer een write-conflict (409): eerst falen, dan slagen → geen verlies."""
    import intake_store
    calls = {"n": 0}
    real = intake_store._save_json

    def flaky(remote, local, data, msg):
        calls["n"] += 1
        if calls["n"] == 1:
            return False, "GitHub API: 409 — conflict"
        return real(remote, local, data, msg)

    monkeypatch.setattr(intake_store, "_save_json", flaky)
    ev = E.HistoryEvent(athlete_key="a", event_type=E.COMPLAINT_STARTED, domain="health",
                        entity="kuit", effective_at="2026-08-01")
    ok, err, n = HS.append_event("a", ev)
    assert ok and n == 1 and calls["n"] == 2          # retry deed het werk


# ── Diff — snapshot-diff-derivatie ───────────────────────────────────────────
def test_diff_prev_none_yields_no_events():
    cur = _state(evidence=[_complaint("kuit", ACTIVE, ["2026-08-12"])])
    assert history.derive_events(None, cur, TODAY) == []


def test_diff_unchanged_yields_no_events():
    ev = _complaint("kuit", ACTIVE, ["2026-08-12"])
    prev = _state(evidence=[ev])
    cur = _state(evidence=[_complaint("kuit", ACTIVE, ["2026-08-12"])])
    assert history.derive_events(prev, cur, TODAY) == []


def test_diff_complaint_started():
    prev = _state(evidence=[_km()])
    cur = _state(evidence=[_km(), _complaint("kuit", ACTIVE, ["2026-08-12"])])
    evs = history.derive_events(prev, cur, TODAY)
    assert [e.event_type for e in evs] == [E.COMPLAINT_STARTED]
    assert evs[0].entity == "kuit" and evs[0].effective_at == "2026-08-12"


def test_diff_complaint_recurred():
    prev = _state(evidence=[_complaint("kuit", ACTIVE, ["2026-08-10"])])
    cur = _state(evidence=[_complaint("kuit", RECURRING, ["2026-06-20", "2026-08-13"])])
    evs = history.derive_events(prev, cur, TODAY)
    assert [e.event_type for e in evs] == [E.COMPLAINT_RECURRED]


def test_diff_complaint_resolved_keeps_history():
    prev = _state(evidence=[_complaint("kuit", ACTIVE, ["2026-08-10"])])
    cur = _state(evidence=[_complaint("kuit", RESOLVED, ["2026-08-10"], resolved_at="2026-08-13")])
    evs = history.derive_events(prev, cur, TODAY)
    assert [e.event_type for e in evs] == [E.COMPLAINT_RESOLVED]
    assert evs[0].effective_at == "2026-08-13" and evs[0].status == E.RESOLVED


def test_diff_complaint_reactivated():
    prev = _state(evidence=[_complaint("kuit", RESOLVED, ["2026-07-01"], resolved_at="2026-07-05")])
    cur = _state(evidence=[_complaint("kuit", ACTIVE, ["2026-08-13"])])
    evs = history.derive_events(prev, cur, TODAY)
    assert [e.event_type for e in evs] == [E.COMPLAINT_REACTIVATED]


def test_diff_interruption_started_and_resumed():
    healthy = _state(evidence=[_km()])
    interrupted = _state(evidence=[_km(), _interruption()])
    started = history.derive_events(healthy, interrupted, TODAY)
    assert [e.event_type for e in started] == [E.TRAINING_INTERRUPTION_STARTED]
    resumed = history.derive_events(interrupted, healthy, TODAY)
    assert [e.event_type for e in resumed] == [E.TRAINING_RESUMED]


def test_diff_no_fake_event_on_source_gap():
    """Bronuitval mag geen 'resolved' faken (§19). Gap in prev óf current → skip."""
    prev = _state(evidence=[_complaint("kuit", ACTIVE, ["2026-08-10"])])
    # training_log valt uit → klacht 'verdwijnt', maar dat is source-health, geen event
    cur_gap = _state(evidence=[], gaps=["fs.training_log"])
    assert history.derive_events(prev, cur_gap, TODAY) == []
    # ook als de vorige build al onder een gap gebeurde
    prev_gap = _state(evidence=[], gaps=["fs.training_log"])
    cur = _state(evidence=[_complaint("kuit", ACTIVE, ["2026-08-13"])])
    assert history.derive_events(prev_gap, cur, TODAY) == []


def test_diff_cross_training_does_not_distort():
    """Non-run activiteit mag geen interruption/return-event veroorzaken.

    Interruption komt uit run-only load-evidence; een state zonder interruption-
    evidence (ongeacht cross-training) levert geen load-events."""
    prev = _state(evidence=[_km(km=42.0)])
    cur = _state(evidence=[_km(km=41.0)])             # kleine fluctuatie, geen interruption
    assert history.derive_events(prev, cur, TODAY) == []


def test_diff_small_fluctuation_no_spam():
    prev = _state(evidence=[_km(km=40.0), _complaint("kuit", ACTIVE, ["2026-08-12"])])
    cur = _state(evidence=[_km(km=39.0), _complaint("kuit", ACTIVE, ["2026-08-12"])])
    assert history.derive_events(prev, cur, TODAY) == []


# ── Capture (gated + persist + idempotent) ───────────────────────────────────
def test_capture_off_is_noop(store, monkeypatch):
    monkeypatch.setenv("BEBETTER_DOSSIER_HISTORY", "off")
    prev = _state(evidence=[_complaint("kuit", ACTIVE, ["2026-08-10"])])
    cur = _state(evidence=[_complaint("kuit", RESOLVED, ["2026-08-10"], resolved_at="2026-08-13")])
    res = history.capture(prev, cur, TODAY)
    assert res["mode"] == "off" and res["written"] == 0
    assert HS.count_events("ath1") == 0


def test_capture_shadow_persists_and_dedupes(store):
    prev = _state(evidence=[_complaint("kuit", ACTIVE, ["2026-08-10"])])
    cur = _state(evidence=[_complaint("kuit", RESOLVED, ["2026-08-10"], resolved_at="2026-08-13")])
    r1 = history.capture(prev, cur, TODAY)
    assert r1["written"] == 1
    r2 = history.capture(prev, cur, TODAY)            # zelfde overgang nogmaals
    assert r2["written"] == 0                         # 0 duplicaten
    assert HS.count_events("ath1") == 1


def test_capture_never_raises_on_store_failure(store, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("store kapot")
    monkeypatch.setattr(HS, "append_events", boom)
    prev = _state(evidence=[_complaint("kuit", ACTIVE, ["2026-08-10"])])
    cur = _state(evidence=[_complaint("kuit", RESOLVED, ["2026-08-10"], resolved_at="2026-08-13")])
    res = history.capture(prev, cur, TODAY)           # mag NIET raisen
    assert "error" in res and res["written"] == 0


# ── Feedback-hook ────────────────────────────────────────────────────────────
def test_feedback_derive_complaint_and_coach_response():
    evs = history.derive_feedback_events(
        "ath1", "wk1", "2026-08-13",
        athlete_messages=["Ging goed maar last van mijn kuit halverwege"],
        coach_text="Goed bezig, houd de kuit in de gaten.", today=TODAY)
    types = [e.event_type for e in evs]
    assert E.ATHLETE_COMPLAINT_REPORTED in types
    assert E.COACH_RESPONSE_RECORDED in types          # alleen omdat er een klacht is


def test_feedback_no_complaint_no_coach_spam():
    evs = history.derive_feedback_events(
        "ath1", "wk1", "2026-08-13",
        athlete_messages=["Lekker gelopen, voelde goed!"],
        coach_text="Goed gedaan!", today=TODAY)
    assert evs == []                                   # geen 'goed gedaan'-spam


def test_capture_feedback_dedupes_same_workout(store):
    args = ("ath1", "wk1", "2026-08-13", ["last van mijn kuit"], "let op de kuit")
    r1 = history.capture_feedback(*args, today=TODAY)
    assert r1["written"] >= 1
    r2 = history.capture_feedback(*args, today=TODAY)  # zelfde workout opnieuw verwerkt
    assert r2["written"] == 0                          # één event, geen duplicaat


# ── Store-isolatie (shadow-service mag productie-history niet vervuilen) ──────
def test_resolve_remote_default_and_override(monkeypatch):
    monkeypatch.delenv("BEBETTER_DOSSIER_HISTORY_FILE", raising=False)
    assert HS._resolve_remote() == "athlete_history.json"
    monkeypatch.setenv("BEBETTER_DOSSIER_HISTORY_FILE", "athlete_history.shadow.json")
    assert HS._resolve_remote() == "athlete_history.shadow.json"


def test_resolve_remote_rejects_traversal_and_junk(monkeypatch):
    # o.a.: andere productie-stores, path-traversal, ontbrekende extensie, spaties
    for bad in ("../secrets.json", "notes.json", "intakes.json", "brain_snapshot.json",
                "notes.json/../x", "athlete_history", "a b.json", ""):
        monkeypatch.setenv("BEBETTER_DOSSIER_HISTORY_FILE", bad)
        assert HS._resolve_remote() == "athlete_history.json"   # veilige default
    # geldige history-varianten worden wél geaccepteerd
    for ok in ("athlete_history.shadow.json", "athlete_history_test.json"):
        monkeypatch.setenv("BEBETTER_DOSSIER_HISTORY_FILE", ok)
        assert HS._resolve_remote() == ok


def test_shadow_file_does_not_touch_production_file(tmp_path, monkeypatch):
    """Bewijs: schrijven naar de shadow-store raakt het productiebestand niet."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    prod_local = tmp_path / ".athlete_history.json"
    shadow_local = tmp_path / ".athlete_history.shadow.json"
    monkeypatch.setattr(HS, "_REMOTE", "athlete_history.shadow.json")
    monkeypatch.setattr(HS, "_LOCAL", str(shadow_local))
    monkeypatch.setenv("BEBETTER_DOSSIER_HISTORY", "shadow")
    HS.append_event("a", E.HistoryEvent(athlete_key="a", event_type=E.COMPLAINT_STARTED,
                                        domain="health", entity="kuit", effective_at="2026-08-01"))
    assert shadow_local.exists()                       # shadow-bestand beschreven
    assert not prod_local.exists()                     # productiebestand ongemoeid
    assert HS.storage_health()["is_shadow_file"] is True


def test_capture_feedback_off_is_noop(store, monkeypatch):
    monkeypatch.setenv("BEBETTER_DOSSIER_HISTORY", "off")
    res = history.capture_feedback("ath1", "wk1", "2026-08-13",
                                   ["last van mijn kuit"], "let op", today=TODAY)
    assert res["mode"] == "off" and res["written"] == 0
    assert HS.count_events("ath1") == 0
