"""Athlete Workspace / Coach Cockpit v2 — één Coach Read Model (generation/freshness).

Harde acceptance (milestone §12):
  1  één CoachRead-generation draagt één load metric;
  2  Home + Teampuls op dezelfde generation → dezelfde load value;
  3  complaint/load truth identiek gedeeld (Dossier via dezelfde load_metric);
  4  nieuwere generation → oude state herkenbaar old (generation_id wijzigt bij inhoud);
  5  geen silent mixed generations (elke response draagt generation; client-wiring aanwezig);
  6  Workspace fast-read blokkeert niet op een refresh/sweep;
  7  trage load-refresh blokkeert schema/complaint-context niet;
  8  trage Feedback blokkeert andere Workspace-secties niet;
  9  handled action blijft canonical (bestaande authority, geen duplicate write);
 10  schema-context canonical (uit de Home-projectie, niet opnieuw berekend);
 11  Dossier-route blijft correct (load_observation-delta via de gedeelde load_metric);
 12  Cohesion-contract byte-identiek (source-guard);
 13  Coach Read Performance fast-path ongemoeid (geen sweep in het renderpad);
 14  volledige suite groen (deze suite draait mee).

    python3 -m pytest tests/test_athlete_workspace_cockpit_v2.py -q
"""
import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import belasting as _bel                     # noqa: E402
import home_core as _home                    # noqa: E402
import teampuls_core as _tp                  # noqa: E402
import coach_read as _cr                     # noqa: E402
import dossier_cockpit as _dc                # noqa: E402

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_HTML = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()


def _res(uk, naam, ernst, km_r=60.0, km_b=20.0):
    ratio = km_r / km_b
    return {"user_key": uk, "naam": naam, "group": "A", "ernst": ernst,
            "signalen": [f"Volume +{round((ratio - 1) * 100)}% deze week"],
            "codes": ["volume"] if ernst != "hoog" else ["volume", "klachten"],
            "metrics": {"km_recent": km_r, "km_basis_week": km_b, "ratio": round(ratio, 2),
                        "runs_recent": []}}


def _stand(datum, results, afgehandeld=None):
    return {"datum": datum, "resultaten": results, "afgehandeld": afgehandeld or {}}


def _fn(name):
    """Body van een top-level `function name(...) { ... }` uit app.js (brace-match)."""
    i = _APP.index("function " + name + "(")
    j = _APP.index("{", i)
    d = 0
    for k in range(j, len(_APP)):
        if _APP[k] == "{":
            d += 1
        elif _APP[k] == "}":
            d -= 1
            if d == 0:
                return _APP[j:k + 1]
    raise AssertionError("unbalanced " + name)


# ── 1. Eén generation → één load metric ──────────────────────────────────────
class TestOneLoadMetric:
    def test_1_load_metric_is_single_formula(self):
        # km-pad (Home) en ratio-pad (Dossier) leveren dezelfde grootheid.
        assert _cr.load_metric({"metrics": {"km_recent": 64, "km_basis_week": 40}})["pct"] == 60
        assert _cr.load_metric({"metrics": {"ratio": 3.0}})["pct"] == 200
        assert _cr.load_metric({"metrics": {}})["pct"] is None       # geen ratio → niet verzonnen

    def test_1b_team_items_all_use_load_metric(self, monkeypatch):
        stand = _stand(TODAY, [_res("u1", "Tom", "hoog", 64, 20),
                               _res("u2", "An", "let_op", 30, 20)])
        monkeypatch.setattr(_bel, "laad_stand", lambda: stand)
        t = _cr.team()
        by = {i["user_key"]: i for i in t["belasting"]["items"]}
        assert by["u1"]["pct"] == _cr.load_metric(stand["resultaten"][0])["pct"]
        assert by["u2"]["pct"] == _cr.load_metric(stand["resultaten"][1])["pct"]
        assert t["generation"]["generation_id"]                       # generation aanwezig


