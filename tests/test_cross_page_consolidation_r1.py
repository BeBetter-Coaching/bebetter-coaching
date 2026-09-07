"""Cross-Page Consolidation Round 1 — A1-A5 + B1-B3.

DOEL: de PWA merkbaar eenvoudiger maken zonder één correctness-lock aan te raken.
Alles in deze ronde is PRESENTATIE, NAVIGATIE of HERGEBRUIK van een bestaand endpoint.

BEWEZEN OORZAKEN (Gate 0, uit de cross-page audit):
  A1  `prioContext`/`prioDetailHtml` labelden de knop 'Dossier', maar `prioDoe` routeert
      `act:"dossier"` naar `openAthleteModule("atleten", …)` → de PROFIEL-module. Teampuls'
      'Dossier →' gaat wél naar #dossier. Eén woord, twee bestemmingen — in strijd met de
      naamgevingsregel in athleteNav zelf. De ROUTE is gelockt, het LABEL niet.
  A2  Workspace, Dossier én Schema bouwen deelden alle drie `#ic-brain` in de zijbalk,
      terwijl `ic("brain")` overal elders AI/Masterbrein betekent.
  A3  Vier datumweergaven voor dezelfde trainingsdatum (`09-03`, `3 sep`, `wo 3 sep`,
      rauwe ISO) en zes enkelvoud/meervoud-fouten ("1 runs in dit venster").
  A4a `_attention` had één elif met een OR over TWEE evidence-keys (rpe_trend én
      feeling_trend) → bij beide waarnemingen twee kaarten met dezelfde titel.
  A4b `dcBuildEvents` filtert klachten bewust naar de VERLEDEN-kolom; is een klacht het
      enige attention-item, dan bleef `now` leeg en vuurde de fallback met de titel
      'Geen open klacht of signaal' — naast diezelfde klacht op hetzelfde scherm.
  B1  Workspace was de ENIGE atleetpagina zonder athleteNav (de `workspace`-tak en de
      `.ws-anchor`-styling bestonden al, maar werden nooit aangeroepen).
  B2  Teampuls == Home's belasting-signaal zonder suppressie (zelfde
      `belasting.zichtbare_resultaten`); Schema-verloop == Home's schema-signaal met een
      breder venster (zelfde `FS.get_schema_end_dates`). Filterstanden, geen pagina's.
  B3  De weekbriefing (uniek) stond onderaan Teampuls, ónder die dubbele lijst.
"""
import os
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_ROOT, os.path.join(_ROOT, "pwa")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dossier_cockpit as _dc                  # noqa: E402
from brain.models import Evidence, DERIVED, ACTIVE, MEDIUM   # noqa: E402

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_IDX = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()
_CSS = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()
_DS = open(os.path.join(_ROOT, "pwa", "static", "design-system.css")).read()
_DC_SRC = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()

# Scope-lock-venster van DEZE ronde: van de basis waarop R1 gebouwd is tot de merge die
# productie werd. Vastgepind (niet open op HEAD), zodat het een historisch feit over de
# R1-build blijft en niet omvalt zodra een latere, eigen gescopede ronde iets aanraakt.
_BASE = "4959360"
_TIP = "9a506cd"


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


def _diff():
    return subprocess.run(["git", "diff", "--name-only", _BASE, _TIP, "--"],
                          cwd=_ROOT, capture_output=True, text=True).stdout.split()


class _St:
    athlete_key, naam, overall = "u1", "Test", "ATTENTION"

    def __init__(self, evs):
        self.evidence, self.conflicts, self.source_gaps = evs, [], []

    def get(self, cid):
        return next((e for e in self.evidence if e.id == cid), None)


