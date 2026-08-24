"""Feedback v1 Completion — acceptance-set (A–H).

Temporal/context salience, output-length/truncation, register, unplanned coverage, date-first
ordering, summary grouping, refresh spinner en debug-knop. Bewaakt de bestaande locks (Class 1/2,
PF-4) via de rest van de suite.

    python3 -m pytest tests/test_feedback_v1_completion.py -q
"""
import os
import sys
from datetime import date, timedelta

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback
import fs_client
import feedback_core as FC
from brain import state as _state, adapter, eventtime
from brain.models import SourceHealth

TODAY = date(2026, 8, 20)          # donderdag


def _d(n):
    return (TODAY - timedelta(days=n)).isoformat()


def _health():
    h = []
    for src in ("intake", "coach_notes", "coach_memory", "on_hold", "garmin", "belasting",
                "fs.training_log", "fs.labels", "fs.zones"):
        h.append(SourceHealth(source=src, available=True, last_success=TODAY.isoformat(), error=""))
    return h


def _raw(intake=None, notes=None):
    return {"intake": intake if intake is not None else {"doel": "10km"},
            "intake_ts": _d(30), "notes": notes or [], "profiel": "", "on_hold": None,
            "garmin": "", "belasting": None, "training_log": [], "labels": [], "zones": {}}


def _brainctx(intake=None, notes=None, athlete_raised_race=False, today=TODAY):
    st = _state.assemble("A", "Lisa", _raw(intake, notes), _health(), today)
    return adapter.feedback_context(st, "", today, athlete_raised_race=athlete_raised_race)["prompt_block"]


class _Resp:
    def __init__(self, text, stop_reason="end_turn"):
        self.content = [type("C", (), {"text": text})()]
        self.stop_reason = stop_reason


# ════════════════════════════════════════════════════════════════════════════
# A — temporal/context salience
# ════════════════════════════════════════════════════════════════════════════
def _wctx(monkeypatch, workout_date):
    monkeypatch.setattr(ai_feedback.intake_store, "garmin_context_text", lambda *a, **k: "", raising=False)
    wd = {"athlete_name": "Lisa Test", "athlete_first_name": "Lisa", "workout_name": "Duurloop",
          "post_notes": "op naar zondag", "athlete_comments": [], "workout_key": "", "athlete_key": "",
          "workout_date": workout_date, "felt": None, "effort": None, "coach_profiel": "", "brein_context": ""}
    ctx, _ = ai_feedback._build_workout_context(wd)
    return ctx


def test_1_huidige_weekdag_en_relatieve_dag(monkeypatch):
    # De huidige weekdag staat expliciet in de context, met de instructie om relatieve dagwoorden
    # tegen vandaag om te rekenen en een voorbije dag niet als actuele afsluiting te echoën.
    ctx = _wctx(monkeypatch, (date.today() - timedelta(days=1)).isoformat())
    weekdagen = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
    assert weekdagen[date.today().weekday()] in ctx          # weekdag van vandaag aanwezig
    assert "Reken die eerst om" in ctx
    assert "NIET als actuele afsluiting" in ctx


def test_2_race_20_dagen_niet_proactief():
    pb = _brainctx(intake={"wedstrijddatum": (TODAY + timedelta(days=20)).isoformat(), "doel": "10km"})
    assert "Bekende afspraak" not in pb and "noemt zelf een wedstrijd" not in pb


def test_2b_race_21_en_49_dagen_niet_proactief():
    for n in (21, 49):
        pb = _brainctx(intake={"wedstrijddatum": (TODAY + timedelta(days=n)).isoformat(), "doel": "10km"})
        assert "Bekende afspraak" not in pb


def test_3_race_binnen_venster_wel_relevant():
    pb = _brainctx(intake={"wedstrijddatum": (TODAY + timedelta(days=5)).isoformat(), "doel": "10km"})
    assert "Bekende afspraak" in pb                           # ≤10 dagen → proactief toegestaan


def test_4_atleet_noemt_verre_race_zelf():
    pb = _brainctx(intake={"wedstrijddatum": (TODAY + timedelta(days=20)).isoformat(), "doel": "10km"},
                   athlete_raised_race=True)
    assert "noemt zelf een wedstrijd" in pb                   # als reactie, niet proactief


