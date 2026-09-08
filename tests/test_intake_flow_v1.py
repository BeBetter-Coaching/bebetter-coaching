"""Intake als ingang naar de coachflow — Intake → atleet → centrale context → Schema.

Vóór deze build was de Intake-module een postbus: een inzending werd overgenomen als
LOSSE intake ('nieuw:naam') en daar hield het op. Dat de aanmelder al als atleet in
FinalSurge stond was in de inbox niet te zien, en na het overnemen wees niets de weg —
terwijl juist de koppelstap bepaalt of Schema en het Masterbrein de intake ooit zien
(die lezen op `user_key`, niet op 'nieuw:naam').

Deze tests leggen de nieuwe schakel vast ZONDER een tweede intakewaarheid: dezelfde
naam-matchregel als bij de losse intakes, dezelfde koppel-write, dezelfde evidence-keten.

De client-bewijzen (rendering, acties, routes) staan in tests/js/intake_flow.test.mjs.

    python3 -m pytest tests/test_intake_flow_v1.py -q
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "pwa")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest                                              # noqa: E402

import atleten_core                                        # noqa: E402
import fs_core                                             # noqa: E402
import intake_core                                         # noqa: E402
import intake_store                                        # noqa: E402
from brain import adapter                                  # noqa: E402

_APP = (_ROOT / "pwa" / "static" / "app.js").read_text(encoding="utf-8")
_API = (_ROOT / "pwa" / "api.py").read_text(encoding="utf-8")
VANDAAG = date(2026, 9, 8)

_ROSTER = [
    {"user_key": "uk-dom", "naam": "Dominique Slooff", "groep": "Dinsdag", "email": "d@x.nl"},
    {"user_key": "uk-jan", "naam": "Jan Jansen", "groep": "Woensdag", "email": "j@x.nl"},
]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Alle intake-stores naar tmp (lokale JSON, geen GitHub, geen productiedata)."""
    monkeypatch.setattr(intake_store, "_gh_token", lambda: "")
    for attr, naam in [
        ("_INTAKES_LOCAL", "intakes.json"),
        ("_INTAKE_ARCHIEF_LOCAL", "intakes_archief.json"),
        ("_INTAKE_INBOX_LOCAL", "intake_inbox.json"),
        ("_LAATSTE_INTAKE_LOCAL", "laatste_intakes.json"),
        ("_INTAKE_LINK_LOCAL", "intake_link.json"),
    ]:
        monkeypatch.setattr(intake_store, attr, str(tmp_path / naam), raising=False)
    return intake_store


@pytest.fixture
def fs(monkeypatch):
    """Een FinalSurge-roster zonder netwerk; telt hoe vaak hij gelezen wordt."""
    tel = {"n": 0}

    def _roster():
        tel["n"] += 1
        return list(_ROSTER)
    monkeypatch.setattr(fs_core, "heeft_token", lambda: True)
    monkeypatch.setattr(fs_core, "roster", _roster)
    return tel


def _inzending(store, naam="Dominique Slooff", **velden):
    ok, err = intake_core.public_submit({"naam": naam, "doel": "Halve marathon",
                                         "huidige_klachten": "", **velden})
    assert ok, err
    return intake_core.inbox_list()[0]["id"]