# ══ T1/T2 — A1: het label vertelt wat de knop opent, de route blijft gelockt ══
class TestA1Label:
    def test_t1_home_knop_heet_profiel(self):
        ctx = _fn("function prioContext")
        assert 'label: "Profiel"' in ctx
        assert 'label: "Dossier"' not in ctx
        assert 'act: "dossier"' in ctx, "de gelockte ACTIE-sleutel blijft ongewijzigd"
        det = _fn("function prioDetailHtml")
        assert '{ act: "dossier", label: "Profiel", icon: "user-plus" }' in det

    def test_t1_route_is_ongewijzigd(self):
        doe = _fn("function prioDoe")
        assert 'if (act === "dossier") { prioHerstelUk = prioOpenUk; openAthleteModule("atleten", it.user_key); return; }' in doe

    def test_t2_echte_dossier_links_heten_nog_dossier(self):
        nav = _fn("function athleteNav")
        assert '{ view: "dossier", label: "Dossier" }' in nav
        assert '{ view: "atleten", label: "Profiel" }' in nav
        # Teampuls-kaart en Workspace-fallback wijzen allebei naar de ÉCHTE dossier-module.
        assert 'el.querySelector("[data-dossier]").addEventListener("click", () => openAthleteModule("dossier", it.user_key));' in _APP
        assert "openAthleteModule('dossier','${esc(key)}')" in _fn("function wsNextHtml")

    def test_home_label_botst_niet_meer(self):
        """Precies één betekenis van 'Dossier' in de coach-copy van de Home-werklijst."""
        for body in (_fn("function prioContext"), _fn("function prioDetailHtml")):
            assert '"Dossier"' not in body


# ══ T3 — A2: drie onderscheiden nav-iconen ═══════════════════════════════════
class TestA2Iconen:
    def test_t3_nav_iconen_zijn_verschillend(self):
        import re
        nav = re.findall(r'nav-item[^>]*data-open-view="([a-z-]+)"[^>]*>'
                         r'<svg class="ic"><use href="#(ic-[a-z-]+)"', _IDX)
        per_view = dict(nav)
        for v in ("workspace", "dossier", "schema"):
            assert v in per_view, f"{v} verdween uit de navigatie"
        drie = {per_view["workspace"], per_view["dossier"], per_view["schema"]}
        assert len(drie) == 3, f"iconen niet onderscheiden: {drie}"

    def test_t3_brain_is_niet_langer_een_navigatie_icoon(self):
        """`ic-brain` betekent overal AI/Masterbrein — dus geen bestemmings-icoon."""
        assert '<use href="#ic-brain"/></svg><span>' not in _IDX
        assert 'ic-brain' in _IDX, "het symbool zelf blijft bestaan (AI-gebruik in app.js)"

    def test_t3_geen_icoon_regressie_elders(self):
        for n in ("ic-home", "ic-message", "ic-users", "ic-pulse", "ic-flag",
                  "ic-clock", "ic-mail", "ic-ticket", "ic-file", "ic-euro",
                  "ic-more", "ic-activity", "ic-note", "ic-calendar", "ic-brain"):
            assert f'<symbol id="{n}"' in _IDX


# ══ T4/T5 — A5: praktijkmodules uit de dagelijkse navigatie, wél bereikbaar ══
class TestA5Praktijk:
    def _views(self):
        import re
        return set(re.findall(r'<section class="view[^"]*" data-view="([a-z-]+)"', _IDX))

    def test_t4_elke_module_blijft_direct_bereikbaar(self):
        import re
        nav = set(re.findall(r'nav-item[^>]*data-open-view="([a-z-]+)"', _IDX))
        meer = _IDX[_IDX.index('data-view="meer"'):]
        kaarten = set(re.findall(r'listcard" data-open-view="([a-z-]+)"', meer))
        onbereikbaar = self._views() - nav - kaarten
        assert not onbereikbaar, f"niet bereikbaar: {sorted(onbereikbaar)}"

    def test_t5_mobiele_meer_toont_de_praktijkmodules(self):
        meer = _IDX[_IDX.index('data-view="meer"'):]
        for v in ("intake", "strippen", "documenten", "admin"):
            assert f'listcard" data-open-view="{v}"' in meer

    def test_t5_meer_toont_ook_de_niet_primaire_teamroutes(self):
        """B2: Teampuls/Schema-verloop zijn geen primaire nav meer → lade moet ze dragen."""
        meer = _IDX[_IDX.index('data-view="meer"'):]
        for v in ("teampuls", "schema-verloop"):
            assert f'listcard" data-open-view="{v}"' in meer

    def test_praktijk_ingang_draagt_het_intake_aantal(self):
        """De zijbalk verloor de Intake-knop; het aantal mag niet stilvallen."""
        zij = _IDX[_IDX.index('<aside class="sidebar">'):_IDX.index("</aside>")]
        assert 'data-open-view="meer"' in zij and 'class="nav-badge"' in zij
        assert '<span class="lc-badge nav-badge" hidden></span>' in _IDX
        assert ".listcard .lc-badge{" in _CSS
        assert '$$(".nav-badge").forEach' in _APP        # setBadge ongewijzigd

    def test_geen_routes_gewijzigd(self):
        """A5 verplaatst ALLEEN ingangen. Elke view-sectie bestaat nog."""
        assert self._views() == {
            "home", "atleten", "dossier", "workspace", "intake", "strippen", "schema",
            "feedback", "documenten", "races", "schema-verloop", "teampuls", "admin", "meer"}

    def test_account_en_installatie_intact(self):
        for el in ('id="faceid-enable"', 'id="install"', 'id="uitloggen"',
                   'id="wie-ingelogd"', 'id="bron"'):
            assert el in _IDX

    def test_home_ook_nog_triggers_intact(self):
        home = _fn("async function renderHome")
        assert '"/api/intake/inbox"' in home and '"/api/kaarten"' in home
        assert 'kaartItem("mail"' in home and 'kaartItem("ticket"' in home
        assert 'setBadge(nNieuw)' in home


