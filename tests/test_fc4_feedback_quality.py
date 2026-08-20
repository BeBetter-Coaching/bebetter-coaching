"""FC-4 — Feedback AI quality/register (bron-fix in prompts/examples/guards, geen string-hacks).

Bewijst dat de kwaliteitsissues bij de BRON zijn opgelost: geen wrapping-quotes-voorbeelden,
expliciete no-wrapping/register/anti-echo/affirmatie-guards symmetrisch in generate_feedback
én generate_reply, en GEEN generieke output-cleanup voor quotes/register/echo/praise. De
deterministische FC-2/FC-3-waarheid en de conversation-dispatch blijven ongewijzigd.

LLM-output is probabilistisch → we toetsen het PROMPT-contract exact + gedrag met mocked
create_message; geen brittle tests op één exacte volzin.

    python3 -m pytest tests/test_fc4_feedback_quality.py -q
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback


class _Resp:
    def __init__(self, text):
        self.content = [type("X", (), {"text": text})()]


def _capture(monkeypatch, out_text="ok"):
    calls = []
    monkeypatch.setattr(ai_feedback, "create_message",
                        lambda **kw: calls.append(kw) or _Resp(out_text))
    return calls


def _run_wd():
    return {"athlete_name": "Lisa T", "athlete_first_name": "Lisa", "workout_name": "Duurloop",
            "post_notes": "", "workout_key": "W", "athlete_key": "A", "workout_type": "run",
            "workout_date": "2026-08-20", "details": {}}


def _nonrun_wd():
    return {"athlete_name": "Sem J", "athlete_first_name": "Sem", "workout_name": "Kracht",
            "post_notes": "", "workout_key": "W", "athlete_key": "A", "workout_type": "strength",
            "workout_date": "2026-08-20", "details": {}}


# ════════════════════════════════════════════════════════════════════════════
# A/B/E — prompt-contract source-guards (exact waar mogelijk)
# ════════════════════════════════════════════════════════════════════════════
class TestPromptContracts:
    SP = ai_feedback.SYSTEM_PROMPT

    def test_1_voorbeelden_zonder_wrapping_quotes(self):
        # de vier voorbeelden staan niet meer tussen aanhalingstekens
        assert '"Helemaal prima' not in self.SP
        assert '"Mooi constant gelopen' not in self.SP
        assert "Helemaal prima. Kijkend" in self.SP        # tekst nog aanwezig, kaal
        # geen enkele VOORBEELD-regel begint met een aanhalingsteken
        for blok in self.SP.split("VOORBEELD")[1:]:
            eerste = blok.split(":", 1)[-1].lstrip()
            assert not eerste.startswith('"'), eerste[:40]

    def test_2_no_wrapping_guard_aanwezig(self):
        assert "GEEN AANHALINGSTEKENS OM DE BOODSCHAP" in self.SP
        assert "niet tussen aanhalingstekens" in self.SP

    def test_3_geen_globale_quote_strip_in_cleanup(self):
        # _clean_text mag legitieme quotes NOOIT strippen (geen output-hack)
        assert ai_feedback._clean_text('"hallo"') == '"hallo"'
        assert ai_feedback._clean_text('Je zei "zwaar" en dat klopt') == 'Je zei "zwaar" en dat klopt'
        src = open(os.path.join(_ROOT, "ai_feedback.py")).read()
        cleanbody = src.split("def _clean_text", 1)[1].split("def ", 1)[0]
        assert "strip('\"" not in cleanbody and 'strip("\\"' not in cleanbody

    def test_4_netjes_gereden_niet_geseed(self):
        # in de VOORBEELDEN (die het model imiteert) staat geen 'gereden'/'netjes gereden'
        voorbeelden = self.SP.split("STIJLREGELS", 1)[0]
        assert "gereden" not in voorbeelden
        assert "netjes" not in voorbeelden                  # stock-affirmatie 'netjes' uit voorbeeld weg
        assert "gelopen" in voorbeelden                     # correct hardloopwerkwoord blijft
        assert "NATUURLIJK SPORTREGISTER" in self.SP        # en een expliciete registerregel

    def test_7_registerregel_verbiedt_gereden(self):
        assert 'NOOIT "gereden"' in self.SP
        assert "Vermijd stopwoord-frases" in self.SP

    def test_8_affirmatie_dosering(self):
        assert "DOSEER COMPLIMENTEN" in self.SP
        assert "niet elke boodschap met een verplicht compliment" in self.SP
        assert "nooit koud of afstandelijk" in self.SP      # geen koude toon

    def test_nonrun_system_heeft_guards(self):
        ns = ai_feedback._NONRUN_SYSTEM
        assert "niet tussen aanhalingstekens" in ns
        assert "parafraseer het niet" in ns
        assert 'geen "je liep' in ns                        # non-run niet als run framen


# ════════════════════════════════════════════════════════════════════════════
# C/D — anti-echo symmetrisch in beide generators
# ════════════════════════════════════════════════════════════════════════════
class TestAntiEchoSymmetry:
    def test_5_generate_feedback_heeft_anti_echo(self, monkeypatch):
        calls = _capture(monkeypatch)
        monkeypatch.setattr(ai_feedback, "_build_workout_context", lambda wd: ("CTX", "Lisa"))
        ai_feedback.generate_feedback(_run_wd())
        prompt = calls[-1]["messages"][0]["content"]
        assert "parafraseer het niet uitgebreid terug" in prompt
        assert "niet tussen aanhalingstekens" in prompt
        assert calls[-1]["system"] is ai_feedback.SYSTEM_PROMPT

    def test_6_generate_reply_behoudt_anti_echo(self, monkeypatch):
        calls = _capture(monkeypatch)
        monkeypatch.setattr(ai_feedback, "_build_workout_context", lambda wd: ("CTX", "Lisa"))
        thread = [{"van": "coach", "tekst": "wat speelt er?"},
                  {"van": "atleet", "tekst": "slecht geslapen door werk, benen zwaar"}]
        ai_feedback.generate_reply(_run_wd(), thread)
        last = calls[-1]["messages"][-1]["content"]
        assert "parafraseer" in last and "niet uitgebreid terug" in last
        assert "niet tussen aanhalingstekens" in last
        assert len(calls[-1]["messages"]) >= 3             # reply-pad (multi-turn), geen reanalyse

    def test_beide_generators_delen_systeem_en_guards(self, monkeypatch):
        calls = _capture(monkeypatch)
        monkeypatch.setattr(ai_feedback, "_build_workout_context", lambda wd: ("CTX", "Lisa"))
        ai_feedback.generate_feedback(_run_wd())
        ai_feedback.generate_reply(_run_wd(), [{"van": "coach", "tekst": "q"},
                                               {"van": "atleet", "tekst": "moe"}])
        assert calls[0]["system"] is ai_feedback.SYSTEM_PROMPT
        assert calls[1]["system"] is ai_feedback.SYSTEM_PROMPT


# ════════════════════════════════════════════════════════════════════════════
# 7 (register) — run vs non-run register blijft correct
# ════════════════════════════════════════════════════════════════════════════
class TestRegister:
    def test_run_gebruikt_run_systeem(self, monkeypatch):
        calls = _capture(monkeypatch)
        monkeypatch.setattr(ai_feedback, "_build_workout_context", lambda wd: ("CTX", "Lisa"))
        ai_feedback.generate_feedback(_run_wd())
        assert calls[-1]["system"] is ai_feedback.SYSTEM_PROMPT

    def test_nonrun_gebruikt_nonrun_systeem_niet_geforceerd_gelopen(self, monkeypatch):
        calls = _capture(monkeypatch)
        monkeypatch.setattr(ai_feedback, "_build_nonrun_context", lambda wd: ("CTX", "Sem"))
        ai_feedback.generate_feedback(_nonrun_wd())
        assert calls[-1]["system"] is ai_feedback._NONRUN_SYSTEM
        prompt = calls[-1]["messages"][0]["content"]
        assert "geen run-termen" in prompt                  # non-run niet als hardlopen framen


# ════════════════════════════════════════════════════════════════════════════
# F — deterministische FC-2/FC-3-waarheid ongewijzigd; H — geen cleanup-hacks
# ════════════════════════════════════════════════════════════════════════════
class TestNoContentRegression:
    SP = ai_feedback.SYSTEM_PROMPT

    def test_9_fc2_zoneregels_intact(self):
        assert "BUITEN de persoonlijke zones" in self.SP    # out-of-range blijft feit
        assert 'HARTSLAG ONDER TARGET ≠ "HARDER LOPEN"' in self.SP
        assert "BLOK-ANALYSE" in self.SP

    def test_10_fc3_event_regels_intact(self):
        assert "reken de tijd tot een event NOOIT zelf uit" in self.SP
        assert "Bekende afspraak" in self.SP

    def test_8_conversation_dispatch_unchanged(self):
        import feedback_core as FC
        assert FC.feedback_mode([]) == FC.INITIAL_ANALYSIS
        assert FC.feedback_mode([{"van": "coach", "tekst": "q"},
                                 {"van": "atleet", "tekst": "a"}]) == FC.FOLLOW_UP_REPLY

    def test_clean_text_alleen_streepjes_whitespace(self):
        # bestaande technische cleanup blijft (streepjes → komma), quotes/register/echo niet
        assert ai_feedback._clean_text("goed — sterk") == "goed, sterk"
        assert ai_feedback._clean_text('"netjes gereden"') == '"netjes gereden"'  # niet weggepoetst


# ════════════════════════════════════════════════════════════════════════════
# J — production-equivalent acceptance (mocked)
# ════════════════════════════════════════════════════════════════════════════
class TestAcceptance:
    def test_scenario1_geen_geforceerde_echo(self, monkeypatch):
        calls = _capture(monkeypatch)
        monkeypatch.setattr(ai_feedback, "_build_workout_context", lambda wd: ("CTX", "Lisa"))
        wd = dict(_run_wd(), post_notes="Slecht geslapen door werk, benen zwaar")
        ai_feedback.generate_feedback(wd)
        prompt = calls[-1]["messages"][0]["content"]
        assert "VAT het niet eerst samen en parafraseer het niet uitgebreid terug" in prompt

    def test_scenario2_geen_wrapping_quote_instructie(self, monkeypatch):
        calls = _capture(monkeypatch)
        monkeypatch.setattr(ai_feedback, "_build_workout_context", lambda wd: ("CTX", "Lisa"))
        ai_feedback.generate_feedback(_run_wd())
        sys_p = calls[-1]["system"]
        assert "GEEN AANHALINGSTEKENS OM DE BOODSCHAP" in sys_p
        assert "niet tussen aanhalingstekens" in calls[-1]["messages"][0]["content"]

    def test_scenario3_hardloopregister(self, monkeypatch):
        calls = _capture(monkeypatch)
        monkeypatch.setattr(ai_feedback, "_build_workout_context", lambda wd: ("CTX", "Lisa"))
        ai_feedback.generate_feedback(_run_wd())
        sys_p = calls[-1]["system"]
        assert 'NOOIT "gereden"' in sys_p                    # register verbiedt het fietswerkwoord
        assert "loopwoorden" in sys_p
        assert "gereden" not in sys_p.split("STIJLREGELS", 1)[0]   # niet in de voorbeelden
