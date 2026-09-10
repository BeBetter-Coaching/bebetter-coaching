"""Strippenkaart Cockpit v2 — groepsafboeken op de telefoon (10 sep 2026).

De module wordt tijdens een training gebruikt: de coach staat naast de groep en moet
in seconden een groep aanwezigen afboeken. Deze tests leggen de contracten vast die
dat veilig maken:

  A  render      — de lijst is één mobiele lijst, actief boven leeg, geen kaartraster
  B  selectie    — meerdere deelnemers, deselecteren, wissen, filter + selectie
  C  bulk        — één batch-write, geen dubbele write, geen negatief saldo,
                   stale-detectie, nooit een half uitgevoerde batch
  D  single      — één persoon loopt via HETZELFDE pad
  E  herladen    — na een write klopt de serverstand
  F  foutpad     — een geweigerde batch verandert niets
  G  undo        — precies één keer terug, tweede undo onmogelijk

    python3 -m pytest tests/test_strippenkaart_cockpit_v2.py -q
"""
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import intake_store                                     # noqa: E402
import strippen_core as core                            # noqa: E402

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_IDX = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()
_CSS = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()
_API = open(os.path.join(_ROOT, "pwa", "api.py")).read()


def _fn(naam: str, bron: str = None) -> str:
    """Body van één JS-functie (brace-matching), zodat een test over de ECHTE code gaat."""
    src = bron if bron is not None else _APP
    i = src.index(naam)
    j = src.index("{", i)
    d = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            d += 1
        elif src[k] == "}":
            d -= 1
            if d == 0:
                return src[i:k + 1]
    raise AssertionError(naam)


# ── Opslag-dubbel: houdt de kaarten in het geheugen en TELT de writes ────────
class _Store:
    def __init__(self, kaarten):
        self.data = kaarten
        self.writes = 0
        self.falen = ""

    def load(self):
        # Diepe kopie: de core mag alleen via save() iets veranderd krijgen, zodat een
        # test 'niets geschreven' ook echt kan bewijzen.
        import copy
        return copy.deepcopy(self.data)

    def save(self, d):
        if self.falen:
            return False, self.falen
        import copy
        self.writes += 1
        self.data = copy.deepcopy(d)
        return True, ""


def _kaart(totaal=10, gebruikt=0, tel="0612345678", hist=None):
    return {"totaal": totaal, "gebruikt": gebruikt, "telefoon": tel,
            "historie": list(hist if hist is not None else ["2026-08-0%d" % (i + 1) for i in range(gebruikt)]),
            "aangemaakt": "2026-06-01"}


@pytest.fixture
def store(monkeypatch):
    s = _Store({
        "Anna Bos": _kaart(10, 3),
        "Bram Willems": _kaart(10, 7),
        "Cas de Wit": _kaart(20, 0),
        "Dana Vos": _kaart(10, 10),            # kaart is OP
        "Eva Smit": _kaart(10, 9, tel=""),     # laatste strip, geen nummer
    })
    monkeypatch.setattr(intake_store, "load_strippenkaarten", s.load)
    monkeypatch.setattr(intake_store, "save_strippenkaarten", s.save)
    core._IDEMPOTENT.clear()
    return s


