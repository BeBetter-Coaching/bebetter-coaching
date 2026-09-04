"""App-wide Design System + Athlete Shell v1 — gedeelde visuele/interactionele taal.

Deze suite bewaakt dat de UI-laag ÉÉN systeem is en blijft:
  • één statussemantiek (`dsTone`) i.p.v. per-module kleurdialecten;
  • één set gedeelde primitives (shell/attention/metric/panel/kv/stream/action/empty);
  • Workspace, Dossier én Home-detail gebruiken DEZELFDE primitives;
  • geen tweede athlete-nav, geen tweede truth-rendering, geen nieuwe engine;
  • de gelockte contracten (generation/freshness, Cohesion-routes, Dossier-ordening,
    copy-contract) blijven intact;
  • performance-contract: geen animatieframework, geen canvas/WebGL, geen blokkerende
    assets — alleen CSS/SVG.

    python3 -m pytest tests/test_app_design_system_v1.py -q
"""
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_HTML = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()
_CSS = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()
_DS = open(os.path.join(_ROOT, "pwa", "static", "design-system.css")).read()
_SW = open(os.path.join(_ROOT, "pwa", "static", "sw.js")).read()


def _fn(name, src=None):
    """Body van een top-level `function name(...) { ... }` (brace-match)."""
    s = src if src is not None else _APP
    i = s.index("function " + name + "(")
    j = s.index("{", i)
    d = 0
    for k in range(j, len(s)):
        if s[k] == "{":
            d += 1
        elif s[k] == "}":
            d -= 1
            if d == 0:
                return s[j:k + 1]
    raise AssertionError("unbalanced " + name)


# ── 1. Foundations: tokens bestaan en zijn de enige bron van maat/kleur ──────
class TestFoundations:
    def test_1_design_system_stylesheet_is_geladen_en_gecachet(self):
        assert "/static/design-system.css" in _HTML          # in de app-schil
        assert "/static/design-system.css" in _SW            # in de SW-shell (offline)

    def test_2_token_schalen_bestaan(self):
        # Vóór deze milestone: 12 tokens (11 kleuren + 1 radius) en verder niets.
        for group in ("--ds-canvas", "--ds-s1", "--ds-s2", "--ds-s3",     # surface-ladder
                      "--ds-text", "--ds-text-2", "--ds-text-3",          # type-hiërarchie
                      "--ds-1", "--ds-2", "--ds-3", "--ds-4", "--ds-6",   # spacing-schaal
                      "--ds-t-display", "--ds-t-body", "--ds-t-xs",       # type-schaal
                      "--ds-r-sm", "--ds-r-md", "--ds-r-lg", "--ds-r-pill",  # radii
                      "--ds-e1", "--ds-e2", "--ds-e3",                    # elevatie
                      "--ds-fast", "--ds-base", "--ds-slow", "--ds-ease"):  # motion
            assert group + ":" in _DS, f"token {group} ontbreekt"

    def test_3_statussemantiek_is_een_enkele_taal(self):
        # Elke betekenis bestaat exact één keer, als tone-klasse met 3 variabelen.
        for cls in ("is-calm", "is-attention", "is-critical",
                    "is-success", "is-stale", "is-unknown"):
            assert re.search(r"\." + cls + r"\s*\{--tone:", _DS), f"statusklasse {cls} ontbreekt"
        # componenten lezen ALLEEN var(--tone*) → geen module-eigen kleuren meer
        assert "--tone:" in _DS and "--tone-bg:" in _DS and "--tone-bd:" in _DS

    def test_4_focus_states_zijn_gedefinieerd(self):
        assert _DS.count(":focus-visible") >= 3             # toetsenbord-toegankelijk