# ══ T6/T7/T8/T9 — A3: copy- en datumconsistentie ═════════════════════════════
class TestA3Copy:
    def test_t6_meervoud_helper_bestaat_en_wordt_gebruikt(self):
        assert "function nlAantal(n, enkel, meerv)" in _APP
        for site in ('nlAantal(nRuns, "training", "trainingen")',
                     'nlAantal(items.length, "atleet", "atleten")',
                     'nlAantal(c.included, "training", "trainingen")',
                     'nlAantal(p.counts.success, "training", "trainingen")',
                     'nlAantal(c.weken, "week", "weken")'):
            assert site in _APP, site

    def test_t6_geen_kale_meervouden_meer(self):
        for kaal in ("${nRuns} runs", "${items.length} atleten", "${c.included} trainingen",
                     "${p.counts.success} trainingen", "${c.weken} weken",
                     "${esc(String(ctx.weken))} weken"):
            assert kaal not in _APP, kaal

    def test_t6_runs_heet_trainingen_in_coach_copy(self):
        assert "runs in dit venster" not in _fn("function wsRender")
        assert 'nlAantal(nRuns, "training", "trainingen")} in dit venster' in _APP

    def test_t7_gedeelde_datumformatter(self):
        assert "function nlDatum(iso)" in _APP and "const _NL_MND = " in _APP
        # Home (belasting-onderbouwing + sessies), Profiel, Teampuls lezen dezelfde formatter.
        assert "esc(nlDatum(r.datum))" in _fn("function prioSignaalBody")
        assert "esc(nlDatum(t.datum))" in _fn("function prioSessiesHtml")
        assert "esc(nlDatum(t.datum))" in _fn("function tekenAtleet")
        assert "esc(nlDatum(r.datum))" in _fn("function pulsItem")

    def test_t8_geen_rauwe_iso_trainingsdatum_op_teampuls(self):
        puls = _fn("function pulsItem")
        assert "esc(r.datum)" not in puls, "rauwe ISO-datum op een gewone coachkaart"

    def test_t9_geen_ambigue_mm_dd_meer(self):
        for body in (_fn("function prioSignaalBody"), _fn("function prioSessiesHtml"),
                     _fn("function tekenAtleet")):
            assert '.slice(5)' not in body

    def test_feedback_houdt_zijn_eigen_dagtaal(self):
        """`Vandaag`/`Gisteren` is in de wachtrij betekenisvol en blijft."""
        assert "function fbDateLabel(" in _APP
        lab = _fn("function fbDateLabel")
        assert '"Vandaag"' in lab and '"Gisteren"' in lab

    def test_feedback_contextkop_is_uniform(self):
        assert '<div class="fb-ctx-h">Context</div>' not in _APP
        assert _APP.count('<div class="fb-ctx-h">Relevante context</div>') >= 4

    def test_km_op_monitoringkaarten_via_nlnum(self):
        for body in (_fn("function prioSignaalBody"), _fn("function pulsItem")):
            assert "esc(nlNum(r.km))" in body