# ══════════════════════════════════════════════════════════════════════════════
# C — bulk-afboeken
# ══════════════════════════════════════════════════════════════════════════════
class TestBulk:
    def test_een_strip_bij_meerdere_deelnemers_in_precies_een_write(self, store):
        ok, err, res = core.afboeken_batch(["Anna Bos", "Bram Willems", "Cas de Wit"])
        assert ok and not err
        assert store.writes == 1, "een groepsafboeking mag maar ÉÉN keer schrijven"
        assert {d["naam"]: d["rest"] for d in res["deelnemers"]} == {
            "Anna Bos": 6, "Bram Willems": 2, "Cas de Wit": 19}
        assert store.data["Anna Bos"]["gebruikt"] == 4
        assert store.data["Cas de Wit"]["gebruikt"] == 1

    def test_elke_deelnemer_krijgt_precies_een_historieregel(self, store):
        voor = len(store.data["Anna Bos"]["historie"])
        core.afboeken_batch(["Anna Bos", "Bram Willems"])
        assert len(store.data["Anna Bos"]["historie"]) == voor + 1
        assert store.data["Anna Bos"]["historie"][-1] == store.data["Bram Willems"]["historie"][-1]

    def test_dubbele_naam_in_een_batch_is_een_strip(self, store):
        ok, _, res = core.afboeken_batch(["Anna Bos", "Anna Bos"])
        assert ok and res["aantal"] == 1
        assert store.data["Anna Bos"]["gebruikt"] == 4

    def test_dubbeltap_met_dezelfde_sleutel_boekt_maar_een_keer_af(self, store):
        ok1, _, r1 = core.afboeken_batch(["Anna Bos", "Bram Willems"], client_id="tik-1")
        ok2, _, r2 = core.afboeken_batch(["Anna Bos", "Bram Willems"], client_id="tik-1")
        assert ok1 and ok2
        assert store.writes == 1, "tweede tik van dezelfde actie mag niet nog eens schrijven"
        assert r2["herhaald"] is True and r2["batch_id"] == r1["batch_id"]
        assert store.data["Anna Bos"]["gebruikt"] == 4

    def test_deelnemer_zonder_strippen_blokkeert_de_hele_batch(self, store):
        ok, err, info = core.afboeken_batch(["Anna Bos", "Dana Vos"])
        assert not ok and "Dana Vos" in err
        assert info["conflict"] == "leeg"
        assert store.writes == 0
        # Niemand half afgeboekt — óók Anna niet, terwijl die wél kon.
        assert store.data["Anna Bos"]["gebruikt"] == 3
        assert store.data["Dana Vos"]["gebruikt"] == 10, "0 resterend mag nooit naar -1"

    def test_onbekende_naam_blokkeert_de_hele_batch(self, store):
        ok, err, info = core.afboeken_batch(["Anna Bos", "Wie Danook"])
        assert not ok and info["conflict"] == "onbekend"
        assert store.writes == 0 and store.data["Anna Bos"]["gebruikt"] == 3

    def test_stale_saldo_wordt_gedetecteerd_en_niets_geschreven(self, store):
        # Tweede tabblad boekte al af; de client stuurt de stand die hij ZAG.
        core.afboeken_batch(["Anna Bos"])
        ok, err, info = core.afboeken_batch(["Anna Bos", "Bram Willems"],
                                            verwacht={"Anna Bos": 3, "Bram Willems": 7})
        assert not ok and info["conflict"] == "stale" and info["namen"] == ["Anna Bos"]
        assert store.writes == 1, "alleen de eerste afboeking heeft geschreven"
        assert store.data["Bram Willems"]["gebruikt"] == 7

    def test_kloppende_verwachting_gaat_gewoon_door(self, store):
        ok, err, _ = core.afboeken_batch(["Anna Bos", "Bram Willems"],
                                         verwacht={"Anna Bos": 3, "Bram Willems": 7})
        assert ok and not err and store.writes == 1

    def test_mislukte_opslag_laat_geen_halve_mutatie_achter(self, store):
        store.falen = "GitHub API: 409"
        ok, err, _ = core.afboeken_batch(["Anna Bos", "Bram Willems"])
        assert not ok and "409" in err
        assert store.data["Anna Bos"]["gebruikt"] == 3 and store.data["Bram Willems"]["gebruikt"] == 7

    def test_lege_selectie_doet_niets(self, store):
        ok, err, _ = core.afboeken_batch([])
        assert not ok and err and store.writes == 0

    def test_idempotentiecache_is_begrensd(self, store):
        for i in range(core._IDEMPOTENT_MAX + 20):
            core._onthoud(f"k{i}", {"batch_id": str(i)})
        assert len(core._IDEMPOTENT) <= core._IDEMPOTENT_MAX