# ── 2. Eén statusmapping in JS (geen per-module kleurkeuzes) ────────────────
class TestStatusSemantics:
    def test_5_dsTone_is_de_enige_mapping(self):
        assert "function dsTone(" in _APP
        assert _APP.count("function dsTone(") == 1
        body = _fn("dsTone")
        assert "_DS_TONE" in body
        # server-vocabulaires komen allemaal binnen op dezelfde mapping
        for term in ("actie", "aandacht", "hoog", "let_op", "stale", "unknown",
                     "green", "amber", "red"):
            assert f"{term}:" in _APP.split("const _DS_TONE")[1][:900], f"{term} niet gemapt"

    def test_6_zwaarste_toon_wint(self):
        assert "function dsWorstTone(" in _APP
        assert "_DS_RANK" in _APP

    def test_7_geen_module_eigen_kleurdialect_meer_in_workspace(self):
        # De oude ws-* kleurklassen (eigen dialect) zijn vervangen door de gedeelde toon.
        assert "function wsChip(" not in _APP                # dode helper opgeruimd
        for dead in (".ws-tag{", ".ws-line{", ".ws-attn{", ".ws-sec{", ".ws-dl{", ".ws-acties{"):
            assert dead not in _CSS, f"superseded {dead} nog aanwezig"


# ── 3. Gedeelde primitives bestaan en worden hergebruikt ────────────────────
class TestPrimitives:
    # UX/IA v1: wsCore (flame) + wsAnchor (medaillon) verwijderd — Workspace is nu een
    # ds-panel-grid; identiteit leeft in de gedeelde appbar-switcher.
    PRIMS = ["wsLine", "dcTlItem", "dcMemPanel", "dsAttnCard", "dsMetric", "dsPanel", "dsChip", "dsFresh",
             "dsKv", "dsStream", "dsAction", "dsEmpty", "dsSpark", "dsRing"]

    def test_8_alle_primitives_bestaan_eenmalig(self):
        for p in self.PRIMS:
            assert f"function {p}(" in _APP, f"primitive {p} ontbreekt"
            assert _APP.count(f"function {p}(") == 1, f"{p} dubbel gedefinieerd"

    def test_9_primitives_escapen_hun_tekst(self):
        # Geen XSS-regressie: elke primitive die tekst rendert gebruikt esc().
        for p in ("dsChip", "dsAttnCard", "dsMetric", "dsKv", "dsStream", "dsAction", "dsEmpty"):
            assert "esc(" in _fn(p), f"{p} escapet niet"

    def test_10_sparkline_en_ring_verzinnen_niets(self):
        # < 2 punten → geen lijn; geen percentage → geen ring (nooit fake data tekenen).
        assert "if (v.length < 2) return \"\"" in _fn("dsSpark")
        assert "return \"\"" in _fn("dsRing")

    def test_11_geen_zware_runtime_afhankelijkheid(self):
        # Performance-contract: alleen CSS/SVG, geen framework/canvas/WebGL.
        for bad in ("getContext(\"2d\")", "getContext('2d')", "WebGL", "requestAnimationFrame(function anim",
                    "cdn.jsdelivr", "unpkg.com", "gsap", "anime.min"):
            assert bad not in _APP, f"zware afhankelijkheid {bad}"
        # precies één eigen script in de body (versie-query mag vrij bewegen)
        scripts = re.findall(r"<script[^>]*>", _HTML.split("<body>")[1])
        assert len(scripts) == 1 and "/static/app.js" in scripts[0], scripts


