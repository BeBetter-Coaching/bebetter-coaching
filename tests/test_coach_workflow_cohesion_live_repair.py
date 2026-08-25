"""Coach Workflow Cohesion v1 — LIVE REPAIR (desktop-hertest bevindingen).

Deze pass repareert de echte live gaps die de source-guards van de eerste build niet
afvingen omdat ze een RACE / viewport-afhankelijk clobber waren:

  A/B — Dossier-deeplink verloor de atleet vanuit meerdere routes en bij reload,
        doordat de late roster-loader het geopende detail overschreef (mobiele tak
        van `toonDossierLijstView` negeerde `dossierSel`, en `openDossier` racete met
        `laadDossierLijst`). Fix = cockpit-patroon (`atletenOpenPending`, detail opent
        ná de lijst-render) + beide master-detail-takken respecteren de open selectie.
        Reproductie + fix zijn los in de browser bevestigd (760px én 1280px).
  Schema-cohesie — de athlete-nav zat alleen in de workbench-stage; nu in álle stages.
  C — één gedeelde refresh-spinner helper (`withSpin`/`bindRefresh`) voor elke knop.
  D — historische orphan-intake (`nieuw:`) blijft terugvindbaar (Intake-module) en
      koppelbaar met een VOORGESTELDE FS-match (coach-confirm, geen auto-link).
  E — expliciet semantiek-contract Teampuls (belasting-monitoring) ≠ Home (actielijst).

De meeste checks zijn source-guards op app.js (het gedrag is deterministisch gemaakt);
de orphan-suggestie + koppel-mechaniek zijn echte backend-unittests.

    python3 -m pytest tests/test_coach_workflow_cohesion_live_repair.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_SW = open(os.path.join(_ROOT, "pwa", "static", "sw.js")).read()
_HTML = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()


def _fn(name):
    """Body van een top-level `function name(...) { ... }` uit app.js (brace-match)."""
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
    raise AssertionError(f"function {name} niet gebalanceerd gevonden")


# ══ A/B — gedeelde reload-safe Dossier route-consume ════════════════════════
class TestDossierRouteConsume:
    def test_1_open_dossier_gebruikt_pending_patroon_zoals_de_cockpit(self):
        # openDossier opent niet meer racend náást laadDossierLijst, maar zet een
        # pending en laat de loader het detail ná de lijst-render openen.
        body = _fn("openDossier")
        assert "atletenOpenPending = ident" in body
        assert "if (!dossierPicker)" in body

    def test_2_laadDossierLijst_replayt_pending_na_lijstrender(self):
        body = _fn("laadDossierLijst")
        # eerst de lijst tonen, DAARNA de pending-atleet openen (detail wint als laatste)
        i_list = body.index("toonDossierLijstView()")
        i_replay = body.index("atletenOpenPending")
        assert i_replay > i_list, "pending-replay moet ná de lijst-render staan"
        assert "openDossier(p)" in body

    def test_3_mobiele_tak_respecteert_open_selectie(self):
        # Kern van de live-bug: een late roster-render mag een geopende atleet
        # (dossierSel) op mobiel NIET verbergen.
        body = _fn("toonDossierLijstView")
        assert "else if (dossierSel)" in body
        assert '$("#d-detail").hidden = false' in body

    def test_4_cockpit_mobiele_tak_respecteert_open_selectie(self):
        body = _fn("dcToonLijst")
        assert "else if (dcSel)" in body
        assert '$("#dc-detail").hidden = false' in body

    def test_5_pending_var_is_gedeclareerd(self):
        assert 'let atletenOpenPending = ""' in _APP

    def test_6_home_dossier_via_gedeeld_contract(self):
        # geen caller-specific openDossier-hack meer; view-gekeyd contract
        body = _fn("prioDoe")
        assert 'openAthleteModule("atleten", it.user_key)' in body
        assert "() => openDossier(it.user_key)" not in body

    def test_7_teampuls_dossier_via_gedeeld_contract(self):
        # Teampuls-kaart 'Dossier' → openAthleteModule("atleten", …), user_key behouden
        assert 'openAthleteModule("atleten", it.user_key)' in _APP

    def test_8_applyRoute_consumeert_atleten_ident_direct(self):
        body = _fn("applyRoute")
        assert 'if (view === "atleten" && ident) openDossier(ident)' in body

    def test_9_route_key_leidend_openAthleteModule_schrijft_hash_en_applyt(self):
        body = _fn("openAthleteModule")
        assert "history.pushState" in body
        assert "applyRoute()" in body
        assert "if (!user_key || !_ATHLETE_VIEWS.has(view))" in body   # geen/globale view → gewone entry


# ══ Schema-cohesie — athlete-nav in ELKE stage ═════════════════════════════
class TestSchemaNavAlleStages:
    def test_10_alle_schema_stages_hebben_athleteNav(self):
        for fn in ("sbRenderConfig", "sbRenderHerijking", "sbRenderPlan", "sbRenderWorkbench"):
            assert 'athleteNav("schema", sbState.key)' in _fn(fn), f"{fn} mist athlete-nav"

    def test_11_config_start_rendert_nav_op_key(self):
        # sbStartConfig header toont de nav al vóór de async config-load
        body = _fn("sbStartConfig")
        assert 'athleteNav("schema", a.key)' in body


# ══ C — gedeelde refresh-spinner helper ════════════════════════════════════
class TestRefreshSpinner:
    def test_12_withSpin_helper_bestaat_met_lifecycle(self):
        body = _fn("withSpin")
        assert 'dataset.busy === "1"' in body           # dubbel afvuren geblokkeerd
        assert 'classList.add("spinning")' in body      # zichtbare start
        assert "disabled = true" in body
        assert "finally" in body                        # reset bij succes én fout
        assert 'classList.remove("spinning")' in body

    def test_13_bindRefresh_helper_bestaat(self):
        assert "function bindRefresh(" in _APP

    def test_14_dossier_en_intake_refresh_via_helper(self):
        assert 'bindRefresh("a-refresh"' in _APP        # Atleten/Dossier-lijst
        assert 'bindRefresh("i-refresh"' in _APP        # Intake
        assert 'bindRefresh("dc-refresh"' in _APP       # Dossier-cockpit

    def test_15_alle_iconbtn_refreshknoppen_gebruiken_helper(self):
        for rid in ("a-refresh", "i-refresh", "sb-refresh", "rc-refresh",
                    "sv-refresh", "tp-refresh", "dc-refresh", "ad-refresh"):
            assert f'bindRefresh("{rid}"' in _APP, f"{rid} niet via bindRefresh"

    def test_16_geen_kale_addEventListener_meer_op_die_knoppen(self):
        for rid in ("a-refresh", "i-refresh", "sb-refresh", "rc-refresh", "sv-refresh"):
            assert f'$("#{rid}").addEventListener("click"' not in _APP


# ══ D — historische orphan-intake zichtbaar + koppelbaar ═══════════════════
class TestOrphanIntakeFrontend:
    def test_17_intake_module_toont_losse_intakes(self):
        assert 'id="i-orphans"' in _HTML
        assert "function laadOrphanIntakes(" in _APP
        assert "laadOrphanIntakes()" in _fn("laadIntake")

    def test_18_orphans_via_pariteit_endpoint(self):
        # FINAL: leest rechtstreeks uit de store (/api/intake/orphans), niet via de
        # roster die een orphan bij een FS-namesake weg-mergt (§9 pariteit).
        body = _fn("laadOrphanIntakes")
        assert "/api/intake/orphans" in body
        assert 'openAthleteModule("atleten"' in body     # één tik naar het koppel-dossier

    def test_19_koppel_ui_biedt_voorgestelde_match_confirm_gated(self):
        # d.suggestie → kp-suggest knop; klik = confirm (geen auto-link)
        assert "d.suggestie" in _APP
        assert 'id="kp-suggest"' in _APP
        assert "doeKoppel(suggestie.user_key)" in _APP


import atleten_core   # noqa: E402
import intake_store    # noqa: E402
import intake_core     # noqa: E402
import dossier_core    # noqa: E402


class TestOrphanIntakeBackend:
    def test_20_fs_suggestie_matcht_eenduidige_naam(self, monkeypatch):
        monkeypatch.setattr(atleten_core.fs_core, "heeft_token", lambda: True)
        monkeypatch.setattr(atleten_core.fs_core, "roster", lambda: [
            {"user_key": "uk-dom", "naam": "Dominique Slooff", "groep": "1. Los"},
            {"user_key": "uk-x", "naam": "Iemand Anders", "groep": "2. Start"},
        ])
        s = atleten_core._fs_suggestie("dominique  slooff")   # norm-ongevoelig
        assert s and s["user_key"] == "uk-dom"

    def test_21_fs_suggestie_geen_match_geen_auto_link(self, monkeypatch):
        monkeypatch.setattr(atleten_core.fs_core, "heeft_token", lambda: True)
        monkeypatch.setattr(atleten_core.fs_core, "roster", lambda: [
            {"user_key": "uk-x", "naam": "Iemand Anders", "groep": ""},
        ])
        assert atleten_core._fs_suggestie("Dominique Slooff") is None

    def test_22_fs_suggestie_dubbele_naam_is_ambigu_geen_suggestie(self, monkeypatch):
        monkeypatch.setattr(atleten_core.fs_core, "heeft_token", lambda: True)
        monkeypatch.setattr(atleten_core.fs_core, "roster", lambda: [
            {"user_key": "uk-1", "naam": "Jan Jansen", "groep": ""},
            {"user_key": "uk-2", "naam": "Jan Jansen", "groep": ""},
        ])
        assert atleten_core._fs_suggestie("Jan Jansen") is None   # coach kiest zelf


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


class TestOrphanLinkNonDestructief:
    def test_23_koppel_rekeyt_naar_canonical_user_key_zonder_duplicaat(self, store):
        store.save_intakes({"nieuw:Dominique Slooff": {
            "athlete_name": "Dominique Slooff", "doel": "10 km", "updated_at": "2026-01-01"}})
        ok, err, naam = intake_core.link_intake("nieuw:Dominique Slooff", "uk-dom")
        assert ok, err
        intakes = store.load_intakes()
        assert "uk-dom" in intakes                       # canonical key
        assert "nieuw:Dominique Slooff" not in intakes    # geen duplicaat-truth
        assert intakes["uk-dom"]["doel"] == "10 km"       # intake-context bewaard

    def test_24_koppel_zonder_geldige_fs_key_weigert(self, store):
        store.save_intakes({"nieuw:X": {"athlete_name": "X"}})
        ok, err, _ = intake_core.link_intake("nieuw:X", "")
        assert not ok and err


# ══ E — expliciet semantiek-contract Teampuls ≠ Home ═══════════════════════
class TestPrioriteitSemantiek:
    def test_25_teampuls_maakt_belasting_monitoring_expliciet(self):
        body = _fn("laadTeampuls")
        assert "Belasting-monitoring" in body
        assert "niet je Home-actielijst" in body
        assert "Dossier &rarr;" in body or "Dossier →" in body        # actionable bridge benoemd

    def test_26_teampuls_label_is_hoge_belasting_niet_kaal_hoog(self):
        body = _fn("laadTeampuls")
        assert "hoge belasting" in body

    def test_27_contract_gedocumenteerd_in_de_code(self):
        # Het bewuste verschil (monitoring vs actielijst) staat als contract in de bron,
        # zodat een latere wijziging het niet stil 'gelijk' trekt.
        body = _fn("laadTeampuls")
        assert "productcontract" in body


# ══ Service worker versie opgehoogd (nieuwe shell live) ════════════════════
class TestServiceWorker:
    def test_28_sw_versie_opgehoogd(self):
        assert 'bebetter-shell-v89' in _SW
