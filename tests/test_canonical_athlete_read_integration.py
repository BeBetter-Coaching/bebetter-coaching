"""Canonical Athlete Read Layer v1 — integratietests (Gates 2/3/4/5).

Drijft de ECHTE dossier_cockpit.cockpit()/explain_claim() en de Feedback-AI-context door de
gedeelde `athlete_read`-laag, met gepatchte `sources.gather` (geen netwerk) en snapshot-IO.

    python3 -m pytest tests/test_canonical_athlete_read_integration.py -q
"""
import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import pytest

import athlete_read as AR
import dossier_cockpit as DC
from brain import sources as SRC
from brain import snapshot as SNAP
from brain.models import SourceHealth

TODAY = date(2026, 9, 1)


def _health(training_log=True):
    h = []
    for src, ok in (("intake", True), ("coach_notes", True), ("coach_memory", True),
                    ("on_hold", True), ("garmin", True), ("belasting", True),
                    ("fs.training_log", training_log), ("fs.labels", True), ("fs.zones", training_log)):
        h.append(SourceHealth(source=src, available=ok, last_success=TODAY.isoformat(),
                              error=("" if ok else "geen bron")))
    return h


def _raw(doel="10km sub 50"):
    return {"intake": {"doel": doel, "athlete_name": "Tester"},
            "intake_ts": (TODAY - timedelta(days=30)).isoformat(), "notes": [], "profiel": "",
            "on_hold": None, "garmin": "", "belasting": None, "training_log": [], "labels": [], "zones": {}}


@pytest.fixture
def wire(monkeypatch):
    """Patch gather + snapshot-IO; retourneer een teller + een setter voor de raw-inhoud."""
    AR.reset()
    monkeypatch.setattr(SNAP, "load_snapshot", lambda k: None, raising=True)
    monkeypatch.setattr(SNAP, "save_snapshot", lambda s: (True, ""), raising=True)
    state = {"raw": _raw(), "health": _health(), "n": 0}

    def _g(user_key, today=None):
        state["n"] += 1
        return state["raw"], state["health"]

    monkeypatch.setattr(SRC, "gather", _g, raising=True)
    yield state
    AR.reset()


# ── Gate 2: cockpit gebruikt de gedeelde read + draagt generation/freshness ──
def test_cockpit_carries_generation_and_freshness(wire):
    vm = DC.cockpit("K", today=TODAY)
    assert vm["ok"] is True
    assert vm.get("state_generation_id"), "cockpit-respons draagt state_generation_id"
    assert vm.get("read_freshness", {}).get("from") == "fresh"
    assert vm["read_freshness"]["raw_available"] is True


def test_cockpit_repeated_read_is_cached(wire):
    DC.cockpit("K", today=TODAY)
    DC.cockpit("K", today=TODAY)
    assert wire["n"] == 1, "tweede cockpit-read van dezelfde atleet binnen TTL bouwt niet opnieuw"


# ── Gate 3: 'Waarom?' generatiecoherentie ────────────────────────────────────
def test_explain_match_shows_explanation(wire):
    vm = DC.cockpit("K", today=TODAY)
    gen = vm["state_generation_id"]
    ev_id = None
    # pak een bestaande evidence-id uit de gebouwde state
    read = AR.get_state("K", today=TODAY)
    if read.state and read.state.evidence:
        ev_id = read.state.evidence[0].id
    res = DC.explain_claim("K", ev_id or "x", today=TODAY, gen=gen)
    assert res["generation_changed"] is False
    assert res["explain"] is not None, "matchende generatie → uitleg tonen"


def test_explain_mismatch_no_fabrication(wire):
    DC.cockpit("K", today=TODAY)
    res = DC.explain_claim("K", "whatever", today=TODAY, gen="stale-old-gen")
    assert res["generation_changed"] is True, "andere generatie → generation_changed"
    assert res["explain"] is None, "geen uitleg van een nieuwere staat fabriceren"


def test_explain_absent_state(monkeypatch):
    AR.reset()
    monkeypatch.setattr(SNAP, "load_snapshot", lambda k: None, raising=True)
    monkeypatch.setattr(SNAP, "save_snapshot", lambda s: (True, ""), raising=True)

    def _boom(user_key, today=None):
        raise RuntimeError("gather kapot")

    monkeypatch.setattr(SRC, "gather", _boom, raising=True)
    res = DC.explain_claim("K", "x", today=TODAY, gen="")
    assert res["explain"] is None and "beschikbaar" in res["note"].lower()
    AR.reset()


def test_explain_no_gen_still_explains(wire):
    # Back-compat: zonder gen (oude client) verklaart de laag de actuele staat.
    read = AR.get_state("K", today=TODAY)
    ev_id = read.state.evidence[0].id if (read.state and read.state.evidence) else "x"
    res = DC.explain_claim("K", ev_id, today=TODAY, gen="")
    assert res["generation_changed"] is False


# ── Gate 4: Feedback AI-context deelt de gedeelde read (geen 2e deep build) ──
def test_feedback_context_shares_read_with_cockpit(wire):
    from brain import adapter as _adapter
    DC.cockpit("K", today=TODAY)                          # bouwt state (n=1)
    assert wire["n"] == 1
    block = _adapter.feedback_context_block("K", "wk1", today=TODAY)   # hot-read, geen 2e build
    assert wire["n"] == 1, "Feedback-AI-context mag geen tweede deep build starten (hot-read)"
    assert isinstance(block, dict) and "prompt_block" in block


