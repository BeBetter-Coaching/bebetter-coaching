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


class TestGedeeldePicker:
    """Gedeelde BeBetter Athlete Picker — één primitive over 3 surfaces."""

    def test_primitive_bestaat_en_wordt_hergebruikt(self):
        assert "function renderPicker" in _APP
        # alle drie de surfaces roepen dezelfde primitive aan
        assert _APP.count("renderPicker(") >= 3          # schema + atleten + koppel-overlay

    def test_zoeken_altijd_over_alle_groepen(self):
        # Regel 2: een actieve chip mag de zoekopdracht niet stil beperken.
        fn = _APP[_APP.index("function renderPicker"):_APP.index("function renderPicker") + 4200]
        gf = fn[fn.index("function gefilterd"):fn.index("function gefilterd") + 320]
        assert "f ?" in gf and "groepFilter" in gf       # bij zoekterm wordt de chip genegeerd

    def test_canonieke_groepsvolgorde_en_alfabetisch(self):
        fn = _APP[_APP.index("function renderPicker"):_APP.index("function renderPicker") + 4200]
        assert "groupOrder" in fn                         # canonieke volgorde uit de server
        assert 'localeCompare(y.naam' in fn or "opNaam" in fn   # alfabetisch binnen groep
        assert "Zonder groep" in fn                       # losse atleten apart onderaan

    def test_vaste_gelijke_rijhoogte(self):
        css = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()
        blok = css[css.index(".pk-row{"):css.index(".pk-row{") + 400]
        assert "height:50px" in blok                      # alle rijen exact even hoog
        assert ".pk-row.sel" in css                       # duidelijke selected state

    def test_task_semantiek_schema_navigate_koppel_confirm(self):
        # Schema = navigate (opent), Intake-koppel = confirm (select → bevestig).
        assert 'mode: "navigate"' in _APP                 # schema + atleten
        assert 'mode: "confirm"' in _APP                  # koppel-overlay
        assert "getSelected()" in _APP                    # confirm leest de selectie

    def test_koppel_write_pas_na_bevestiging(self):
        # Native dropdown weg; write pas op de bevestigknop (geen accidental write).
        assert 'id="kp-sel"' not in _APP and 'id="kp-do"' not in _APP   # geen native select meer
        assert "openAthletePickerOverlay" in _APP
        ov = _APP[_APP.index("function openAthletePickerOverlay"):_APP.index("function openAthletePickerOverlay") + 1600]
        assert "onConfirm" in ov and "confirmBtn.onclick" in ov         # write alleen via confirm-knop


class TestAtletenGroepering:
    """Atleten-lijst via de picker: group-first + 'Zonder groep', identity = id."""

    def test_atleten_gebruikt_picker_group_first(self):
        fn = _APP[_APP.index("async function laadDossierLijst"):_APP.index("async function laadDossierLijst") + 1200]
        assert "renderPicker(" in fn
        assert "groep_volgorde" in fn                     # canonieke volgorde
        assert "a.id" in fn                               # identity = user_key/store_key, geen nieuwe key


class TestIntakeFreshness:
    def test_revalidatie_op_focus(self):
        assert "visibilitychange" in _APP
        assert "geladen.atleten = false" in _APP and "geladen.schema = false" in _APP

    def test_geen_unbounded_polling(self):
        # Geen setInterval-poll voor de atleten/schema-lijsten (freshness via focus).
        assert "setInterval(laadDossierLijst" not in _APP
        assert "setInterval(laadSchema" not in _APP
