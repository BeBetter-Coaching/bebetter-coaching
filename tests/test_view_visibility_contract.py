"""View-zichtbaarheid: één actieve route, één zichtbare `.view` (10 sep 2026).

Aanleiding (P1, `66d0b3d`): de Strippenkaart-layoutregel was geschreven als

    .view[data-view="strippen"]{display:flex; ...}

Die selector heeft DEZELFDE specificiteit als `.view.on` (klasse + attribuut vs twee
klassen) maar staat later in het bestand. Daardoor won hij óók van `.view{display:none}`
en stond de Strippenkaart-sectie op ÉLKE route open — terwijl router, hash, `.on` en
nav-highlight aantoonbaar correct waren.

Deze test legt de GRENS vast, niet dat ene geval: geen enkele view-specifieke regel mag
`display` zetten zonder `.on` in de selector. Zo kan een volgende module-layoutregel
deze fout niet opnieuw introduceren.

    python3 -m pytest tests/test_view_visibility_contract.py -q
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATIC = os.path.join(_ROOT, "pwa", "static")
_CSS_BESTANDEN = ("styles.css", "design-system.css")

# Eén regelblok: "selector{declaraties}". Genest in @media werkt ook, want we scannen
# alleen op selector+body en niet op de blokstructuur eromheen.
_REGEL = re.compile(r"(?P<sel>[^{}]+?)\{(?P<body>[^{}]*)\}")
_COMMENT = re.compile(r"/\*.*?\*/", re.S)

# De twee basisregels die de zichtbaarheid MOGEN bepalen.
_BASIS = {".view", ".view.on"}


def _regels():
    """(bestand, selector, body) voor elke CSS-regel, commentaar eruit."""
    uit = []
    for naam in _CSS_BESTANDEN:
        src = _COMMENT.sub("", open(os.path.join(_STATIC, naam)).read())
        for m in _REGEL.finditer(src):
            sel = " ".join(m.group("sel").split())
            if not sel or sel.startswith("@"):
                continue
            uit.append((naam, sel, m.group("body")))
    return uit


def _zet_display(body: str) -> bool:
    return re.search(r"(^|;)\s*display\s*:", body) is not None


def _raakt_een_view(deel: str) -> bool:
    """Selecteert dit selector-deel een `.view`-element ZELF (geen afstammeling)?"""
    laatste = deel.strip().split()[-1] if deel.strip() else ""
    return ".view" in laatste


class TestZichtbaarheidsgrens:
    def test_basisregels_staan_er_nog(self):
        alle = {sel for _, sel, _ in _regels()}
        assert ".view" in alle and ".view.on" in alle, "de hide/show-semantiek is weg"

    def test_geen_view_regel_zet_display_zonder_on(self):
        """DE grens. Een view-specifieke regel die `display` zet zonder `.on` maakt een
        niet-actieve view weer zichtbaar — precies de P1 van `66d0b3d`."""
        overtreders = []
        for bestand, sel, body in _regels():
            if not _zet_display(body):
                continue
            for deel in sel.split(","):
                deel = deel.strip()
                if not _raakt_een_view(deel) or deel in _BASIS:
                    continue
                if ".on" not in deel:
                    overtreders.append(f"{bestand}: {deel} {{{body.strip()[:60]}}}")
        assert not overtreders, (
            "view-specifieke display-regel zonder `.on` — een niet-actieve view kan "
            "hierdoor zichtbaar worden:\n  " + "\n  ".join(overtreders))

    def test_module_layoutregels_gebruiken_geen_important(self):
        """`!important` zou de grens omzeilen in plaats van hem te respecteren."""
        fout = [f"{b}: {s}" for b, s, body in _regels()
                if _raakt_een_view(s.split(",")[0]) and "!important" in body
                and s not in ("[hidden]",)]
        assert not fout, fout

    def test_strippenkaart_layout_hangt_aan_de_actieve_view(self):
        """De concrete P1: de regel bestaat nog (de balk moet onderaan blijven staan)
        maar geldt alleen voor de ACTIEVE strippenkaart-view."""
        sels = {sel for _, sel, _ in _regels()}
        assert '.view.on[data-view="strippen"]' in sels
        assert '.view[data-view="strippen"]' not in sels

    def test_elke_view_in_de_html_heeft_precies_een_sectie(self):
        idx = open(os.path.join(_STATIC, "index.html")).read()
        views = re.findall(r'<section class="view[^"]*" data-view="([a-z-]+)"', idx)
        assert len(views) == len(set(views)), "dubbele view-sectie: " + str(views)
        assert "strippen" in views and "home" in views

    def test_maar_een_view_draagt_on_in_de_html(self):
        """De start-DOM moet zelf al voldoen aan het contract: precies één `.on`."""
        idx = open(os.path.join(_STATIC, "index.html")).read()
        aan = re.findall(r'<section class="view([^"]*)" data-view="([a-z-]+)"', idx)
        met_on = [v for k, v in aan if re.search(r"(^|\s)on(\s|$)", k)]
        assert len(met_on) <= 1, f"meer dan één view start als actief: {met_on}"