# ── 2 & 3. Home = Teampuls = Dossier op dezelfde stand ───────────────────────
class TestSameGenerationSameValue:
    def test_2_home_teampuls_same_pct_and_generation(self, monkeypatch):
        r = _res("u1", "Tom", "hoog", 64, 20)
        stand = _stand(TODAY, [r])
        monkeypatch.setattr(_bel, "laad_stand", lambda: stand)
        home_pct = _home._belasting_signal(r)["detail"]["pct"]
        tp_pct = _tp._norm(r)["pct"]
        assert home_pct == tp_pct == _cr.load_metric(r)["pct"]
        # Zelfde onderliggende stand → dezelfde generation_id (parity by construction).
        g1 = _cr.generation()["generation_id"]
        g2 = _cr.generation()["generation_id"]
        assert g1 == g2

    def test_3_dossier_delta_shares_load_metric(self):
        raw = {"belasting": {"ernst": "hoog", "metrics": {"ratio": 3.0},
                             "_stand_datum": TODAY}}
        lo = _dc._load_observation(raw, date.today())
        assert lo["delta_pct"] == _cr.load_metric(raw["belasting"])["pct"] == 200


# ── 4 & 5. Generation-identiteit ─────────────────────────────────────────────
class TestGenerationIdentity:
    def test_4_content_change_changes_generation(self, monkeypatch):
        s_a = _stand(TODAY, [_res("u1", "Tom", "let_op", 46, 40)])   # +15%
        monkeypatch.setattr(_bel, "laad_stand", lambda: s_a)
        gen_a = _cr.generation()["generation_id"]
        s_b = _stand(TODAY, [_res("u1", "Tom", "hoog", 64, 40)])     # +60% (nieuwe sweep)
        monkeypatch.setattr(_bel, "laad_stand", lambda: s_b)
        gen_b = _cr.generation()["generation_id"]
        assert gen_a != gen_b                                         # nieuwere generation herkenbaar

    def test_4b_same_content_same_generation(self, monkeypatch):
        s = _stand(TODAY, [_res("u1", "Tom", "hoog", 64, 40)])
        monkeypatch.setattr(_bel, "laad_stand", lambda: s)
        assert _cr.generation()["generation_id"] == _cr.generation()["generation_id"]

    def test_5_every_response_carries_generation(self, monkeypatch):
        stand = _stand(TODAY, [_res("u1", "Tom", "hoog", 64, 20)])
        monkeypatch.setattr(_bel, "laad_stand", lambda: stand)
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        pay = _tp.signalen(force=False)
        assert "generation" in pay and pay["generation"]["generation_id"]

    def test_5b_freshness_per_component(self, monkeypatch):
        # Oudere stand → belasting-component 'stale', niet 'fresh'; geen stand → 'unknown'.
        monkeypatch.setattr(_bel, "laad_stand", lambda: _stand(YESTERDAY, []))
        assert _cr.generation()["freshness"]["belasting"] == "stale"
        monkeypatch.setattr(_bel, "laad_stand", lambda: {})
        assert _cr.generation()["freshness"]["belasting"] == "unknown"


