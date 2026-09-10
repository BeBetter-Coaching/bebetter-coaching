"""App Polish + Remaining Pages Alignment (7 sep 2026).

Finite presentatie-mijlpaal: de legacy-pagina's (Races, Intake, Strippenkaart, Documenten,
Administratie, Meer/Praktijk, Teampuls, Schema-verloop) spreken dezelfde taal als Home,
Feedback, Workspace, Dossier en Schema. Geen nieuwe logica, geen routes, geen truth.

Zie docs/audits/APP_POLISH_REMAINING_PAGES_2026-09-07.md.

    python3 -m pytest tests/test_app_polish_remaining_pages.py -q
"""
import os
import re
import re as _re
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_IDX = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()
_CSS = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()
_DS = open(os.path.join(_ROOT, "pwa", "static", "design-system.css")).read()
_DC = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()

# Scope-lock-venster: basis → merge (vastgepind, geen bewegend doel op HEAD).
_BASE, _TIP = "7cd278f", "ada006c"


def _fn(name: str) -> str:
    """Body van één JS-functie (brace-matching)."""
    i = _APP.index(name)
    j = _APP.index("{", i)
    d = 0
    for k in range(j, len(_APP)):
        if _APP[k] == "{":
            d += 1
        elif _APP[k] == "}":
            d -= 1
            if d == 0:
                return _APP[i:k + 1]
    raise AssertionError(name)


# De acht modules die uit de "legacy"-hoek moesten komen + hun canonieke paginatitel.
_PAGINAS = {
    "atleten": "Atleten", "intake": "Intake", "strippen": "Strippenkaart",
    "schema": "Schema bouwen", "documenten": "Documenten", "races": "Races",
    "schema-verloop": "Schema-verloop", "teampuls": "Teampuls",
    "admin": "Administratie", "meer": "Praktijk &amp; account",
}


# ══════════════════════════════════════════════════════════════════════════════
# 1 — één paginakop-ritme
# ══════════════════════════════════════════════════════════════════════════════
class TestPaginakop:
    def test_elke_module_opent_met_titel_plus_doelregel(self):
        for view, titel in _PAGINAS.items():
            blok = _IDX.split(f'data-view="{view}"', 1)[1][:600]
            assert "pagehead" in blok, f"{view} mist de gedeelde paginakop"
            assert f"<h1>{titel}</h1>" in blok, f"{view} heeft niet de canonieke titel"
            assert 'class="pagesub"' in blok, f"{view} mist de doelregel"

    def test_geen_kale_h1_meer_in_een_appbar(self):
        """Precies dít was de luidste 'oude pagina'-aanwijzing."""
        kaal = re.findall(r'<header class="appbar"><h1>', _IDX)
        assert not kaal, f"{len(kaal)} module(s) hebben nog een kale titel"

    def test_paginakop_heeft_eigen_stijl(self):
        assert ".pagehead{" in _CSS and ".pagesub{" in _CSS

    def test_zelfde_bestemming_zelfde_label(self):
        """Regel 1: de lade heette 'Meer' terwijl de zijbalk 'Praktijk & account' zei."""
        assert "Praktijk &amp; account</span>" in _IDX          # zijbalk
        assert "<h1>Praktijk &amp; account</h1>" in _IDX        # paginatitel
        assert "<h1>Meer</h1>" not in _IDX


