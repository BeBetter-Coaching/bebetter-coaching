"""Coach Workflow Cohesion v1 — athlete-context navigatie-contract.

Deze milestone is een workflow/navigation-laag bovenop de bestaande PWA: één canoniek
athlete-deeplink-contract (`openAthleteModule`) plus een gedeelde context-nav (`athleteNav`),
zodat de coach vanuit een athlete-signaal/-view naar een andere module gaat zonder opnieuw te
zoeken. Het gedrag zit in de frontend (app.js); deze source-guards borgen dat de mechaniek
aanwezig blijft en niet stil terugvalt op de oude 'algemene lijst'-navigatie. De end-to-end
werking (hash-bouw, draft-flush, chip-render) is los in de browser geverifieerd via `new Function`.

    python3 -m pytest tests/test_coach_workflow_cohesion.py -q
"""
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_CSS = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()


def _fn(name):
    """Grab de body van een top-level `function name(...) { ... }` uit app.js."""
    i = _APP.index(f"function {name}(")
    depth, started = 0, False
    for j in range(i, len(_APP)):
        c = _APP[j]
        if c == "{":
            depth += 1; started = True
        elif c == "}":
            depth -= 1
            if started and depth == 0:
                return _APP[i:j + 1]
    raise AssertionError(f"function {name} niet afgesloten")


# ── 1. Het canonieke navigatiecontract ──────────────────────────────────────
class TestNavigationContract:
    def test_openathletemodule_bestaat(self):
        assert "function openAthleteModule" in _APP
        assert "function athleteNav" in _APP

    def test_route_map_dekt_de_drie_athlete_views(self):
        # dossier→atleten (klassiek dossier), schema→schema, cockpit→dossier (Masterbrein-cockpit).
        assert '_AM_ROUTES = { dossier: "atleten", schema: "schema", cockpit: "dossier" }' in _APP

    def test_contract_schrijft_userkey_in_de_hash(self):
        body = _fn("openAthleteModule")
        assert 'encodeURIComponent(user_key)' in body        # user_key in de route
        assert '"#" + view + "/"' in body
        assert "applyRoute()" in body                          # laadt via bestaande consume-paden

    def test_route_userkey_is_leidend(self):
        # applyRoute her-dispatcht uit de hash → route user_key wint van stale UI-state.
        assert "function applyRoute" in _APP
        body = _fn("openAthleteModule")
        assert "applyRoute()" in body

    def test_geen_key_valt_terug_op_gewone_module_entry(self):
        body = _fn("openAthleteModule")
        assert "if (!user_key)" in body and "toonView(view)" in body

    def test_schema_draft_flush_voor_wegnavigeren(self):
        # §9/PF-1: verlaten van de schema-workbench flush't eerst de coach-draft.
        body = _fn("openAthleteModule")
        assert 'huidigeView === "schema"' in body
        assert "sbDraftSave" in body and "sbState" in body


# ── 2. Gedeelde athlete-context nav (§5) ─────────────────────────────────────
class TestAthleteNav:
    def test_nav_component_gedeeld_en_geen_key_leeg(self):
        body = _fn("athleteNav")
        assert "if (!user_key) return \"\"" in body
        assert "anav-chip" in body

    def test_nav_verbergt_de_actieve_view(self):
        body = _fn("athleteNav")
        assert "o.view !== activeView" in body                # actieve tool niet dubbel

    def test_nav_gebruikt_het_contract(self):
        body = _fn("athleteNav")
        assert "openAthleteModule(" in body

    def test_nav_hergebruikt_over_modules_geen_duplicatie(self):
        # Zelfde component op dossier + schema-entry + schema-workbench + cockpit.
        assert 'athleteNav("atleten", d.user_key)' in _APP         # klassiek dossier
        assert 'athleteNav("schema", a.key)' in _APP               # schema config-entry
        assert 'athleteNav("schema", sbState.key)' in _APP         # schema workbench
        assert 'athleteNav("dossier", vm.key)' in _APP             # cockpit
        assert _APP.count("function athleteNav") == 1              # één definitie

    def test_css_aanwezig_en_mobiel_compact(self):
        assert ".anav-chip{" in _CSS
        assert "@media(max-width:480px)" in _CSS and ".anav-chip" in _CSS.split("@media(max-width:480px)")[1][:120]