def test_5_6_oude_klacht_niet_opnieuw_vragen_en_absence_guard():
    pb = _brainctx(notes=[{"datum": _d(3), "tekst": "last van mijn knie"}])
    assert "Vraag NIET actief naar een bestaande klacht" in pb   # niet uit onszelf opnieuw vragen
    assert "geen hinder gaf" in pb                               # afwezigheid ≠ opgelost


def test_7_geen_nieuwe_fase_zonder_bron():
    pb = _brainctx(notes=[{"datum": _d(3), "tekst": "last van mijn knie"}])
    assert "nieuwe fase" in pb.lower()                        # expliciete guard aanwezig


# ════════════════════════════════════════════════════════════════════════════
# B — output length + truncation contract
# ════════════════════════════════════════════════════════════════════════════
def test_8_length_scaling_in_prompt_contract():
    assert "LENGTE" in ai_feedback.SYSTEM_PROMPT
    assert "2 tot 5 korte zinnen" in ai_feedback.SYSTEM_PROMPT
    assert "NOOIT drie of vier alinea" in ai_feedback.SYSTEM_PROMPT


def test_9_truncatie_niet_stil_gepubliceerd(monkeypatch):
    # tweemaal afgekapt → FeedbackTruncated (nooit stil een half antwoord teruggeven)
    monkeypatch.setattr(ai_feedback, "create_message",
                        lambda **kw: _Resp("half antwoord dat", stop_reason="max_tokens"))
    with pytest.raises(ai_feedback.FeedbackTruncated):
        ai_feedback._generate_text(max_tokens=1000, model="m", messages=[])


def test_9b_truncatie_retry_levert_compleet(monkeypatch):
    calls = {"n": 0}

    def _fake(**kw):
        calls["n"] += 1
        return _Resp("kort", "max_tokens") if calls["n"] == 1 else _Resp("volledig antwoord", "end_turn")
    monkeypatch.setattr(ai_feedback, "create_message", _fake)
    out = ai_feedback._generate_text(max_tokens=1000, model="m", messages=[])
    assert out == "volledig antwoord" and calls["n"] == 2


def test_9c_ruim_budget(monkeypatch):
    caught = {}
    monkeypatch.setattr(ai_feedback, "create_message",
                        lambda **kw: caught.update(kw) or _Resp("ok", "end_turn"))
    ai_feedback._generate_text(max_tokens=ai_feedback._FEEDBACK_MAX_TOKENS, model="m", messages=[])
    assert caught["max_tokens"] >= 1000                      # geen krappe 400-cap meer


# ════════════════════════════════════════════════════════════════════════════
# C — register (natuurlijke taal, geen neologismen)
# ════════════════════════════════════════════════════════════════════════════
def test_10_register_contract_geen_neologismen():
    sp = ai_feedback.SYSTEM_PROMPT
    assert "REGISTER" in sp and "neologismen" in sp
    assert "niet overdreven creatief" in sp.lower() or "overdreven creatief" in sp.lower()


# ════════════════════════════════════════════════════════════════════════════
# D — unplanned workout coverage
# ════════════════════════════════════════════════════════════════════════════
def _mock_fs_unplanned(monkeypatch, comments):
    monkeypatch.setattr(fs_client, "get_coach_key", lambda: "COACH")
    monkeypatch.setattr(fs_client, "get_athletes",
                        lambda: [{"user_key": "A", "name": "Lisa Test", "first_name": "Lisa",
                                  "group": "Getting Better", "all_groups": ["Getting Better"]}])
    run = {"key": "U1", "workout_date": (date.today() - timedelta(days=1)).isoformat(),
           "name": "Avondrun", "CommentCount": 0, "post_workout_notes": ""}
    monkeypatch.setattr(fs_client, "get_workouts_deduped", lambda ak, s, e: [run])
    monkeypatch.setattr(fs_client, "is_executed_workout", lambda w: True)      # uitgevoerd
    monkeypatch.setattr(fs_client, "is_planned_workout", lambda w: False)      # ongepland
    monkeypatch.setattr(fs_client, "classify_workout_type", lambda w: "run")
    monkeypatch.setattr(fs_client, "get_comments", lambda wk, ak: comments)


def test_11_unplanned_met_comment_exact_een_item(monkeypatch):
    _mock_fs_unplanned(monkeypatch, [{"comment": "Lekker gelopen!", "user_key": "A",
                                      "timestamp": (date.today() - timedelta(days=1)).isoformat() + "T18:00:00"}])
    res = fs_client.get_workouts_needing_feedback(
        days_back=7, exclude_groups={"los schema"}, include_details=False,
        include_unplanned_reactions=True)
    assert len(res) == 1 and res[0]["workout_key"] == "U1"    # ad-hoc run met atleet-comment verschijnt, exact één keer