# ══ T10 — A4a: één 'Herstel onder druk', beide bronregels ════════════════════
class TestA4aHerstel:
    def _ev(self, key, value):
        return Evidence(key=key, domain="recovery", value=value, truth_type=DERIVED,
                        status=ACTIVE, strength=MEDIUM, source="brain.derive",
                        observed_at="2026-09-01", athlete_key="u1")

    def test_t10_twee_bronnen_geven_een_kaart_met_beide_details(self):
        evs = [self._ev("recovery.rpe_trend", "zwaarder"),
               self._ev("recovery.feeling_trend", "slechter")]
        kaarten = [c for c in _dc._attention(_St(evs)) if c["kind"] == "recovery_neg"]
        assert len(kaarten) == 1, f"nog steeds dubbel: {[c['title'] for c in kaarten]}"
        why = kaarten[0]["why"]
        assert "zwaarder" in why and "slechter" in why, why
        assert kaarten[0]["title"] == "Herstel onder druk"

    def test_t10_een_bron_blijft_exact_zoals_hij_was(self):
        kaarten = [c for c in _dc._attention(_St([self._ev("recovery.rpe_trend", "zwaarder")]))
                   if c["kind"] == "recovery_neg"]
        assert len(kaarten) == 1
        assert kaarten[0]["why"] == f"{_dc._label('recovery.rpe_trend')}: zwaarder"

    def test_t10_geen_bron_geeft_geen_kaart(self):
        evs = [self._ev("recovery.rpe_trend", "lichter")]
        assert not [c for c in _dc._attention(_St(evs)) if c["kind"] == "recovery_neg"]

    def test_t10_kaart_id_is_deterministisch(self):
        """Volgorde van de evidence mag de deep-link niet verschuiven."""
        a, b = self._ev("recovery.rpe_trend", "zwaarder"), self._ev("recovery.feeling_trend", "slechter")
        id1 = [c for c in _dc._attention(_St([a, b])) if c["kind"] == "recovery_neg"][0]["id"]
        id2 = [c for c in _dc._attention(_St([b, a])) if c["kind"] == "recovery_neg"][0]["id"]
        assert id1 == id2

    def test_t10_geen_evidence_herclassificatie(self):
        """Beide waarnemingen blijven bestaan; we voegen alleen de PRESENTATIE samen."""
        blok = _DC_SRC[_DC_SRC.index("_recovery_neg.append(e)"):_DC_SRC.index("for cid in getattr(st,")]
        for verboden in ("status =", "strength =", "truth_type =", ".value ="):
            assert verboden not in blok


# ══ T11 — A4b: geen valse 'Geen open klacht of signaal' ══════════════════════
class TestA4bKlacht:
    def test_t11_fallback_is_gegate_op_een_echt_lege_attention(self):
        body = _fn("function dcBuildEvents")
        assert 'const openKlacht = (attn || []).find(c => c.kind === "complaint") || null;' in body
        assert "if (openKlacht && !insuf) {" in body
        i_guard = body.index("const openKlacht")
        i_calm = body.index('"Geen open klacht of signaal"')
        assert i_guard < i_calm, "de guard moet vóór de kalme fallback staan"

    def test_t11_het_nu_anker_hergebruikt_de_canonieke_klacht(self):
        body = _fn("function dcBuildEvents")
        assert "title: openKlacht.title" in body        # geen nieuwe formulering
        assert "ev: openKlacht.id || null" in body      # bestaande deep-link blijft werken

    def test_t11_klachten_blijven_gedateerd_in_het_verleden(self):
        """De bestaande scheiding (klacht = gedateerd verleden-event) is ongewijzigd."""
        body = _fn("function dcBuildEvents")
        assert '.concat((attn || []).filter(c => c.kind === "complaint")' in body
        assert '(attn || []).filter(c => c.kind !== "complaint" && !(lo && c.kind === "load_signal"))' in body

    def test_t12_dossier_locks_intact(self):
        """Deep-links, 'Waarom?' en generation-coherentie zijn niet aangeraakt."""
        assert "function dcSelectEvent(" in _APP and "dcOpenEvent" in _APP
        assert "async function dcWaarom(" in _APP
        assert "dcVMgen = vm.state_generation_id" in _APP
        assert "/api/cockpit/explain?key=" in _APP