# ── 4. Athlete Shell: één identiteit over drie views ────────────────────────
class TestAthleteShell:
    def test_12_athlete_identiteit_is_dominant_in_beide_views(self):
        # Workspace (north-star pass): het focal-systeem (ringen + medaillon) draagt
        # de identiteit in het centrum; de NAAM staat in de kop van de scène — zoals
        # de referentie-compositie (identiteit linksboven, centrum puur grafisch).
        # Dossier: dezelfde taal, eigen compositie. Zelfde identiteitsbron.
        # UX/IA v1: Workspace-identiteit leeft in de gedeelde appbar-switcher (ws-switch),
        # niet meer in een scène-medaillon. Dossier houdt zijn eigen kop-identiteit.
        assert "ws-switch-nm" in _HTML and "id=\"ws-switch\"" in _HTML
        dc = _fn("dcHeader")                                 # Dossier-identiteit in de kop
        for part in ("dc-mono", "dc-name", "initialen("):
            assert part in dc, f"dossier-kop mist {part}"
        # opgeruimd: de flame-kern + medaillon zijn echt weg, geen dode primitives
        for dead in ("function dsShell(", "function dsStage(", "function dsFocal(", "function dsStat(",
                     "function wsCore(", "function wsAnchor("):
            assert dead not in _APP, f"dode primitive {dead} nog aanwezig"

    def test_13_workspace_en_dossier_delen_de_athlete_taal(self):
        # Workspace is een canvas-scène (wsAnchor), Dossier een memory-compositie —
        # verschillende layouts, maar DEZELFDE athlete-taal: zelfde identiteitsbron,
        # zelfde statussemantiek, zelfde gedeelde nav. Geen tweede vocabulaire.
        # Dossier is opgesplitst in render/header/scene/stack — dezelfde athlete-taal
        # leeft over die familie (identiteit, toon, gedeelde nav).
        wsb = _fn("wsRender")
        dcb = _fn("dcRender") + _fn("dcHeader") + _fn("dcScene") + _fn("dcStack")
        for body, view in ((wsb, "workspace"), (dcb, "dossier")):
            assert "dsTone(" in body, f"{view} gebruikt de gedeelde statussemantiek niet"
        # UX/IA v1: Workspace deelt nu de ds-panel-kaarttaal met Dossier (één visuele familie);
        # athlete-continuïteit loopt via de gedeelde sidebar (activeAthleteKey), niet via een
        # scène-nav in wsRender.
        assert "ds-panel" in wsb, "workspace mist de gedeelde ds-panel kaarttaal"
        assert "function wsCore(" not in _APP and "function wsAnchor(" not in _APP

    def test_14_alle_athlete_views_spreken_hetzelfde_signaaldialect(self):
        # Journey A/D: hetzelfde signaal krijgt op Home, Workspace en Dossier dezelfde
        # toon uit dezelfde mapper — ongeacht welke presentatievorm de view kiest.
        for fn in ("prioDetailHtml", "wsRender", "dcRender"):
            assert "dsTone(" in _fn(fn), f"{fn} kiest zelf kleuren i.p.v. dsTone"
        # Elke view kiest de presentatievorm die bij haar doel past, maar put uit
        # dezelfde primitives-familie en dezelfde toon-mapper.
        assert "dsAttnCard(" in _fn("prioDetailHtml")         # Home-detail: briefing-kaart
        assert "dcTlItem(" in _fn("dcScene")                  # Dossier: event op de tijdlijn
        assert "wsLine(" in _fn("wsRender")                   # Workspace: embedded regel op het canvas

    def test_15_geen_tweede_athlete_nav(self):
        # De bestaande gedeelde nav blijft de enige; het DS stijlt 'm alleen.
        assert _APP.count("function athleteNav") == 1
        assert "function dsAthleteNav" not in _APP
        assert 'athleteNav("dossier", vm.key)' in _APP        # Cohesion-contract intact
        assert ".ws-anchor .anav-chip" in _DS                 # opgewaardeerd, niet vervangen
        assert ".dc-nav2 .anav-chip" in _DS

    def test_16_workspace_heeft_geen_permanente_athlete_lijst_meer(self):
        # De master/detail-rail was het fundament van het lijstgevoel. In een actieve
        # athlete-context bestaat hij niet meer; wisselen gaat via een compacte switcher
        # die de BESTAANDE overlay-picker hergebruikt (geen tweede navigatieconcept).
        assert 'class="view ds-view ws-view" data-view="workspace"' in _HTML
        assert 'id="ws-switch"' in _HTML                      # compacte switcher
        assert 'class="ws-canvas"' in _HTML                   # canvas i.p.v. md-split
        assert 'id="ws-lijst"' not in _HTML and 'id="ws-zoek"' not in _HTML
        assert "md-split" not in _HTML.split('data-view="workspace"')[1].split("</section>")[0]
        assert "openAthletePickerOverlay(" in _fn("wsOpenSwitcher")
        assert ".view.ds-view{max-width:" in _DS
        assert 'class="view ds-view" data-view="dossier"' in _HTML