# ══════════════════════════════════════════════════════════════════════════════
# 2 — datums: geen rauwe ISO meer in coach-facing kaarten
# ══════════════════════════════════════════════════════════════════════════════
class TestDatums:
    def test_primitieven_bestaan(self):
        assert "function nlDatumTijd(" in _APP
        assert "function nlDagenTot(" in _APP
        assert "function nlWaarde(" in _APP

    def test_schema_verloop_toont_geen_rauwe_iso(self):
        rij = _fn("function svItem(")
        assert 'esc(it.laatste)' not in rij and "nlDatum(it.laatste)" in rij
        assert 'esc(it.zichtbaar_tot)' not in rij and "nlDatum(it.zichtbaar_tot)" in rij
        assert "laatste training " in rij                        # ambigu 'laatste' → benoemd
        assert "training(en)" not in rij                         # meervoud via nlAantal

    def test_races_toont_leesbare_datum_en_afstand(self):
        kaart = _fn("function raceItem(")
        assert "nlDatum(it.datum)" in kaart and "nlDagenTot(it.datum)" in kaart
        assert "esc(it.datum)" not in kaart

    def test_intake_toont_geen_iso_timestamp(self):
        f = _fn("async function laadInbox(")
        assert "nlDatumTijd(sub.ingezonden)" in f
        assert "esc(sub.ingezonden)" not in f

    def test_overige_coachkaarten_normaliseren_datums(self):
        # Strippenkaart: de ring-kaart is vervangen door de mobiele afboeklijst. De BELOFTE
        # blijft dezelfde — nergens een rauwe ISO-datum in coach-facing tekst — dus toetsen
        # we de renderer die er nu is, plus de detailregel met de afboekhistorie.
        assert "nlDatum(k.laatst)" in _fn("function skRijBinnen(")          # strippenkaart-rij
        assert "nlDatum(k.laatst)" in _fn("function skVerversRij(")         # dezelfde rij na een write
        assert "nlDatum(h)" in _fn("function skDetail(")                    # historie in het detail
        for verboden in ("esc(k.laatst)", "esc(h)}"):
            assert verboden not in _APP
        assert "nlDatum(k.datum_grens)" in _fn("function tekenAdmin(")      # administratie
        assert "nlDatum(r.datum)" in _fn("function tpRenderSignalen(")      # teampuls
        assert "nlDatum(x.date)" in _fn("function dsStream(")               # dossier-stream

    def test_geen_bekende_rauwe_iso_patronen_meer(self):
        """Vangnet op de exacte P2's: `laatste 2026-09-11` en `2026-09-01T11:53`."""
        for verboden in ('" · laatste " + esc(it.laatste)', "esc(sub.ingezonden)",
                         'esc(it.datum)} · ${esc(it.race)'):
            assert verboden not in _APP, f"rauwe ISO-bron nog aanwezig: {verboden}"

    def test_nl_datumtijd_semantiek(self):
        """De formatter zelf: met tijd → datum + tijd, zonder tijd → alleen datum."""
        f = _fn("function nlDatumTijd(")
        assert "[T ]" in f and "nlDatum(s)" in f

    def test_nl_dagen_tot_kent_de_randgevallen(self):
        f = _fn("function nlDagenTot(")
        for woord in ('"vandaag"', '"morgen"', '"gisteren"', "over ${n} dagen"):
            assert woord in f


# ══════════════════════════════════════════════════════════════════════════════
# 3 — één familie lege/fout-staten
# ══════════════════════════════════════════════════════════════════════════════
class TestStaten:
    def test_gedeelde_helpers_bestaan(self):
        assert "function leegState(" in _APP and "function foutState(" in _APP
        assert ".leeg-sub{" in _CSS and ".leeg.fout" in _CSS

    def test_foutstaat_is_eerlijk_en_actioneerbaar(self):
        f = _fn("function foutState(")
        assert "Opnieuw proberen" in f
        assert "er is niets gewijzigd" in f                      # eerlijk: geen datamutatie
        assert "leeg fout" in f                                  # zelfde familie als .leeg

    def test_geen_kale_geen_verbinding_meldingen_meer(self):
        """14 doodlopende `<p class="muted center">Geen verbinding.</p>` → gedeelde staat."""
        kaal = _APP.count('\'<p class="muted center">Geen verbinding.</p>\'')
        assert kaal == 0, f"{kaal} kale foutmelding(en) over"

    def test_elke_hoofdlijst_heeft_een_retry(self):
        for f, retry in (("async function laadRaces(", "foutState(box, laadRaces)"),
                         ("async function laadSchemaVerloop(", "foutState(box, laadSchemaVerloop)"),
                         ("async function laadInbox(", "foutState(box, laadInbox)"),
                         ("async function laadDocs(", "foutState(keuze, laadDocs)"),
                         ("async function laadSchema(", "foutState(box, laadSchema)")):
            assert retry in _fn(f), f"{f} mist een retry-pad"

    def test_niet_gekoppeld_is_een_lege_staat_geen_fout(self):
        """FinalSurge-niet-gekoppeld is geen storing: kalme lege staat, geen retry-knop."""
        for f in ("async function laadRaces(", "async function laadSchemaVerloop("):
            body = _fn(f)
            assert 'leegState("alert", "FinalSurge nog niet gekoppeld."' in body

    def test_pending_belasting_is_geen_kalme_lege_stand(self):
        """'Unknown ≠ calm': een nog-niet-berekende stand zegt dat, en zegt wat je kunt doen."""
        body = _fn("function homeMonBelasting(")
        assert "voor het eerst berekend" in body and "leegState(" in body


