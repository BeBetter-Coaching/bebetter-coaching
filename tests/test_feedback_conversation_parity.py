"""Fase 2 — Feedback conversation parity.

De eerste feedback op een training blijft een trainingsanalyse (generate_feedback).
Zodra de atleet daarna inhoudelijk reageert loopt er een gesprek en moet de AI op dat
laatste bericht reageren (generate_reply) — zonder de hele training opnieuw te analyseren.
De mode-keuze is DETERMINISTISCH (spreker + volgorde, geen LLM/tekstheuristiek) en
spiegelt 1:1 het bewezen Streamlit-gedrag (main.py:2392 / :2526:
`bool(thread) and last_van=="atleet" and any(van=="coach")`).

    python3 -m pytest tests/test_feedback_conversation_parity.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import fs_client
import feedback_core as FC


# Kleine bouwers voor thread-berichten in de queue-vorm ({tekst, van, naam, timestamp}).
def _coach(t, ts="2026-08-12T10:00:00"):
    return {"tekst": t, "van": "coach", "naam": "jij", "timestamp": ts}


def _atleet(t, ts="2026-08-12T11:00:00"):
    return {"tekst": t, "van": "atleet", "naam": "Lisa", "timestamp": ts}


def _notes(t):
    return {"tekst": t, "van": "atleet", "naam": "Lisa", "timestamp": "", "_display": False}


# ════════════════════════════════════════════════════════════════════════════
# 1. Pure dispatch-helper — alle §8 edge cases (geen I/O, geen AI)
# ════════════════════════════════════════════════════════════════════════════
class TestFeedbackMode:
    def test_1_geen_thread(self):
        assert FC.feedback_mode([]) == FC.INITIAL_ANALYSIS
        assert FC.feedback_mode(None) == FC.INITIAL_ANALYSIS

    def test_2_alleen_athlete_notes_geen_coach(self):
        # Post-notes van de atleet, nog geen coachfeedback → geen fake follow-up.
        assert FC.feedback_mode([_notes("Voelde zwaar")]) == FC.INITIAL_ANALYSIS

    def test_2b_alleen_coachfeedback(self):
        # Coach gaf net de eerste analyse; atleet reageerde nog niet → initial.
        assert FC.feedback_mode([_notes("Zwaar"), _coach("Netjes gelopen")]) == FC.INITIAL_ANALYSIS

    def test_3_coach_dan_athlete_reply(self):
        thread = [_notes("Zwaar"), _coach("Wat speelt er?"), _atleet("Slecht geslapen")]
        assert FC.feedback_mode(thread) == FC.FOLLOW_UP_REPLY

    def test_4_multiturn_eindigt_op_athlete(self):
        thread = [_coach("a"), _atleet("b"), _coach("c"), _atleet("d")]
        assert FC.feedback_mode(thread) == FC.FOLLOW_UP_REPLY

    def test_5_laatste_is_coach_geen_reply(self):
        thread = [_coach("a"), _atleet("b"), _coach("c")]
        assert FC.feedback_mode(thread) == FC.INITIAL_ANALYSIS

    def test_6_lege_athlete_reply_geen_fake_followup(self):
        # Een blanco/whitespace 'reply' telt niet als gesprekstobeurt → val terug op de
        # voorgaande relevante toestand (coach als laatste) → geen follow-up.
        thread = [_notes("Zwaar"), _coach("Wat speelt er?"), _atleet("   ")]
        assert FC.feedback_mode(thread) == FC.INITIAL_ANALYSIS

    def test_7_volgorde_bepaalt_niet_timestamp_maar_lijstorde(self):
        # De helper vertrouwt op de (chronologische) lijstvolgorde die de queue levert.
        thread = [_coach("q"), _atleet("a")]
        assert FC.feedback_mode(thread) == FC.FOLLOW_UP_REPLY

    def test_8_malformed_thread_veilige_fallback(self):
        assert FC.feedback_mode("niet-een-lijst") == FC.INITIAL_ANALYSIS
        assert FC.feedback_mode([None, 42, "x"]) == FC.INITIAL_ANALYSIS
        # dict zonder 'van'/'tekst' → veilige initial
        assert FC.feedback_mode([{"foo": "bar"}]) == FC.INITIAL_ANALYSIS

    def test_9_athlete_beantwoordt_klachtvraag(self):
        thread = [_coach("Hoe voelt de achillespees nu?"),
                  _atleet("Pees is rustig, alleen benen waren zwaar")]
        assert FC.feedback_mode(thread) == FC.FOLLOW_UP_REPLY


# ════════════════════════════════════════════════════════════════════════════
# 2. Thread parsing — build_thread is de ENE bron van de thread-vorm
# ════════════════════════════════════════════════════════════════════════════
class TestBuildThread:
    def test_is_athlete_comment_expliciet_veld(self):
        assert fs_client.is_athlete_comment({"is_athlete": True, "user_key": "C"}, "C") is True
        assert fs_client.is_athlete_comment({"is_athlete": False, "user_key": "X"}, "C") is False

    def test_is_athlete_comment_fallback_coachkey(self):
        assert fs_client.is_athlete_comment({"user_key": "C"}, "C") is False   # coach
        assert fs_client.is_athlete_comment({"user_key": "A"}, "C") is True    # atleet

    def test_post_notes_eerst_dan_comments(self):
        comments = [
            {"comment": "Wat speelt er?", "user_key": "C", "first_name": "Jip",
             "timestamp": "2026-08-12T10:00"},
            {"comment": "Slecht geslapen", "user_key": "A", "first_name": "Lisa",
             "timestamp": "2026-08-12T11:00"},
        ]
        thread = fs_client.build_thread(comments, "Voelde zwaar", "Lisa", coach_key="C")
        assert [m["van"] for m in thread] == ["atleet", "coach", "atleet"]
        assert thread[0]["_display"] is False and thread[0]["timestamp"] == ""
        assert thread[-1]["tekst"] == "Slecht geslapen"

    def test_lege_comment_wordt_overgeslagen(self):
        comments = [{"comment": "   ", "user_key": "A", "timestamp": "t"}]
        assert fs_client.build_thread(comments, "", "Lisa", coach_key="C") == []

    def test_geen_postnotes_geen_comments(self):
        assert fs_client.build_thread([], "", "Lisa", coach_key="C") == []

    def test_get_workout_thread_sorteert_chronologisch(self, monkeypatch):
        # Comments out-of-order aangeleverd → get_workout_thread sorteert op timestamp,
        # post_notes blijft vooraan.
        monkeypatch.setattr(fs_client, "get_coach_key", lambda: "C")
        monkeypatch.setattr(fs_client, "get_comments", lambda wk, ak: [
            {"comment": "later athlete", "user_key": "A", "timestamp": "2026-08-12T12:00"},
            {"comment": "eerder coach", "user_key": "C", "timestamp": "2026-08-12T09:00"},
        ])
        thread = fs_client.get_workout_thread("W", "A", "notes", "Lisa")
        assert [m["van"] for m in thread] == ["atleet", "coach", "atleet"]
        assert thread[1]["tekst"] == "eerder coach"          # chronologisch vóór de athlete-reply
        assert thread[2]["tekst"] == "later athlete"


# ════════════════════════════════════════════════════════════════════════════
# 3. Dispatch-routing — genereer kiest de juiste engine op de VERSE thread
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def routed(monkeypatch):
    """Isoleer genereer: no-op details/brein, controleerbare verse thread, recorders op
    beide engines. Yield (calls, set_fresh) — set_fresh(thread) bepaalt wat _refresh_thread
    (via get_workout_thread) teruggeeft."""
    import ai_feedback
    FC._cache.clear()
    monkeypatch.setattr(FC, "_ensure_details", lambda wid: None)
    monkeypatch.setattr(FC, "_brein_context", lambda w: "")
    calls = {"reply": 0, "feedback": 0, "reply_thread": None}
    monkeypatch.setattr(ai_feedback, "generate_reply",
                        lambda w, thread: calls.update(reply=calls["reply"] + 1,
                                                        reply_thread=thread) or "REPLY")
    monkeypatch.setattr(ai_feedback, "generate_feedback",
                        lambda w: calls.update(feedback=calls["feedback"] + 1) or "FEEDBACK")
    _box = {"fresh": None}

    def _set_fresh(thread):
        _box["fresh"] = thread
        monkeypatch.setattr(fs_client, "get_workout_thread",
                            lambda wk, ak, pn="", fn="": list(thread))
    yield calls, _set_fresh
    FC._cache.clear()


def _seed(wid="W1", **over):
    w = {"workout_key": wid, "athlete_key": "A", "athlete_first_name": "Lisa",
         "athlete_name": "Lisa T", "post_notes": "Voelde zwaar", "workout_type": "run",
         "thread": []}
    w.update(over)
    FC._cache[wid] = w
    return w


class TestDispatchRouting:
    def test_initial_geen_reply(self, routed):
        calls, set_fresh = routed
        _seed(thread=[])
        set_fresh([_notes("Zwaar"), _coach("Netjes gelopen")])   # laatste = coach
        assert FC.genereer("W1") == "FEEDBACK"
        assert calls["feedback"] == 1 and calls["reply"] == 0

    def test_followup_roept_reply_niet_feedback(self, routed):
        calls, set_fresh = routed
        _seed(thread=[])
        set_fresh([_coach("Wat speelt er?"), _atleet("Slecht geslapen")])
        assert FC.genereer("W1") == "REPLY"
        assert calls["reply"] == 1 and calls["feedback"] == 0
        # generate_reply krijgt de ACTUELE (verse) thread mee, laatste = athlete
        assert calls["reply_thread"][-1]["van"] == "atleet"

    def test_verse_athlete_comment_kantelt_naar_followup(self, routed):
        # Queue-thread was nog 'alleen coach' (stale); server heeft nu een athlete-reply.
        calls, set_fresh = routed
        _seed(thread=[_coach("Wat speelt er?")])                 # stale cache = initial
        set_fresh([_coach("Wat speelt er?"), _atleet("Zware benen door werk")])
        assert FC.genereer("W1") == "REPLY"
        assert calls["reply"] == 1 and calls["feedback"] == 0

    def test_nonrun_followup_ook_reply(self, routed):
        calls, set_fresh = routed
        _seed(thread=[], workout_type="bike")
        set_fresh([_coach("Hoe ging de rit?"), _atleet("Benen zwaar")])
        assert FC.genereer("W1") == "REPLY"
        assert calls["reply"] == 1


# ════════════════════════════════════════════════════════════════════════════
# 4. _refresh_thread — §9 verse thread-state, non-fataal
# ════════════════════════════════════════════════════════════════════════════
class TestRefreshThread:
    def test_leest_verse_thread(self, monkeypatch):
        fresh = [_coach("q"), _atleet("a")]
        monkeypatch.setattr(fs_client, "get_workout_thread",
                            lambda wk, ak, pn="", fn="": list(fresh))
        w = {"workout_key": "W", "athlete_key": "A", "thread": [_coach("q")]}
        FC._refresh_thread(w)
        assert [m["van"] for m in w["thread"]] == ["coach", "atleet"]

    def test_fs_fout_behoudt_cache(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("FS down")
        monkeypatch.setattr(fs_client, "get_workout_thread", _boom)
        cached = [_coach("q"), _atleet("a")]
        w = {"workout_key": "W", "athlete_key": "A", "thread": list(cached)}
        FC._refresh_thread(w)                                    # mag niet raisen
        assert w["thread"] == cached                            # cache intact

    def test_lege_verse_read_wist_gesprek_niet(self, monkeypatch):
        monkeypatch.setattr(fs_client, "get_workout_thread", lambda *a, **k: [])
        cached = [_coach("q"), _atleet("a")]
        w = {"workout_key": "W", "athlete_key": "A", "thread": list(cached)}
        FC._refresh_thread(w)
        assert w["thread"] == cached

    def test_geen_koppeling_geen_call(self, monkeypatch):
        called = {"n": 0}
        monkeypatch.setattr(fs_client, "get_workout_thread",
                            lambda *a, **k: called.update(n=called["n"] + 1) or [])
        w = {"workout_key": "", "athlete_key": "", "thread": []}
        FC._refresh_thread(w)
        assert called["n"] == 0


# ════════════════════════════════════════════════════════════════════════════
# 5. Acceptance (§11) — realistische end-to-end, vergeleken met Streamlit-semantiek
# ════════════════════════════════════════════════════════════════════════════
class TestAcceptanceE2E:
    """Workout met tempo/context; eerste coachfeedback met vraag 'wat speelt er?';
    atleet antwoordt dat zware benen door slechte nachtrust/werk kwamen; tweede generatie.
    PASS: mode=FOLLOW_UP, AI ziet primair de athlete-reply als laatste bericht, wordt
    expliciet geïnstrueerd de training niet opnieuw te analyseren en de vraag niet te
    herhalen; initial generation zonder reply blijft de bewezen analyse-prompt."""

    def _capture_create_message(self, monkeypatch):
        import ai_feedback
        captured = []

        class _Resp:
            def __init__(self, text):
                self.content = [type("X", (), {"text": text})()]

        def _fake(model, max_tokens, system, messages):
            captured.append({"system": system, "messages": messages})
            return _Resp("ok")

        monkeypatch.setattr(ai_feedback, "create_message", _fake)
        # Isoleer contextopbouw zodat we het gespreksgedrag toetsen, niet de run-parser.
        monkeypatch.setattr(ai_feedback, "_build_workout_context",
                            lambda wd: ("Training: tempoduurloop\nGepland: Z2→Z3", "Lisa"))
        return captured

    def _workout(self):
        return {"workout_key": "W", "athlete_key": "A", "athlete_first_name": "Lisa",
                "workout_type": "run", "post_notes": "Benen voelden zwaar"}

    def test_followup_reageert_op_reply_niet_heranalyse(self, monkeypatch):
        import ai_feedback
        captured = self._capture_create_message(monkeypatch)
        thread = [_notes("Benen voelden zwaar"),
                  _coach("Sterke tempo's! Wat speelt er, waardoor voelden de benen zwaar?"),
                  _atleet("Slecht geslapen deze week en druk op werk, benen waren daardoor zwaar")]
        # mode is deterministisch FOLLOW_UP
        assert FC.feedback_mode(thread) == FC.FOLLOW_UP_REPLY
        out = ai_feedback.generate_reply(self._workout(), thread)
        assert out == "ok"
        msgs = captured[-1]["messages"]
        # Multi-turn (achtergrond + coach + athlete), niet één analyse-prompt
        assert len(msgs) >= 3
        last = msgs[-1]
        assert last["role"] == "user"
        # De AI ziet de athlete-reply als laatste bericht (primair te beantwoorden)
        assert "slecht geslapen" in last["content"].lower()
        assert "werk" in last["content"].lower()
        # Expliciete follow-up-instructie: niet heranalyseren, vraag niet herhalen
        assert "niet opnieuw" in last["content"].lower()
        assert "reageer alleen" in last["content"].lower()
        # De eenmalige analyse-prompt van generate_feedback wordt hier NIET gebruikt
        joined = " ".join(m["content"] for m in msgs)
        assert "AANPAK:" not in joined

    def test_initial_zonder_reply_blijft_analyse(self, monkeypatch):
        import ai_feedback
        captured = self._capture_create_message(monkeypatch)
        # Zelfde workout, géén athlete-reply → initial pad ongewijzigd
        thread = [_notes("Benen voelden zwaar"), _coach("Wat speelt er?")]
        assert FC.feedback_mode(thread) == FC.INITIAL_ANALYSIS
        ai_feedback.generate_feedback(self._workout())
        msgs = captured[-1]["messages"]
        assert len(msgs) == 1                                   # één analyse-prompt
        assert "AANPAK:" in msgs[0]["content"]                 # de bewezen analyse-structuur

    def test_source_gap_followup_blijft_eerlijk(self, monkeypatch):
        # §8.10 — ontbrekende workoutcontext mag de follow-up niet breken; het gesprek
        # gaat door op de athlete-reply.
        import ai_feedback
        captured = self._capture_create_message(monkeypatch)
        monkeypatch.setattr(ai_feedback, "_build_workout_context",
                            lambda wd: ("Training: (weinig data beschikbaar)", "Lisa"))
        thread = [_coach("Hoe ging het?"), _atleet("Prima, alleen moe van werk")]
        out = ai_feedback.generate_reply(self._workout(), thread)
        assert out == "ok"
        assert "moe van werk" in captured[-1]["messages"][-1]["content"].lower()


# ════════════════════════════════════════════════════════════════════════════
# 6. Parity-guard — PWA-dispatchregel == Streamlit-dispatchregel (broncontrole)
# ════════════════════════════════════════════════════════════════════════════
class TestStreamlitParity:
    def test_streamlit_regel_ongewijzigd_aanwezig(self):
        src = open(os.path.join(_ROOT, "main.py")).read()
        # De bewezen Streamlit-regel die feedback_mode 1:1 spiegelt
        assert 'last_van == "atleet"' in src.replace("_last_van", "last_van")
        assert 'any(m.get("van") == "coach"' in src

    def test_feedback_mode_matcht_streamlit_op_matrix(self):
        # Repliceer de exacte Streamlit-expressie en vergelijk op een casusmatrix.
        def _streamlit(thread):
            last_van = thread[-1].get("van") if thread else None
            has_coach = any(m.get("van") == "coach" for m in thread)
            return bool(thread) and last_van == "atleet" and has_coach

        matrix = [
            [],
            [_notes("x")],
            [_notes("x"), _coach("c")],
            [_coach("c"), _atleet("a")],
            [_coach("a"), _atleet("b"), _coach("c"), _atleet("d")],
            [_coach("a"), _atleet("b"), _coach("c")],
        ]
        for thread in matrix:
            expect = FC.FOLLOW_UP_REPLY if _streamlit(thread) else FC.INITIAL_ANALYSIS
            assert FC.feedback_mode(thread) == expect, thread