# ── 5. Gelockte functionaliteit blijft intact ───────────────────────────────
class TestLockedFunctionalityPreserved:
    def test_17_generation_freshness_indicatoren_intact(self):
        for token in ("function noteGeneration(", "function genBanner(", "function genMount(",
                      "source_versions", "_genDominates"):
            assert token in _APP, f"generation-contract mist {token}"
        # V-11: Home stampt de generatie niet meer als zwevende overlay-banner, maar via de
        # niet-obstructieve, gereserveerde 'Bijgewerkt HH:MM'-status (homeSetUpdated → noteGeneration).
        assert 'function homeSetUpdated(' in _APP and 'homeSetUpdated(' in _APP
        assert 'genMount("#tp-genbar"' in _APP

    def test_18_workspace_quick_actions_hergebruiken_bestaande_routes(self):
        body = _fn("wsRender")
        for call in ("openAthleteModule('schema'", "openModuleFromNav('feedback'"):
            assert call in body, f"route {call} verdwenen"
        # geen duplicate write-logica: dempen loopt via de bestaande authority
        assert "/api/teampuls/gezien" in _fn("wsMarkeerGezien")

    def test_19_dossier_ordening_en_copy_contract_intact(self):
        # De load-observatie-duiding (LIVE-CLOSE) blijft woordelijk behouden in de
        # nieuwe cockpit; de context-lenzen dragen de vaste copy-koppen.
        body = _fn("dcRender")
        assert "build_diagnostic" in body
        for copy in ("open Home-actie", "eerder afgehandeld", "geen open Home-actie",
                     "t.o.v. referentie", "monitoring — nog geen coachactie"):
            assert copy in body, f"copy-contract mist: {copy}"
        scene = _fn("dcScene")
        for copy in ("Tijdlijn", "Periode", "Naar schema"):   # 2-zone: 'Gerelateerde draden' verwijderd
            assert copy in scene, f"cockpit-copy mist: {copy}"

    def test_20_cohesion_route_contract_byte_identiek(self):
        assert '_ATHLETE_VIEWS = new Set(["atleten", "schema", "dossier"])' in _APP
        assert _APP.count("function openAthleteModule(") == 1
        assert _APP.count("function applyRoute") == 1
        assert _APP.count("openModuleFromNav(b.dataset.openView)") == 4   # anti-DRY lock
        assert ".anav-chip{" in _CSS                                      # in styles.css

    def test_21_workspace_shell_blijft_niet_blokkerend(self):
        # De deep-context blijft lazy: de shell wacht nergens op.
        assert "/api/cockpit" in _fn("wsLoadDeep")
        body = _fn("wsRender")
        assert 'api("/api/cockpit' not in body                # shell doet zelf geen deep-call
        assert "ws-plan" in body                               # doel/planning-slot wordt lazy gevuld
        # B12: de #ws-context klachten-slot is uit de Feedback-kaart verwijderd.
        assert "ws-context" not in body

    def test_22_geen_nieuwe_truth_of_store_in_de_ui(self):
        for bad in ("localStorage.setItem(\"bb_athlete", "localStorage.setItem('bb_athlete",
                    "new Worker(", "indexedDB"):
            assert bad not in _APP, f"nieuwe client-state {bad}"


# ── 6. Motion & toegankelijkheid ───────────────────────────────────────────
class TestMotionAndA11y:
    def test_23_reduced_motion_wordt_gerespecteerd(self):
        assert "prefers-reduced-motion" in _DS
        blok = _DS.split("prefers-reduced-motion")[1][:400]
        assert "animation:none" in blok

    def test_24_motion_is_subtiel_en_kort(self):
        # Geen theatrale animaties: alle DS-duren <= 400ms.
        for ms in re.findall(r"--ds-(?:fast|base|slow):(\d+)ms", _DS):
            assert int(ms) <= 400, f"duur {ms}ms te lang"

    def test_25_progressive_disclosure_bestaat(self):
        assert "function dsFoldToggle(" in _APP
        assert ".ds-fold" in _DS and ".ds-disc" in _DS


# ── 7. Backend: presentatie-data komt uit dezelfde captured stand ───────────
class TestBackendPresentationOnly:
    def test_26_runs_sparkline_data_uit_dezelfde_stand(self):
        src = open(os.path.join(_ROOT, "pwa", "coach_read.py")).read()
        i = src.index("def _athlete_belasting(")
        blok = src[i:i + 1800]
        assert "runs_recent" in blok                          # bestaande waarheid
        assert "\"runs\": runs" in blok
        # geen tweede stand-read en geen herberekening voor de presentatie
        assert blok.count("laad_stand()") <= 1

    def test_27_geen_nieuwe_engine_of_store(self):
        src = open(os.path.join(_ROOT, "pwa", "coach_read.py")).read()
        for bad in ("save_", "open(", "sqlite", "requests.post"):
            assert bad not in src, f"coach_read schrijft/opent iets: {bad}"


