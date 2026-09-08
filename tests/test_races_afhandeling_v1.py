"""Races-afhandeling v1 — broncontract + scope-lock.

De GEDRAGSBEWIJZEN (bevestiging, afhandeling, telling, foutpad, anti-dubbelpost)
staan in tests/js/races_afhandeling.test.mjs: die snijdt de echte functies uit
app.js en draait ze. Hier bewaken we wat een executable test niet ziet:

  * de native `confirm()` is uit de races-flow verdwenen (en komt niet terug);
  * de bevestiging is een GEDEELDE primitief, geen races-eigen dialoog;
  * de schrijfkant (endpoint, payload, races_core) is ONGEWIJZIGD — dit is een
    client-batch, geen wijziging aan wat er naar FinalSurge gaat;
  * client-bytes veranderden, dus de service-worker/asset-versie is meegebumpt;
  * de scope: alleen de bestanden die bij deze batch horen (opt-in, zie _REVIEW).
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_APP = (_ROOT / "pwa" / "static" / "app.js").read_text(encoding="utf-8")
_CSS = (_ROOT / "pwa" / "static" / "styles.css").read_text(encoding="utf-8")
_API = (_ROOT / "pwa" / "api.py").read_text(encoding="utf-8")
_CORE = (_ROOT / "pwa" / "races_core.py").read_text(encoding="utf-8")

# Het VENSTER van deze batch: van de productiestand waarop hij is gebaseerd tot de
# commit waarin hij landde. Zo blijft de lock over precies deze wijziging gaan en niet
# over alles wat er daarna nog bij komt.
_BASIS = "becc3a4"
_MERGE = "3798b33"

# De scope- en byte-identiteitscontroles vergelijken de HUIDIGE werkboom met `_BASIS`.
# Dat is precies wat je wilt tijdens de review van DEZE batch, en precies wat je niet
# wilt daarna: elke latere, volkomen legitieme wijziging aan races_core, de server of
# een clientbestand zou hier als 'regressie' opduiken. Ze draaien daarom alleen op
# verzoek en zijn verder overgeslagen:
#
#     BEBETTER_REVIEW_LOCK=1 python3 -m pytest tests/test_races_afhandeling_v1.py
#
# De inhoudelijke contracten hieronder (bevestiging, afhandeling, endpoint, versies)
# hebben géén git nodig en blijven dus altijd meelopen.
_REVIEW = os.environ.get("BEBETTER_REVIEW_LOCK") == "1"
_review_only = pytest.mark.skipif(
    not _REVIEW, reason="eenmalige reviewcontrole van deze batch — draai met BEBETTER_REVIEW_LOCK=1")


def _fn(sig: str) -> str:
    """Snijdt één functie uit app.js met een haakjes-teller (zelfde slicer als de JS-tests)."""
    i = _APP.index(sig)
    j = _APP.index("{", i)
    diep = 0
    for k in range(j, len(_APP)):
        if _APP[k] == "{":
            diep += 1
        elif _APP[k] == "}":
            diep -= 1
            if diep == 0:
                return _APP[i:k + 1]
    raise AssertionError(f"ongebalanceerd: {sig}")


# ══════════════════════════════════════════════════════════════════════════════
# 1 — de native confirm is weg uit de races-flow
# ══════════════════════════════════════════════════════════════════════════════
class TestBevestiging:
    def test_races_gebruikt_geen_native_confirm_meer(self):
        for sig in ("function raceItem(", "async function rcPlaats("):
            assert "confirm(" not in _fn(sig), f"{sig} gebruikt nog het native confirm()"

    def test_races_bevestigt_via_de_gedeelde_dialoog(self):
        f = _fn("async function rcPlaats(")
        assert "await bevestigActie(" in f
        assert f.count("bevestigActie(") == 1, "één bevestigingspad, geen tweede variant ernaast"

    def test_bevestiging_is_een_gedeelde_primitief(self):
        """Naast de shared helpers (melding/leegState/foutState), niet in de races-sectie:
        de volgende module die een onomkeerbare actie bevestigt hoort 'm te hergebruiken."""
        assert "function bevestigActie(" in _APP
        assert _APP.index("function bevestigActie(") < _APP.index("const RC_CHIP_DAGEN")
        assert _APP.index("function foutState(") < _APP.index("function bevestigActie(")

    def test_dialoog_is_toegankelijk_en_hergebruikt_de_bestaande_chrome(self):
        f = _fn("function bevestigActie(")
        assert 'ov.className = "pk-overlay"' in f and "pk-modal" in f   # taal van de picker
        assert 'role="dialog"' in f and 'aria-modal="true"' in f
        assert "aria-labelledby=" in f                           # titel benoemt de dialoog
        assert 'aria-label="Sluiten"' in f

    def test_elke_uitgang_behalve_bevestigen_is_annuleren(self):
        f = _fn("function bevestigActie(")
        for uitgang in (".pk-x", ".pk-cancel", "Escape", "e.target === ov"):
            assert uitgang in f, f"geen annuleer-uitgang voor {uitgang}"
        assert f.count("klaar(true)") == 1, "alleen de bevestigknop mag true opleveren"

    def test_dialoog_ruimt_zichzelf_op(self):
        """Een blijvende keydown-listener of overlay is een lek dat pas veel later opvalt."""
        f = _fn("function bevestigActie(")
        assert 'removeEventListener("keydown"' in f and "ov.remove()" in f
        assert "if (af) return;" in f                            # precies één antwoord

    def test_css_voor_de_bevestiging_bestaat(self):
        assert ".pk-bevestig{" in _CSS and ".pk-tekst{" in _CSS and ".pk-detail{" in _CSS
        assert "white-space:pre-wrap" in _CSS                    # meerregelige wens leesbaar