# ══ T13-T18 — B1: permanente atleet-nav op alle vier de routes ═══════════════
class TestB1Tabbar:
    def test_t13_alle_vier_de_atleetoppervlakken_dragen_de_nav(self):
        assert 'athleteNav("workspace", key)' in _fn("function wsRender")
        assert 'athleteNav("dossier", vm.key)' in _fn("function dcHeader")
        assert 'athleteNav("atleten", d.user_key)' in _fn("function tekenAtleet")
        assert _APP.count('athleteNav("schema"') >= 5

    def test_t13_workspace_gebruikt_de_bestaande_styling_haak(self):
        assert '<div class="ws-pagehead ws-anchor">' in _APP
        assert ".ws-anchor .anav-chip" in _DS         # bestond al, wordt nu pas geraakt

    def test_t13_een_component_geen_tweede_nav(self):
        assert _APP.count("function athleteNav") == 1
        assert "function dsAthleteNav" not in _APP

    def test_t13_zelfde_relatieve_volgorde_overal(self):
        nav = _fn("function athleteNav")
        assert nav.index('"atleten"') < nav.index('"dossier"') < nav.index('"schema"')
        assert "o.view !== activeView" in nav          # actieve tool niet dubbel (gelockt)
        assert 'activeView === "workspace" ? "" :' in nav

    def test_t14_t15_route_is_de_enige_atleet_waarheid(self):
        key = _fn("function activeAthleteKey")
        assert "location.hash" in key and "_ATHLETE_CTX_VIEWS.has(view)" in key
        assert 'if (key && key.indexOf("nieuw:") === 0) key = "";' in _fn("function openModuleFromNav")
        assert 'const _ATHLETE_VIEWS = new Set(["atleten", "schema", "dossier"]);' in _APP

    def test_t16_back_forward_contract_ongewijzigd(self):
        assert 'window.addEventListener("popstate", applyRoute);' in _APP
        ar = _fn("function applyRoute")
        assert "const slash = raw.indexOf(\"/\");" in ar          # twee segmenten
        assert 'else if (view === "workspace") { if (ident) openWorkspace(ident);' in ar

    def test_t17_workspace_picker_en_routing_intact(self):
        assert "openAthletePickerOverlay({" in _fn("function wsOpenSwitcher")
        assert "onConfirm: a => openWorkspace(a.key)" in _fn("function wsOpenSwitcher")
        ow = _fn("function openWorkspace")
        assert "_routing" in ow and "wsShow" in ow

    def test_t18_schema_draft_flush_onaangeroerd(self):
        oam = _fn("function openAthleteModule")
        assert 'if (huidigeView === "schema" && view !== "schema"' in oam
        assert "sbDraftSave()" in oam
        assert "let schemaOpenMode = " in _APP and "function openSchemaMode(" in _APP