# ══════════════════════════════════════════════════════════════════════════════
# 4 — Races / Intake / Documenten hiërarchie
# ══════════════════════════════════════════════════════════════════════════════
class TestPaginas:
    def test_races_composer_is_gelabeld_en_kent_zijn_actie(self):
        kaart = _fn("function raceItem(")
        assert 'class="lbl"' in kaart                              # composer heeft een label
        assert "Wens bijwerken" in kaart and "Plaats wens" in kaart  # actie volgt de staat
        assert kaart.count('class="btn primary"') == 1              # één primaire actie
        assert '.rc-when{' in _CSS and ".rc-status{" in _CSS

    def test_races_meervoud_is_nederlands(self):
        # De inforegel is verhuisd van `laadRaces` naar `rcInfoTeken` (één afgeleide van
        # `rcItems`, zodat de telling ook ná een geplaatste wens klopt). De GARANTIE is
        # ongewijzigd: meervoud via nlAantal, nergens een handmatige `s`-ternary.
        f = _fn("function rcInfoTeken(")
        assert 'nlAantal(rcItems.length, "race", "races")' in f
        assert 'race${rcItems.length === 1 ? "" : "s"}' not in f
        assert "nlAantal" not in _fn("async function laadRaces(")   # niet op twee plekken

    def test_intake_onderscheidt_nieuw_en_los(self):
        assert '<span class="mrow-tag soon-tag">nieuw</span>' in _fn("async function laadInbox(")
        orph = _fn("async function laadOrphanIntakes(")
        assert '"kandidaat" : "niet gekoppeld"' in orph

    def test_onbekende_maten_worden_niet_als_data_getoond(self):
        """`Recente week ? km · gevoel — vs —` leest als een meting terwijl er niets is."""
        assert "function pulsMaten(" in _APP
        f = _fn("function pulsMaten(")
        assert "niet bekend" in f
        rij = _fn("function pulsItem(")
        assert 'km_recent ?? "?"' not in rij and 'gevoel_recent ?? "—"' not in rij
        assert "pulsMaten(m)" in rij
        assert 'd.gevoel_recent ?? "—"' not in _APP        # ook de Home-prioriteitskaart

    def test_documenten_toont_een_uitkomststaat(self):
        f = _fn("async function genereerDoc(")
        assert "docs-ok" in f and "docs-err" in f
        assert ".docs-ok{" in _CSS and ".docs-err{" in _CSS
        assert 'status.textContent = "Mislukt: "' not in _APP     # geen rauwe servertekst meer

    def test_meer_is_een_directory_met_gescheiden_account(self):
        assert 'class="sec-label meer-scheiding"' in _IDX
        assert ".meer-scheiding{" in _CSS
        for groep in ("Atleet", "Team", "Praktijk", "Account &amp; app"):
            assert f">{groep}</p>" in _IDX


# ══════════════════════════════════════════════════════════════════════════════
# 5 — athleteNav: één ritme op alle vier de atleet-oppervlakken
# ══════════════════════════════════════════════════════════════════════════════
class TestAthleteNav:
    def test_alle_vier_de_routes_dragen_de_nav(self):
        for view in ("atleten", "dossier", "schema", "workspace"):
            assert f'athleteNav("{view}"' in _APP

    def test_een_ritme_eigen_regel_links_uitgelijnd(self):
        regel = [r for r in _CSS.splitlines() if ".d-head>.anav" in r][0]
        assert "flex:1 0 100%" in regel and "order:99" in regel
        assert "margin:0 0 0 auto" not in regel                   # niet meer rechts inline
        assert ".d-head{display:flex;flex-wrap:wrap" in _CSS
        assert ".sb-ctx-head{display:flex;flex-wrap:wrap" in _CSS

    def test_labels_en_volgorde_ongewijzigd(self):
        nav = _fn("function athleteNav(")
        opts = nav.split("const opts = [", 1)[1].split("];", 1)[0]   # de volgorde, niet het commentaar
        assert opts.index("Profiel") < opts.index("Dossier") < opts.index("Schema")
        assert "openWorkspace(" in nav and "openAthleteModule(" in nav
        for verboden in ('"Nu"', '"Historie"', '"Plan"'):
            assert verboden not in nav