# ══════════════════════════════════════════════════════════════════════════════
# 1 — de inbox weet of deze aanmelder al atleet is (opt-in, één regel)
# ══════════════════════════════════════════════════════════════════════════════
class TestInboxAtleetbewust:
    def test_bestaande_atleet_wordt_herkend_als_kandidaat(self, store, fs):
        _inzending(store)
        rij = intake_core.inbox_list(match=True)[0]
        assert rij["suggestie"] == {"user_key": "uk-dom", "naam": "Dominique Slooff",
                                    "groep": "Dinsdag"}

    def test_onbekende_aanmelder_krijgt_geen_kandidaat(self, store, fs):
        _inzending(store, naam="Nieuwe Nieuweling")
        assert intake_core.inbox_list(match=True)[0]["suggestie"] is None

    def test_dubbelzinnige_naam_levert_geen_kandidaat(self, store, monkeypatch):
        """Zelfde regel als bij de losse intakes: alleen een EENDUIDIGE match telt.
        Bij twee naamgenoten kiest de coach zelf — nooit de app."""
        monkeypatch.setattr(fs_core, "heeft_token", lambda: True)
        monkeypatch.setattr(fs_core, "roster", lambda: [
            {"user_key": "a", "naam": "Jan Jansen"}, {"user_key": "b", "naam": "Jan Jansen"}])
        _inzending(store, naam="Jan Jansen")
        assert intake_core.inbox_list(match=True)[0]["suggestie"] is None

    def test_match_gebruikt_dezelfde_regel_als_de_losse_intakes(self):
        """Geen tweede matchimplementatie: één functie, twee ingangen."""
        bron = (_ROOT / "pwa" / "intake_core.py").read_text(encoding="utf-8")
        assert bron.count("_fs_suggestie(") == 2, "orphans + inbox delen dezelfde regel"
        assert "def _fs_suggestie" not in bron, "de regel hoort in atleten_core te blijven"

    def test_zonder_match_geen_roster_read(self, store, fs):
        """Home leest deze lijst als goedkoop, store-only praktijksignaal. Een
        FinalSurge-roster-read hoort daar niet in — vandaar dat de match opt-in is."""
        _inzending(store)
        intake_core.inbox_list()
        assert fs["n"] == 0, "de standaardlijst mag FinalSurge niet aanraken"
        intake_core.inbox_list(match=True)
        assert fs["n"] > 0

    def test_home_vraagt_de_match_niet_op(self):
        blok = _APP[_APP.index("Secundaire praktijk-signalen"):]
        regel = blok[blok.index('api("/api/intake/inbox'):][:60]
        assert "match" not in regel, regel

    def test_api_geeft_match_door(self):
        assert "def intake_inbox(match: int = 0)" in _API
        assert "intake.inbox_list(match=bool(match))" in _API


# ══════════════════════════════════════════════════════════════════════════════
# 2 — één sleutel-derivatie: de server zegt welke sleutel hij schreef
# ══════════════════════════════════════════════════════════════════════════════
class TestSleutel:
    def test_overnemen_schrijft_de_sleutel_die_de_api_teruggeeft(self, store):
        iid = _inzending(store)
        ok, err, naam = intake_core.inbox_take(iid)
        assert ok, err
        key = intake_core.intake_key(naam)
        assert key in intake_store.load_intakes(), "de gerapporteerde sleutel bestaat echt"
        assert key == "nieuw:dominique_slooff"

    def test_api_rapporteert_de_sleutel(self):
        assert 'intake.intake_key(naam) if ok else ""' in _API

    def test_client_leidt_de_sleutel_niet_zelf_af(self):
        """Een tweede afleiding in de client kan stil uiteenlopen met wat er is
        weggeschreven; de vervolgstap gebruikt daarom `r2.key` van de server."""
        assert "koppelIntake(r2.key, koppelAan)" in _APP
        assert '"nieuw:" +' not in _APP, "geen sleutelbouw in de client"


# ══════════════════════════════════════════════════════════════════════════════
# 3 — nieuwe aanmelding vs. reeds bestaande atleet, tot in de centrale context
# ══════════════════════════════════════════════════════════════════════════════
def _ctx(user_key):
    """De canonieke Schema/Masterbrein-context via het echte v2-pad, zonder FS-sweep."""
    state, raw = adapter.build_state(user_key, VANDAAG, gather_fn=lambda uk, today=None: adapter._light_intake_gather(uk))
    return adapter.to_legacy_context(state, raw, VANDAAG)