# ══ T19-T22 — B2: Monitoring-segment op Vandaag ══════════════════════════════
class TestB2Monitoring:
    def test_t19_actie_segment_is_de_ongewijzigde_home_werklijst(self):
        home = _fn("async function renderHome")
        assert ('<div class="sec-head"><p class="sec-label">Prioriteit vandaag</p>'
                '<span class="sec-note" id="prio-note"></span>'
                '<span class="sec-updated" id="home-updated" aria-live="polite"></span></div>') in home
        assert '<div id="home-prio">' in home
        assert "prio-skel" in home
        # De renderers en de suppressie-flow zijn niet aangeraakt.
        assert "function prioItem(" in _APP and "function prioDoe(" in _APP
        assert '"/api/home/handled"' in _APP or "stuurHandled" in _APP

    def test_t19_segmenten_zijn_broers_geen_herbouw(self):
        home = _fn("async function renderHome")
        assert '<div id="home-actie" role="tabpanel"' in home
        assert '<div id="home-mon" role="tabpanel"' in home
        assert 'class="hseg on" data-seg="actie"' in home
        assert 'data-seg="monitoring"' in home
        assert ".hseg{" in _CSS and ".home-seg{" in _CSS

    def test_t20_monitoring_leest_het_bestaande_teampuls_endpoint(self):
        vul = _fn("async function homeVulMonitoring")
        assert 'api("/api/teampuls/signalen")' in vul
        assert "force=true" not in vul, "monitoring mag nooit een recompute forceren"

    def test_t21_monitoring_leest_het_bestaande_schema_verloop_endpoint(self):
        vul = _fn("async function homeVulMonitoring")
        assert 'api("/api/schema-verloop")' in vul

    def test_t20_t21_hergebruikt_exact_dezelfde_kaartbouwers(self):
        assert "items.forEach(it => box.appendChild(pulsItem(it)));" in _fn("function homeMonBelasting")
        assert "items.forEach(it => box.appendChild(svItem(it)));" in _fn("function homeMonSchema")
        # geen tweede kaart-implementatie
        assert _APP.count("function pulsItem(") == 1 and _APP.count("function svItem(") == 1

    def test_t20_duiding_en_onderbouwing_blijven(self):
        puls = _fn("function pulsItem")
        assert "it.duiding" in puls
        assert "Onderbouwing (welke trainingen zijn geteld)" in puls
        assert "Gezien (7 dagen)" in puls
        assert '"/api/teampuls/gezien"' in puls

    def test_t22_home_suppressie_semantiek_is_niet_geraakt(self):
        """Monitoring is OBSERVATIE; het raakt de Home-werklijst niet aan."""
        assert "pwa/home_core.py" not in _diff()
        assert "belasting.py" not in _diff()
        assert "pwa/teampuls_core.py" not in _diff()
        for fn in ("function homeMonBelasting", "function homeMonSchema",
                   "async function homeVulMonitoring"):
            body = _fn(fn)
            assert "handled" not in body and "gezien" not in body.replace("Gezien (7 dagen)", "")

    def test_monitoring_is_lazy(self):
        zet = _fn("function homeZetSegment")
        assert 'if (seg === "monitoring") homeVulMonitoring();' in zet
        vul = _fn("async function homeVulMonitoring")
        assert "if (homeMonGeladen && !force) return;" in vul
        home = _fn("async function renderHome")
        assert "homeVulMonitoring(" not in home, "page-open mag geen monitoring ophalen"

    def test_t23_t24_standalone_routes_blijven_werken(self):
        assert 'data-view="teampuls"' in _IDX and 'data-view="schema-verloop"' in _IDX
        assert "laders.teampuls = laadTeampuls;" in _APP
        assert 'laders["schema-verloop"] = laadSchemaVerloop;' in _APP
        assert "async function laadTeampuls(" in _APP and "async function laadSchemaVerloop(" in _APP


# ══ T25-T28 — B3: weekbriefing op Vandaag ════════════════════════════════════
class TestB3Briefing:
    def test_t25_briefing_staat_op_vandaag(self):
        home = _fn("async function renderHome")
        assert '<div id="home-brief"></div>' in home
        assert "homeVulBriefing();" in home
        assert "async function homeVulBriefing(" in _APP

    def test_t25_briefing_staat_niet_achter_de_monitoringkaarten(self):
        home = _fn("async function renderHome")
        assert home.index('id="home-brief"') > home.index('id="home-mon"')
        # ... maar in het DEFAULT-segment (Actie) staat er geen monitoringkaart boven:
        assert 'class="hseg on" data-seg="actie"' in home
        zet = _fn("function homeZetSegment")
        assert 'if (m) m.hidden = seg !== "monitoring";' in zet

    def test_t26_populatie_semantiek_bewaard(self):
        kaart = _fn("function briefKaartHtml")
        assert "r.populatie_label" in kaart and "r.populatie_uitleg" in kaart
        assert '"gecoachte atleten actief"' in kaart
        assert "s.n_actief" in kaart and "s.n_atleten" in kaart

    def test_t27_dateringsmarkering_bewaard(self):
        assert "function briefGemaaktLabel(" in _APP
        assert "briefGemaaktLabel(r.gemaakt)" in _fn("function briefKaartHtml")

    def test_t27_inhoud_bewaard(self):
        kaart = _fn("function briefKaartHtml")
        assert "briefHtml(r.tekst" in kaart
        assert "gedeeld met beide coaches" in kaart
        assert "s.n_trainingen" in kaart and "s.km_totaal" in kaart

    def test_t28_een_ophaalpad_geen_dubbele_generatie(self):
        assert "async function briefingGet(" in _APP
        get = _fn("async function briefingGet")
        assert "if (!force && _briefMemo) return _briefMemo;" in get
        # Beide oppervlakken gebruiken dezelfde get + dezelfde render.
        assert "await briefingGet(false)" in _fn("async function homeVulBriefing")
        lb = _fn("async function laadBriefing")
        assert "await briefingGet(force)" in lb and "briefKaartHtml(r)" in lb
        assert _APP.count('api(`/api/teampuls/briefing') == 1, "meer dan één fetch-site"

    def test_t28_teampuls_blijft_de_briefing_parallel_starten(self):
        assert "laadBriefing(force)" in _fn("async function laadTeampuls")

    def test_alleen_expliciet_vernieuwen_forceert(self):
        assert 'briefingGet(true)' in _APP
        assert "data-brief-refresh" in _APP


