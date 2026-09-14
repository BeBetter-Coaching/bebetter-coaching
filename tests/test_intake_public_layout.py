"""Publiek intakeformulier: een eigen, scrollende pagina, niet de app-schil (14 sep 2026).

Oorzaak van 'op de computer hartstikke klein': de pagina laadde styles.css, de app-schil.
Die maakt de body een vaste 640px-kolom met overflow:hidden en vanaf 900px een raster
met een 250px-zijbalkkolom; het formulier viel precies in die kolom. De `.pub-*`-stijlen
waren sinds de app-schil (b84a15d) verdwenen, dus niets overschreef dat.

    python3 -m pytest tests/test_intake_public_layout.py -q
"""
import os
import re

_STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pwa", "static")
_HTML = open(os.path.join(_STATIC, "intake_public.html"), encoding="utf-8").read()


def _stylesheets():
    return re.findall(r'<link rel="stylesheet" href="/static/([^"?]+)', _HTML)


def test_laadt_niet_de_app_schil():
    assert "styles.css" not in _stylesheets()


def test_elke_gebruikte_klasse_is_gestyled():
    """Geen formulier dat terugvalt op kale browserstijl omdat een klasse nergens bestaat."""
    css = "".join(open(os.path.join(_STATIC, f), encoding="utf-8").read() for f in _stylesheets())
    klassen = {k for attr in re.findall(r'class="([^"]+)"', _HTML) for k in attr.split()}
    los = sorted(k for k in klassen - {"primary", "big"} if f".{k}" not in css)
    assert not los, f"klassen zonder stijl: {los}"


def test_geen_stylesheet_zet_de_body_vast():
    for naam in _stylesheets():
        css = open(os.path.join(_STATIC, naam), encoding="utf-8").read()
        for regel in re.findall(r"(?<![\w.#-])body(?:\.pub)?\s*\{([^}]*)\}", css):
            assert "overflow:hidden" not in regel.replace(" ", ""), naam
            assert "grid-template-columns" not in regel, naam


def test_js_vindt_zijn_elementen_nog():
    for sel in ('id="f"', 'id="bevestig"', 'id="ondergrond"', 'id="msg"', 'id="app"', 'id="dank"',
                'id="ongeldig"', 'id="welkom"', 'type="submit"'):
        assert sel in _HTML, sel