# ══════════════════════════════════════════════════════════════════════════════
# 2 — afhandeling: één plek bepaalt de stand
# ══════════════════════════════════════════════════════════════════════════════
class TestAfhandeling:
    def test_plaatsing_kent_een_expliciete_dubbelpost_guard(self):
        f = _fn("async function rcPlaats(")
        assert "rcBezig.has(id)" in f and "rcBezig.add(id)" in f
        assert "rcBezig.delete(id)" in f and "finally" in f      # ook vrijgeven bij een fout

    def test_alleen_een_bevestigd_ok_handelt_de_race_af(self):
        f = _fn("async function rcPlaats(")
        assert "if (!akkoord) return;" in f                      # geannuleerd = niets
        assert 'if (uit.status === "ok")' in f                    # alleen 'ok' handelt af
        assert "rcNaMislukking(" in f                             # al het andere niet

    def test_foutpad_herstelt_het_eigen_actielabel(self):
        """De oude code zette de knop ALTIJD terug op 'Plaats wens' — ook op een kaart
        waar de actie 'Wens bijwerken' hoort te zijn."""
        f = _fn("function rcNaMislukking(")
        assert "btn.innerHTML = labelHtml;" in f                  # afgewezen → eigen actie terug
        assert 'btn.innerHTML = "' not in f, "nooit een vast label bij een afwijzing"

    def test_kaart_wordt_herbouwd_met_dezelfde_bouwer(self):
        """Geen losse DOM-patches naast raceItem: anders lopen twee weergaven uiteen."""
        f = _fn("function rcNaPlaatsing(")
        assert "raceItem(it)" in f and "replaceWith(" in f

    def test_zeven_dagen_filter_laat_de_afgehandelde_race_los(self):
        f = _fn("function rcNaPlaatsing(")
        assert 'rcScope === "7d"' in f and "rcItems.splice(i, 1)" in f and "kaart.remove()" in f
        assert "rcLeegHtml()" in f                               # laatste rij weg → lege staat

    def test_telling_is_een_afgeleide_van_de_stand(self):
        assert "function rcInfoTeken(" in _APP
        assert "rcInfoTeken();" in _fn("function rcNaPlaatsing(")
        assert "rcInfoTeken();" in _fn("async function laadRaces(")

    def test_home_chip_deelt_een_formulering_met_home(self):
        assert "function rcChipHtml(" in _APP
        assert "rcChipHtml(info.races)" in _fn("function vulCockpit(")
        assert "rcChipHtml(nieuw)" in _fn("function rcHomeChipBij(")

    def test_home_chip_respecteert_zijn_eigen_venster(self):
        """Het volledige overzicht bevat ook races van over een maand; die telde de
        chip nooit mee, dus een wens daarop mag hem ook niet verlagen."""
        f = _fn("function rcHomeChipBij(")
        assert "dagenTot(datum)" in f and "n > RC_CHIP_DAGEN" in f
        assert "Math.max(0," in f                                # nooit negatief

    def test_datumrekening_staat_op_een_plek(self):
        assert "function dagenTot(" in _APP
        assert "dagenTot(iso)" in _fn("function nlDagenTot(")     # label deelt de rekening


