"""Races Coachhulp v2 — context bij één race, een voorstel op expliciete actie, geen write.

De Races-basis (7-daagse actiewachtrij, één write, stale-protection, empty state) blijft
ongemoeid; die staat in tests/test_races_afhandeling_v1.py + tests/js/races_afhandeling.test.mjs.
Deze suite dekt wat erbij komt:

  • de coachcontext komt uit de GEDEELDE AthleteState — dezelfde bron als Workspace,
    Dossier en Feedback — en niet uit een tweede leespad;
  • klachten lopen uitsluitend via `adapter.actuele_klachten` (canoniek ACTIVE/RECENT),
    dus een historisch of puur terugkerend patroon komt hier NOOIT binnen;
  • een voorstel gebruikt echte racedata en echte context, verzint niets, en wordt
    nooit automatisch verstuurd of over bestaande coachtekst gezet.

De client-bewijzen (renderen, overnemen, geen write bij openen/genereren/sluiten) staan
in tests/js/races_coachhulp.test.mjs.

    python3 -m pytest tests/test_races_coachhulp_v2.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback                                          # noqa: E402
import athlete_read                                         # noqa: E402
import races_core as rc                                     # noqa: E402
from brain import adapter, projections                      # noqa: E402

TODAY = date.today()
_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js"), encoding="utf-8").read()
_API = open(os.path.join(_ROOT, "pwa", "api.py"), encoding="utf-8").read()
_RACES = open(os.path.join(_ROOT, "pwa", "races_core.py"), encoding="utf-8").read()


def _race(**kw):
    r = {"athlete_name": "Sanne de Vries", "athlete_first_name": "Sanne",
         "athlete_key": "uk-sanne", "workout_key": "W1",
         "workout_name": "Dam tot Damloop", "workout_date": (TODAY + timedelta(days=4)).isoformat(),
         "race_type": "10 km", "description": "", "comments": [], "wish_given": False}
    r.update(kw)
    return r


def _raw(klacht_dagen=(), doel="", km=None):
    log = [{"date": (TODAY - timedelta(days=d)).isoformat(), "post_notes": "Achillespees gevoelig.",
            "workout_key": f"w{d}", "completed": True, "actual_km": km or 10}
           for d in klacht_dagen]
    return {"intake": {"athlete_name": "Sanne de Vries", "doel": doel}, "intake_ts": TODAY.isoformat(),
            "notes": [], "profiel": "", "garmin": "", "on_hold": None, "labels": [],
            "belasting": None, "training_log": log}


@pytest.fixture
def race(monkeypatch):
    """Eén race in de lookup + een gestubde gedeelde state-read (geen FinalSurge, geen AI)."""
    rc._cache.clear()
    athlete_read.reset()

    def _zet(raw, **kw):
        rc._cache["W1"] = _race(**kw)
        athlete_read.reset()
        athlete_read.get_state("uk-sanne", TODAY, gather_fn=lambda uk, today=None: (raw, []))
        return "W1"
    return _zet


# ══════════════════════════════════════════════════════════════════════════════
# A — persoonlijke racecontext
# ══════════════════════════════════════════════════════════════════════════════
class TestARaceContext:
    def test_race_met_doel_en_context_toont_de_juiste_feiten(self, race):
        wid = race(_raw(doel="Onder de 50 minuten op de 10 km"),
                   description="Doel: onder de 50 minuten.")
        h = rc.coachhulp(wid)
        assert h["race"] == "Dam tot Damloop" and h["type"] == "10 km"
        assert h["dagen_tot"] == 4                            # lichte urgentie uit de bestaande datum
        assert h["voornaam"] == "Sanne" and h["atleet_key"] == "uk-sanne"
        assert h["beschrijving"] == "Doel: onder de 50 minuten."
        assert "50 minuten" in h["doel"]
        assert h["context_onzeker"] is False

    def test_historische_klacht_komt_niet_binnen(self, race):
        """Eén melding van ~1,5 maand terug is HISTORICAL — geen actuele aanleiding."""
        wid = race(_raw(klacht_dagen=(45,)))
        assert rc.coachhulp(wid)["klachten"] == []

    def test_terugkerend_zonder_recente_melding_komt_niet_binnen(self, race):
        """Twee meldingen, laatste 20 dagen terug → RECURRING maar niet ACTUEEL. Dat is
        achtergrond, geen aanleiding, en mag dus niet spontaan in de coachhulp staan —
        exact dezelfde grens als Feedback hanteert."""
        wid = race(_raw(klacht_dagen=(45, 20)))
        assert rc.coachhulp(wid)["klachten"] == []

    def test_actuele_klacht_mag_compact_zichtbaar_zijn(self, race):
        wid = race(_raw(klacht_dagen=(3,)))
        kl = rc.coachhulp(wid)["klachten"]
        assert len(kl) == 1 and kl[0]["area"] == "achilles"
        assert kl[0]["status"] == "ACTIVE" and kl[0]["laatst_dagen"] == 3

    def test_recente_klacht_telt_ook_als_actueel(self, race):
        wid = race(_raw(klacht_dagen=(15,)))
        assert [k["area"] for k in rc.coachhulp(wid)["klachten"]] == ["achilles"]

    def test_dezelfde_klachtwaarheid_als_feedback(self, race):
        """Geen tweede klachtselectie: Races en Feedback lezen één functie."""
        assert "actuele_klachten" in _RACES
        assert "_vind_klachten" not in _RACES and "COMPLAINT_RECENT" not in _RACES
        bron = open(os.path.join(_ROOT, "pwa", "brain", "adapter.py"), encoding="utf-8").read()
        assert '"complaint_new": [c["area"] for c in actuele_klachten(complaints)]' in bron

    def test_onbereikbare_context_wordt_als_onzeker_gemeld(self, race, monkeypatch):
        """Een gefaalde read is ONZEKER, nooit stil 'geen bijzonderheden'."""
        wid = race(_raw())

        def _stuk(*a, **k):
            raise RuntimeError("leeslaag stuk")
        monkeypatch.setattr(athlete_read, "get_state", _stuk)
        h = rc.coachhulp(wid)
        assert h["context_onzeker"] is True
        assert not h.get("klachten") and not h.get("doel")
        assert h["race"] == "Dam tot Damloop"                 # racefeiten blijven wel staan

    def test_onbekende_race_geeft_de_bestaande_melding(self):
        rc._cache.clear()
        with pytest.raises(ValueError) as e:
            rc.coachhulp("weg")
        assert "niet meer in beeld" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════════
# B — voorsteltekst
# ══════════════════════════════════════════════════════════════════════════════
class TestBVoorstel:
    def _vang(self, monkeypatch):
        """Vervangt ALLEEN de externe AI-grens; de contextopbouw draait echt."""
        gezien = {}

        def _fake(first_name, race_name, race_type, race_date, context=""):
            gezien.update(first_name=first_name, race_name=race_name, race_type=race_type,
                          race_date=race_date, context=context)
            return "Veel succes zaterdag, je bent er klaar voor."
        monkeypatch.setattr(ai_feedback, "generate_race_wish", _fake)
        return gezien

    def test_voorstel_gebruikt_echte_racedata(self, race, monkeypatch):
        gezien = self._vang(monkeypatch)
        wid = race(_raw())
        r = rc.voorstel(wid)
        assert r["tekst"] == "Veel succes zaterdag, je bent er klaar voor."
        assert gezien["first_name"] == "Sanne"
        assert gezien["race_name"] == "Dam tot Damloop" and gezien["race_type"] == "10 km"
        assert gezien["race_date"] == (TODAY + timedelta(days=4)).isoformat()

    def test_voorstel_krijgt_de_relevante_actuele_context(self, race, monkeypatch):
        gezien = self._vang(monkeypatch)
        wid = race(_raw(doel="Onder de 50 minuten", klacht_dagen=(3,)),
                   description="Vlak parcours, ga voor een PR.")
        r = rc.voorstel(wid)
        ctx = gezien["context"]
        assert "Onder de 50 minuten" in ctx
        assert "Vlak parcours" in ctx
        assert "achilles" in ctx
        assert "Geen diagnose" in ctx                         # medisch terughoudend meegegeven
        assert r["persoonlijk"] is True

    def test_voorstel_noemt_geen_oude_klacht(self, race, monkeypatch):
        gezien = self._vang(monkeypatch)
        wid = race(_raw(klacht_dagen=(45, 20)))
        rc.voorstel(wid)
        assert "achilles" not in gezien["context"]

    def test_zonder_context_blijft_het_voorstel_neutraal(self, race, monkeypatch):
        gezien = self._vang(monkeypatch)
        wid = race(_raw())
        r = rc.voorstel(wid)
        assert gezien["context"] == ""                        # niets verzonnen om te vullen
        assert r["persoonlijk"] is False

    def test_onzekere_context_vraagt_expliciet_om_neutraal(self, race, monkeypatch):
        gezien = self._vang(monkeypatch)
        wid = race(_raw())
        monkeypatch.setattr(athlete_read, "get_state",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stuk")))
        r = rc.voorstel(wid)
        assert "verzin geen voorbereiding" in gezien["context"]
        assert r["context_onzeker"] is True

    def test_geen_tweede_generatiesysteem(self):
        """Hergebruikt de bestaande, productie-bewezen race-wens-generator."""
        assert "ai_feedback.generate_race_wish(" in _RACES
        assert "create_message" not in _RACES and "SYSTEM_PROMPT" not in _RACES


# ══════════════════════════════════════════════════════════════════════════════
# C — geen automatische write
# ══════════════════════════════════════════════════════════════════════════════
class TestCGeenWrite:
    def test_context_en_voorstel_posten_nooit(self, race, monkeypatch):
        import fs_client

        def _nooit(*a, **k):
            raise AssertionError("post_comment aangeroepen zonder coachactie")
        monkeypatch.setattr(fs_client, "post_comment", _nooit)
        monkeypatch.setattr(ai_feedback, "generate_race_wish", lambda **kw: "Succes!")
        wid = race(_raw(doel="PR lopen"))
        rc.coachhulp(wid)
        rc.voorstel(wid)
        rc.coachhulp(wid)                                     # 'sluiten en opnieuw openen'

    def test_de_write_blijft_een_apart_expliciet_pad(self):
        assert _RACES.count("FS.post_comment(") == 1
        assert _API.count("races.plaats_wens(") == 1
        for fn in ("def coachhulp(", "def voorstel(", "def _atleetcontext(", "def _voorstel_context("):
            blok = _RACES[_RACES.index(fn):]
            blok = blok[:blok.index("\ndef ", 1)] if "\ndef " in blok[1:] else blok
            assert "post_comment" not in blok, fn

    def test_endpoints_zijn_lezend(self):
        assert '@app.get("/api/races/coachhulp")' in _API
        blok = _API[_API.index('def races_voorstel('):]
        blok = blok[:blok.index("\n@app.")]
        assert "races.voorstel(" in blok and "plaats_wens" not in blok


# ══════════════════════════════════════════════════════════════════════════════
# D — race met een bestaande wens
# ══════════════════════════════════════════════════════════════════════════════
class TestDBestaandeWens:
    def test_bestaande_wens_blijft_zichtbaar_in_de_coachhulp(self, race):
        wid = race(_raw(), wish_given=True,
                   comments=[{"is_athlete": False, "comment": "Heel veel succes zondag!"}])
        assert rc.coachhulp(wid)["wens"] == "Heel veel succes zondag!"

    def test_een_gegeven_wens_blijft_buiten_de_actiewachtrij(self, monkeypatch):
        import fs_client
        races = [_race(workout_key="A", wish_given=True,
                       comments=[{"is_athlete": False, "comment": "Succes!"}]),
                 _race(workout_key="B", athlete_key="uk-2", wish_given=False)]
        monkeypatch.setattr(fs_client, "get_token", lambda: "t")
        monkeypatch.setattr(fs_client, "get_upcoming_races", lambda days_ahead=42: list(races))
        open_lijst = rc.komende(days_ahead=rc.CHIP_DAGEN, alleen_zonder_wens=True)["items"]
        assert [i["id"] for i in open_lijst] == ["B"]
        alle = rc.komende()["items"]
        assert [(i["id"], i["wens_gegeven"], i["wens"]) for i in alle] == \
               [("A", True, "Succes!"), ("B", False, "")]

    def test_coachhulp_verandert_de_comment_semantiek_niet(self):
        """`Wens bijwerken` blijft de bekende residual: server-side ongewijzigd."""
        blok = _RACES[_RACES.index("def plaats_wens("):]
        assert "FS.post_comment(" in blok and "update" not in blok.lower()


# ══════════════════════════════════════════════════════════════════════════════
# E — atleetcontext / navigatie
# ══════════════════════════════════════════════════════════════════════════════
class TestEAtleetcontext:
    def test_de_racekaart_draagt_de_canonieke_atleet_id(self, monkeypatch):
        import fs_client
        monkeypatch.setattr(fs_client, "get_token", lambda: "t")
        monkeypatch.setattr(fs_client, "get_upcoming_races", lambda days_ahead=42: [_race()])
        assert rc.komende()["items"][0]["atleet_key"] == "uk-sanne"

    def test_navigatie_gebruikt_de_gedeelde_route_entry(self):
        """Geen eigen navigatie in Races: dezelfde chips als elke andere atleetpagina,
        en die schrijven `#<view>/<id>` — dus refresh-vast."""
        assert 'athleteNav("races", h.atleet_key)' in _APP
        nav = _APP[_APP.index("function athleteNav("):]
        nav = nav[:nav.index("\n}") + 2]
        assert "openAthleteModule(" in nav and "openWorkspace(" in nav
        assert "history.pushState" not in nav                 # routeschrijven blijft in de entries

    def test_geen_tweede_atleetselectie(self):
        blok = _APP[_APP.index("// ── COACHHULP"):]
        blok = blok[:blok.index("// Plaatsen van één race-wens")] if "// Plaatsen van één race-wens" in blok else blok
        for verboden in ("wsSel =", "dcSel =", "dossierSel =", "sbState ="):
            assert verboden not in blok, verboden


# ══════════════════════════════════════════════════════════════════════════════
# F — de bestaande Races-basis blijft staan
# ══════════════════════════════════════════════════════════════════════════════
class TestFBasisOngemoeid:
    def test_chip_venster_en_filter_ongewijzigd(self, monkeypatch):
        import fs_client
        monkeypatch.setattr(fs_client, "get_token", lambda: "t")
        monkeypatch.setattr(fs_client, "get_upcoming_races",
                            lambda days_ahead=42: [_race(workout_key="A"),
                                                   _race(workout_key="B", wish_given=True)])
        assert rc.CHIP_DAGEN == 7 and rc.CHIP_SCOPE == "7d"
        assert rc.chip_count() == 1

    def test_lege_en_ongekoppelde_stand_ongewijzigd(self, monkeypatch):
        import fs_client
        monkeypatch.setattr(fs_client, "get_token", lambda: "")
        assert rc.komende() == {"items": [], "fs": False}

    def test_plaats_wens_blijft_dezelfde_write(self, monkeypatch, race):
        import fs_client
        gepost = []
        monkeypatch.setattr(fs_client, "post_comment", lambda **kw: gepost.append(kw))
        monkeypatch.setattr(fs_client, "get_athletes", lambda: [])
        wid = race(_raw())
        assert rc.plaats_wens(wid, "Succes!") is True
        assert len(gepost) == 1 and gepost[0]["comment"] == "Succes!"
        with pytest.raises(ValueError):
            rc.plaats_wens(wid, "   ")                        # lege wens blijft geweigerd
        assert len(gepost) == 1

    def test_cache_blijft_begrensd(self):
        assert rc._CACHE_MAX == 400 and "_prune_cache()" in _RACES
