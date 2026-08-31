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
    PRIMS = ["wsAnchor", "wsCore", "wsLine", "dcNodeEl", "dsAttnCard", "dsMetric", "dsPanel", "dsChip", "dsFresh",
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
        dc = _fn("dcHeader")                                 # Dossier-identiteit in de kop
        for part in ("dc-mono", "dc-name", "initialen("):
            assert part in dc, f"dossier-kop mist {part}"
        # opgeruimd: geen achtergelaten shell/stage-primitives naast de nieuwe compositie
        for dead in ("function dsShell(", "function dsStage(", "function dsFocal(", "function dsStat("):
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
            assert f'athleteNav("{view}"' in body, f"{view} mist de gedeelde athlete-nav"
        assert "wsAnchor(" in wsb and "wsCore(" in wsb        # canvas-anchor + Athlete Core
        assert _APP.count("function wsAnchor(") == 1

    def test_14_alle_athlete_views_spreken_hetzelfde_signaaldialect(self):
        # Journey A/D: hetzelfde signaal krijgt op Home, Workspace en Dossier dezelfde
        # toon uit dezelfde mapper — ongeacht welke presentatievorm de view kiest.
        for fn in ("prioDetailHtml", "wsRender", "dcRender"):
            assert "dsTone(" in _fn(fn), f"{fn} kiest zelf kleuren i.p.v. dsTone"
        # Elke view kiest de presentatievorm die bij haar doel past, maar put uit
        # dezelfde primitives-familie en dezelfde toon-mapper.
        assert "dsAttnCard(" in _fn("prioDetailHtml")         # Home-detail: briefing-kaart
        assert "dcNodeEl(" in _fn("dcScene")                  # Dossier: knooppunt op de tijd-spine
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
        # De load-observatie-duiding (LIVE-CLOSE) blijft woordelijk behouden in de
        # nieuwe cockpit; de context-lenzen dragen de vaste copy-koppen.
        body = _fn("dcRender")
        assert "build_diagnostic" in body
        for copy in ("open Home-actie", "eerder afgehandeld", "geen open Home-actie",
                     "t.o.v. referentie", "monitoring — nog geen coachactie"):
            assert copy in body, f"copy-contract mist: {copy}"
        scene = _fn("dcScene")
        for copy in ("Laatste veranderingen", "Klachten &amp; signalen",
                     "Doelen &amp; beslissingen", "Coachkennis", "Actuele lijn"):
            assert copy in scene, f"lens-copy mist: {copy}"

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
        # het dominante cijfer bestaat één keer als instrument; de aandacht-zin
        # wordt uit DEZELFDE canonieke velden opgebouwd (geen tweede bron-%)
        assert "belZin" in body and "bel.pct" in body
        assert 'owns("bel-pct") ? "1" : ""' in body

    def test_33_dossier_spine_maakt_tijd_ruimtelijk(self):
        # Living Memory Cockpit: ÉÉN memory-spine met een lichtgevend VANDAAG-ankerpunt.
        # Verleden (warm) uit changes[], toekomst (koel, gestippeld) uit planning — de
        # kern draagt de dominante toon. Tijd wordt ruimte, geen verticale lijsttijdlijn.
        rn = _fn("dcRender")
        assert "dcPastNodes(chg)" in rn                          # verleden = echte changes
        assert "dcFutureNodes(plan)" in rn                       # toekomst = planning
        assert "coreTone" in rn                                  # kern draagt dominante toon
        assert "future: true" in _fn("dcFutureNodes")            # planning ligt vóór ons
        scene = _fn("dcScene")
        assert "dc-rail" in scene and "dcHex(coreTone)" in scene  # warm→toon→koel spine
        assert "Vandaag" in scene                                 # lichtgevend ankerpunt
        # tijd is ook echt visueel gestyled: rail, dots, gestippelde toekomst, kern-sun
        for sel in (".dc-rail-future", ".dc-dot", ".dc-coredot", ".dc-node.future"):
            assert sel in _DS, f"tijd-primitive {sel} niet gestyled"

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

    def test_37_athlete_core_scene(self):
        # Workspace-afronding zonder avatar: de menslijn (avatar/bust/portret/
        # pre-rendered human asset) is VOLLEDIG verlaten. De centrale hero is een
        # abstracte, ruimtelijke ATHLETE CORE (glazen sphere + gekantelde orbits +
        # radar-basis) met het dominante signaal geïntegreerd IN de kern. Verder
        # blijft het spatiale contract: gebroken verre geometrie, borderless
        # fragmenten op z-vlakken, geïntegreerd commando.
        core = _fn("wsCore")
        ws = _fn("wsRender")
        # de kern bestaat en wordt gebruikt; de menslijn is echt weg
        assert "function wsCore(" in _APP and "wsCore(focal)" in ws
        assert "function wsHuman(" not in _APP and "function wsBust(" not in _APP
        assert "ws-human" not in _APP and "wsSignal(" not in _APP
        assert "/static/presence/" not in _APP           # geen human-asset meer
        assert not os.path.exists(os.path.join(_ROOT, "pwa", "static", "presence"))
        assert "geslacht" not in ws and "presVar" not in ws        # geen gender-inferentie
        # de kern zelf: sphere + gekantelde ring(en) + geïntegreerd signaal
        assert 'class="ws-sphere"' in core and 'class="ws-rings"' in core
        assert 'class="ws-read"' in core and "ws-read-v" in core   # signaal ín de kern
        # eerlijk instrument: gauge alleen bij data (gaugeFrac), niet verzonnen
        assert "f.gaugeFrac != null" in core
        # verre gebroken geometrie blijft (geen perfecte KPI-ring als centrum)
        assert 'class="ws-geo"' in ws and ws.count("ws-arc") >= 4
        # radar-basis: de kern staat érgens
        assert 'class="ws-plat"' in ws and ".ws-plat{" in _DS
        # fragmenten + twee zichtbare relaties (attn↔node, load↔kern)
        assert "ws-frag-attn" in ws and "ws-frag-load" in ws and "ws-frag-plan" in ws
        assert "ws-frag-fb" in ws and "ws-frag-src" in ws
        # zichtbare relaties: de kern voedt elke aanwezige context via het verbindingsweb
        assert 'class="ws-web"' in ws and "ws-webline" in ws and "ws-webnode" in ws
        # command als instrument-strip: één dominante trigger + lead-in (waaróm) +
        # stille secundaire controls — geen losse pill onderaan.
        assert 'class="ws-cmd"' in ws and "ws-cmd-lead" in ws and "ws-util" in ws
        # De context leeft in premium spatial GLASS LENSES (extern-review-besluit:
        # borderless losgelaten). Geen klassiek card-veld; het is glas (translucent +
        # backdrop-blur + fade naar de scène), geen dashboard-kaart.
        assert ".ws-field{" not in _DS
        assert 'class="ws-lens' in ws and ws.count('class="ws-lens') >= 4
        lens = _DS.split(".ws-lens{")[1][:600]
        assert "backdrop-filter:blur" in lens.replace(" ", "")   # echt glas
        assert "mask-image" in lens                              # fade naar de scène (geen harde kaart)
        # rijkere kern (intelligentie-object, geen platte bol): intermediate
        # shell-rim, dovende meridiaan-fragmenten, core-light — abstract (geen mens).
        for rich in ("ws-shell-rim", "ws-sph-grad", "ws-corelight"):
            assert rich in core, f"kern mist verrijking {rich}"
        # honest locale: NL-decimaalkomma, presentationeel (verzint geen waarde)
        assert "function nlNum(" in _APP and "nlNum(bel.km_recent)" in ws
        assert ".ws-amb{" in _DS and ".ws-vig{" in _DS             # omgeving doet mee
        # de centrerings-transform van signaal én command mag niet door 'none'
        # sneuvelen: hij staat in de BASIS-regel, niet alleen in de entree-keyframe.
        assert "ws-readin" in _DS
        assert "prefers-reduced-motion" in _DS
        read_rule = _DS.split(".ws-read{")[1][:200]
        assert "translate(-50%,-50%)" in read_rule

    def test_38_final_10pct_refinement(self):
        # Laatste 10%: levende intelligence-core, één load-instrument, command uit
        # het platform, ruimtelijke periferie — alles presentation-only en op echte data.
        core = _fn("wsCore")
        ws = _fn("wsRender")
        # A. levende core: interne datastromen (geen labels/waarden) + reading-plane
        assert "ws-dataflow" in core and "ws-flow" in core
        assert "ws-readplane" in core                          # waarde komt uit de kern
        assert ".ws-flow{" in _DS and "@keyframes ws-flow" in _DS
        # B. het load-cluster is ÉÉN instrument (weekstrip + curve gefuseerd), op
        #    dezelfde bronvelden; cumulatief stijgt of blijft vlak (rustdag).
        assert "function wsLoadInstrument(" in _APP and _APP.count("function wsLoadInstrument(") == 1
        li = _fn("wsLoadInstrument")
        assert "bel.runs" in li and "bel.km_basis_week" in li  # zelfde bron, geen nieuwe data
        assert "d.cum = acc" in li and "acc += d.km" in li     # eerlijke cumulatie
        assert "wsLoadInstrument(bel)" in ws
        assert "esc(" in li                                    # geen XSS-regressie
        assert ".ws-loadinst{" in _DS and ".li-cum{" in _DS
        # C. command komt uit het platform: output-node + track (alleen bij een actie)
        #    en een plug op de command. Bestaande actie-semantiek blijft.
        assert "ws-ptrack" in ws and "ws-pout" in ws
        assert 'class="ws-plug"' in ws
        assert "wsMarkeerGezien(" in ws                        # actie intact
        # D. ruimtelijke periferie: vloer-perspectief (geen fake data/labels)
        assert 'class="ws-floor"' in ws and ".ws-floor " in _DS
        # discipline: nieuwe motion staat óók uit onder reduced-motion
        assert ".ws-flow,.ws-scan,.li-bar" in _DS.replace(" ", "")

    def test_39_final_polish_pass(self):
        # Polish-pass: geen "globe" meer maar een gelaagd intelligence-object;
        # load minder chart-achtig; één extra dieptelaag; command-emanation.
        core = _fn("wsCore")
        ws = _fn("wsRender")
        li = _fn("wsLoadInstrument")
        # DE-GLOBE: geen VOLLEDIGE meridiaan/breedte-ellipsen meer als globe-grid;
        # de structuur bestaat uit onvolledige/asymmetrische arc-fragmenten (paths).
        assert 'class="ws-sph-grad" cx=' not in core           # geen complete ellipse-meridianen
        assert '<path class="ws-sph-grad"' in core             # gebroken meridiaan-fragmenten
        # DRIE dieptelagen: intermediate intelligence-field + eigen rand-highlight
        assert "url(#ws-ifield)" in core and "ws-shell-rim" in core and "ws-shell-rim dim" in core
        assert 'radialGradient id="ws-ifield"' in core          # intermediate-field gradient in de defs
        # de bol-silhouet blijft (rim) zodat het volume leest, maar het interieur is gebroken
        assert "ws-sph-rim" in core
        # LOAD: referentie is een thin threshold-beam (fade-gradient), geen chart-gridline
        assert 'linearGradient id="ws-liref"' in li             # beam-gradient in de instrument-defs
        assert "url(#ws-liref)" in _DS                          # .li-ref gebruikt de fade-beam
        assert 'stroke-dasharray:3 6' not in _DS.split(".li-ref{")[1][:80]  # geen dashed gridline meer
        # DIEPTE: één extra ambient laag (horizontale haze), reduced-motion-safe
        assert 'class="ws-haze"' in ws and ".ws-haze{" in _DS and "@keyframes ws-haze" in _DS
        # COMMAND-EMANATION: output-node pulse + track-draw als eenmalige entree-sequence
        assert "@keyframes ws-trackdraw" in _DS and "@keyframes ws-poutpulse" in _DS
        # a11y: expliciete focus-indicator op de primaire actie
        assert ".ws-cmd:focus-visible{outline" in _DS.replace(" ", "").replace("\n", "")
        # motion-performance: geen transition:all in de workspace-laag
        assert "transition:all" not in _DS.replace(" ", "")

    def test_40_north_star_convergence(self):
        # Convergentie naar de referentie: de kern is een verbindings-hub die elke
        # AANWEZIGE context voedt (data-gestuurd, per-context accent), een luminous
        # particle-core, en een planet-horizon voor kosmische diepte.
        core = _fn("wsCore")
        ws = _fn("wsRender")
        # verbindingsweb, data-gestuurd (alleen echte context krijgt een lijn)
        assert 'class="ws-web"' in ws
        assert "if (attn.length) web +=" in ws                 # geen aandacht-lijn zonder aandacht
        assert "if (bel.km_recent != null) web +=" in ws       # geen belasting-lijn zonder data
        # per-context accent via de tone-klasse op elk segment
        assert "webSeg(tone" in ws and "webSeg(belTone" in ws
        assert "webSeg(planWebTone" in ws and "webSeg(fbTone" in ws
        assert ".ws-webline{" in _DS and ".ws-webnode{" in _DS
        # de oude losse connectoren zijn vervangen door het web
        assert "ws-conn2" not in ws and 'class="ws-conn"' not in ws
        # luminous particle-core: dichter deeltjesveld dan de vorige pass
        assert core.count("ws-sph-dot") >= 16
        # planet-horizon: kosmische z-diepte (statisch, reduced-motion-neutraal)
        assert 'class="ws-horizon"' in ws and ".ws-horizon{" in _DS
        # discipline: web verborgen op mobiel + bevroren onder reduced-motion
        assert ".ws-web{display:none}" in _DS.replace(" ", "")
        assert ".ws-web,.ws-webnode" in _DS.replace(" ", "")

    def test_41_glass_lenses(self):
        # Extern-review-besluit: de 4 kern-contexten leven in premium spatial GLASS
        # LENSES (borderless losgelaten). Het moet glas zijn (translucent + backdrop-
        # blur + fade), geen dashboard-card; bronnen blijft subordinate; command apart.
        ws = _fn("wsRender")
        # precies de 4 betekenisvolle lenzen: aandacht, load, plan, feedback
        assert 'ws-frag-attn' in ws and 'class="ws-lens' in ws
        assert ws.count('class="ws-lens') >= 4                  # attn + load(2×) + plan + fb
        # glas-materiaal, geen kaart
        lens = _DS.split(".ws-lens{")[1][:600].replace(" ", "")
        assert "backdrop-filter:blur" in lens and "mask-image:linear-gradient" in lens
        assert "box-shadow:inset" in lens                       # licht-van-boven, geen web-card-shadow
        # accent-glow ALLEEN bij een lens mét connector (.conn), exact op het
        # instappunt (per-lens left/top) — geen generieke middenpositie.
        assert ".ws-lens.conn::after" in _DS
        for f in ("ws-frag-attn", "ws-frag-load", "ws-frag-plan", "ws-frag-fb"):
            assert f".ws-frag-{f.split('-')[-1]} .ws-lens::after" in _DS or f"{f} .ws-lens::after" in _DS
        # data-gestuurd: attn-lens krijgt .conn alleen bij echte aandacht
        assert "ws-lens ${attn.length ? 'conn' : ''}" in ws.replace('"', "'")
        # bronnen blijft een subordinate strip (geen 5e lens); command blijft apart
        assert "ws-frag-src" in ws and "ws-src-rail" in ws
        assert 'ws-frag-src ws-lens' not in ws and 'ws-dock' in ws
        # Core blijft dominant: lens staat achter de content (z-index:-1)
        assert "z-index:-1" in _DS.split(".ws-lens{")[1][:120]
        # het oude scrim-primitive is echt vervangen (niet overlaagd)
        assert 'class="ws-scrim"' not in ws
