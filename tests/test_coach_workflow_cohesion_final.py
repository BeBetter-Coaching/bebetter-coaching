"""Coach Workflow Cohesion v1 — FINAL REPAIR (athlete-first shell).

De vorige repairs fixten losse deeplinks; deze pass maakt de PWA als geheel
athlete-first: ÉÉN view-gekeyd navigatiecontract dat de actieve atleet (uit de
route-hash) door de hele shell meeneemt — inclusief de GLOBALE sidebar — tot de
coach bewust een andere atleet kiest of naar een globale view gaat.

Kern:
  • `activeAthleteKey()` leest de actieve atleet uit de route-hash (enige bron).
  • `openAthleteModule(view, key)` — view-gekeyd (geen module-alias-map meer).
  • `openModuleFromNav(view)` — sidebar/bottomnav/'meer'/home-kaarten worden
    athlete-aware: athlete-view + actieve atleet → die atleet; globale view → globaal.
  • Schema-refresh behoudt de actieve workbench (finding #9).
  • Orphan-intake pariteit met Streamlit via /api/intake/orphans (finding #8).

    python3 -m pytest tests/test_coach_workflow_cohesion_final.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_HTML = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()


def _fn(name):
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
    raise AssertionError(f"function {name} niet gebalanceerd")


# ══ Eén view-gekeyd contract (§3, §16 simplificatie) ═══════════════════════
class TestOneContract:
    def test_1_athlete_views_set(self):
        assert '_ATHLETE_VIEWS = new Set(["atleten", "schema", "dossier"])' in _APP

    def test_2_module_alias_map_verwijderd(self):
        assert "_AM_ROUTES" not in _APP        # oude indirectie weg

    def test_3_een_openAthleteModule_definitie(self):
        assert _APP.count("function openAthleteModule(") == 1

    def test_4_active_athlete_key_leest_route(self):
        body = _fn("activeAthleteKey")
        assert "location.hash" in body
        assert "_ATHLETE_VIEWS.has(view)" in body

    def test_5_openAthleteModule_view_gekeyd_route_leidend(self):
        body = _fn("openAthleteModule")
        assert "!_ATHLETE_VIEWS.has(view)" in body       # globale view → gewone entry
        assert '"#" + view + "/"' in body
        assert "applyRoute()" in body


# ══ Athlete-aware globale sidebar (§4 — finding #2/#6) ═════════════════════
class TestAthleteAwareSidebar:
    def test_6_nav_adapter_bestaat(self):
        body = _fn("openModuleFromNav")
        assert "activeAthleteKey()" in body
        assert "_ATHLETE_VIEWS.has(view)" in body
        assert "openAthleteModule(view, key)" in body
        assert "else toonView(view)" in body

    def test_7_alle_data_open_view_handlers_via_adapter(self):
        # sidebar + bottomnav + 'meer'-grid + home-kaarten → athlete-aware adapter
        assert _APP.count("openModuleFromNav(b.dataset.openView)") == 4
        assert "() => toonView(b.dataset.openView)" not in _APP     # geen kale context-loze route meer

    def test_8_globale_views_blijven_globaal(self):
        # races/admin/home/intake/strippen/documenten zijn GEEN athlete-view → context los
        for glob in ("home", "races", "admin", "intake", "strippen", "documenten", "feedback", "teampuls"):
            assert glob not in ('atleten', 'schema', 'dossier')
        # de set bevat exact de drie athlete-views
        assert '"atleten", "schema", "dossier"' in _APP

    def test_9_sidebar_athlete_modules_aanwezig(self):
        # de athlete-aware sidebarlinks bestaan (Atleten=dossier-detail, Dossier=cockpit, Schema)
        assert 'data-open-view="atleten"' in _HTML
        assert 'data-open-view="dossier"' in _HTML
        assert 'data-open-view="schema"' in _HTML


# ══ Schema-refresh behoudt actieve workbench (finding #9) ══════════════════
class TestSchemaRefreshPreserve:
    def test_10_sb_refresh_heropent_actieve_atleet_en_modus(self):
        i = _APP.index('bindRefresh("sb-refresh"')
        block = _APP[i:i + 500]
        assert "const st = sbState" in block
        assert "sbDraftSave()" in block                 # PF-1 flush vóór reload
        assert "schemaWerk(a, st.mode)" in block        # zelfde atleet + modus terug


# ══ Orphan-intake pariteit met Streamlit (§9 — finding #8) ═════════════════
class TestOrphanParityFrontend:
    def test_11_orphan_lijst_uit_pariteit_endpoint(self):
        body = _fn("laadOrphanIntakes")
        assert "/api/intake/orphans" in body
        assert "a.suggestie" in body                     # voorgestelde match getoond
        assert 'openAthleteModule("atleten"' in body     # naar het koppel-dossier

    def test_12_endpoint_bestaat(self):
        api = open(os.path.join(_ROOT, "pwa", "api.py")).read()
        assert '@app.get("/api/intake/orphans")' in api
        assert "intake.orphan_intakes()" in api


import intake_store   # noqa: E402
import intake_core    # noqa: E402
import atleten_core   # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_store, "_gh_token", lambda: "")
    for attr, naam in [
        ("_INTAKES_LOCAL", "intakes.json"),
        ("_INTAKE_ARCHIEF_LOCAL", "intakes_archief.json"),
        ("_LAATSTE_INTAKE_LOCAL", "laatste_intakes.json"),
    ]:
        monkeypatch.setattr(intake_store, attr, str(tmp_path / naam), raising=False)
    return intake_store


# ══ Identity-guard: `nieuw:` is geen app-brede athlete-context (externe review) ══
# Een pre-link route (#atleten/nieuw:Naam) opent wél het orphan-detail voor de koppel-
# flow, maar mag NOOIT cross-module worden meegenomen (globale sidebar → Schema/Dossier),
# want die verwachten een canonical FS user_key. Alleen na koppelen werkt athlete-first.
class TestOrphanIdentityGuard:
    def test_g1_active_key_negeert_nieuw_prefix(self):
        body = _fn("activeAthleteKey")
        assert 'ident.startsWith("nieuw:")' in body
        assert "return \"\"" in body

    def test_g2_orphan_detail_blijft_via_route_consume(self):
        # applyRoute opent openDossier(ident) voor een atleten-route — óók een nieuw:-orphan
        # (de guard zit in activeAthleteKey, niet in de route-consume).
        body = _fn("applyRoute")
        assert 'if (view === "atleten" && ident) openDossier(ident)' in body

    def test_g3_sidebar_adapter_leunt_op_active_key(self):
        # Zonder canonical active key (nieuw: → "") valt openModuleFromNav terug op de
        # gewone module-entry → geen #schema/nieuw:... .
        body = _fn("openModuleFromNav")
        assert "activeAthleteKey()" in body
        assert "else toonView(view)" in body

    def test_g4_geen_key_of_globale_view_valt_terug(self):
        body = _fn("openAthleteModule")
        assert "if (!user_key || !_ATHLETE_VIEWS.has(view))" in body

    def test_g5_active_key_behaviour_matrix(self):
        # Deterministische her-implementatie van de guard-logica, gedreven door dezelfde
        # regels als de JS (route wint; nieuw: telt niet; alleen athlete-views).
        ATH = {"atleten", "schema", "dossier"}

        def active(hash_):
            raw = hash_.lstrip("#")
            i = raw.find("/")
            if i == -1:
                return ""
            view, ident = raw[:i], raw[i + 1:]
            if ident.startswith("nieuw:"):
                return ""
            return ident if (view in ATH and ident) else ""

        assert active("#atleten/nieuw:Dominique Slooff") == ""     # orphan → geen context
        assert active("#schema/nieuw:X") == ""                     # orphan → geen context
        assert active("#atleten/uk-dom") == "uk-dom"               # canonical → context
        assert active("#schema/uk-dom") == "uk-dom"                # canonical → context
        assert active("#races") == ""                              # globale view → geen context
        assert active("#home") == ""


class TestOrphanParityBackend:
    def test_13_orphan_intakes_toont_nieuw_ondanks_fs_namesake(self, store, monkeypatch):
        # De Dominique-case: orphan blijft zichtbaar ook al bestaat er nu een FS-namesake
        # (de roster zou 'm weg-mergen; deze lijst leest RECHTSTREEKS de store).
        store.save_intakes({
            "nieuw:Dominique Slooff": {"athlete_name": "Dominique Slooff", "doel": "10 km"},
            "uk-bestaand": {"athlete_name": "Al Gekoppeld", "doel": "5 km"},
        })
        monkeypatch.setattr(atleten_core.fs_core, "heeft_token", lambda: True)
        monkeypatch.setattr(atleten_core.fs_core, "roster", lambda: [
            {"user_key": "uk-dom", "naam": "Dominique Slooff", "groep": "1. Los"},
        ])
        orphans = intake_core.orphan_intakes()
        keys = [o["key"] for o in orphans]
        assert "nieuw:Dominique Slooff" in keys           # zichtbaar
        assert "uk-bestaand" not in keys                  # gekoppelde intake is geen orphan
        dom = next(o for o in orphans if o["key"] == "nieuw:Dominique Slooff")
        assert dom["suggestie"] and dom["suggestie"]["user_key"] == "uk-dom"   # voorgestelde match

    def test_14_geen_orphans_als_alles_gekoppeld(self, store, monkeypatch):
        store.save_intakes({"uk-1": {"athlete_name": "X"}})
        monkeypatch.setattr(atleten_core.fs_core, "heeft_token", lambda: False)
        assert intake_core.orphan_intakes() == []