# ══════════════════════════════════════════════════════════════════════════════
# 6 — Dossier-presentatie: nette datum, geen kaal streepje
# ══════════════════════════════════════════════════════════════════════════════
class TestDossierPresentatie:
    def test_nl_datum_helper(self):
        sys.path.insert(0, os.path.join(_ROOT, "pwa"))
        import dossier_cockpit as DCK
        assert DCK._nl_datum("2026-08-18") == "18 aug"
        assert DCK._nl_datum("") == ""
        assert DCK._nl_datum("kwartaal 3") == "kwartaal 3"        # onparseerbaar → onveranderd

    def test_lege_bronwaarde_wordt_niet_getoond(self):
        import dossier_cockpit as DCK
        for leeg in ("-", "—", "?", " ", "onbekend", "n.v.t."):
            assert DCK._zeg_iets(leeg) == ""
        assert DCK._zeg_iets("last van mijn knie") == "last van mijn knie"

    def test_klachtkaart_zegt_iets_zinnigs_bij_een_leeg_veld(self):
        """De Tymo-case: `Klacht: onbekend — actief — - · 2026-08-18`."""
        assert "geen omschrijving vastgelegd" in _DC
        assert "_nl_datum(datum) if datum else" in _DC

    def test_kaarttitel_en_ranking_onaangeroerd(self):
        assert 'f"Klacht: {area} — {st_txt}"' in _DC              # Workspace parst deze titel
        assert "def _complaint_rank(" in _DC and "def _neg_datum(" in _DC
        assert "cards.sort(key=lambda c: (c.get(\"rank\", 9), _complaint_rank(c), _neg_datum(c)," in _DC

    def test_run_afwijking_en_bronverval_ook_leesbaar(self):
        assert '_nl_datum(d.get("datum") or e.get("observed_at") or "")' in _DC
        assert '_nl_datum(ev.observed_at or "")' in _DC


# ══════════════════════════════════════════════════════════════════════════════
# 7 — responsive: code-niveau mismatches weg
# ══════════════════════════════════════════════════════════════════════════════
class TestResponsive:
    def test_feedback_krijgt_een_tussenstap_onder_1360(self):
        """Bij 1101px hield de middenkolom (het case-detail) ~231px over."""
        assert "@media (min-width:1101px) and (max-width:1359px){" in _DS
        blok = _DS.split("@media (min-width:1101px) and (max-width:1359px){", 1)[1][:400]
        assert "grid-template-columns:minmax(240px,282px) minmax(0,1fr)" in blok
        assert "grid-column:1 / -1" in blok                        # context eronder, volle breedte

    def test_middenkolom_krijgt_ruimte_net_boven_de_grens(self):
        """Op 1400px stonden beide zijkolommen op hun maximum → case-detail bleef 418px.
        Gemeten na de fix: 476px (browser, 1400x900)."""
        assert "@media (min-width:1360px) and (max-width:1499px){" in _DS
        blok = _DS.split("@media (min-width:1360px) and (max-width:1499px){", 1)[1][:260]
        assert "minmax(0,2.2fr)" in blok

    def test_mobiele_stapeling_blijft_op_1100(self):
        assert "@media (max-width:1100px){" in _DS

    def test_dossier_js_en_css_delen_een_drempel(self):
        assert "function dcIsNarrow(" in _APP
        assert "window.innerWidth < 1280" in _fn("function dcIsNarrow(")
        assert "const isNarrow = dcIsNarrow();" in _fn("function dcRender(")
        assert "@media (max-width:1279px){ .dc-grid{grid-template-columns:1fr}" in _DS
        assert "@media (max-width:1180px){ .dc-grid" not in _DS

    def test_dossier_herrendert_bij_een_drempelomslag(self):
        f = _fn("function dcBindResize(")
        assert "dcIsNarrow() !== _dcNarrow" in f and "dcRender(_dcActiveWrap, _dcActiveVm)" in f
        assert "isConnected" in f                                  # geen render op een losse node
        assert "dcBindResize(wrap);" in _fn("function dcRender(")   # ook vanuit de stack


# ══════════════════════════════════════════════════════════════════════════════
# Locks — presentatie-only, geen truth/route/Feedback-architectuur
# ══════════════════════════════════════════════════════════════════════════════
def _diff():
    return subprocess.run(["git", "diff", "--name-only", _BASE, _TIP, "--"],
                          cwd=_ROOT, capture_output=True, text=True).stdout.split()


