"""Trainingsweekend Vakantiehuis de Kraanvogels v1 (14 sep 2026).

Wat hier vastligt is de BELOFTE, niet de vorm:
- Openbaar blijft de inschrijving dicht tot beheer haar opent, en openen kan pas als
  prijs, aanbetaling, betaaltermijn en voorwaarden zijn ingevuld (de code verzint niets).
- Tim komt met zijn sessie op de server NERGENS anders dan weekendbeheer — getest over
  álle geregistreerde routes, dus ook routes die later bijkomen.
- Openbare bezoekers zien nooit deelnemers en nooit iets buiten de kosten-whitelist.
- Een inschrijving bewaart wat de deelnemer accepteerde, en dat blijft staan.
- Niets hiervan maakt een coachingatleet aan.

    python3 -m pytest tests/test_trainingsweekend_v1.py -q
"""
import copy
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

from fastapi.routing import APIRoute                   # noqa: E402
from fastapi.testclient import TestClient              # noqa: E402

import api                                              # noqa: E402
import intake_store                                     # noqa: E402
import weekend_core as W                                # noqa: E402

_STATIC = os.path.join(_ROOT, "pwa", "static")


class _Store:
    def __init__(self):
        self.data, self.writes, self.kapot = {}, 0, False

    def load(self):
        if self.kapot:
            raise RuntimeError("GitHub API: 502")
        return copy.deepcopy(self.data)

    def save(self, d):
        self.writes += 1
        self.data = copy.deepcopy(d)
        return True, ""


def _verboden(*a, **k):
    raise AssertionError("weekendmodule mag geen coaching-/intakedata schrijven")


@pytest.fixture
def store(monkeypatch):
    s = _Store()
    monkeypatch.setattr(W, "_load", s.load)
    monkeypatch.setattr(W, "_save", s.save)
    for naam in dir(intake_store):                       # geen enkele andere store mag geraakt worden
        if naam.startswith("save_") and naam != "save_weekend":
            monkeypatch.setattr(intake_store, naam, _verboden)
    W.reset_cache()
    yield s
    W.reset_cache()


@pytest.fixture(autouse=True)
def _schone_logintellers():
    api._LOGIN_FOUTEN.clear()
    yield
    api._LOGIN_FOUTEN.clear()


@pytest.fixture
def slot(monkeypatch):
    """Productie-achtig: login aan, Tim heeft een eigen wachtwoord."""
    monkeypatch.setattr(api, "_APP_PASSWORD", "coach-wachtwoord")
    monkeypatch.setattr(api, "_WEEKEND_TIM_PASSWORD", "tim-wachtwoord")


def _c():
    return TestClient(api.app)                           # vers: geen cookies van een vorige identiteit