# ══════════════════════════════════════════════════════════════════════════════
# D + E — één persoon via hetzelfde pad, en de stand na herladen
# ══════════════════════════════════════════════════════════════════════════════
class TestSingleEnHerladen:
    def test_een_persoon_is_gewoon_een_batch_van_een(self, store):
        ok, _, res = core.afboeken_batch(["Bram Willems"], client_id="solo")
        assert ok and res["aantal"] == 1 and store.writes == 1
        assert res["deelnemers"][0]["rest"] == 2

    def test_bericht_en_wa_link_blijven_bestaan(self, store):
        _, _, res = core.afboeken_batch(["Bram Willems"])
        d = res["deelnemers"][0]
        assert d["bericht"].startswith("Hoi Bram") and "nog 2 van je 10" in d["bericht"]
        assert d["wa_link"].startswith("https://wa.me/31612345678?text=")

    def test_laatste_strip_geeft_het_vol_bericht_en_geen_link_zonder_nummer(self, store):
        _, _, res = core.afboeken_batch(["Eva Smit"])
        d = res["deelnemers"][0]
        assert d["rest"] == 0 and "kaart is nu vol" in d["bericht"]
        assert d["wa_link"] == ""

    def test_herladen_toont_dezelfde_saldi(self, store):
        core.afboeken_batch(["Anna Bos", "Cas de Wit"])
        na = {k["naam"]: (k["gebruikt"], k["rest"], k["totaal"]) for k in core.list_kaarten()}
        assert na["Anna Bos"] == (4, 6, 10) and na["Cas de Wit"] == (1, 19, 20)

    def test_lijst_geeft_de_historiestaart_mee_voor_het_detail(self, store):
        rij = {k["naam"]: k for k in core.list_kaarten()}["Bram Willems"]
        assert rij["historie"] == rij["historie"][-6:] and len(rij["historie"]) <= 6
        assert all(isinstance(h, str) for h in rij["historie"])


# ══════════════════════════════════════════════════════════════════════════════
# G — ongedaan maken
# ══════════════════════════════════════════════════════════════════════════════
class TestUndo:
    def test_exact_dezelfde_batch_gaat_terug(self, store):
        hist_voor = list(store.data["Anna Bos"]["historie"])
        _, _, res = core.afboeken_batch(["Anna Bos", "Cas de Wit"])
        ok, err, terug = core.batch_terug(res["batch_id"])
        assert ok and not err and terug["aantal"] == 2
        assert store.data["Anna Bos"]["gebruikt"] == 3
        assert store.data["Anna Bos"]["historie"] == hist_voor, "historie moet exact terug"
        assert store.data["Cas de Wit"]["gebruikt"] == 0
        assert "laatste_batch" not in store.data["Anna Bos"]

    def test_tweede_undo_van_dezelfde_batch_is_onmogelijk(self, store):
        _, _, res = core.afboeken_batch(["Anna Bos"])
        assert core.batch_terug(res["batch_id"])[0] is True
        schrijf_na_eerste = store.writes
        ok, err, info = core.batch_terug(res["batch_id"])
        assert not ok and info["conflict"] == "weg" and "teruggedraaid" in err
        assert store.writes == schrijf_na_eerste, "een tweede undo mag niets schrijven"
        assert store.data["Anna Bos"]["gebruikt"] == 3

    def test_undo_weigert_als_de_kaart_daarna_gewijzigd_is(self, store):
        _, _, res = core.afboeken_batch(["Anna Bos", "Cas de Wit"])
        core.afboeken(_naam := "Anna Bos")                      # losse afboeking ertussendoor
        ok, err, info = core.batch_terug(res["batch_id"])
        assert not ok and info["conflict"] == "gewijzigd" and _naam in info["namen"]
        # Ook Cas — die WEL onaangeroerd was — blijft staan: geen halve undo.
        assert store.data["Cas de Wit"]["gebruikt"] == 1

    def test_onbekende_batch_doet_niets(self, store):
        ok, _, _ = core.batch_terug("bestaat-niet")
        assert not ok and store.writes == 0


# ══════════════════════════════════════════════════════════════════════════════
# API — de twee nieuwe endpoints, en wat NIET verdween
# ══════════════════════════════════════════════════════════════════════════════
class TestApi:
    def test_groepsendpoints_bestaan_en_zijn_gekoppeld(self):
        assert '@app.post("/api/kaarten/afboeken")' in _API
        assert "core.afboeken_batch(body.namen, body.verwacht, body.client_id)" in _API
        assert '@app.post("/api/kaarten/terugdraaien")' in _API
        assert "core.batch_terug(body.batch_id)" in _API

    def test_bestaande_endpoints_blijven(self):
        """De losse afboeking voedt nog de offline-wachtrij en de Streamlit-gelijkheid."""
        for pad in ('@app.get("/api/kaarten")', '@app.post("/api/kaarten/{naam}/afboeken")',
                    '@app.post("/api/kaarten/{naam}/terug")', '@app.delete("/api/kaarten/{naam}")',
                    '@app.post("/api/import/preview")', '@app.post("/api/import")'):
            assert pad in _API, pad

    def test_geen_tweede_kaartadministratie(self):
        """Alles blijft door dezelfde store lopen als de Streamlit-app. Geen aantal
        vastleggen (dat verandert bij elke nieuwe actie) maar de GARANTIE: er is precies
        één schrijf- en één leesfunctie, en geen eigen opslagpad ernaast."""
        src = open(os.path.join(_ROOT, "pwa", "strippen_core.py")).read()
        schrijft = set(re.findall(r"\b(\w*save\w*)\(", src))
        leest = set(re.findall(r"\b(\w*load\w*)\(", src))
        assert schrijft == {"save_strippenkaarten"}, schrijft
        assert leest == {"load_strippenkaarten"}, leest
        for verboden in ("open(", "json.dump", "json.load", "requests.", "sqlite", "pickle"):
            assert verboden not in src, f"eigen opslagpad in strippen_core: {verboden}"

    def test_batchgrens_is_begrensd(self, store):
        ok, err, _ = core.afboeken_batch([f"n{i}" for i in range(core._MAX_BATCH + 1)])
        assert not ok and "max" in err