# ══════════════════════════════════════════════════════════════════════════════
# 2b — correctieronde: veroudering tijdens een lopend verzoek
# ══════════════════════════════════════════════════════════════════════════════
class TestVeroudering:
    def test_afhandeling_werkt_op_id_niet_op_het_oude_element(self):
        """Tijdens de POST kan de lijst herbouwd zijn (filterwissel/verversing). Het
        element en het race-object van het klikmoment zijn dan losgekoppeld."""
        f = _fn("function rcNaPlaatsing(")
        assert f.startswith("function rcNaPlaatsing(id, meta, tekst)")
        assert "rcKaart(id)" in f                                  # kaart op id opzoeken
        assert "rcItems.findIndex(x => x.id === id)" in f          # stand op id opzoeken
        assert "function rcKaart(" in _APP

    def test_oudere_laadrespons_mag_niet_meer_tekenen(self):
        f = _fn("async function laadRaces(")
        assert "const seq = ++rcLaadSeq;" in f
        assert "if (seq !== rcLaadSeq" in f
        assert f.index("const seq") < f.index("await api(url)")    # vóór het verzoek

    def test_bevestigde_plaatsing_overleeft_een_herbouw(self):
        """Een verse listing kan een net geplaatste wens nog als 'open' teruggeven
        (CommentCount loopt achter). Zonder overlay 'verdwijnt' de wens dan."""
        assert "rcGeplaatst.set(id, tekst)" in _fn("function rcNaPlaatsing(")
        assert "rcPasGeplaatstToe(r.items || [], zeven)" in _fn("async function laadRaces(")
        f = _fn("function rcPasGeplaatstToe(")
        assert "rcGeplaatst.delete(it.id)" in f                    # server bij → overlay los
        assert "gefilterd ? uit.filter(x => !x.wens_gegeven) : uit" in f

    def test_gefilterde_lijst_ruimt_niets_op_buiten_zijn_bereik(self):
        """Het 7-dagenfilter bevat geen races daarbuiten en geen races mét wens.
        Afwezigheid daarin bewijst dus niets over een race over 30 dagen."""
        f = _fn("function rcPasGeplaatstToe(")
        assert f.startswith("function rcPasGeplaatstToe(items, gefilterd)")
        assert "if (!gefilterd) {" in f
        # het opruimen-op-afwezigheid staat BINNEN die guard
        na = f.split("if (!gefilterd) {")[1]
        assert "if (!gezien.has(id)) rcGeplaatst.delete(id);" in na.split("}")[0] + na.split("}")[1]
        assert "rcPasGeplaatstToe(r.items || [], zeven)" in _fn("async function laadRaces(")

    def test_concepttekst_gaat_niet_verloren_bij_een_herbouw(self):
        f = _fn("function rcNaMislukking(")
        assert "if (kaart !== el)" in f and "v.value = tekst" in f

    def test_knop_wordt_hersteld_op_de_actuele_kaart(self):
        f = _fn("async function rcPlaats(")
        assert "rcKaart(id) || (el.isConnected ? el : null)" in f