class TestLocks:
    def test_alleen_presentatiebestanden_gewijzigd(self):
        verwacht = {"pwa/static/app.js", "pwa/static/index.html", "pwa/static/styles.css",
                    "pwa/static/design-system.css", "pwa/static/sw.js",
                    "pwa/dossier_cockpit.py",
                    "docs/audits/APP_POLISH_REMAINING_PAGES_2026-09-07.md"}
        onverwacht = [f for f in _diff() if f not in verwacht and not f.startswith("tests/")]
        assert not onverwacht, f"buiten scope gewijzigd: {onverwacht}"

    def test_geen_truth_cache_of_queue_module_geraakt(self):
        diff = _diff()
        for verboden in ("pwa/api.py", "pwa/feedback_core.py", "pwa/home_core.py",
                         "pwa/teampuls_core.py", "pwa/coach_read.py", "pwa/athlete_read.py",
                         "pwa/races_core.py", "pwa/schema_core.py", "pwa/intake_core.py",
                         "pwa/strippen_core.py", "pwa/admin_core.py", "pwa/schema_verloop_core.py",
                         "belasting.py", "fs_client.py", "ai_feedback.py", "feedback_atoms.py",
                         "feedback_facts.py", "feedback_copy.py", "feedback_obligations.py",
                         "metric_authority.py", "intake_store.py",
                         "pwa/brain/derive.py", "pwa/brain/projections.py",
                         "pwa/brain/adapter.py", "pwa/brain/complaints.py"):
            assert verboden not in diff, f"buiten scope: {verboden}"

    def test_dossier_cockpit_alleen_presentatie(self):
        """De cockpit-wijziging raakt uitsluitend de TEKST van een kaart, niet welke kaarten
        er zijn of in welke volgorde ze staan. Bewijs: elke regel die over selectie, rank of
        ordening gaat is identiek aan de basis."""
        import re as _re
        oud = subprocess.run(["git", "show", f"{_BASE}:pwa/dossier_cockpit.py"],
                             cwd=_ROOT, capture_output=True, text=True).stdout

        def _ordening(src):
            pat = _re.compile(r"(rank=\d+|cards\.sort\(.*|_LIVE|def _complaint_rank|def _neg_datum|"
                              r"status = |_card_obj\(\"[a-z_]+\")")
            return [m.group(0) for m in pat.finditer(src)]

        assert _ordening(_DC) == _ordening(oud), "selectie/ranking/ordening gewijzigd"

    def test_routeset_ongewijzigd(self):
        views = set(_re.findall(r'data-view="([a-z-]+)"', _IDX))
        assert views == {"home", "atleten", "dossier", "workspace", "intake", "strippen",
                         "schema", "feedback", "documenten", "races", "schema-verloop",
                         "teampuls", "admin", "meer"}
        assert "function activeAthleteKey(" in _APP
        assert "_ATHLETE_VIEWS" in _APP

    def test_feedback_module_onaangeraakt(self):
        """Feedback-queue, ordering, copy en generatie blijven exact zoals ze waren."""
        for anker in ("function fbRowHtml(", "function fbDateLabel(", "async function fbGen(",
                      "async function fbSend(", "function fbThreadHtml(", "async function fbEnter("):
            assert anker in _APP
        assert "FB_CAT[it.categorie]" in _fn("function fbRowHtml(")

    def test_schema_engine_en_intake_guard_intact(self):
        assert "function sbModeBar(" in _APP and "function sbWireModeBar(" in _APP
        assert "sbDraftSave" in _APP and "built_plan_hash" in _APP
        assert "nieuw:" in _APP                                    # intake-identiteitsguard
        assert "/api/races/wens" in _APP                            # FS-write-pad ongewijzigd
        assert "/api/admin/overzicht" in _APP and "adminPin" in _APP

    def test_client_versie_gebumpt(self):
        """Historisch feit over DEZE build; leest op `_TIP` zodat een latere ronde vrij
        kan bumpen zonder deze lock te breken."""
        def _op_tip(pad):
            return subprocess.run(["git", "show", f"{_TIP}:{pad}"],
                                  cwd=_ROOT, capture_output=True, text=True).stdout
        assert "bebetter-shell-v135" in _op_tip("pwa/static/sw.js")
        idx = _op_tip("pwa/static/index.html")
        assert idx.count("?v=139a") == 3 and "?v=138a" not in idx


import re as _re  # noqa: E402  (gebruikt in TestLocks.test_routeset_ongewijzigd)