# ══ T29-T33 — scope- en correctness-locks ════════════════════════════════════
class TestLocks:
    def test_t29_feedback_architectuur_onaangeroerd(self):
        verboden = {"ai_feedback.py", "feedback_atoms.py", "feedback_copy.py",
                    "feedback_facts.py", "feedback_obligations.py", "metric_authority.py",
                    "pwa/feedback_core.py", "pwa/feedback_week.py", "fs_client.py"}
        assert not verboden.intersection(_diff())

    def test_t29_feedback_lifecycle_hooks_intact(self):
        tv = _fn("function toonView")
        assert 'if (huidigeView === "feedback" && view !== "feedback")' in tv
        assert "fbLeave();" in tv and 'classList.remove("kb-open")' in tv

    def test_t29_feedback_queue_en_volgorde_ongewijzigd(self):
        for f in ("function fbGroupOrder(", "function fbFilterItems(",
                  "function renderQueue(", "function fbRowHtml("):
            assert f in _APP

    def test_t30_run_deviations_onaangeroerd(self):
        assert "pwa/brain/derive.py" not in _diff()
        assert "pwa/brain/projections.py" not in _diff()

    def test_t31_render_cachegrenzen_onaangeroerd(self):
        for f in ("pwa/athlete_read.py", "pwa/races_core.py", "pwa/schema_core.py",
                  "pwa/feedback_core.py"):
            assert f not in _diff()

    def test_t32_home_teampuls_belasting_kern_onaangeroerd(self):
        for f in ("pwa/home_core.py", "pwa/teampuls_core.py", "pwa/coach_read.py",
                  "belasting.py"):
            assert f not in _diff()

    def test_t33_workspace_lock_semantiek_intact(self):
        ws = _fn("function wsRender")
        assert 'const wsStaat = attn.length ? "aandacht" : (belStand ? "rustig" : "onbekend");' in ws
        assert "Geen belastingstand bekend." in ws
        assert "function wsMagRustig(" in _APP and "function wsUniekeSignalen(" in _APP

    def test_routegrammatica_ongewijzigd(self):
        pr = _fn("function pushRoute")
        assert 'const h = "#" + (ident ? `${view}/${encodeURIComponent(ident)}` : view);' in pr
        assert "/verlengen" not in _fn("function openSchemaMode")

    def test_geen_nieuwe_store_of_engine(self):
        for fn in ("async function homeVulMonitoring", "function homeMonBelasting",
                   "function homeMonSchema", "async function homeVulBriefing",
                   "async function briefingGet"):
            body = _fn(fn)
            assert "localStorage" not in body and "jpost(" not in body

    def test_alleen_verwachte_bestanden_gewijzigd(self):
        verwacht = {"pwa/static/app.js", "pwa/static/index.html", "pwa/static/styles.css",
                    "pwa/dossier_cockpit.py", "pwa/static/sw.js",
                    "tests/test_cross_page_consolidation_r1.py",
                    "tests/test_run_plan_deviations_v1.py",
                    "tests/js/consolidation_r1.test.mjs",
                    "tests/js/workspace_render.test.mjs",
                    "tests/js/workspace_cleanup.test.mjs"}
        extra = {f for f in _diff() if not f.startswith("docs/")} - verwacht
        assert not extra, f"onverwacht gewijzigd: {sorted(extra)}"