# ══════════════════════════════════════════════════════════════════════════════
# 2c — correctieronde: onzekere verzenduitkomst
# ══════════════════════════════════════════════════════════════════════════════
class TestOnzekereUitkomst:
    def test_drie_uitkomsten_niet_twee(self):
        f = _fn("async function rcVerstuur(")
        assert '{ status: "ok" }' in f
        assert '"afgewezen"' in f and '"onbekend"' in f
        # Een verloren respons (fetch/parse gooit) is nooit een bewezen afwijzing.
        assert 'return { status: "onbekend" };' in f

    def test_auth_is_een_echte_afwijzing(self):
        """401 wordt vóór de handler afgevangen: het verzoek is nooit uitgevoerd."""
        assert 'e.message === "auth"' in _fn("async function rcVerstuur(")

    def test_onbekend_leidt_tot_een_controle(self):
        f = _fn("async function rcPlaats(")
        assert 'if (uit.status === "onbekend")' in f
        assert 'await rcControleer(id, tekst) === "geplaatst"' in f

    def test_controle_vergelijkt_de_VERSTUURDE_wens(self):
        """Bij bijwerken staat de VORIGE wens er al. `wens_gegeven === true` bewijst dus
        niets over de tekst die we net verstuurden."""
        f = _fn("async function rcControleer(")
        assert f.startswith("async function rcControleer(id, tekst)")
        assert "rcZelfdeWens(it.wens, tekst)" in f
        assert "rcControleer(id, tekst)" in _fn("async function rcPlaats(")

    def test_wensvergelijking_is_streng(self):
        f = _fn("function rcZelfdeWens(")
        assert "replace(/\\s+/g, \" \").trim()" in f          # witruimte normaliseren
        assert "!!g && g === norm(verstuurd)" in f            # leeg is nooit bewijs

    def test_overlay_laat_alleen_los_op_onze_eigen_tekst(self):
        f = _fn("function rcPasGeplaatstToe(")
        assert "it.wens_gegeven && rcZelfdeWens(it.wens, tekst)" in f

    def test_controle_kan_succes_bevestigen_maar_nooit_mislukking_bewijzen(self):
        """Kernregel: een nog niet bijgewerkte CommentCount is GEEN bewijs dat het
        verzenden is mislukt. De controle geeft dus alleen 'geplaatst' of 'onbekend'."""
        f = _fn("async function rcControleer(")
        assert '"geplaatst"' in f and '"onbekend"' in f
        assert '"mislukt"' not in f and '"afgewezen"' not in f
        assert re.findall(r'return\s+[^;]*?"(geplaatst|onbekend)"', f), "alleen die twee uitkomsten"
        assert 'api("/api/races")' in f                             # volledige lijst, niet het 7d-filter

    def test_geen_blinde_herhaalplaatsing(self):
        plaats = _fn("async function rcPlaats(")
        assert "rcOnzeker.has(id)" in plaats
        assert "Toch opnieuw plaatsen" in plaats                    # eigen, expliciete bevestiging
        mis = _fn("function rcNaMislukking(")
        assert "rcOnzeker.add(id)" in mis and "rcOnzeker.delete(id)" in mis
        assert "Opnieuw proberen" in mis

    def test_onzekerheid_wordt_benoemd_en_de_tekst_blijft(self):
        f = _fn("function rcNaMislukking(")
        assert "Onbekend of deze wens is aangekomen" in f
        assert "Mogelijk is de wens wél geplaatst." in f
        # Bij een ONBEKENDE uitkomst nooit beweren dat er niets is geplaatst.
        assert "niet geplaatst" not in f.split('rcOnzeker.add(id)')[1]


# ══════════════════════════════════════════════════════════════════════════════
# 2d — correctieronde: toetsenbord en focus
# ══════════════════════════════════════════════════════════════════════════════
class TestToetsenbord:
    def test_focus_blijft_in_de_dialoog(self):
        f = _fn("function bevestigActie(")
        assert 'e.key !== "Tab"' in f and "e.shiftKey" in f
        assert "laatste.focus()" in f and "eerste.focus()" in f
        assert "_FOCUS_SEL" in f and "_FOCUS_SEL = " in _APP

    def test_achtergrond_is_niet_bedienbaar(self):
        f = _fn("function bevestigActie(")
        assert 'n.setAttribute("inert", "")' in f
        assert 'removeAttribute("inert")' in f                      # en netjes terug

    def test_focus_herstel_wacht_op_de_aanroeper(self):
        """De plaatsknop staat UIT tijdens de bevestiging; focus op een uitgeschakelde
        knop doet niets. Herstellen mag dus pas nadat de aanroeper 'm weer aanzet."""
        f = _fn("function bevestigActie(")
        assert "setTimeout(" in f
        assert "vorigeFocus.isConnected && !vorigeFocus.disabled" in f

    def test_aanroeper_kan_het_focusdoel_benoemen(self):
        """Gevonden in de browser: `btn.disabled = true` BLURT de knop meteen, dus op het
        moment dat de dialoog opent is `document.activeElement` al de body. Wie zijn eigen
        knop uitzet moet dus zeggen waar de focus heen terug moet."""
        assert "opts.focusTerug || document.activeElement" in _fn("function bevestigActie(")
        plaats = _fn("async function rcPlaats(")
        assert plaats.count("focusTerug: btn") == 2, "beide bevestigingspaden benoemen het doel"
        assert plaats.index("btn.disabled = true") < plaats.index("focusTerug: btn")

    def test_na_succes_krijgt_focus_een_bestaand_doel(self):
        assert "function rcFocusNa(" in _APP
        f = _fn("function rcNaPlaatsing(")
        assert f.count("rcFocusNa(") == 3                           # elk van de drie takken
        g = _fn("function rcFocusNa(")
        assert "box.tabIndex = -1" in g                             # lege lijst blijft focusbaar


