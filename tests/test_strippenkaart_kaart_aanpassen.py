"""Strippenkaart: kaartgrootte achteraf aanpassen, 10 ↔ 20 (11 sep 2026).

Alleen `totaal` wijzigt. `gebruikt`, `historie`, `laatste_batch` en de rest van de kaart blijven
exact staan, zodat ook de groepsafboeking en 'ongedaan maken' daarna gewoon werken.

    python3 -m pytest tests/test_strippenkaart_kaart_aanpassen.py -q
"""
import copy
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import intake_store                                     # noqa: E402
import strippen_core as core                            # noqa: E402


class _Store:
    def __init__(self, kaarten):
        self.data, self.writes = kaarten, 0

    def load(self):
        return copy.deepcopy(self.data)

    def save(self, d):
        self.writes += 1
        self.data = copy.deepcopy(d)
        return True, ""


def _kaart(totaal, gebruikt, **extra):
    k = {"totaal": totaal, "gebruikt": gebruikt, "telefoon": "0612345678",
         "historie": ["2026-09-%02d" % (i + 1) for i in range(gebruikt)], "aangemaakt": "2026-06-01"}
    k.update(extra)
    return k


@pytest.fixture
def store(monkeypatch):
    s = _Store({
        "Anna Bos": _kaart(10, 3),
        "Bram Willems": _kaart(20, 7, laatste_batch={"id": "b1", "gebruikt_na": 7, "datum": "2026-09-07"}),
        "Cas de Wit": _kaart(20, 12),
    })
    monkeypatch.setattr(intake_store, "load_strippenkaarten", s.load)
    monkeypatch.setattr(intake_store, "save_strippenkaarten", s.save)
    core._IDEMPOTENT.clear()
    return s


def _view(naam):
    return next(k for k in core.list_kaarten() if k["naam"] == naam)


class TestGrootte:
    def test_10_naar_20_behoudt_gebruikt(self, store):
        ok, err, res = core.kaart_grootte("Anna Bos", 20, 10, 3)
        assert ok, err
        assert res["kaart"]["gebruikt"] == 3 and res["kaart"]["totaal"] == 20 and res["kaart"]["rest"] == 17

    def test_20_naar_10_behoudt_gebruikt(self, store):
        ok, err, res = core.kaart_grootte("Bram Willems", 10, 20, 7)
        assert ok, err
        assert (res["kaart"]["gebruikt"], res["kaart"]["totaal"], res["kaart"]["rest"]) == (7, 10, 3)

    def test_alleen_totaal_verandert_de_rest_blijft_exact(self, store):
        voor = copy.deepcopy(store.data["Bram Willems"])
        core.kaart_grootte("Bram Willems", 10, 20, 7)
        na = store.data["Bram Willems"]
        assert na.pop("totaal") == 10 and voor.pop("totaal") == 20
        assert na == voor                        # historie, laatste_batch, telefoon, aangemaakt

    def test_20_naar_10_geblokkeerd_bij_meer_dan_10_gebruikt(self, store):
        ok, err, res = core.kaart_grootte("Cas de Wit", 10, 20, 12)
        assert not ok and res["conflict"] == "te_klein" and "12" in err
        assert store.writes == 0 and store.data["Cas de Wit"]["totaal"] == 20

    def test_precies_10_gebruikt_mag_wel_naar_10(self, store):
        store.data["Cas de Wit"]["gebruikt"] = 10
        ok, _, res = core.kaart_grootte("Cas de Wit", 10, 20, 10)
        assert ok and res["kaart"]["rest"] == 0

    def test_geen_wijziging_als_de_kaart_al_die_grootte_heeft(self, store):
        ok, err, res = core.kaart_grootte("Anna Bos", 10, 10, 3)
        assert ok and res.get("ongewijzigd") is True and store.writes == 0

    def test_stale_stand_overschrijft_niets(self, store):
        # De coach zag 3 gebruikt; intussen is er elders nog een strip afgeboekt.
        store.data["Anna Bos"]["gebruikt"] = 4
        ok, err, res = core.kaart_grootte("Anna Bos", 20, 10, 3)
        assert not ok and res["conflict"] == "stale" and store.writes == 0
        ok, err, res = core.kaart_grootte("Anna Bos", 20, 20, 4)     # totaal elders al gewijzigd
        assert not ok and res["conflict"] == "stale"

    def test_alleen_10_of_20(self, store):
        for fout in (15, 0, -10, "twintig", None):
            ok, _, _ = core.kaart_grootte("Anna Bos", fout, 10, 3)
            assert not ok, fout
        assert store.writes == 0

    def test_onbekende_kaart(self, store):
        ok, _, res = core.kaart_grootte("Onbekend", 20)
        assert not ok and res["conflict"] == "onbekend"

    def test_refresh_toont_de_nieuwe_grootte(self, store):
        core.kaart_grootte("Anna Bos", 20, 10, 3)
        v = _view("Anna Bos")
        assert (v["totaal"], v["gebruikt"], v["rest"]) == (20, 3, 17)


class TestDaarnaWerktAllesNog:
    def test_batch_afboeken_rekent_met_de_nieuwe_grootte(self, store):
        core.kaart_grootte("Anna Bos", 20, 10, 3)
        ok, err, res = core.afboeken_batch(["Anna Bos"], {"Anna Bos": 3}, "c1")
        assert ok, err
        d = res["deelnemers"][0]
        assert (d["gebruikt"], d["totaal"], d["rest"]) == (4, 20, 16)
        assert "nog 16 van je 20" in d["bericht"]

    def test_undo_van_de_laatste_batch_blijft_werken_na_aanpassen(self, store):
        ok, _, res = core.afboeken_batch(["Anna Bos"], {"Anna Bos": 3}, "c2")
        core.kaart_grootte("Anna Bos", 20, 10, 4)
        ok, err, terug = core.batch_terug(res["batch_id"])
        assert ok, err
        v = _view("Anna Bos")
        assert (v["gebruikt"], v["totaal"], v["rest"]) == (3, 20, 17)

    def test_de_route_valideert_via_de_server(self, store):
        from fastapi.testclient import TestClient
        import api
        c = TestClient(api.app)
        r = c.post("/api/kaarten/Anna Bos/grootte",
                   json={"totaal": 20, "verwacht_totaal": 10, "verwacht_gebruikt": 3}).json()
        assert r["ok"] and r["kaart"]["rest"] == 17
        r = c.post("/api/kaarten/Cas de Wit/grootte",
                   json={"totaal": 10, "verwacht_totaal": 20, "verwacht_gebruikt": 12}).json()
        assert r["ok"] is False and r["conflict"] == "te_klein"
        assert store.data["Cas de Wit"]["totaal"] == 20