def _token(wie, pw):
    r = _c().post("/api/login", json={"wie": wie, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _vaststellen(prijs=24900, aanbetaling=5000, termijn="Fictieve betaaltermijn (test)",
                 voorwaarden="Fictieve voorwaarden (test)"):
    versie = W.beheer_overzicht()["instellingen"]["voorwaarden_versie"]
    return W.instellingen_opslaan({"deelnemersprijs_cent": prijs, "aanbetaling_cent": aanbetaling,
                                   "betaaltermijn": termijn, "voorwaarden": voorwaarden,
                                   "verwacht_versie": versie}, "Jip")


def _deelnemer(**extra):
    d = {"naam": "Fictieve Deelnemer", "email": "fictief@example.com", "telefoon": "06 12345678",
         "betaalkeuze": "aanbetaling", "bevestig_deelname": True, "akkoord_voorwaarden": True}
    d.update(extra)
    return d


def _fout(fn):
    with pytest.raises(W.WeekendFout) as e:
        fn()
    return e.value


# ══ Openbaar: dicht, en nooit meer dan de whitelist ═════════════════════════
class TestOpenbaar:
    def test_standaard_dicht_met_de_afgesproken_tekst(self, store):
        body = _c().get("/api/weekend").json()
        assert body["open"] is False and body["formulier"] is False
        assert body["melding"] == "Inschrijving opent binnenkort — definitieve informatie volgt"
        assert set(body) == {"evenement", "open", "testmodus", "formulier", "melding"}

    def test_dicht_toont_ook_vastgestelde_kosten_niet(self, store):
        _vaststellen()
        body = _c().get("/api/weekend").json()
        assert "kosten" not in body and "249" not in str(body)

    def test_openen_kan_niet_zonder_alle_kosten_en_voorwaarden(self, store):
        e = _fout(lambda: W.inschrijving_open_zetten(True, "Jip"))
        assert e.status == 409 and e.extra["ontbreekt"] == ["deelnemersprijs", "aanbetaling", "betaaltermijn", "voorwaarden"]
        _vaststellen(termijn="")
        assert _fout(lambda: W.inschrijving_open_zetten(True, "Jip")).extra["ontbreekt"] == ["betaaltermijn"]
        assert _c().get("/api/weekend").json()["open"] is False

    def test_open_toont_precies_de_deelnemerskosten(self, store):
        _vaststellen()
        W.inschrijving_open_zetten(True, "Jip")
        W.reset_cache()
        body = _c().get("/api/weekend").json()
        assert body["open"] is True and body["melding"] == ""
        assert set(body["kosten"]) == {"deelnemersprijs_cent", "aanbetaling_cent", "betaaltermijn",
                                       "voorwaarden", "voorwaarden_versie"}
        assert body["kosten"]["deelnemersprijs_cent"] == 24900

    def test_openbaar_inschrijven_dicht_wordt_geweigerd_en_niets_opgeslagen(self, store):
        _vaststellen()
        r = _c().post("/api/weekend/inschrijven", json=_deelnemer(voorwaarden_versie=1))
        assert r.status_code == 403
        assert store.data.get("inschrijvingen", {}) == {}

    def test_openbare_responses_bevatten_nooit_deelnemers(self, store):
        _vaststellen()
        W.inschrijving_open_zetten(True, "Jip")
        assert _c().post("/api/weekend/inschrijven", json=_deelnemer(voorwaarden_versie=1)).status_code == 200
        W.reset_cache()
        for url in ("/api/weekend", "/api/weekend?test=1"):
            tekst = _c().get(url).text
            assert "fictief@example.com" not in tekst and "Fictieve Deelnemer" not in tekst and "12345678" not in tekst

    def test_paginas_zijn_openbaar_beheer_api_niet(self, store, slot):
        assert _c().get("/weekend").status_code == 200
        assert _c().get("/weekend/beheer").status_code == 200
        assert _c().get("/api/weekend/beheer").status_code == 401

    def test_openbare_broncode_bevat_geen_bedragen_of_begroting(self):
        for naam in ("weekend.html", "weekend.js", "weekend.css"):
            src = open(os.path.join(_STATIC, naam), encoding="utf-8").read().lower()
            assert not re.search(r"€\s*\d|\d+,\d{2}\b", src), naam
            assert "begroting" not in src and "kostenopbouw" not in src, naam


# ══ Afgeschermd testen ══════════════════════════════════════════════════════
class TestTestmodus:
    def test_test_parameter_zonder_sessie_is_een_gewone_dichte_pagina(self, store, slot):
        _vaststellen()
        body = _c().get("/api/weekend?test=1").json()
        assert body["testmodus"] is False and "kosten" not in body

    def test_testinschrijving_zonder_sessie_geweigerd(self, store, slot):
        r = _c().post("/api/weekend/inschrijven", json=_deelnemer(voorwaarden_versie=0, test=True))
        assert r.status_code == 403 and store.writes == 0

    def test_beheer_kan_testen_terwijl_dicht_en_wordt_als_test_gemarkeerd(self, store, slot):
        tim = _token("Tim", "tim-wachtwoord")
        info = _c().get("/api/weekend?test=1", headers=tim).json()
        assert info["testmodus"] is True and info["formulier"] is True and info["open"] is False
        r = _c().post("/api/weekend/inschrijven", headers=tim, json=_deelnemer(voorwaarden_versie=0, test=True))
        assert r.status_code == 200 and r.json()["test"] is True
        (rec,) = store.data["inschrijvingen"].values()
        assert rec["test"] is True and rec["test_door"] == "Tim"
        assert W.beheer_overzicht()["tellingen"] == {**W.beheer_overzicht()["tellingen"], "totaal": 0, "test": 1}
        assert _c().get("/api/weekend").json()["open"] is False   # testen opent niets


# ══ Toegang: Tim alleen weekend, Jip/Remco ongewijzigd ══════════════════════
def _concreet(pad):
    return re.sub(r"\{[^}]+\}", "x", pad)


def _ruw_get(raw_path, headers):
    """GET via de ASGI-app zelf, zonder URL-normalisatie door een HTTP-client."""
    import asyncio
    from urllib.parse import unquote
    uit = {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        if msg["type"] == "http.response.start":
            uit["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            uit["body"] = uit.get("body", b"") + msg.get("body", b"")

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "server": ("testserver", 80), "client": ("127.0.0.1", 1), "root_path": "",
             "path": unquote(raw_path), "raw_path": raw_path.encode(), "query_string": b"",
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    asyncio.run(api.app(scope, receive, send))
    return uit["status"], uit.get("body", b"")


class TestToegang:
    def test_tim_logt_alleen_in_met_zijn_eigen_wachtwoord(self, slot):
        assert _c().post("/api/login", json={"wie": "Tim", "password": "coach-wachtwoord"}).status_code == 401
        assert _c().post("/api/login", json={"wie": "Jip", "password": "tim-wachtwoord"}).status_code == 401
        me = _c().get("/api/me", headers=_token("Tim", "tim-wachtwoord")).json()
        assert me == {"ingelogd": True, "wie": "Tim", "rol": "weekend"}

    def test_zonder_ingesteld_weekendwachtwoord_kan_tim_niet_in(self, slot, monkeypatch):
        monkeypatch.setattr(api, "_WEEKEND_TIM_PASSWORD", "")
        assert _c().post("/api/login", json={"wie": "Tim", "password": ""}).status_code == 401

    def test_tim_krijgt_op_elke_andere_route_403_van_de_server(self, store, slot):
        tim = _token("Tim", "tim-wachtwoord")
        gecontroleerd = 0
        for route in api.app.routes:
            if not isinstance(route, APIRoute):
                continue
            pad = _concreet(route.path)
            if api._is_public(pad) or api._is_weekend_beheer_pad(pad):
                continue
            for methode in route.methods:
                r = _c().request(methode, pad, headers=tim, json={})
                assert r.status_code == 403 and r.json() == {"err": "geen toegang"}, (methode, pad, r.status_code)
                gecontroleerd += 1
        assert gecontroleerd > 60                          # alle coach-API's, niet een handvol
        for pad in ("/openapi.json", "/docs", "/api/weekend/beheerx"):
            assert _c().get(pad, headers=tim).status_code == 403, pad
        # Ruwe paden (httpx zou '..' zelf wegnormaliseren): de router ziet exact hetzelfde pad
        # als de middleware, dus een weekendprefix + '..' landt op geen enkele coachroute.
        for pad in ("/api/weekend/beheer/../../kaarten", "/api/weekend/beheer/%2e%2e/%2e%2e/kaarten",
                    "/api/weekend/beheer/..%2f..%2fkaarten"):
            assert _ruw_get(pad, tim)[0] in (403, 404), pad
        assert _c().get("/api/weekend/beheer", headers=tim).status_code == 200
        assert _c().get("/api/weekend/beheer", headers=tim).status_code == 200
        assert _c().post("/api/logout", headers=tim).status_code == 200

    def test_coaches_houden_hun_toegang_en_krijgen_weekendbeheer(self, store, slot, monkeypatch):
        monkeypatch.setattr(api.core, "list_kaarten", lambda: [])
        monkeypatch.setattr(api.core, "cloud_backed", lambda: False)
        for wie in ("Jip", "Remco"):
            h = _token(wie, "coach-wachtwoord")
            assert _c().get("/api/kaarten", headers=h).status_code == 200
            assert _c().get("/api/weekend/beheer", headers=h).json()["wie"] == wie
            assert _c().get("/api/me", headers=h).json()["rol"] == "coach"

    def test_geldig_ondertekende_sessie_van_onbekende_gebruiker_komt_nergens_in(self, store, slot):
        h = {"Authorization": "Bearer " + api._sign_session("Mallory")}
        assert _c().get("/api/kaarten", headers=h).status_code == 401
        assert _c().get("/api/weekend/beheer", headers=h).status_code == 401
        assert _c().get("/api/me", headers=h).json()["ingelogd"] is False

    def test_weekendsessie_vervalt_bij_nieuw_of_gewist_weekendwachtwoord(self, store, slot, monkeypatch):
        tim = _token("Tim", "tim-wachtwoord")
        jip = _token("Jip", "coach-wachtwoord")
        assert _c().get("/api/weekend/beheer", headers=tim).status_code == 200
        monkeypatch.setattr(api, "_WEEKEND_TIM_PASSWORD", "nieuw-wachtwoord")
        assert _c().get("/api/weekend/beheer", headers=tim).status_code == 401
        assert _c().get("/api/weekend?test=1", headers=tim).json()["testmodus"] is False
        assert _c().post("/api/weekend/inschrijven", headers=tim,
                         json=_deelnemer(voorwaarden_versie=0, test=True)).status_code == 403
        monkeypatch.setattr(api, "_WEEKEND_TIM_PASSWORD", "")
        assert _c().get("/api/me", headers=tim).json()["ingelogd"] is False
        assert _c().get("/api/weekend/beheer", headers=jip).status_code == 200   # coaches merken niets

    def test_tim_sessie_zonder_weekendsleutel_telt_niet(self, store, slot):
        h = {"Authorization": "Bearer " + api._sign_session("Tim")}
        assert _c().get("/api/weekend/beheer", headers=h).status_code == 401
        assert _c().get("/api/weekend?test=1", headers=h).json()["testmodus"] is False

    def test_passkeys_blijven_alleen_voor_coaches(self, slot):
        r = _c().post("/api/webauthn/auth/options?wie=Tim")
        assert r.status_code == 404


# ══ Kosten, voorwaardenversie en wat bij inschrijving bewaard wordt ═════════
class TestKostenEnVoorwaarden:
    def test_wijziging_geeft_nieuwe_versie_en_bewaart_die_integraal(self, store):
        _vaststellen()
        d = _vaststellen(prijs=26900)
        assert d["instellingen"]["voorwaarden_versie"] == 2
        assert store.data["versies"]["1"]["deelnemersprijs_cent"] == 24900
        assert store.data["versies"]["2"]["deelnemersprijs_cent"] == 26900
        writes = store.writes
        _vaststellen(prijs=26900)                          # niets gewijzigd → geen nieuwe versie
        assert store.writes == writes and W.beheer_overzicht()["instellingen"]["voorwaarden_versie"] == 2

    def test_gelijktijdige_wijziging_wordt_niet_stil_overschreven(self, store):
        _vaststellen()
        e = _fout(lambda: W.instellingen_opslaan({"deelnemersprijs_cent": 1, "aanbetaling_cent": 1,
                                                  "betaaltermijn": "x", "voorwaarden": "y",
                                                  "verwacht_versie": 0}, "Remco"))
        assert e.status == 409

    @pytest.mark.parametrize("prijs,aanbetaling", [(5000, 6000), (-1, 0), (True, 0), (10_000_01, 0), ("250", 0)])
    def test_onzinnige_bedragen_geweigerd(self, store, prijs, aanbetaling):
        e = _fout(lambda: _vaststellen(prijs=prijs, aanbetaling=aanbetaling))
        assert e.status == 400 and store.writes == 0

    def test_open_inschrijving_kan_niet_onvolledig_worden(self, store):
        _vaststellen()
        W.inschrijving_open_zetten(True, "Jip")
        assert _fout(lambda: _vaststellen(voorwaarden="")).status == 409

    def test_inschrijving_bewaart_geaccepteerde_bedragen_versie_en_tijdstip(self, store):
        _vaststellen()
        W.inschrijving_open_zetten(True, "Jip")
        W.inschrijven(_deelnemer(voorwaarden_versie=1))
        (rec,) = store.data["inschrijvingen"].values()
        a = rec["akkoord"]
        assert (a["deelnemersprijs_cent"], a["aanbetaling_cent"], a["voorwaarden_versie"]) == (24900, 5000, 1)
        assert a["betaaltermijn"] == "Fictieve betaaltermijn (test)" and len(a["voorwaarden_sha256"]) == 64
        assert datetime.fromisoformat(a["geaccepteerd_op"]).tzinfo is not None
        assert (rec["inschrijfstatus"], rec["betaalstatus"], rec["test"]) == ("ingeschreven", "open", False)
        assert rec["betaalkeuze"] == a["betaalkeuze"] == "aanbetaling"
        W.inschrijven(_deelnemer(email="volledig@example.com", betaalkeuze="volledig", voorwaarden_versie=1))
        assert W.beheer_overzicht()["tellingen"]["betaalkeuze"] == {"aanbetaling": 1, "volledig": 1}
        # Beheer wijzigt daarna de kosten: wat de deelnemer accepteerde blijft staan.
        W.inschrijving_open_zetten(False, "Jip")
        _vaststellen(prijs=29900)
        assert store.data["inschrijvingen"][rec["id"]]["akkoord"] == a

    def test_gewijzigde_voorwaarden_tussen_lezen_en_inschrijven_geweigerd(self, store):
        _vaststellen()
        W.inschrijving_open_zetten(True, "Jip")
        _vaststellen(prijs=26900)                          # deelnemer zag nog versie 1
        writes = store.writes
        assert _fout(lambda: W.inschrijven(_deelnemer(voorwaarden_versie=1))).status == 409
        assert store.writes == writes

    @pytest.mark.parametrize("veld,waarde", [("bevestig_deelname", False), ("akkoord_voorwaarden", False),
                                             ("email", "geen-email"), ("telefoon", "123"), ("naam", " "),
                                             ("betaalkeuze", ""), ("betaalkeuze", "gratis")])
    def test_expliciete_bevestiging_en_geldige_gegevens_verplicht(self, store, veld, waarde):
        _vaststellen()
        W.inschrijving_open_zetten(True, "Jip")
        writes = store.writes
        assert _fout(lambda: W.inschrijven(_deelnemer(voorwaarden_versie=1, **{veld: waarde}))).status == 400
        assert store.writes == writes

    def test_api_accepteert_alleen_een_echte_true_als_bevestiging(self, store):
        r = _c().post("/api/weekend/inschrijven", json=_deelnemer(bevestig_deelname="true", voorwaarden_versie=1))
        assert r.status_code == 422

    def test_honeypot_slaat_niets_op(self, store):
        _vaststellen()
        W.inschrijving_open_zetten(True, "Jip")
        writes = store.writes
        assert W.inschrijven(_deelnemer(voorwaarden_versie=1, website="http://spam")) == {"ok": True}
        assert store.writes == writes

    def test_leesfout_schrijft_nooit_over_bestaande_inschrijvingen_heen(self, store):
        _vaststellen()
        W.inschrijving_open_zetten(True, "Jip")
        W.inschrijven(_deelnemer(voorwaarden_versie=1))
        store.kapot = True
        writes = store.writes
        assert _fout(lambda: W.inschrijven(_deelnemer(email="twee@example.com", voorwaarden_versie=1))).status == 503
        assert store.writes == writes and len(store.data["inschrijvingen"]) == 1


# ══ Beheer: inschrijfstatus en betaalstatus afzonderlijk ════════════════════
class TestStatusbeheer:
    def _een(self, store, test=False):
        _vaststellen()
        if not test:
            W.inschrijving_open_zetten(True, "Jip")
        W.inschrijven(_deelnemer(voorwaarden_versie=1), test=test, door="Tim" if test else "")
        return next(iter(store.data["inschrijvingen"]))

    def test_statussen_zijn_onafhankelijk_en_worden_gelogd(self, store):
        iid = self._een(store)
        W.status_zetten(iid, "betaalstatus", "aanbetaling", "open", "Tim")
        rec = store.data["inschrijvingen"][iid]
        assert (rec["inschrijfstatus"], rec["betaalstatus"]) == ("ingeschreven", "aanbetaling")
        W.status_zetten(iid, "inschrijfstatus", "bevestigd", "ingeschreven", "Remco")
        rec = store.data["inschrijvingen"][iid]
        assert (rec["inschrijfstatus"], rec["betaalstatus"]) == ("bevestigd", "aanbetaling")
        assert [(h["veld"], h["door"]) for h in rec["historie"]] == [("betaalstatus", "Tim"), ("inschrijfstatus", "Remco")]

    def test_verouderde_of_onbekende_status_geweigerd(self, store):
        iid = self._een(store)
        assert _fout(lambda: W.status_zetten(iid, "betaalstatus", "betaald", "aanbetaling", "Jip")).status == 409
        assert _fout(lambda: W.status_zetten(iid, "betaalstatus", "gratis", "open", "Jip")).status == 400
        assert _fout(lambda: W.status_zetten(iid, "naam", "x", "open", "Jip")).status == 400
        assert _fout(lambda: W.status_zetten("bestaat-niet", "betaalstatus", "betaald", "open", "Jip")).status == 404

    def test_via_api_als_tim(self, store, slot):
        iid = self._een(store)
        tim = _token("Tim", "tim-wachtwoord")
        r = _c().post(f"/api/weekend/beheer/inschrijvingen/{iid}/betaalstatus", headers=tim,
                      json={"waarde": "betaald", "verwacht": "open"})
        assert r.status_code == 200
        assert store.data["inschrijvingen"][iid]["betaalstatus"] == "betaald"
        assert store.data["inschrijvingen"][iid]["historie"][-1]["door"] == "Tim"

    def test_alleen_testinschrijvingen_kunnen_weg(self, store):
        echt = self._een(store)
        assert _fout(lambda: W.testinschrijving_verwijderen(echt)).status == 409
        W.inschrijven(_deelnemer(email="test@example.com", voorwaarden_versie=1), test=True, door="Jip")
        test_id = next(k for k, v in store.data["inschrijvingen"].items() if v["test"])
        W.testinschrijving_verwijderen(test_id)
        assert list(store.data["inschrijvingen"]) == [echt]

    def test_dubbel_emailadres_wordt_gemarkeerd_niet_gelekt(self, store):
        self._een(store)
        r = _c().post("/api/weekend/inschrijven", json=_deelnemer(naam="Tweede Persoon", voorwaarden_versie=1))
        assert r.status_code == 200                        # zelfde antwoord: geen e-mailadres-enumeratie
        assert sorted(v["mogelijk_dubbel"] for v in store.data["inschrijvingen"].values()) == [False, True]


# ══ Pogingenlimiet op inloggen (14 sep 2026) ════════════════════════════════
class _Klok:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def _login(wie, pw):
    return _c().post("/api/login", json={"wie": wie, "password": pw})


class TestPogingenlimiet:
    def test_na_vijf_fouten_wordt_ook_het_juiste_wachtwoord_geweigerd(self, slot, monkeypatch):
        klok = _Klok()
        monkeypatch.setattr(api, "_klok", klok)
        for _ in range(5):
            assert _login("Tim", "fout").status_code == 401
        r = _login("Tim", "tim-wachtwoord")                # juist, maar tijdens de blokkade
        assert r.status_code == 429 and "Te veel mislukte pogingen" in r.json()["err"]
        assert 0 < int(r.headers["Retry-After"]) <= 15 * 60 + 1
        klok.t += 15 * 60 + 1
        assert _login("Tim", "tim-wachtwoord").status_code == 200
        for _ in range(4):                                 # geslaagd inloggen zette de teller op nul
            assert _login("Tim", "fout").status_code == 401
        assert _login("Tim", "tim-wachtwoord").status_code == 200

    def test_jip_en_remco_delen_een_wachtwoord_en_dus_een_teller_tim_niet(self, slot, monkeypatch):
        monkeypatch.setattr(api, "_klok", _Klok())
        for _ in range(5):
            _login("Jip", "fout")
        assert _login("Remco", "coach-wachtwoord").status_code == 429
        assert _login("Tim", "tim-wachtwoord").status_code == 200

    def test_daglimiet_na_twintig_fouten(self, slot, monkeypatch):
        klok = _Klok()
        monkeypatch.setattr(api, "_klok", klok)
        for _ in range(4):                                 # telkens netjes de korte wachttijd uitzitten
            for _ in range(5):
                assert _login("Tim", "fout").status_code == 401
            klok.t += 15 * 60 + 1
        r = _login("Tim", "tim-wachtwoord")
        assert r.status_code == 429 and int(r.headers["Retry-After"]) > 15 * 60
        klok.t += 24 * 3600
        assert _login("Tim", "tim-wachtwoord").status_code == 200

    def test_onbekende_naam_vult_geen_teller(self, slot, monkeypatch):
        monkeypatch.setattr(api, "_klok", _Klok())
        for _ in range(10):
            assert _login("Mallory", "x").status_code == 401
        assert api._LOGIN_FOUTEN == {}
        assert _login("Tim", "tim-wachtwoord").status_code == 200


# ══ Vangrail op openbaar inschrijven ════════════════════════════════════════
class TestInschrijfVangrail:
    def _open(self):
        _vaststellen()
        W.inschrijving_open_zetten(True, "Jip")

    def test_twintig_per_tien_minuten_daarna_even_wachten(self, store, monkeypatch):
        self._open()
        nu = datetime(2027, 1, 5, 12, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(W, "_klok", lambda: nu)
        for i in range(20):
            W.inschrijven(_deelnemer(email=f"d{i}@example.com", voorwaarden_versie=1))
        writes = store.writes
        r = _c().post("/api/weekend/inschrijven", json=_deelnemer(email="extra@example.com", voorwaarden_versie=1))
        assert r.status_code == 429 and "erg veel inschrijvingen" in r.json()["err"]
        assert store.writes == writes
        W.inschrijven(_deelnemer(email="test@example.com", voorwaarden_versie=1), test=True, door="Tim")  # testen kan wel
        later = nu + timedelta(minutes=10, seconds=1)
        monkeypatch.setattr(W, "_klok", lambda: later)
        W.inschrijven(_deelnemer(email="extra@example.com", voorwaarden_versie=1))

    def test_honderd_per_dag(self, store, monkeypatch):
        self._open()
        start = datetime(2027, 1, 5, 0, 0, tzinfo=timezone.utc)
        for ronde in range(20):                            # 5 per 11 minuten: de korte grens wordt nooit geraakt
            moment = start + timedelta(minutes=11 * ronde)
            monkeypatch.setattr(W, "_klok", lambda m=moment: m)
            for i in range(5):
                W.inschrijven(_deelnemer(email=f"r{ronde}-{i}@example.com", voorwaarden_versie=1))
        assert _fout(lambda: W.inschrijven(_deelnemer(email="extra@example.com", voorwaarden_versie=1))).status == 429
        monkeypatch.setattr(W, "_klok", lambda: start + timedelta(hours=24, seconds=1))
        W.inschrijven(_deelnemer(email="extra@example.com", voorwaarden_versie=1))


# ══ Dashboard + betaalopvolging (14 sep 2026) ═══════════════════════════════
from urllib.parse import unquote                          # noqa: E402

_SEPT15 = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)


class TestDashboard:
    def _open(self, monkeypatch, moment=_SEPT15):
        monkeypatch.setattr(W, "_klok", lambda: moment)
        _vaststellen(prijs=36000, aanbetaling=18000)
        W.inschrijving_open_zetten(True, "Jip")

    def _in(self, store, email, keuze="aanbetaling", naam="Anna Fictief", test=False):
        W.inschrijven(_deelnemer(naam=naam, email=email, betaalkeuze=keuze, voorwaarden_versie=1),
                      test=test, door="Tim" if test else "")
        return next(k for k, v in store.data["inschrijvingen"].items() if v["email"] == email)

    def _dash(self, met_test=False):
        return W.beheer_overzicht()["dashboard"]["met_test" if met_test else "echt"]

    def test_volgende_betaalstap_volgt_keuze_en_status(self, store, monkeypatch):
        self._open(monkeypatch)
        a = self._in(store, "a@example.com", "aanbetaling", "Anna Fictief")
        b = self._in(store, "b@example.com", "volledig", "Bram Fictief")
        d = self._dash()
        stappen = {x["id"]: (x["fase"], x["bedrag_cent"]) for x in d["acties"]["versturen"]}
        assert stappen == {a: ("aanbetaling", 18000), b: ("volledig", 36000)}
        assert d["betaalkeuze"] == {"aanbetaling": 1, "volledig": 1, "onbekend": 0}
        W.status_zetten(a, "betaalstatus", "aanbetaling", "open", "Tim")
        W.status_zetten(b, "betaalstatus", "betaald", "open", "Tim")
        d = self._dash()
        assert [(x["id"], x["fase"], x["bedrag_cent"]) for x in d["acties"]["versturen"]] == [(a, "rest", 18000)]
        assert d["geld"] == {"toegezegd_cent": 72000, "ontvangen_cent": 54000, "open_cent": 18000, "te_laat_cent": 0}
        assert d["betaalstatus"] == {"open": 0, "aanbetaling": 1, "betaald": 1, "terugbetaald": 0}
        rij = next(r for r in W.beheer_overzicht()["inschrijvingen"] if r["id"] == b)
        assert rij["actie"] is None                        # volledig betaald: niets meer te doen

    def test_geannuleerd_telt_nergens_mee(self, store, monkeypatch):
        self._open(monkeypatch)
        a = self._in(store, "a@example.com")
        W.status_zetten(a, "inschrijfstatus", "geannuleerd", "ingeschreven", "Jip")
        d = self._dash()
        assert d["aantal"] == {"actief": 0, "geannuleerd": 1, "test": 0}
        assert d["acties"]["versturen"] == [] and d["geld"]["toegezegd_cent"] == 0

    def test_verzoek_verstuurd_verhuist_naar_wachten_en_terug(self, store, monkeypatch):
        self._open(monkeypatch)
        a = self._in(store, "a@example.com")
        W.verzoek_markeren(a, "aanbetaling", True, "Tim")
        d = self._dash()
        assert d["acties"]["versturen"] == [] and d["acties"]["wachten"][0]["verzoek"]["door"] == "Tim"
        writes = store.writes
        W.verzoek_markeren(a, "aanbetaling", True, "Jip")  # nogmaals: geen dubbele write, eerste melder blijft
        assert store.writes == writes and self._dash()["acties"]["wachten"][0]["verzoek"]["door"] == "Tim"
        W.verzoek_markeren(a, "aanbetaling", False, "Jip")
        assert len(self._dash()["acties"]["versturen"]) == 1
        assert [h["veld"] for h in store.data["inschrijvingen"][a]["historie"]] == ["betaalverzoek", "betaalverzoek"]
        assert _fout(lambda: W.verzoek_markeren(a, "iets", True, "Jip")).status == 400
        # Na ontvangst van de aanbetaling staat de restbetaling weer bij 'nog sturen'.
        W.verzoek_markeren(a, "aanbetaling", True, "Tim")
        W.status_zetten(a, "betaalstatus", "aanbetaling", "open", "Tim")
        (stap,) = self._dash()["acties"]["versturen"]
        assert stap["fase"] == "rest" and stap["verzoek"] is None

    def test_te_laat_rekent_in_nederlandse_tijd_en_niet_voor_late_inschrijvers(self, store, monkeypatch):
        self._open(monkeypatch)
        a = self._in(store, "a@example.com")
        W.deadlines_opslaan({"deadline_eerste": "2026-09-23T20:00", "deadline_rest": "2026-11-29"}, "Jip")
        # 20:00 in september = 18:00 UTC (zomertijd).
        monkeypatch.setattr(W, "_klok", lambda: datetime(2026, 9, 23, 17, 59, tzinfo=timezone.utc))
        assert self._dash()["acties"]["versturen"][0]["te_laat"] is False
        laat = datetime(2026, 9, 23, 18, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(W, "_klok", lambda: laat)
        c = self._in(store, "c@example.com", naam="Cas Fictief")   # schreef zich pas NA de deadline in
        d = self._dash()
        status = {x["id"]: x["te_laat"] for x in d["acties"]["versturen"]}
        assert status == {a: True, c: False}
        assert d["geld"]["te_laat_cent"] == 18000
        eerste = d["deadlines"][0]
        assert (eerste["verlopen"], eerste["open"], eerste["te_laat"], eerste["tekst"]) == \
            (True, 2, 1, "woensdag 23 september 20:00")
        assert d["deadlines"][1]["tekst"] == "zondag 29 november" and d["deadlines"][1]["verlopen"] is False

    def test_deadlines_valideren_en_nooit_openbaar(self, store, monkeypatch):
        self._open(monkeypatch)
        assert _fout(lambda: W.deadlines_opslaan({"deadline_eerste": "23-09-2026 20:00"}, "Jip")).status == 400
        assert _fout(lambda: W.deadlines_opslaan({"deadline_eerste": "2026-09-23T20:00",
                                                   "deadline_rest": "2026-09-01"}, "Jip")).status == 400
        W.deadlines_opslaan({"deadline_eerste": "2026-09-23T20:00", "deadline_rest": "2026-11-29"}, "Jip")
        W.reset_cache()
        tekst = _c().get("/api/weekend").text
        assert "2026-09-23" not in tekst and "deadline" not in tekst

    def test_whatsapp_bericht_met_bedrag_en_deadline(self, store, monkeypatch):
        self._open(monkeypatch)
        self._in(store, "a@example.com", naam="Anna Fictief")
        W.deadlines_opslaan({"deadline_eerste": "2026-09-23T20:00", "deadline_rest": ""}, "Jip")
        (stap,) = self._dash()["acties"]["versturen"]
        assert stap["wa_link"].startswith("https://wa.me/31612345678?text=")
        bericht = unquote(stap["wa_link"].split("text=", 1)[1])
        assert bericht.startswith("Hoi Anna!") and "de aanbetaling van € 180,00" in bericht
        assert "vóór woensdag 23 september 20:00" in bericht

    def test_instroom_is_cumulatief_per_dag(self, store, monkeypatch):
        self._open(monkeypatch)
        self._in(store, "a@example.com")
        self._in(store, "b@example.com")
        monkeypatch.setattr(W, "_klok", lambda: _SEPT15 + timedelta(days=2))
        self._in(store, "c@example.com")
        assert self._dash()["tijdlijn"] == [{"datum": "2026-09-15", "aantal": 2, "cumulatief": 2},
                                            {"datum": "2026-09-17", "aantal": 1, "cumulatief": 3}]

    def test_tests_alleen_in_de_testweergave(self, store, monkeypatch):
        self._open(monkeypatch)
        self._in(store, "echt@example.com")
        self._in(store, "test@example.com", test=True)
        assert self._dash()["aantal"]["actief"] == 1
        assert self._dash(met_test=True)["aantal"] == {"actief": 2, "geannuleerd": 0, "test": 1}

    def test_verzoek_en_deadlines_via_api_als_tim(self, store, slot, monkeypatch):
        self._open(monkeypatch)
        a = self._in(store, "a@example.com")
        tim = _token("Tim", "tim-wachtwoord")
        r = _c().post(f"/api/weekend/beheer/inschrijvingen/{a}/verzoek", headers=tim,
                      json={"fase": "aanbetaling", "verstuurd": True})
        assert r.status_code == 200                        # niet opgeslokt door de statusroute
        assert store.data["inschrijvingen"][a]["verzoeken"]["aanbetaling"]["door"] == "Tim"
        r = _c().post("/api/weekend/beheer/deadlines", headers=tim,
                      json={"deadline_eerste": "2026-09-23T20:00", "deadline_rest": "2026-11-29"})
        assert r.status_code == 200 and r.json()["instellingen"]["deadline_rest"] == "2026-11-29"
        assert _c().post(f"/api/weekend/beheer/inschrijvingen/{a}/verzoek",
                         json={"fase": "aanbetaling", "verstuurd": True}).status_code == 401