# ══════════ Athlete Canvas — visuele hercompositie (presentation risks) ══════
class TestAthleteCanvas:
    """De hercompositie verving de master/detail-structuur. Deze tests bewaken de
    functionele risico's die dáárdoor ontstaan: athlete-switch, deep-links, het
    wegvallen van de rail, en het behoud van alle acties."""

    def test_28_workspace_switch_werkt_zonder_lijst(self):
        # Geen picker/rail meer in Workspace: wisselen loopt via de overlay-picker,
        # die dezelfde renderPicker + onConfirm→openWorkspace gebruikt.
        body = _fn("wsOpenSwitcher")
        assert "openAthletePickerOverlay(" in body
        assert "openWorkspace(a.key)" in body
        assert "wsPicker" not in _APP                          # geen tweede picker-instantie

    def test_29_workspace_deeplink_wacht_op_roster(self):
        # #workspace/<key> vóór de roster binnen is mag niet stilvallen.
        body = _fn("wsShow")
        assert "wsOpenPending = ident" in body
        assert "wsRosterKlaar" in body
        assert "laadWorkspace()" in body
        assert 'view === "workspace"' in _fn("applyRoute")     # routecontract intact

    def test_30_dossier_rail_valt_weg_bij_open_atleet(self):
        body = _fn("dcToonLijst")
        assert "else if (dcSel)" in body                       # Cohesion-contract intact
        assert '$("#dc-detail").hidden = false' in body
        assert "lijst.hidden = true" in body                   # rail is geen fundament meer
        assert ".ds-view.has-athlete .md-split" in _DS         # grid geeft de volle breedte

    def test_31_alle_acties_blijven_bereikbaar(self):
        # UX/IA v1 + Cowork B8/B12: de Feedback-kaart-CTA is 'Naar feedback' (generieke queue),
        # niet meer 'Cockpit openen'→Dossier. Essentiële acties: schema openen, naar feedback,
        # belasting-signaal afhandelen. Dossier is athlete-aware via de sidebar bereikbaar.
        ws = _fn("wsRender")
        for call in ("openAthleteModule('schema'", "openModuleFromNav('feedback'", "wsMarkeerGezien("):
            assert call in ws, f"actie {call} verdwenen uit de Workspace-grid"
        assert "/api/teampuls/gezien" in _fn("wsMarkeerGezien")   # bestaande authority

    def test_32_workspace_one_load_truth(self):
        # UX/IA v1 (Target C/G): geen focal-flame-ladder meer. De belasting staat precies
        # één keer, in de load-kaart (km/%/referentie + instrument). Geen tweede bron-%.
        body = _fn("wsRender")
        assert body.count("ws-load-panel") == 1, "load moet precies één kaart zijn"
        assert "focal.owner" not in body and "belZin" not in body, "oude focal-ladder nog aanwezig"
        assert "wsLoadInstrument(bel)" in body
        assert "grid-area:load" in body
        # de belasting-observatie hoort bij de load-kaart → wsLoadDeep herhaalt 'm niet
        assert 'wrap.dataset.belOwned = (bel.km_recent != null)' in body

    def test_33_dossier_2zone_geheugencockpit(self):
        # UX/IA v1 (Target D): 2-zone geheugencockpit — tijdlijn (echte events) → geselecteerde
        # herinnering (hero). Het gededupliceerde 'Gerelateerde draden'-paneel (zelfde events als
        # de tijdlijn) is weg; navigeren gebeurt via de klikbare tijdlijn.
        rn = _fn("dcRender")
        assert "dcBuildEvents(" in rn                            # events uit echte velden
        scene = _fn("dcScene")
        assert "dc-grid-2" in scene and "dcTlItem(" in scene and "dcMemPanel(sel)" in scene
        assert "dcRelCard" not in scene and "dc-rt-pane" not in scene, "duplicate draden-paneel nog aanwezig"
        for sel in (".dc-grid.dc-grid-2", ".dc-tl-item", ".dc-mem"):
            assert sel in _DS, f"2-zone-primitive {sel} niet gestyled"

    def test_34_home_briefing_is_geen_uitgeklapt_paneel(self):
        body = _fn("prioDetailHtml")
        for part in ("pb-head", "pb-orb", "pb-naam", "pb-reden"):
            assert part in body, f"briefing mist {part}"
        assert "ds-fold" in body                                 # onderbouwing progressief
        assert "swBtn({ act: \"workspace\"" in body              # route naar Workspace
        assert "swBtn({ act: \"dossier\"" in body                # route naar Dossier
        # per-signaal afhandeling blijft volledig intact
        assert 'data-act="gezien"' in body and 'data-act="later"' in body

    def test_35_freshness_en_generation_blijven_zichtbaar(self):
        ws = _fn("wsRender")
        assert "noteGeneration(vm.generation)" in ws
        assert "genBanner(vm.generation)" in ws
        assert "dsFresh(" in ws                                  # stale/fresh in de scène
        assert "dsFresh(" in _fn("dcHeader")                     # freshness in de Dossier-kop

    def test_36_geen_legacy_layout_resten(self):
        # De vervangen presentatie is echt opgeruimd, niet overlaagd.
        for dead in ("ws-detail\" class=\"md-detail", "id=\"ws-lijst\"", "id=\"ws-zoek\""):
            assert dead not in _HTML, f"legacy markup {dead} nog aanwezig"
        for dead in (".ws-tag{", ".ws-dl{", ".ws-sec{", ".dc-head{", ".dc-card{"):
            assert dead not in _CSS, f"legacy CSS {dead} nog aanwezig"
        assert "function wsToonLijst(" not in _APP               # rail-toggle is weg

    # ── UX/IA v1 (Cross-Module UX/IA Fix): Workspace = Now/Next grid, geen flame ──
    def test_37_workspace_grid_no_flame(self):
        # De dominante flame/orbit/sphere is verwijderd; Workspace is een robuust grid.
        ws = _fn("wsRender")
        assert "function wsCore(" not in _APP and "function wsAnchor(" not in _APP
        for gone in ("ws-scene", "ws-core", "ws-web", "ws-geo", "ws-lens", "ws-dock", "ws-frag"):
            assert gone not in ws, f"verwijderde decoratie nog aanwezig: {gone}"
        assert "ws-grid" in ws
        # menslijn blijft weg (regressiegarantie)
        assert "function wsHuman(" not in _APP and "ws-human" not in _APP
        assert not os.path.exists(os.path.join(_ROOT, "pwa", "static", "presence"))

    def test_38_load_is_one_instrument(self):
        # Eén load-instrument op dezelfde bronvelden, met "laatste 7 dagen"-label (rolling-7).
        ws = _fn("wsRender")
        assert "function wsLoadInstrument(" in _APP and _APP.count("function wsLoadInstrument(") == 1
        li = _fn("wsLoadInstrument")
        assert "bel.runs" in li and "bel.km_basis_week" in li  # zelfde bron, geen nieuwe data
        assert "d.cum = acc" in li and "acc += d.km" in li     # eerlijke cumulatie
        assert "wsLoadInstrument(bel)" in ws and "esc(" in li
        assert "laatste 7 dagen" in ws and "deze week" not in ws

    def test_39_workspace_no_duplicate_kpis(self):
        # Dedup: load precies één kaart, feedback/open-reactie precies één kaart.
        # (De gerenderde-output-dedup wordt end-to-end bewezen in workspace_render.test.mjs.)
        ws = _fn("wsRender")
        assert ws.count("ws-load-panel") == 1
        assert ws.count("ws-fb-panel") == 1

    def test_40_workspace_grid_hierarchy(self):
        # Robuuste responsieve hiërarchie via grid-areas (geen absolute placement).
        ws = _fn("wsRender")
        for area in ("grid-area:attn", "grid-area:load", "grid-area:plan",
                     "grid-area:next", "grid-area:fb", "grid-area:src"):
            assert area in ws, f"grid-area ontbreekt: {area}"
        assert "grid-template-areas" in _DS
        assert "webSeg" not in ws                              # web vervangen door grid

    def test_41_workspace_shares_panel_language(self):
        # Workspace deelt de ds-panel-kaarttaal met Dossier; geen glass-lens meer.
        ws = _fn("wsRender")
        assert "ws-lens" not in ws
        assert "ds-panel" in ws and "ds-sechead" in ws and "ds-label" in ws