# ── 3. Teampuls → Dossier (bugfix) ───────────────────────────────────────────
class TestTeampulsDossier:
    def test_dossier_knop_opent_de_atleet_niet_de_lijst(self):
        # Was: toonView("atleten") (key weggegooid). Nu: canonieke deep-link.
        block = _APP[_APP.index("function pulsItem"):_APP.index("function pulsItem") + 2400]
        assert 'openAthleteModule("dossier", it.user_key)' in block
        assert '"[data-dossier]").addEventListener("click", () => toonView("atleten")' not in _APP


# ── 4. Schema-verloop → Schema (nieuw) ───────────────────────────────────────
class TestSchemaVerloop:
    def test_kaart_krijgt_schema_actie_naar_dezelfde_atleet(self):
        block = _APP[_APP.index("function svItem"):_APP.index("function svItem") + 1800]
        assert "data-open-schema" in block
        assert 'openAthleteModule("schema", it.user_key)' in block


# ── 5. Dossier ↔ Schema ──────────────────────────────────────────────────────
class TestDossierSchema:
    def test_cockpit_naar_schema_via_contract(self):
        body = _fn("dcGoSchema")
        assert 'openAthleteModule("schema", key)' in body     # genormaliseerd, geen hand-rolled pushState
        assert "history.pushState" not in body

    def test_schema_workbench_heeft_dossier_chip(self):
        # De athlete-nav in de schema-kop levert Dossier/Cockpit (Schema zelf verborgen).
        assert 'athleteNav("schema", sbState.key)' in _APP


# ── 6. Intake → Schema (§10) ─────────────────────────────────────────────────
class TestIntakeNaarSchema:
    def test_na_koppel_primaire_next_action_is_schema(self):
        block = _APP[_APP.index("const doeKoppel"):_APP.index("const doeKoppel") + 900]
        assert 'openAthleteModule("schema", userKey)' in block   # primair: Bouw schema
        assert "bouw nu het schema" in block                     # expliciete next-action-tekst

    def test_nieuw_prefix_blijft_pre_link_identity(self):
        # De koppel-guard weigert nog steeds een niet-canonieke (nieuw:) target.
        core = open(os.path.join(_ROOT, "pwa", "intake_core.py")).read()
        assert 'startswith("nieuw:")' in core


# ── 7. Home → directe coachactie (§6) ────────────────────────────────────────
class TestHomeDirect:
    def test_schema_signaal_opent_de_workbench_niet_de_verlooplijst(self):
        block = _APP[_APP.index("function prioDoe"):_APP.index("function prioDoe") + 1200]
        assert 'openAthleteModule("schema", it.user_key)' in block
        assert 'deepAtleet("schema-verloop"' not in block        # niet meer de algemene lijst

    def test_dossier_signaal_blijft_direct_de_atleet_openen(self):
        block = _APP[_APP.index("function prioDoe"):_APP.index("function prioDoe") + 1200]
        assert 'deepAtleet("atleten", it.user_key, () => openDossier(it.user_key))' in block


# ── 8. Athlete picker gating (§11) — behoud short-circuit bij bekende key ─────
class TestPickerGating:
    def test_deeplink_routes_short_circuiten_de_picker(self):
        # applyRoute opent bij een ident direct de atleet; picker/lijst alleen zonder ident.
        block = _APP[_APP.index("function applyRoute"):_APP.index("function applyRoute") + 700]
        assert "if (ident) openSchemaAthlete(ident)" in block
        assert "if (view === \"atleten\" && ident) openDossier(ident)" in block
        assert "openDossierCockpit(ident)" in block

    def test_andere_atleet_kiezen_blijft_mogelijk(self):
        # 'Alle atleten' back-navigatie verlaat de context expliciet (geen verborgen wissel).
        assert "Alle atleten" in _APP


# ── 9. Geen architecture drift ───────────────────────────────────────────────
class TestNoDrift:
    def test_geen_nieuwe_localstorage_canonical_truth(self):
        body = _fn("openAthleteModule") + _fn("athleteNav")
        assert "localStorage" not in body                       # nav draagt geen eigen store
        assert "fetch(" not in body                             # geen eigen dataload/truth

    def test_hergebruikt_bestaande_router(self):
        # Geen tweede routing-laag: het contract leunt op pushState + het bestaande applyRoute.
        body = _fn("openAthleteModule")
        assert "applyRoute()" in body
        assert _APP.count("function applyRoute") == 1