def test_feedback_context_alone_builds_once(wire):
    from brain import adapter as _adapter
    _adapter.feedback_context_block("K", "wk1", today=TODAY)
    _adapter.feedback_context_block("K", "wk1", today=TODAY)
    assert wire["n"] == 1, "twee AI-context-reads van dezelfde atleet → één gedeelde build"


def test_legacy_brain_mode_no_build(wire, monkeypatch):
    import feedback_core as FC
    monkeypatch.setattr(FC, "feedback_brain_mode", lambda: "legacy", raising=True)
    out = FC._brein_context({"athlete_key": "K", "workout_key": "wk1"})
    assert out == "", "legacy brain-mode levert geen context"
    assert wire["n"] == 0, "legacy brain-mode start GEEN deep build"


# ── Gate 5: invalidatie na zelf-veroorzaakte writes (per categorie één test) ──
def _seed_cache(monkeypatch, key="K"):
    """Zet een gecachete state voor `key` (patched gather + snapshot); return teller."""
    monkeypatch.setattr(SNAP, "load_snapshot", lambda k: None, raising=True)
    monkeypatch.setattr(SNAP, "save_snapshot", lambda s: (True, ""), raising=True)
    c = {"n": 0}

    def _g(user_key, today=None):
        c["n"] += 1
        return _raw(), _health()

    monkeypatch.setattr(SRC, "gather", _g, raising=True)
    AR.get_state(key, today=TODAY)
    assert AR.peek_generation(key) is not None, "state gecachet vóór de write"
    return c


@pytest.fixture
def api_mod():
    AR.reset()
    import api
    yield api
    AR.reset()


def test_invalidate_dossier_note(api_mod, monkeypatch):
    _seed_cache(monkeypatch)
    monkeypatch.setattr(api_mod.dossier, "add_note", lambda k, c, t: (True, ""), raising=True)
    api_mod.dossier_add_note("K", api_mod.Notitie(coach="c", tekst="t"))
    assert AR.peek_generation("K") is None, "coach-notitie → invalidatie"


def test_invalidate_dossier_profiel(api_mod, monkeypatch):
    _seed_cache(monkeypatch)
    monkeypatch.setattr(api_mod.dossier, "save_profiel", lambda k, t: (True, ""), raising=True)
    api_mod.dossier_save_profiel("K", api_mod.Profiel(tekst="x"))
    assert AR.peek_generation("K") is None, "profiel-save → invalidatie"


def test_invalidate_schema_publish(api_mod, monkeypatch):
    _seed_cache(monkeypatch)
    monkeypatch.setattr(api_mod.schema_core, "publish", lambda k, cfg, rows, wid: {"written": 1}, raising=True)
    api_mod.schema_publish(api_mod.SchemaGen(key="K", config={}, rows=[], write_id="w1"))
    assert AR.peek_generation("K") is None, "schema publish (FS-kalender) → invalidatie"


def test_invalidate_schema_push(api_mod, monkeypatch):
    _seed_cache(monkeypatch)
    monkeypatch.setattr(api_mod.schema_core, "push", lambda k, csv: {"pushed": 1}, raising=True)
    api_mod.schema_push(api_mod.SchemaGen(key="K", csv="x"))
    assert AR.peek_generation("K") is None, "schema push (FS-kalender) → invalidatie"


def test_invalidate_intake_koppel(api_mod, monkeypatch):
    _seed_cache(monkeypatch)
    monkeypatch.setattr(api_mod.intake, "link_intake", lambda nk, uk: (True, "", "Naam"), raising=True)
    api_mod.intake_koppel(api_mod.IntakeKoppel(nieuw_key="nieuw:x", user_key="K"))
    assert AR.peek_generation("K") is None, "intake koppelen → invalidatie"


def test_invalidate_teampuls_gezien_belasting(api_mod, monkeypatch):
    _seed_cache(monkeypatch)
    monkeypatch.setattr(api_mod.teampuls, "markeer_gezien", lambda uk, ernst, undo=False: None, raising=True)
    api_mod.teampuls_gezien(api_mod.PulsGezien(user_key="K", ernst="hoog"))
    assert AR.peek_generation("K") is None, "belasting-gezien → invalidatie"


def test_feedback_post_does_NOT_invalidate(api_mod, monkeypatch):
    _seed_cache(monkeypatch)
    monkeypatch.setattr(api_mod.feedback, "session_log_item", lambda i, t: {"ok": 1}, raising=True)
    monkeypatch.setattr(api_mod.feedback, "plaats", lambda i, t: True, raising=True)
    api_mod.feedback_post(api_mod.FeedbackGen(id="wk1", tekst="mooi gedaan"))
    assert AR.peek_generation("K") is not None, "feedback-post (comment) mag NIET invalideren"


def test_race_wens_does_NOT_invalidate(api_mod, monkeypatch):
    _seed_cache(monkeypatch)
    monkeypatch.setattr(api_mod.races, "plaats_wens", lambda i, t: None, raising=True)
    api_mod.races_wens(api_mod.RaceWens(id="r1", tekst="graag deze race"))
    assert AR.peek_generation("K") is not None, "race-wens (comment) mag NIET invalideren"