# ── 6, 7, 8. Non-blocking Workspace shell ────────────────────────────────────
class TestWorkspaceNonBlocking:
    def _wire(self, monkeypatch, stand, row=None, feedback_ok=True):
        monkeypatch.setattr(_bel, "laad_stand", lambda: stand)
        # Home-snapshot levert de canonieke rij (schema/attention); geen sweep.
        snap = {"fs": True, "atleten": 5, "prioriteit": [row] if row else [],
                "berekend": None}
        monkeypatch.setattr(_home, "_current", lambda: snap)
        monkeypatch.setattr(_cr, "_roster_naam", lambda uk: "Tom")

        def _boom(*a, **k):
            raise AssertionError("Workspace-shell mag GEEN feedback-queue nodig hebben als die faalt")
        if not feedback_ok:
            import feedback_core
            monkeypatch.setattr(feedback_core, "_queue_current", _boom)

    def test_6_shell_never_triggers_a_sweep(self, monkeypatch):
        stand = _stand(TODAY, [_res("u1", "Tom", "hoog", 64, 20)])
        self._wire(monkeypatch, stand)
        # Elke zware recompute moet ONBEREikt blijven vanuit de shell.
        monkeypatch.setattr(_bel, "dagelijkse_check",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("sweep!")))
        monkeypatch.setattr(_bel, "check_alle",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("sweep!")))
        out = _cr.athlete("u1")
        assert out["ok"] and out["belasting"]["actief"] and out["belasting"]["pct"] == 220

    def test_7_slow_load_does_not_block_schema_context(self, monkeypatch):
        # Belasting-stand leeg/traag (geen datum), maar de schema-context (Home-rij) blijft.
        row = {"user_key": "u1", "naam": "Tom", "voornaam": "Tom",
               "signalen": [{"soort": "schema", "tier": "aandacht", "kort": "schema nog 3d",
                             "detail": {"days_left": 3, "einddatum": "2026-09-10"}}]}
        self._wire(monkeypatch, _stand("", []), row=row)
        out = _cr.athlete("u1")
        assert out["schema"] and out["schema"]["kort"] == "schema nog 3d"
        assert out["belasting"]["actief"] is False           # load niet beschikbaar, blokkeert niet

    def test_8_slow_feedback_does_not_block_other_sections(self, monkeypatch):
        stand = _stand(TODAY, [_res("u1", "Tom", "hoog", 64, 20)])
        self._wire(monkeypatch, stand, feedback_ok=False)    # feedback-queue gooit
        out = _cr.athlete("u1")
        assert out["ok"] and out["belasting"]["actief"]      # belasting-sectie intact
        assert out["feedback"]["status"] == "unknown"        # feedback degradeert alleen zichzelf


# ── 9, 10, 11. Canonical authority / routes ──────────────────────────────────
class TestCanonicalAuthority:
    def test_9_workspace_handled_uses_existing_teampuls_authority(self):
        body = _fn("wsMarkeerGezien")
        assert "/api/teampuls/gezien" in body               # geen duplicate write-logica
        assert "belasting.markeer_gezien" not in body       # niet zelf schrijven

    def test_10_schema_context_is_canonical_home_projection(self, monkeypatch):
        row = {"user_key": "u1", "naam": "Tom", "voornaam": "Tom",
               "signalen": [{"soort": "schema", "tier": "actie", "kort": "schema verlopen",
                             "detail": {"days_left": -2, "einddatum": "2026-08-20"}}]}
        monkeypatch.setattr(_home, "_current",
                            lambda: {"fs": True, "prioriteit": [row]})
        sig = _cr._schema_signal(_cr._home_row("u1"))
        assert sig["tier"] == "actie" and sig["days_left"] == -2

    def test_11_dossier_route_load_observation_intact(self):
        # /api/cockpit → dossier_cockpit.cockpit blijft de deep-bron; delta via load_metric.
        assert "/api/cockpit" in _fn("wsLoadDeep")
        raw = {"belasting": {"ernst": "let_op", "metrics": {"ratio": 1.32},
                             "_stand_datum": TODAY}}
        assert _dc._load_observation(raw, date.today())["delta_pct"] == 32


# ── 12 & 13. Locked contracts intact ─────────────────────────────────────────
class TestLockedContractsIntact:
    def test_12_cohesion_athlete_views_literal_unchanged(self):
        # Workspace is athlete-aware BUITEN _ATHLETE_VIEWS → Cohesion-contract byte-identiek.
        assert '_ATHLETE_VIEWS = new Set(["atleten", "schema", "dossier"])' in _APP
        assert 'function openWorkspace(' in _APP
        assert _APP.count("function openAthleteModule(") == 1

    def test_13_home_fast_read_still_no_sweep(self, monkeypatch):
        # cockpit(refresh=False) mag nooit _bereken aanroepen (Coach Read Performance-fastpath).
        monkeypatch.setattr(_home, "_heeft_token", lambda: True)
        monkeypatch.setattr(_home, "_current", lambda: {})
        monkeypatch.setattr(_home, "_bereken",
                            lambda: (_ for _ in ()).throw(AssertionError("sweep in fast-read!")))
        out = _home.cockpit(refresh=False)
        assert out.get("pending") is True
        assert "generation" in out                           # ook de pending-response draagt generation


