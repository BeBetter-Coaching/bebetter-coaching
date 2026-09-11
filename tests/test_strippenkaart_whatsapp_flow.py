"""WhatsApp Flow v1 — berichten na groepsafboeken (11 sep 2026).

Na een batch loopt de coach de berichten één voor één af:
    berichtenlijst → WhatsApp openen → 'geopend' → teller x/y → Volgende.
`wa.me` opent WhatsApp met een klaargezet bericht, meer niet. De app legt dus alleen
'geopend' vast, op het toestel, per batch-id — nooit 'verzonden'.

Het clientgedrag (A–E, G, H) draait executeerbaar in
`tests/js/strippenkaart_whatsapp.test.mjs`. Deze suite legt vast wat aan de
serverkant en in de markup moet blijven gelden:

  F  de tekst per persoon komt uit het bestaande contract (naam, echt saldo,
     laatste strip) — niets verzonnen, de link draagt precies dat bericht
  H  er bestaat geen server-pad voor berichtstatus of verzending, en geen
     WABA-configuratie: deze build schrijft niets en verstuurt niets
  M  de berichtenfase is een eigen fase naast de kaartenlijst; teller en
     'Volgende' staan in de sticky balk onder de duim

    python3 -m pytest tests/test_strippenkaart_whatsapp_flow.py -q
"""
import os
import re
import sys
import urllib.parse

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
_CORE = open(os.path.join(_ROOT, "pwa", "strippen_core.py")).read()


class _Store:
    def __init__(self, kaarten):
        self.data = kaarten
        self.writes = 0

    def load(self):
        import copy
        return copy.deepcopy(self.data)

    def save(self, d):
        import copy
        self.writes += 1
        self.data = copy.deepcopy(d)
        return True, ""


def _kaart(totaal=10, gebruikt=0, tel="06 12 34 56 78"):
    return {"totaal": totaal, "gebruikt": gebruikt, "telefoon": tel,
            "historie": ["2026-09-0%d" % (i % 9 + 1) for i in range(gebruikt)],
            "aangemaakt": "2026-06-01"}


@pytest.fixture
def store(monkeypatch):
    s = _Store({
        "Anna Bos": _kaart(10, 3),
        "Bram van der Meer": _kaart(10, 8),         # na afboeken: 1 over
        "Cas de Wit": _kaart(20, 19),               # na afboeken: laatste strip, op
        "Eva Smit": _kaart(10, 2, tel=""),          # geen nummer
    })
    monkeypatch.setattr(intake_store, "load_strippenkaarten", s.load)
    monkeypatch.setattr(intake_store, "save_strippenkaarten", s.save)
    core._IDEMPOTENT.clear()
    return s


def _tekst_uit_link(link: str) -> str:
    return urllib.parse.unquote(link.split("?text=", 1)[1])


# ══════════════════════════════════════════════════════════════════════════════
# F — tekst per persoon
# ══════════════════════════════════════════════════════════════════════════════
class TestTekst:
    def test_naam_en_saldo_komen_uit_de_kaart(self, store):
        _, _, res = core.afboeken_batch(["Anna Bos", "Bram van der Meer"])
        d = {x["naam"]: x for x in res["deelnemers"]}
        assert d["Anna Bos"]["bericht"].startswith("Hoi Anna,")
        assert "nog 6 van je 10 trainingen over" in d["Anna Bos"]["bericht"]
        # Bijna leeg krijgt het ECHTE getal — geen tweede 'bijna'-definitie op de server.
        assert "nog 1 van je 10 trainingen over" in d["Bram van der Meer"]["bericht"]
        assert d["Bram van der Meer"]["bericht"].startswith("Hoi Bram,")

    def test_laatste_strip_krijgt_de_kaart_op_tekst(self, store):
        _, _, res = core.afboeken_batch(["Cas de Wit"])
        d = res["deelnemers"][0]
        assert d["rest"] == 0
        assert "laatste training" in d["bericht"] and "kaart is nu vol" in d["bericht"]
        assert "nog 0" not in d["bericht"]

    def test_de_link_draagt_precies_dat_bericht_naar_het_eigen_nummer(self, store):
        _, _, res = core.afboeken_batch(["Anna Bos", "Cas de Wit"])
        for d in res["deelnemers"]:
            assert d["wa_link"].startswith("https://wa.me/31612345678?text=")
            assert _tekst_uit_link(d["wa_link"]) == d["bericht"]

    def test_niets_verzonnen_alleen_naam_en_getallen_van_de_kaart(self, store):
        """Het bericht bevat geen gegevens die niet op de kaart staan: vervang naam en
        getallen door plaatshouders en er blijft exact één van de twee vaste teksten over."""
        _, _, res = core.afboeken_batch(["Anna Bos", "Bram van der Meer", "Cas de Wit"])
        vorm = set()
        for d in res["deelnemers"]:
            t = d["bericht"].replace(d["naam"].split()[0], "{V}")
            t = re.sub(r"\b%d\b" % d["totaal"], "{T}", t)
            t = re.sub(r"\b%d\b" % d["rest"], "{R}", t) if d["rest"] else t
            vorm.add(t)
            assert not re.search(r"\d", t), t
        normaal = re.sub(r"\b7\b", "{R}", re.sub(r"\b13\b", "{T}", core.afboek_bericht("{V}", 7, 13)))
        assert vorm == {normaal, core.afboek_bericht("{V}", 0, 10)}

    def test_zonder_nummer_geen_link(self, store):
        _, _, res = core.afboeken_batch(["Eva Smit"])
        assert res["deelnemers"][0]["wa_link"] == ""

    def test_elke_deelnemer_draagt_de_stand_waarop_zijn_bericht_rust(self, store):
        """De client legt de berichtenlijst na een verse read naast de serverstand
        (`gebruikt`); daarvoor moet elke deelnemer die stand meekrijgen."""
        _, _, res = core.afboeken_batch(["Anna Bos", "Eva Smit"])
        assert res["batch_id"]
        for d in res["deelnemers"]:
            assert {"naam", "rest", "totaal", "gebruikt", "wa_link"} <= set(d)
        assert {k["naam"]: k["gebruikt"] for k in core.list_kaarten()}["Anna Bos"] == 4


