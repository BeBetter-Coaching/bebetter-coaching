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
    PRIMS = ["dsShell", "dsAttnCard", "dsMetric", "dsPanel", "dsChip", "dsFresh",
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
    def test_12_shell_bestaat_en_toont_identiteit_dominant(self):
        body = _fn("dsShell")
        for part in ("ds-med", "ds-shell-name", "initialen(", "ds-shell-sub"):
            assert part in body, f"shell mist {part}"

    def test_13_workspace_en_dossier_gebruiken_dezelfde_shell(self):
        assert "dsShell({" in _fn("wsRender")
        assert "dsShell({" in _fn("dcRender")

    def test_14_home_detail_deelt_de_attention_primitive(self):
        # Journey A/D: hetzelfde signaal ziet er op Home, Workspace en Dossier gelijk uit.
        assert "dsAttnCard(" in _fn("prioDetailHtml")
        assert "dsAttnCard(" in _fn("wsRender")
        assert "dsAttnCard(" in _fn("dcRender")

    def test_15_geen_tweede_athlete_nav(self):
        # De bestaande gedeelde nav blijft de enige; het DS stijlt 'm alleen.
        assert _APP.count("function athleteNav") == 1
        assert "function dsAthleteNav" not in _APP
        assert 'athleteNav("dossier", vm.key)' in _APP        # Cohesion-contract intact
        assert ".ds-shell .anav-chip" in _DS                  # opgewaardeerd, niet vervangen

    def test_16_athlete_views_krijgen_het_volle_canvas(self):
        # Root cause van het split-screen-gevoel: Workspace/Dossier misten de brede view.
        assert 'class="view ds-view" data-view="workspace"' in _HTML
        assert 'class="view ds-view" data-view="dossier"' in _HTML
        assert ".view.ds-view{max-width:" in _DS
        assert ".ds-view .md-list" in _DS                     # lijst wordt ondersteunende rail


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