# ── Client-wiring (source-guards) ────────────────────────────────────────────
class TestClientWiring:
    def test_generation_helpers_present(self):
        for token in ("function noteGeneration(", "function bbGenSync(",
                      "function genBanner(", "function genMount("):
            assert token in _APP

    def test_home_and_teampuls_stamp_generation(self):
        assert 'genMount("#home-genbar"' in _APP
        assert 'genMount("#tp-genbar"' in _APP

    def test_refresh_adopts_new_generation_without_silent_swap(self):
        body = _fn("cockpitVersen")
        # Bij een actieve lijst: adopteer de nieuwe generatie (banner 'nieuw beschikbaar'),
        # verspring de lijst NIET → geen verborgen mix A/B.
        assert "noteGeneration(fresh.generation)" in body
        assert "cockpitDiffToon(fresh)" in body

    def test_workspace_view_and_nav_registered(self):
        assert 'data-view="workspace"' in _HTML
        assert 'data-open-view="workspace"' in _HTML
        assert "laders.workspace = laadWorkspace" in _APP
        assert 'view === "workspace"' in _fn("applyRoute")

    def test_workspace_quick_actions_reuse_existing_routes(self):
        body = _fn("wsRender")
        assert "openAthleteModule('schema'" in body
        assert "openAthleteModule('atleten'" in body
        assert "openAthleteModule('dossier'" in body


# ═══════════ External-review correctness delta — generation-contract ═════════

def _stand_at(datum, results, prod):
    s = _stand(datum, results)
    s["_produced_at"] = prod
    return s


def _dominates(nv, cv):
    """Python-spiegel van de client `_genDominates`: nieuwer op ≥1 source, ouder op geen.
    Test het ORDENING-contract dat de server-vectoren moeten respecteren (de client-JS
    gebruikt exact dezelfde regel; source-guard + live-check dekken de JS-kant)."""
    keys = set(nv) | set(cv)
    newer = older = False
    for k in keys:
        a, b = nv.get(k, ""), cv.get(k, "")
        if a > b:
            newer = True
        elif a < b:
            older = True
    return newer and not older