# ══════════════════════════════════════════════════════════════════════════════
# H — geen automatische messaging, geen server-write
# ══════════════════════════════════════════════════════════════════════════════
class TestGeenMessaging:
    def test_geen_endpoint_voor_berichtstatus_of_verzending(self):
        routes = re.findall(r'@\w+\.(?:get|post|put|patch|delete)\("([^"]+)"', _API)
        assert routes, "routes niet gevonden"
        verdacht = [r for r in routes if re.search(r"whatsapp|wa\b|bericht|geopend|verzend|verstuur", r, re.I)]
        assert not verdacht, verdacht

    def test_geen_waba_configuratie_of_verzender(self):
        """Echte WhatsApp Business API vraagt een token en een verzender. Die horen er
        pas te komen mét provider-config; deze build mag er niets van bevatten."""
        for bron, naam in ((_CORE, "strippen_core.py"), (_API, "api.py")):
            assert not re.search(r"graph\.facebook|WHATSAPP_|WABA|messages\?|/messages\b", bron), naam

    def test_berichtenfase_praat_niet_met_de_server(self):
        i = _APP.index("// ── WhatsApp na afboeken")
        j = _APP.index("// ── Detail per persoon", i)
        code = re.sub(r"//.*", "", _APP[i:j])
        assert not re.search(r"\bjpost\(|\bapi\(|\bfetch\(|enqueue\(", code)
        assert not re.search(r"window\.open|location\s*=|location\.href\s*=|\.click\(\)", code)


# ══════════════════════════════════════════════════════════════════════════════
# M — markup en layout
# ══════════════════════════════════════════════════════════════════════════════
class TestMarkup:
    def _view(self):
        i = _IDX.index('data-view="strippen"')
        return _IDX[i:_IDX.index("</section>\n", _IDX.index('id="sk-bar"', i))]

    def test_berichtenfase_staat_naast_de_kaartenlijst_niet_erin(self):
        v = self._view()
        kaarten = v.index('id="sk-kaarten"')
        berichten = v.index('id="sk-berichten"')
        lijst = v.index('id="lijst"')
        assert kaarten < lijst < berichten, "de berichten horen niet in de kaartenlijst"
        assert re.search(r'id="sk-berichten"[^>]*\bhidden\b', v), "de fase is standaard dicht"

    def test_teller_en_volgende_staan_in_de_sticky_balk(self):
        v = self._view()
        bar = v[v.index('id="sk-bar"'):]
        for id_ in ("sk-b-teller", "sk-volgende", "sk-b-klaar"):
            assert f'id="{id_}"' in bar, id_
        assert re.search(r'id="sk-volgende"[^>]*target="_blank"', bar)

    def test_rijen_zijn_duimformaat_en_krimpen_zonder_horizontale_scroll(self):
        m = re.search(r"\.sk-b-open\{[^}]*min-height:(\d+)px", _CSS)
        assert m and int(m.group(1)) >= 48
        assert re.search(r"\.sk-volgende\{[^}]*min-height:(5\d)px", _CSS)
        assert re.search(r"\.sk-volgende-t\{[^}]*text-overflow:ellipsis", _CSS)
        assert "width:" not in (re.search(r"\.sk-b-lijst\{[^}]*\}", _CSS).group(0))

    def test_sticky_balk_compenseert_precies_de_scrollerpadding(self):
        """Een sticky element pint op de scrollerrand MIN diens padding. Met `bottom:0`
        stond de balk daardoor 20px boven de onderbalk en scrolde de lijst eronder
        zichtbaar mee. De garantie is een RELATIE: elke bodempadding van #scroller en de
        `bottom` van de balk lezen dezelfde variabele — op elk schermformaat."""
        css = re.sub(r"/\*.*?\*/", "", _CSS, flags=re.S)
        scroller = re.findall(r"#scroller\{[^}]*?padding:([^;}]+)", css)
        assert scroller, "#scroller-padding niet gevonden"
        for p in scroller:
            delen = p.split()
            onder = delen[2] if len(delen) >= 3 else delen[0]
            assert onder == "var(--scroll-pad-b)", f"#scroller-bodempadding los van de variabele: {p}"
        assert re.search(r"\.sk-bar\{position:sticky;bottom:calc\(-1 \* var\(--scroll-pad-b\)\)", css)

    def test_oude_losse_knoppenrij_is_weg(self):
        """Vijftien losse voornaamknoppen in de uitkomstbalk zeiden niet wie je al had."""
        assert "sk-wa-btn" not in _APP and ".sk-wa-btn" not in _CSS