def test_12_unplanned_zonder_comment_niet_getoond(monkeypatch):
    _mock_fs_unplanned(monkeypatch, [])                       # geen atleet-comment
    res = fs_client.get_workouts_needing_feedback(
        days_back=7, exclude_groups={"los schema"}, include_details=False,
        include_unplanned_reactions=True)
    assert res == []                                          # geen reactie → niet elke ongeplande run


def test_12b_zonder_opt_in_ongewijzigd(monkeypatch):
    _mock_fs_unplanned(monkeypatch, [{"comment": "Lekker!", "user_key": "A",
                                      "timestamp": (date.today() - timedelta(days=1)).isoformat() + "T18:00:00"}])
    res = fs_client.get_workouts_needing_feedback(
        days_back=7, exclude_groups={"los schema"}, include_details=False)  # opt-in off
    assert res == []                                          # Streamlit-gedrag ongewijzigd


# ════════════════════════════════════════════════════════════════════════════
# E — date-first deterministic ordering
# ════════════════════════════════════════════════════════════════════════════
def test_13_date_first_ordering(monkeypatch):
    monkeypatch.setattr(FC.intake_store, "load_skipped", lambda: {})
    snap = {"fs": True, "gepost": 0, "berekend": "x", "datum": "x", "items": [
        {"id": "b", "datum": "2026-08-22", "groep": "getting_better", "categorie": "reactie", "athlete_ts": "", "naam": "B"},
        {"id": "a", "datum": "2026-08-20", "groep": "high_performer", "categorie": "uitgevoerd", "athlete_ts": "", "naam": "A"},
        {"id": "c", "datum": "2026-08-21", "groep": "comfort", "categorie": "gevoel", "athlete_ts": "", "naam": "C"},
    ]}
    out = FC._queue_public(snap, cached=True)
    assert [i["id"] for i in out["items"]] == ["a", "c", "b"]  # oudste datum eerst


# ════════════════════════════════════════════════════════════════════════════
# F — summary grouping per datum/groep (successfully-posted truth behouden)
# ════════════════════════════════════════════════════════════════════════════
def test_14_summary_gegroepeerd_per_datum_en_groep(monkeypatch):
    cap = {}
    monkeypatch.setattr(ai_feedback, "create_message",
                        lambda **kw: cap.update(prompt=kw["messages"][0]["content"]) or _Resp("SAMENVATTING"))
    items = [
        {"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "top", "datum": "2026-08-20", "groep_label": "Getting Better"},
        {"athlete_name": "Sem", "workout_name": "Interval", "feedback_text": "sterk", "datum": "2026-08-22", "groep_label": "High Performer"},
    ]
    out = ai_feedback.generate_session_summary("Jip", items)
    assert out == "SAMENVATTING"
    p = cap["prompt"]
    assert "20 augustus" in p and "22 augustus" in p          # per datum
    assert "Groep Getting Better" in p and "Groep High Performer" in p   # per groep
    assert "GEGROEPEERD PER TRAININGSDATUM" in p


def test_14b_summary_alleen_geposte_items():
    # de core krijgt exact de meegegeven (geposte) set; niets toegevoegd
    clean = FC._clean_summary_items([
        {"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "top", "workout_key": "W1"},
        {"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "top", "workout_key": "W1"},  # dubbel
    ])
    assert len(clean) == 1                                    # dedup; geen verzonnen items


# ════════════════════════════════════════════════════════════════════════════
# G, H — spinner loading-state + debug-knop production-hidden (source-guards)
# ════════════════════════════════════════════════════════════════════════════
def _appjs():
    return open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()


def test_15_refresh_spinner_loading_state():
    src = _appjs()
    seg = src.split('$("#fb-refresh").addEventListener')[1].split("document.addEventListener")[0]
    assert 'classList.add("spinning")' in seg and 'classList.remove("spinning")' in seg
    assert "@keyframes spin" in open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()


def test_16_debugknop_production_hidden():
    src = _appjs()
    seg = src.split("function fbLogBind()")[1].split("function ")[0]
    assert "bb_swdebug" in seg and "dbg.hidden = true" in seg   # verborgen buiten debug-modus