# ── Fix #1: generation gebonden aan EXACT de captured payload ────────────────
class TestGenerationBoundToCapturedPayload:
    def test_teampuls_items_A_never_carry_generation_B(self, monkeypatch):
        A = _stand_at(TODAY, [_res("u1", "Tom", "hoog", 64, 20)], TODAY + "T10:00:00")
        B = _stand_at(TODAY, [_res("u1", "Tom", "let_op", 30, 20)], TODAY + "T10:05:00")
        calls = {"n": 0}

        def _laad():
            calls["n"] += 1
            return A if calls["n"] == 1 else B          # 1e read = A; elke latere read = B

        monkeypatch.setattr(_bel, "laad_stand", _laad)
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        pay = _tp.signalen(force=False)
        # De getoonde items komen uit A → de generation MOET A's belasting-sig dragen,
        # nooit die van een intussen weggeschreven B.
        assert pay["items"][0]["ernst"] == "hoog"
        assert pay["generation"]["sources"]["belasting_sig"] == _cr._belasting_sig(A)
        assert pay["generation"]["sources"]["belasting_sig"] != _cr._belasting_sig(B)

    def test_workspace_load_and_generation_from_same_captured_stand(self, monkeypatch):
        A = _stand_at(TODAY, [_res("u1", "Tom", "hoog", 64, 20)], TODAY + "T10:00:00")
        B = _stand_at(TODAY, [_res("u1", "Tom", "let_op", 30, 20)], TODAY + "T10:05:00")
        calls = {"n": 0}

        def _laad():
            calls["n"] += 1
            return A if calls["n"] == 1 else B

        monkeypatch.setattr(_bel, "laad_stand", _laad)
        monkeypatch.setattr(_home, "_current", lambda: {"fs": True, "prioriteit": []})
        monkeypatch.setattr(_cr, "_roster_naam", lambda uk: "Tom")
        out = _cr.athlete("u1")
        assert out["belasting"]["pct"] == 220                         # uit A (64/20 → +220%)
        assert out["generation"]["sources"]["belasting_sig"] == _cr._belasting_sig(A)

    def test_home_generation_binds_to_overlay_stand(self, monkeypatch):
        A = _stand_at(TODAY, [_res("u1", "Tom", "hoog", 64, 20)], TODAY + "T10:00:00")
        B = _stand_at(TODAY, [_res("u1", "Tom", "let_op", 30, 20)], TODAY + "T10:05:00")
        calls = {"n": 0}

        def _laad():
            calls["n"] += 1
            return A if calls["n"] == 1 else B

        monkeypatch.setattr(_home, "_heeft_token", lambda: True)
        monkeypatch.setattr(_bel, "laad_stand", _laad)
        monkeypatch.setattr(_home.intake_store, "load_home_handled", lambda: {})
        snap = {"fs": True, "atleten": 5, "prioriteit": [], "feedback": None,
                "berekend": None, "team": {}}
        monkeypatch.setattr(_home, "_current", lambda: snap)
        out = _home.cockpit(refresh=False)
        # De belasting-overlay TOONDE A; het generation-stempel bindt aan diezelfde sig.
        assert out["belasting"]["sig"] == _cr._belasting_sig(A)
        assert out["generation"]["sources"]["belasting_sig"] == out["belasting"]["sig"]


# ── Fix #2: monotone, expliciet vergelijkbare generation_at ──────────────────
class TestGenerationMonotone:
    def test_generation_at_is_production_time_monotone(self, monkeypatch):
        A = _stand_at(TODAY, [_res("u1", "Tom", "let_op", 46, 40)], TODAY + "T09:00:00")
        B = _stand_at(TODAY, [_res("u1", "Tom", "hoog", 64, 40)], TODAY + "T09:05:00")
        monkeypatch.setattr(_home, "_current", lambda: {})           # isoleer de home-component
        monkeypatch.setattr(_cr, "_feedback_marker", lambda: ("UNKNOWN", "", ""))  # isoleer feedback
        monkeypatch.setattr(_bel, "laad_stand", lambda: A)
        ga = _cr.generation()
        monkeypatch.setattr(_bel, "laad_stand", lambda: B)
        gb = _cr.generation()
        assert ga["generation_at"] < gb["generation_at"]              # nieuwer = later geproduceerd
        assert ga["generation_id"] != gb["generation_id"]

    def test_generation_at_not_read_time(self, monkeypatch):
        # Oudere persisted state, twee keer gelezen → zelfde generation_at (NIET now()).
        A = _stand_at(TODAY, [_res("u1", "Tom", "hoog", 64, 40)], TODAY + "T08:00:00")
        monkeypatch.setattr(_home, "_current", lambda: {})           # isoleer de home-component
        monkeypatch.setattr(_cr, "_feedback_marker", lambda: ("UNKNOWN", "", ""))  # isoleer feedback
        monkeypatch.setattr(_bel, "laad_stand", lambda: A)
        g1, g2 = _cr.generation(), _cr.generation()
        assert g1["generation_at"] == g2["generation_at"] == TODAY + "T08:00:00"
        assert g1["generation_id"] == g2["generation_id"]

    def test_belasting_recompute_bumps_produced_at(self, monkeypatch):
        # Een echte recompute schrijft een monotone productie-tijd op de stand.
        saved = {}
        monkeypatch.setattr(_bel.intake_store, "save_belasting", lambda d: saved.update(d))
        monkeypatch.setattr(_bel.intake_store, "load_belasting", lambda: {})
        monkeypatch.setattr(_bel, "check_alle", lambda *a, **k: [])
        _bel._recompute_stand([], TODAY)
        assert "_produced_at" in saved and saved["_produced_at"] >= TODAY

    def test_client_uses_vector_dominance_not_max(self):
        note = _fn("noteGeneration")
        dom = _fn("_genDominates")
        assert "_genDominates(nv, _bbGen.sv)" in note                 # vergelijkt de versie-vector
        assert "source_versions" in note
        assert "newer && !older" in dom                              # dominance-invariant
        assert "if (id === _bbGen.id) return" in note                # zelfde generation → no-op

    def test_client_banner_still_from_id(self):
        # Banner 'oud?' blijft op generation_id (equality), niet op arrival-order.
        body = _fn("genBanner")
        assert "_bbGen.id" in body and "generation_id" in body


