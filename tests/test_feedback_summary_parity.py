"""Feedback Summary Parity — herstel van de Streamlit-sessiesamenvatting in de PWA.

Kernprincipe: één coaching-handover over UITSLUITEND daadwerkelijk geposte feedback,
via exact de bewezen pure core `ai_feedback.generate_session_summary` — geen tweede
prompt, geen FinalSurge/Masterbrein-write, geen nieuwe permanente store. De sessielog is
workflow-state (client-side, in-memory).

    python3 -m pytest tests/test_feedback_summary_parity.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import fs_client
import feedback_core as FC


# ════════════════════════════════════════════════════════════════════════════
# 1. session_log_item — server-bevestigde identiteit ná een geslaagde post
# ════════════════════════════════════════════════════════════════════════════
class TestSessionLogItem:
    def _seed(self, wid="W1"):
        FC._cache[wid] = {"workout_key": wid, "athlete_key": "A",
                          "athlete_name": "Lisa Test", "workout_name": "Tempoduurloop"}

    def teardown_method(self):
        FC._cache.clear()

    def test_canonieke_vorm(self):
        self._seed("W1")
        it = FC.session_log_item("W1", "  Sterke tempo's!  ")
        assert it == {"athlete_name": "Lisa Test", "workout_name": "Tempoduurloop",
                      "workout_key": "W1", "feedback_text": "Sterke tempo's!"}

    def test_missende_cache_valt_terug(self):
        it = FC.session_log_item("Wx", "tekst")
        assert it["workout_key"] == "Wx" and it["workout_name"] == "Training"
        assert it["athlete_name"] == "" and it["feedback_text"] == "tekst"


# ════════════════════════════════════════════════════════════════════════════
# 2. _clean_summary_items — alleen echte, unieke posts; malformed eruit
# ════════════════════════════════════════════════════════════════════════════
class TestCleanItems:
    def test_dedup_op_workout_key(self):
        items = [
            {"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "a", "workout_key": "W1"},
            {"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "a (retry)", "workout_key": "W1"},
        ]
        out = FC._clean_summary_items(items)
        assert len(out) == 1                              # retry/dubbel telt niet dubbel

    def test_dedup_fallback_athlete_workout(self):
        items = [
            {"athlete_name": "Sem", "workout_name": "Interval", "feedback_text": "x"},
            {"athlete_name": "Sem", "workout_name": "Interval", "feedback_text": "y"},
        ]
        assert len(FC._clean_summary_items(items)) == 1

    def test_dropt_lege_en_malformed(self):
        items = [
            {"athlete_name": "", "workout_name": "W", "feedback_text": "x"},   # geen naam
            {"athlete_name": "Lisa", "workout_name": "W", "feedback_text": "   "},  # geen tekst
            None, 42, "str",                                                   # malformed
            {"athlete_name": "Bo", "workout_name": "W", "feedback_text": "echt"},
        ]
        out = FC._clean_summary_items(items)
        assert len(out) == 1 and out[0]["athlete_name"] == "Bo"

    def test_vorm_is_exact_de_core_velden(self):
        out = FC._clean_summary_items(
            [{"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "top", "workout_key": "W1"}])
        assert set(out[0].keys()) == {"athlete_name", "workout_name", "feedback_text"}


# ════════════════════════════════════════════════════════════════════════════
# 3. session_summary — hergebruikt de bewezen core, geen tweede prompt
# ════════════════════════════════════════════════════════════════════════════
class TestSessionSummary:
    def test_roept_core_met_schone_items(self, monkeypatch):
        import ai_feedback
        captured = {}
        monkeypatch.setattr(ai_feedback, "generate_session_summary",
                            lambda coach, items: captured.update(coach=coach, items=items) or "SAMENVATTING")
        items = [{"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "top", "workout_key": "W1"}]
        out = FC.session_summary("Jip", items)
        assert out == "SAMENVATTING"                      # verbatim resultaat van de core
        assert captured["coach"] == "Jip"
        assert captured["items"] == [{"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "top"}]

    def test_lege_log_geen_core_call(self, monkeypatch):
        import ai_feedback
        called = {"n": 0}
        monkeypatch.setattr(ai_feedback, "generate_session_summary",
                            lambda coach, items: called.update(n=called["n"] + 1) or "x")
        assert FC.session_summary("Jip", []) == ""
        assert called["n"] == 0

    def test_geen_finalsurge_write(self, monkeypatch):
        import ai_feedback
        monkeypatch.setattr(ai_feedback, "generate_session_summary", lambda c, i: "ok")
        def _boom(*a, **k):
            raise AssertionError("session_summary mag NOOIT naar FinalSurge schrijven")
        monkeypatch.setattr(fs_client, "post_comment", _boom)
        assert FC.session_summary("Jip", [{"athlete_name": "L", "workout_name": "W", "feedback_text": "t"}]) == "ok"

    def test_acceptance_alleen_geposte_items(self, monkeypatch):
        """§7: 3 posts + 1 draft (niet gepost) + 1 skip → de summary-log bevat exact de 3
        geposte items. Drafts/skips zitten simpelweg niet in de log die de client meestuurt."""
        import ai_feedback
        cap = {}
        monkeypatch.setattr(ai_feedback, "generate_session_summary",
                            lambda coach, items: cap.update(items=items) or "S")
        # De client stuurt UITSLUITEND geposte items mee (drafts/skips komen nooit in de log):
        posted_log = [
            {"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "top", "workout_key": "W1"},
            {"athlete_name": "Sem", "workout_name": "Interval", "feedback_text": "sterk", "workout_key": "W2"},
            {"athlete_name": "Bo", "workout_name": "Hersteltraining", "feedback_text": "rustig", "workout_key": "W3"},
        ]
        FC.session_summary("Jip", posted_log)
        assert [it["athlete_name"] for it in cap["items"]] == ["Lisa", "Sem", "Bo"]
        assert len(cap["items"]) == 3


# ════════════════════════════════════════════════════════════════════════════
# 4. PWA ↔ Streamlit parity — dezelfde input naar dezelfde core
# ════════════════════════════════════════════════════════════════════════════
class TestStreamlitParity:
    def test_zelfde_posts_zelfde_core_input(self, monkeypatch):
        # Streamlit bouwt per post {athlete_name, workout_name, feedback_text} en roept
        # generate_session_summary(coach, log). De PWA-core moet exact diezelfde lijst
        # doorgeven voor dezelfde geposte set.
        streamlit_log = [
            {"athlete_name": "Lisa Test", "workout_name": "Duurloop", "feedback_text": "top"},
            {"athlete_name": "Sem Jansen", "workout_name": "Interval", "feedback_text": "sterk"},
        ]
        pwa_log = [dict(it, workout_key=f"W{n}") for n, it in enumerate(streamlit_log)]  # PWA voegt alleen key toe
        import ai_feedback
        cap = {}
        monkeypatch.setattr(ai_feedback, "generate_session_summary",
                            lambda coach, items: cap.update(items=items) or "S")
        FC.session_summary("Jip", pwa_log)
        assert cap["items"] == streamlit_log             # identieke core-input


# ════════════════════════════════════════════════════════════════════════════
# 5. API-endpoints — /post geeft sessielog-item terug; /summary draait de core
# ════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def client(monkeypatch):
    from starlette.testclient import TestClient
    import api
    return TestClient(api.app)


class TestEndpoints:
    def teardown_method(self):
        FC._cache.clear()

    def test_post_geeft_sessielog_item(self, client, monkeypatch):
        FC._cache["W1"] = {"workout_key": "W1", "athlete_key": "A",
                           "athlete_name": "Lisa Test", "workout_name": "Duurloop"}
        monkeypatch.setattr(fs_client, "post_comment", lambda **kw: {"ok": True}, raising=False)
        monkeypatch.setattr(fs_client, "get_athletes", lambda: [], raising=False)
        monkeypatch.setattr(FC, "_home_invalidate_feedback", lambda: None)
        r = client.post("/api/feedback/post", json={"id": "W1", "tekst": "Sterke tempo's!"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["item"] == {"athlete_name": "Lisa Test", "workout_name": "Duurloop",
                                "workout_key": "W1", "feedback_text": "Sterke tempo's!"}

    def test_summary_endpoint_gebruikt_core(self, client, monkeypatch):
        import ai_feedback
        cap = {}
        monkeypatch.setattr(ai_feedback, "generate_session_summary",
                            lambda coach, items: cap.update(coach=coach, items=items) or "📋 Coaching update")
        items = [{"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "top", "workout_key": "W1"}]
        r = client.post("/api/feedback/summary", json={"coach": "Jip", "items": items})
        assert r.status_code == 200 and r.json()["tekst"].startswith("📋")
        assert cap["coach"] == "Jip" and len(cap["items"]) == 1

    def test_summary_leeg_is_400(self, client, monkeypatch):
        import ai_feedback
        monkeypatch.setattr(ai_feedback, "generate_session_summary", lambda c, i: "x")
        r = client.post("/api/feedback/summary", json={"coach": "Jip", "items": []})
        assert r.status_code == 400

    def test_ontbrekende_coach_geen_summary(self, client, monkeypatch):
        """Correctness-hardening: zonder coach-identiteit GEEN samenvatting onder een
        verzonnen naam — duidelijke 400, en de core wordt niet eens aangeroepen."""
        import ai_feedback
        called = {"n": 0}
        monkeypatch.setattr(ai_feedback, "generate_session_summary",
                            lambda c, i: called.update(n=called["n"] + 1) or "x")
        items = [{"athlete_name": "Lisa", "workout_name": "Duurloop", "feedback_text": "top", "workout_key": "W1"}]
        for payload in ({"coach": "", "items": items},          # lege coach
                        {"coach": "   ", "items": items},       # whitespace
                        {"items": items}):                      # coach ontbreekt volledig
            r = client.post("/api/feedback/summary", json=payload)
            assert r.status_code == 400
            assert "onbekend" in r.json()["err"].lower()
        assert called["n"] == 0                                 # core nooit aangeroepen zonder coach


# ════════════════════════════════════════════════════════════════════════════
# 6. Client-wiring (source-guards) — alleen na server-ok, dedup, share/copy/mail
# ════════════════════════════════════════════════════════════════════════════
class TestClientWiring:
    def _js(self):
        return open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()

    def _html(self):
        return open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()

    def test_append_alleen_na_send_success(self):
        js = self._js()
        # de append-CALL in fbSend staat vlak ná FB.sentSet.add (server-ok), niet in de fouttak
        i_ok = js.index("FB.sentSet.add(id); fbDraftClear(id)")
        i_app = js.index("fbSummaryAppend(r.item")           # de aanroep (niet de definitie)
        assert i_ok < i_app and (i_app - i_ok) < 200

    def test_dedup_op_workout_key(self):
        assert "FB.summaryLog.some(r => r.workout_key === rec.workout_key)" in self._js()

    def test_hidden_tot_minstens_een_post(self):
        assert "box.hidden = n < 1" in self._js()

    def test_coach_uit_ingelogde_coach_zonder_default(self):
        js = self._js()
        assert 'coach: ingelogdeCoach' in js                    # authenticated login-context
        assert 'ingelogdeCoach || "Jip"' not in js             # geen stille verzonnen-naam-default
        assert "if (!ingelogdeCoach) return melding(" in js    # duidelijke fout bij ontbrekende identiteit

    def test_whatsapp_en_mail_en_copy(self):
        js = self._js()
        assert "https://wa.me/?text=" in js
        assert "jip_vanlent@hotmail.com,Remco-groen@hotmail.com" in js   # bestaande Streamlit-ontvangers
        assert "navigator.clipboard?.writeText" in js
        assert "Coaching update" in js                    # subject-parity

    def test_html_panel_en_acties_aanwezig(self):
        html = self._html()
        for el in ("fb-summary", "fb-sum-gen", "fb-sum-out", "fb-sum-copy",
                   "fb-sum-wa", "fb-sum-mail", "fb-sum-regen"):
            assert f'id="{el}"' in html

    def test_summarylog_reset_bij_reload(self):
        # in-memory op FB → geen localStorage/sessionStorage-persistentie (Streamlit-sessieparity)
        js = self._js()
        assert "summaryLog: []" in js
        assert "localStorage.setItem(\"fb_summary" not in js and "sessionStorage" not in js.split("summaryLog")[1][:400]
