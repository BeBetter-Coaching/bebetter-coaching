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


class TestIntakeFreshness:
    def test_revalidatie_op_focus(self):
        assert "visibilitychange" in _APP
        assert "geladen.atleten = false" in _APP and "geladen.schema = false" in _APP

    def test_geen_unbounded_polling(self):
        # Geen setInterval-poll voor de atleten/schema-lijsten (freshness via focus).
        assert "setInterval(laadDossierLijst" not in _APP
        assert "setInterval(laadSchema" not in _APP