# ══════════════════════════════════════════════════════════════════════════════
# A + B — clientcontract: mobiele lijst, selectie, sticky balk
# ══════════════════════════════════════════════════════════════════════════════
class TestClientContract:
    def test_de_kaartweergave_is_vervangen_door_een_lijst(self):
        for weg in ('id="kaart-tpl"', 'class="kaart"', "swipe-fg", "swipe-hint"):
            assert weg not in _IDX, f"oude kaartweergave nog aanwezig: {weg}"
        for weg in ("function kaartEl(", "function addSwipe(", "function setRing("):
            assert weg not in _APP, f"oude renderer nog aanwezig: {weg}"
        assert 'id="lijst" class="sk-lijst"' in _IDX

    def test_de_primaire_flow_staat_bovenaan_de_pagina(self):
        """Lijst eerst, beheer (nieuwe kaart / import) daarna — anders scrollt de coach
        tijdens een training eerst langs formulieren."""
        view = _IDX[_IDX.index('data-view="strippen"'):_IDX.index('data-view="schema"')]
        assert view.index('id="sk-q"') < view.index('id="lijst"') < view.index('data-target="nieuw"')
        assert view.index('data-target="nieuw"') < view.index('id="sk-bar"')

    def test_sticky_balk_draagt_de_verplichte_hoofdactie(self):
        assert "`1 strip afboeken bij ${n} geselecteerd`" in _fn("function skBalk(")
        assert ".sk-bar{position:sticky" in _CSS
        assert "env(safe-area-inset-bottom)" in _CSS.split("--scroll-pad-b:")[1][:60]

    def test_tikvlak_is_duimformaat_en_geen_checkbox(self):
        blok = _CSS[_CSS.index(".sk-kies{"):_CSS.index(".sk-kies{") + 260]
        assert re.search(r"min-height:(5[4-9]|[6-9]\d)px", blok), "rij-tikvlak te klein"
        assert re.search(r"\.sk-af\{[^}]*min-height:5[0-9]px", _CSS), "hoofdactie te klein"
        assert 'type="checkbox"' not in _IDX[_IDX.index('data-view="strippen"'):
                                             _IDX.index('data-view="schema"')]

    def test_lange_namen_kunnen_niet_horizontaal_scrollen(self):
        blok = _CSS[_CSS.index(".sk-naam{"):_CSS.index(".sk-naam{") + 200]
        assert "text-overflow:ellipsis" in blok and "overflow:hidden" in blok
        assert "min-width:0" in _CSS[_CSS.index(".sk-mid{"):_CSS.index(".sk-mid{") + 120]

    def test_selectie_leeft_buiten_de_dom(self):
        """Een hertekening (filter, saldo-update) mag de selectie nooit kwijtraken."""
        assert "const skSel = new Set();" in _APP
        toggle = _fn("function skToggle(")
        assert "skSel.has(naam)" in toggle and "skSel.add(naam)" in toggle
        # Filteren verandert alleen zichtbaarheid, niet de selectie.
        zoek = _fn("function skZoek(")
        assert "skSel" not in zoek and "skFilter" in zoek

    def test_selecteer_alles_geldt_alleen_voor_de_zichtbare_actieve_lijst(self):
        f = _fn("function skAllesZichtbaar(")
        assert "skActief(k)" in f and "skZichtbaar(k.naam)" in f

    def test_lege_kaart_is_niet_selecteerbaar(self):
        assert "if (!k || !skActief(k)) return;" in _fn("function skToggle(")
        assert "kies.disabled = leeg" in _fn("function skVerversRij(")

    def test_actieve_kaarten_staan_boven_lege(self):
        assert "(a.rest <= 0) - (b.rest <= 0)" in _fn("function skSorteer(")
        assert 'localeCompare(b.naam, "nl")' in _fn("function skSorteer(")

    def test_status_is_functioneel_gekleurd_via_het_gedeelde_dialect(self):
        f = _fn("function skVerversRij(")
        for klasse in ("is-critical", "is-attention", "is-calm"):
            assert klasse in f
        assert '"OP" : k.rest + " over"' in f

    def test_een_drempel_voor_bijna_leeg(self):
        """Home ('nog 1 training') en de lijst mogen niet uit elkaar lopen."""
        assert _APP.count("const KAART_BIJNA") == 1
        assert "k.rest <= KAART_BIJNA" in _fn("async function renderHome(")
        assert "k.rest <= KAART_BIJNA" in _fn("function skVerversRij(")


