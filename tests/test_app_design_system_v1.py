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
    PRIMS = ["wsAnchor", "wsSignal", "wsLine", "dcNode", "dsAttnCard", "dsMetric", "dsPanel", "dsChip", "dsFresh",
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
        ws = _fn("wsAnchor")
        for part in ("ws-orb", "initialen("):
            assert part in ws, f"anchor mist {part}"
        assert "ws-name" in _fn("wsRender")                  # naam in de scène-kop
        dc = _fn("dcRender")
        for part in ("dc-orb", "dc-name", "initialen("):
            assert part in dc, f"dossier-kop mist {part}"
        # opgeruimd: geen achtergelaten shell/stage-primitives naast de nieuwe compositie
        for dead in ("function dsShell(", "function dsStage(", "function dsFocal(", "function dsStat("):
            assert dead not in _APP, f"dode primitive {dead} nog aanwezig"

    def test_13_workspace_en_dossier_delen_de_athlete_taal(self):
        # Workspace is een canvas-scène (wsAnchor), Dossier een memory-compositie —
        # verschillende layouts, maar DEZELFDE athlete-taal: zelfde identiteitsbron,
        # zelfde statussemantiek, zelfde gedeelde nav. Geen tweede vocabulaire.
        wsb, dcb = _fn("wsRender"), _fn("dcRender")
        for body, view in ((wsb, "workspace"), (dcb, "dossier")):
            assert "dsTone(" in body, f"{view} gebruikt de gedeelde statussemantiek niet"
            assert f'athleteNav("{view}"' in body, f"{view} mist de gedeelde athlete-nav"
        assert "wsAnchor(" in wsb and "wsSignal(" in wsb      # canvas-anchor + dominant signaal
        assert _APP.count("function wsAnchor(") == 1

    def test_14_alle_athlete_views_spreken_hetzelfde_signaaldialect(self):
        # Journey A/D: hetzelfde signaal krijgt op Home, Workspace en Dossier dezelfde
        # toon uit dezelfde mapper — ongeacht welke presentatievorm de view kiest.
        for fn in ("prioDetailHtml", "wsRender", "dcRender"):
            assert "dsTone(" in _fn(fn), f"{fn} kiest zelf kleuren i.p.v. dsTone"
        # Elke view kiest de presentatievorm die bij haar doel past, maar put uit
        # dezelfde primitives-familie en dezelfde toon-mapper.
        assert "dsAttnCard(" in _fn("prioDetailHtml")         # Home-detail: briefing-kaart
        assert "dcNode(" in _fn("dcRender")                   # Dossier: knooppunt op de tijd-spine
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
        assert 'genMount("#home-genbar"' in _APP and 'genMount("#tp-genbar"' in _APP

    def test_18_workspace_quick_actions_hergebruiken_bestaande_routes(self):
        body = _fn("wsRender")
        for call in ("openAthleteModule('schema'", "openAthleteModule('atleten'",
                     "openAthleteModule('dossier'"):
            assert call in body, f"route {call} verdwenen"
        # geen duplicate write-logica: dempen loopt via de bestaande authority
        assert "/api/teampuls/gezien" in _fn("wsMarkeerGezien")

    def test_19_dossier_ordening_en_copy_contract_intact(self):
        body = _fn("dcRender")
        i = body.index("build_diagnostic")
        assert body.index("dc-attn", i) > i and body.index("dc-planning", i) > i
        for copy in ("Aandacht nu", "Geen actiepunten", "Doelen &amp; planning",
                     "eerder afgehandeld", "geen open Home-actie", "t.o.v. referentie"):
            assert copy in body, f"copy-contract mist: {copy}"

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
        assert "ws-plan" in body and "ws-context" in body      # slots worden lazy gevuld

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
        ws = _fn("wsRender")
        for call in ("openAthleteModule('schema'", "openAthleteModule('atleten'",
                     "openAthleteModule('dossier'", "deepAtleet('teampuls'", "wsMarkeerGezien("):
            assert call in ws, f"actie {call} verdwenen uit de canvas-compositie"
        assert "/api/teampuls/gezien" in _fn("wsMarkeerGezien")   # bestaande authority

    def test_32_focal_ladder_heeft_precies_een_eigenaar(self):
        body = _fn("wsRender")
        for owner in ('owner: "bel-pct"', 'owner: "bel-km"', 'owner: "attn"', 'owner: "rust"'):
            assert owner in body, f"focal-ladder mist {owner}"
        assert "const owns = s => focal.owner === s;" in body
        # het dominante cijfer wordt downstream niet herhaald
        assert 'owns("bel-pct") && a.soort === "belasting"' in body

    def test_33_dossier_spine_maakt_tijd_ruimtelijk(self):
        body = _fn("dcRender")
        assert "dc-spine" in body and "dc-era" in body
        assert "weight: 1" in body                              # vandaag = sterkste punt
        assert "future: true" in body                           # planning ligt vóór ons
        assert "Math.min(4, 2 + Math.floor(i / 4))" in body     # ouder = zwakker
        # gewicht is ook echt visueel: contrast/schaal per niveau
        for w in (".dc-node.w1", ".dc-node.w3", ".dc-node.w4"):
            assert w in _DS, f"tijd-gewicht {w} niet gestyled"

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
        assert "dsFresh(" in _fn("dcRender")

    def test_36_geen_legacy_layout_resten(self):
        # De vervangen presentatie is echt opgeruimd, niet overlaagd.
        for dead in ("ws-detail\" class=\"md-detail", "id=\"ws-lijst\"", "id=\"ws-zoek\""):
            assert dead not in _HTML, f"legacy markup {dead} nog aanwezig"
        for dead in (".ws-tag{", ".ws-dl{", ".ws-sec{", ".dc-head{", ".dc-card{"):
            assert dead not in _CSS, f"legacy CSS {dead} nog aanwezig"
        assert "function wsToonLijst(" not in _APP               # rail-toggle is weg

    def test_37_cockpit_is_scene_met_maximaal_twee_glaspanels(self):
        # 1:1 north-star-contract (bewuste wijziging t.o.v. de schijf-compositie):
        # de athlete-BUST is het centrale object, met orbit-lagen achter én vóór
        # (echte overlap); het signaal is scène-typografie + de orbit-gauge (geen
        # schijf/kaart); er zijn maximaal TWEE glas-panels; de achtergrond doet
        # mee. Embedded regels (.ws-line) blijven randloos.
        pane = _DS.split(".ws-pane{")[1][:420]
        assert "backdrop-filter" in pane and "linear-gradient" in pane
        assert _fn("wsRender").count('class="ws-pane') == 2       # harde twee-panels-grens
        blok = _DS.split(".ws-line{")[1][:220]
        assert "border:1px solid" not in blok                     # regel blijft embedded
        assert "function wsBust(" in _APP and "wsBust()" in _fn("wsRender")
        assert "ws-orbit-back" in _fn("wsRender") and "ws-orbit-front" in _fn("wsRender")
        assert ".ws-plat" in _DS                                  # platform: de athlete stáát
        assert ".ws-gauge-lap1" in _DS and ".ws-gauge-lap2" in _DS  # ratio in de geometrie
        assert ".ws-amb{" in _DS                                  # ambient licht
        assert ".ws-orbits" in _DS and ".ws-vig{" in _DS          # achtergrondlagen
        assert "prefers-reduced-motion" in _DS