# ── Fix #3: volledige ordening via per-source version-dominance ──────────────
class TestGenerationVectorOrdering:
    def test_source_versions_is_a_per_source_vector(self, monkeypatch):
        A = _stand_at(TODAY, [_res("u1", "Tom", "hoog", 64, 40)], TODAY + "T09:00:00")
        monkeypatch.setattr(_home, "_current", lambda: {"berekend": TODAY + "T11:00:00"})
        monkeypatch.setattr(_bel, "laad_stand", lambda: A)
        sv = _cr.generation()["source_versions"]
        assert set(sv.keys()) == {"belasting", "home", "feedback"}
        assert sv["belasting"] == TODAY + "T09:00:00"
        assert sv["home"] == TODAY + "T11:00:00"

    def test_same_max_at_but_newer_belasting_is_a_distinct_version(self, monkeypatch):
        # home = 11:00 domineert de max; load A=10:58 vs B=10:59 → zelfde generation_at,
        # maar de belasting-versie in de vector verschilt → deterministisch te ordenen.
        monkeypatch.setattr(_home, "_current", lambda: {"berekend": TODAY + "T11:00:00"})
        monkeypatch.setattr(_cr, "_feedback_marker", lambda: ("UNKNOWN", "", ""))  # isoleer feedback
        A = _stand_at(TODAY, [_res("u1", "Tom", "let_op", 45, 40)], TODAY + "T10:58:00")
        B = _stand_at(TODAY, [_res("u1", "Tom", "hoog", 64, 40)], TODAY + "T10:59:00")
        monkeypatch.setattr(_bel, "laad_stand", lambda: A)
        ga = _cr.generation()
        monkeypatch.setattr(_bel, "laad_stand", lambda: B)
        gb = _cr.generation()
        assert ga["generation_at"] == gb["generation_at"] == TODAY + "T11:00:00"   # zelfde max
        assert gb["source_versions"]["belasting"] > ga["source_versions"]["belasting"]  # B nieuwer op belasting
        assert ga["source_versions"]["home"] == gb["source_versions"]["home"]          # home gelijk
        # B domineert A (nieuwer op belasting, nergens ouder); A domineert B niet.
        assert _dominates(gb["source_versions"], ga["source_versions"])
        assert not _dominates(ga["source_versions"], gb["source_versions"])

    def test_newer_feedback_older_belasting_is_concurrent_not_dominant(self):
        # C: nieuwere feedback maar OUDERE belasting → domineert NIET (mag load niet terugdraaien).
        latest = {"belasting": TODAY + "T10:59:00", "home": TODAY + "T11:00:00",
                  "feedback": TODAY + "T10:00:00"}
        incoming = {"belasting": TODAY + "T10:58:00", "home": TODAY + "T11:00:00",
                    "feedback": TODAY + "T10:30:00"}                       # feedback nieuwer, belasting ouder
        assert not _dominates(incoming, latest)                           # niet als volledige latest
        assert not _dominates(latest, incoming)                           # (concurrent, geen van beide domineert)
