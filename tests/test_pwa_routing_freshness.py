"""PWA workflow — refresh state-retention (C) + intake-freshness (D).

Deze twee fixes zitten volledig in de frontend (app.js) en zijn zonder echte
browser/DOM niet puur uit te voeren; deze guard-tests borgen dat de mechaniek
aanwezig blijft en niet stil terugvalt naar 'altijd Home' / 'één keer laden per
sessie'. De end-to-end werking is los in de browser geverifieerd.

    python3 -m pytest tests/test_pwa_routing_freshness.py -q
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()


class TestRefreshRetention:
    def test_hash_routing_aanwezig(self):
        assert "function applyRoute" in _APP and "function pushRoute" in _APP
        assert "popstate" in _APP                      # terug/vooruit
        assert 'pushRoute("atleten", ident)' in _APP   # geselecteerde atleet in de URL

    def test_boot_herstelt_route_ipv_altijd_home(self):
        # De opstart eindigt met applyRoute() (herstel uit URL), niet met een kaal renderHome().
        staart = _APP[-1200:]
        assert "applyRoute();" in staart


class TestSchemaSelector:
    """G — hybride atletenselector (tegels/grid + zoek/filter + selected state)."""

    def test_selector_mechaniek_aanwezig(self):
        assert "function tekenSchemaGrid" in _APP and "_schemaKaart" in _APP
        assert 'id="sb-zoek-in"' in _APP                # zoekbalk
        assert 'id="sb-chips"' in _APP                  # groep-filter
        assert 'class="sb-tile' in _APP                 # compacte tegel

    def test_grid_desktop_2_dan_3_kolommen(self):
        css = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()
        assert "repeat(2,1fr)" in css and "repeat(3,1fr)" in css   # 2 default, 3 pas bij ruimte
        assert ".sb-tile.sel" in css                    # duidelijke selected state

    def test_tegels_vaste_gelijke_hoogte(self):
        css = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()
        blok = css[css.index(".sb-tile{"):css.index(".sb-tile{") + 400]
        assert "height:48px" in blok                    # exact gelijke hoogte, geen min-height-variatie

    def test_secundaire_regel_groep_plus_doel(self):
        # Eén compacte secundaire regel met bestaande info: groep + doel waar aanwezig.
        kaart = _APP[_APP.index("function _schemaKaart"):_APP.index("function tekenSchemaGrid")]
        assert "a.groep" in kaart and "a.doel" in kaart and "a.heeft_intake" in kaart
        assert "sb-badge" not in _APP                    # geen redundante badge meer


class TestAtletenGroepering:
    """Punt 2 — Atleten/Intake-lijst gegroepeerd op bestaande trainingsgroep."""

    def test_groepeert_en_zet_losse_apart(self):
        fn = _APP[_APP.index("function tekenDossierLijst"):_APP.index("function _dossierKaart")]
        assert "a.groep" in fn and "perGroep" in fn and "losse" in fn
        assert "Zonder groep" in fn                      # ongekoppelde atleten apart onderaan
        assert "localeCompare" in fn                     # alfabetisch binnen groep + op groepsnaam


class TestIntakeFreshness:
    def test_revalidatie_op_focus(self):
        assert "visibilitychange" in _APP
        assert "geladen.atleten = false" in _APP and "geladen.schema = false" in _APP

    def test_geen_unbounded_polling(self):
        # Geen setInterval-poll voor de atleten/schema-lijsten (freshness via focus).
        assert "setInterval(laadDossierLijst" not in _APP
        assert "setInterval(laadSchema" not in _APP