class TestNaarDeCentraleContext:
    def test_nieuwe_aanmelder_blijft_los_en_lekt_niet_naar_een_atleet(self, store, fs):
        """Nieuwe intake: overnemen maakt een LOSSE intake. Die hoort (nog) bij geen
        enkele user_key — geen willekeurige oude context erbij."""
        iid = _inzending(store, naam="Nieuwe Nieuweling", loopervaring="3 jaar")
        ok, _, naam = intake_core.inbox_take(iid)
        assert ok
        assert intake_core.intake_key(naam) in intake_store.load_intakes()
        assert [o["naam"] for o in intake_core.orphan_intakes()] == ["Nieuwe Nieuweling"]
        for uk in ("uk-dom", "uk-jan"):
            assert not (_ctx(uk).get("profile") or {}).get("loopervaring")

    def test_bestaande_atleet_overnemen_en_koppelen_vult_de_centrale_context(self, store, fs):
        """De volledige keten in één test: inbox → overnemen → koppelen → AthleteState.
        Vóór het koppelen ziet Schema/Masterbrein niets; erná de intake-kennis."""
        iid = _inzending(store, loopervaring="8 jaar", trainingsdagen="4",
                         wat_werkte="rustig opbouwen", blessurehistorie="hamstring 2024")
        rij = intake_core.inbox_list(match=True)[0]
        assert rij["suggestie"]["user_key"] == "uk-dom"

        ok, err, naam = intake_core.inbox_take(iid)
        assert ok, err
        assert not (_ctx("uk-dom").get("profile") or {}).get("loopervaring"), \
            "voorwaarde: een losse intake is nog onzichtbaar voor Schema"

        ok, err, _ = intake_core.link_intake(intake_core.intake_key(naam), "uk-dom")
        assert ok, err
        ctx = _ctx("uk-dom")
        assert ctx["profile"]["loopervaring"] == "8 jaar"
        assert ctx["profile"]["trainingsdagen"] == "4"
        assert ctx["training"]["reageerde_goed_op"] == "rustig opbouwen"
        assert ctx["health"]["blessurehistorie"] == "hamstring 2024"
        assert intake_core.orphan_intakes() == [], "hij staat niet meer los"
        assert intake_core.inbox_list() == [], "en niet meer in de inbox"

    def test_intakeklacht_levert_precies_een_klacht(self, store, fs):
        """Geen dubbele entries uit dezelfde bron: één intakemelding = één actuele
        klacht in de centrale context, niet twee (mention + groep)."""
        iid = _inzending(store, huidige_klachten="Pijn aan de achillespees")
        _, _, naam = intake_core.inbox_take(iid)
        intake_core.link_intake(intake_core.intake_key(naam), "uk-dom")
        klachten = (_ctx("uk-dom").get("health") or {}).get("actuele_klachten") or []
        assert len(klachten) == 1, klachten
        assert "achilles" in klachten[0]["tekst"].lower()

    def test_opnieuw_koppelen_verdubbelt_de_intake_niet(self, store, fs):
        """Twee inzendingen van dezelfde persoon achter elkaar: de laatste is de
        waarheid, de vorige wordt gearchiveerd — nooit twee levende intakes."""
        for tekst in ("5 jaar", "6 jaar"):
            iid = _inzending(store, loopervaring=tekst)
            _, _, naam = intake_core.inbox_take(iid)
            intake_core.link_intake(intake_core.intake_key(naam), "uk-dom")
        intakes = intake_store.load_intakes()
        assert [k for k in intakes if k.startswith("nieuw:")] == []
        assert intakes["uk-dom"]["loopervaring"] == "6 jaar"
        assert _ctx("uk-dom")["profile"]["loopervaring"] == "6 jaar"


# ══════════════════════════════════════════════════════════════════════════════
# 4 — één koppel-implementatie, gedeeld door beide ingangen
# ══════════════════════════════════════════════════════════════════════════════
class TestEenKoppelImplementatie:
    def test_atletendetail_delegeert_naar_de_gedeelde_functie(self):
        assert "async function koppelIntake(" in _APP
        assert "const doeKoppel = userKey => koppelIntake(nieuwKey, userKey);" in _APP
        assert _APP.count('jpost("/api/intake/koppel"') == 1, "één koppel-write in de client"

    def test_de_write_gebeurt_pas_na_een_expliciete_actie(self, store, fs):
        """Een naam-match koppelt nooit uit zichzelf: overnemen laat de intake los."""
        iid = _inzending(store)
        intake_core.inbox_take(iid)
        assert "uk-dom" not in intake_store.load_intakes()
        assert len(intake_core.orphan_intakes()) == 1

    def test_koppelen_ververst_de_gedeelde_leeslaag(self):
        blok = _API[_API.index("def intake_koppel("):]
        assert "athlete_read.invalidate(body.user_key)" in blok[:600]