# ══════════════════════════════════════════════════════════════════════════════
# 3 — de schrijfkant is ONGEWIJZIGD (client-batch)
# ══════════════════════════════════════════════════════════════════════════════
class TestSchrijfkantOngemoeid:
    def test_endpoint_en_payload_ongewijzigd(self):
        assert '@app.post("/api/races/wens")' in _API
        assert "races.plaats_wens(body.id, body.tekst)" in _API
        assert 'jpost("/api/races/wens", { id, tekst })' in _fn("async function rcVerstuur(")
        assert "jpost(" not in _fn("async function rcPlaats("), "één verzendpad (rcVerstuur)"

    @_review_only
    def test_races_core_is_byte_identiek_aan_de_basis(self):
        r = subprocess.run(["git", "diff", "--name-only", f"{_BASIS}..{_MERGE}", "--", "pwa/races_core.py"],
                           cwd=_ROOT, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "", "races_core.py is gewijzigd — dit is een client-batch"

    @_review_only
    def test_geen_serverwijziging_in_deze_batch(self):
        gewijzigd = subprocess.run(["git", "diff", "--name-only", f"{_BASIS}..{_MERGE}", "--"],
                                   cwd=_ROOT, capture_output=True, text=True).stdout.split()
        py = [f for f in gewijzigd if f.endswith(".py") and not f.startswith("tests/")]
        assert py == [], f"onverwachte serverwijziging: {py}"


# ══════════════════════════════════════════════════════════════════════════════
# 4 — client-change → versies mee
# ══════════════════════════════════════════════════════════════════════════════
class TestVersies:
    def test_service_worker_en_assets_zijn_gebumpt(self):
        """Git-vrij: `_BASIS` draaide op v135, dus alles vanaf v136 is een bump. Blijft
        kloppen bij elke volgende ronde (die bumpt verder omhoog)."""
        sw = (_ROOT / "pwa" / "static" / "sw.js").read_text(encoding="utf-8")
        html = (_ROOT / "pwa" / "static" / "index.html").read_text(encoding="utf-8")
        nu = int(re.search(r"bebetter-shell-v(\d+)", sw).group(1))
        assert nu >= 136, f"service-worker niet gebumpt t.o.v. {_BASIS} (v135): v{nu}"
        versies = set(re.findall(r"\?v=(\d+[a-z])", html))
        assert len(versies) == 1, f"asset-versies lopen uiteen: {versies}"


# ══════════════════════════════════════════════════════════════════════════════
# 5 — scope-lock
# ══════════════════════════════════════════════════════════════════════════════
class TestScope:
    @_review_only
    def test_alleen_verwachte_bestanden_gewijzigd(self):
        """Gepind op `_BASIS.._MERGE`: het venster van DEZE batch. Een open vergelijking
        met de werkboom wordt bij de volgende ronde een permanente rem."""
        gewijzigd = set(subprocess.run(["git", "diff", "--name-only", f"{_BASIS}..{_MERGE}", "--"],
                                       cwd=_ROOT, capture_output=True, text=True).stdout.split())
        verwacht = {
            "pwa/static/app.js", "pwa/static/styles.css",
            "pwa/static/index.html", "pwa/static/sw.js",
            "tests/js/races_afhandeling.test.mjs",
            "tests/js/home_teampuls_cleanup.test.mjs",
            "tests/test_races_afhandeling_v1.py",
            "tests/test_app_polish_remaining_pages.py",
        }
        assert gewijzigd <= verwacht, f"buiten scope: {sorted(gewijzigd - verwacht)}"

    def test_geen_nieuwe_module_of_route(self):
        """Deze batch voegt geen navigatie of endpoint toe — alleen afhandeling."""
        assert _APP.count('else if (view === "races")') == 2   # applyRoute + openModuleFromNav
        assert _API.count('@app.post("/api/races') == 1
        assert _API.count('@app.get("/api/races') == 1