# ══════════════════════════════════════════════════════════════════════════════
# C/F op de client — één write, bevestiging, geen verzonnen saldo
# ══════════════════════════════════════════════════════════════════════════════
class TestClientSchrijfpad:
    def test_precies_een_schrijfpad_naar_de_groepsafboeking(self):
        assert _APP.count('jpost("/api/kaarten/afboeken"') == 1
        assert _APP.count('"/api/kaarten/afboeken"') == 2      # + de offline-wachtrij
        assert _APP.count('jpost("/api/kaarten/terugdraaien"') == 1

    def test_afboeken_vraagt_een_expliciete_bevestiging_met_namen(self):
        f = _fn("async function skAfboeken(")
        assert "await bevestigActie(" in f
        assert 'detail: namen.join(" · ")' in f
        assert "if (!akkoord || skBezig) return;" in f

    def test_dubbeltap_wordt_op_drie_plekken_gestopt(self):
        f = _fn("async function skAfboeken(")
        assert f.strip().splitlines()[1].strip().startswith("if (skBezig) return;")
        assert "client_id: cid" in f                              # server-idempotentie
        assert "af.disabled = skBezig" in _fn("function skBalk(")  # knop uit tijdens verwerken

    def test_saldo_komt_uit_het_serverantwoord(self):
        f = _fn("function skPasToe(")
        assert "k.rest = d.rest" in f and "k.gebruikt = d.gebruikt" in f
        # Geen optimistische verlaging in het ONLINE pad.
        online = _fn("async function skAfboeken(")
        assert "k.gebruikt += 1" not in online

    def test_fout_verandert_niets_en_houdt_de_selectie(self):
        f = _fn("async function skAfboeken(")
        tak = f[f.index("if (!r.ok)"):]
        assert "melding(" in tak and "skPasToe" not in tak.split("}")[0]
        assert "skSel.clear()" not in f[f.index("if (!r) {"):f.index("if (!r.ok)")]

    def test_stale_conflict_haalt_de_echte_stand_op(self):
        assert "if (r.conflict) await laad();" in _fn("async function skAfboeken(")

    def test_offline_boekt_vooruit_maar_zegt_dat_erbij(self):
        f = _fn("function skOffline(")
        assert 'enqueue({ url: "/api/kaarten/afboeken"' in f and "k.wacht = true" in f
        assert "wacht ? \" · ⏳ wordt verzonden\"" in _fn("function skVerversRij(")

    def test_wachtrij_blijft_niet_eeuwig_hangen_op_een_afwijzing(self):
        f = _fn("async function flush(")
        assert "it.body ? await jpost(it.url, it.body)" in f
        assert "mislukt.push" in f and "rest.push(it)" in f

    def test_geen_volledige_herlaad_na_een_geslaagde_afboeking(self):
        """Alleen de geraakte rijen verversen — 30 rijen opnieuw bouwen is merkbaar traag."""
        f = _fn("async function skAfboeken(")
        na = f[f.index("skPasToe(r.deelnemers"):]
        assert "laad()" not in na and "skTeken()" not in na

    def test_undo_kan_maar_een_keer_vanuit_de_client(self):
        f = _fn("async function skUndo(")
        assert "if (!skLaatsteBatch || skBezig) return;" in f
        assert f.index("skLaatsteBatch = null;") < f.index("jpost(")
