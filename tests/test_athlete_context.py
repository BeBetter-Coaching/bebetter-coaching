"""Masterbrein — athlete_context: recency/relevantie, ruisonderdrukking,
anti-hallucinatie, traceability. `assemble()` is puur → deterministisch testbaar.

Draaien met:  python3 -m pytest tests/ -q
"""

import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import athlete_context as AC

TODAY = date(2026, 8, 11)
def _d(n): return (TODAY - timedelta(days=n)).isoformat()


def _ctx(**over):
    raw = {"intake": {"doel": "10km sub 50", "trainingsdagen": "di/do"}, "intake_ts": _d(30)}
    raw.update(over)
    return AC.assemble("A", "Anna", raw, TODAY)


class TestRecencyKlachten:
    def test_recente_klacht_meegenomen(self):
        c = _ctx(notes=[{"datum": _d(3), "tekst": "Achilles weer gevoelig na tempo"}])
        klachten = c["health"]["actuele_klachten"]
        assert any("achilles" in k["tekst"].lower() for k in klachten)
        assert klachten[0]["status"] == "recent"

    def test_oude_losse_klacht_niet_standaard(self):
        # één losse melding van 200 dagen geleden → niet 'actueel', niet 'terugkerend'
        c = _ctx(notes=[{"datum": _d(200), "tekst": "kuit stijf na wedstrijd"}])
        assert not c["health"].get("actuele_klachten")
        assert not c["health"].get("terugkerend")

    def test_terugkerende_klacht_activeert_historie(self):
        c = _ctx(notes=[{"datum": _d(3), "tekst": "achilles zeurt"},
                        {"datum": _d(90), "tekst": "weer achilles"}])
        assert "achilles" in (c["health"].get("terugkerend") or [])

    def test_intake_klacht_verouderd_gemarkeerd(self):
        c = _ctx(intake={"doel": "x", "huidige_klachten": "hamstring"}, intake_ts=_d(200))
        k = [x for x in c["health"]["actuele_klachten"] if x["bron"] == "intake"][0]
        assert k["status"] == "mogelijk verouderd"


class TestTrainingHistory:
    def _log(self, weken_km):
        # weken_km: list van km per week (index 0 = deze week)
        log = []
        for wi, km in enumerate(weken_km):
            if km:
                log.append({"date": _d(wi * 7 + 1), "actual_km": km, "completed": True})
        return log

    def test_volume_en_frequentie(self):
        c = _ctx(training_log=self._log([10, 10, 10, 10, 0, 0, 0, 0]))
        assert c["training"]["km_per_week"] == 10.0
        assert c["training"]["runs_per_week"] == 1.0

    def test_onderbreking_recent_niet_getraind(self):
        # laatste 3 weken 0 km na actieve periode
        c = _ctx(training_log=self._log([0, 0, 0, 20, 20, 20, 20]))
        assert c["training"]["onderbreking"] and "niet getraind" in c["training"]["onderbreking"]

    def test_on_hold_telt_als_onderbreking(self):
        c = _ctx(on_hold={"since": _d(20), "reden": "knieblessure"})
        assert "on hold" in (c["training"].get("onderbreking") or "")


class TestLifestyleStructural:
    def test_slaap_werkdruk_blijven_geldig(self):
        c = _ctx(intake={"doel": "x", "slaap": "6-7 uur", "werkdruk": "Hoog",
                         "herstelcapaciteit": "Langzaam"}, intake_ts=_d(300))
        r = c["recovery"]
        assert r["slaap"] == "6-7 uur" and r["werkdruk_stress"] == "Hoog"
        assert r["herstelcapaciteit"] == "Langzaam"          # structureel, geen veroudering


class TestFeedbackSignals:
    def test_actief_belastingsignaal_meegenomen(self):
        c = _ctx(belasting={"ernst": "hoog", "signalen": ["omvang +40%"],
                            "_stand_datum": _d(0), "_afgehandeld": False})
        assert c["feedback"]["belasting_signaal"]["ernst"] == "hoog"

    def test_afgehandeld_signaal_niet_meegenomen(self):
        c = _ctx(belasting={"ernst": "hoog", "signalen": ["x"],
                            "_stand_datum": _d(0), "_afgehandeld": True})
        assert not c["feedback"].get("belasting_signaal")

    def test_verouderde_stand_niet_meegenomen(self):
        c = _ctx(belasting={"ernst": "hoog", "signalen": ["x"],
                            "_stand_datum": _d(30), "_afgehandeld": False})
        assert not c["feedback"].get("belasting_signaal")

    def test_recente_coach_observatie_wel_oude_niet(self):
        c = _ctx(notes=[{"datum": _d(5), "tekst": "sterk mentaal"},
                        {"datum": _d(120), "tekst": "oude observatie"}])
        obs = c["feedback"]["recente_coach_observaties"]
        assert len(obs) == 1 and "sterk" in obs[0]["tekst"]


class TestPromptEnAntiHallucinatie:
    def test_prompt_bevat_relevante_context(self):
        c = _ctx(notes=[{"datum": _d(3), "tekst": "achilles gevoelig"}],
                 belasting={"ernst": "hoog", "signalen": ["+40%"], "_stand_datum": _d(0), "_afgehandeld": False})
        txt = AC.to_prompt_text(AC.schema_projection(c))
        assert "achilles" in txt.lower() and "belasting hoog" in txt.lower()

    def test_geen_klachten_expliciet_negatief(self):
        c = _ctx()                                            # geen notes/belasting
        txt = AC.to_prompt_text(AC.schema_projection(c))
        assert "GEEN bekend" in txt                           # AI mag niets verzinnen

    def test_used_summary_geen_tekst(self):
        c = _ctx(notes=[{"datum": _d(3), "tekst": "achilles"}])
        u = AC.used_summary(c)
        assert u["active_complaints"] == 1 and u["recurring_complaints"] == 0
        # alleen booleans/ints, geen vrije tekst
        assert all(isinstance(v, (bool, int)) for v in u.values())


class TestUISections:
    def test_onbekend_gemarkeerd(self):
        c = _ctx()
        secties = AC.ui_sections(c)
        health = next(s for s in secties if s["titel"].startswith("Gezondheid"))
        assert health["onbekend"] is True
