"""Coach Read Performance v1 — fast read, background refresh, geen nieuwe truth/cache.

Bewijst met dependency-fakes (geen flaky wall-clock) dat:
  • de fast-read paden bestaande canonical/LKG-state direct teruggeven en NIET op de
    zware recompute wachten (Teampuls signalen non-force, Home cockpit refresh=False);
  • de belasting-freshness één contract volgt: FRESH / STALE-but-valid / UNKNOWN;
  • de roster-memo TeamAthleteList dedupt binnen de request-lifecycle (geen ~7× refetch);
  • de AI-duiding parallel draait (barrier-bewijs, niet serieel);
  • timing-instrumentatie opt-in/no-op is;
  • bestaande truth/semantiek (Class 1, handled/zichtbaar) intact blijft.

    python3 -m pytest tests/test_coach_read_performance_v1.py -q
"""
import os
import sys
import threading
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import belasting as _bel                     # noqa: E402
import fs_client as _fs                      # noqa: E402
import teampuls_core as _tp                  # noqa: E402
import home_core as _home                    # noqa: E402
import perf as _perf                         # noqa: E402

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


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


def _stand(datum, uk="u1", ernst="hoog"):
    return {"datum": datum, "afgehandeld": {},
            "resultaten": [{"user_key": uk, "naam": "Test", "group": "A",
                            "ernst": ernst, "signalen": ["Volume +200%"], "metrics": {}}]}


# ══ Teampuls fast-read + belasting-freshness contract ══════════════════════
class TestTeampulsFastRead:
    def test_1_fast_read_geen_recompute_geen_roster(self, monkeypatch):
        """Non-force signalen leest de opgeslagen stand en raakt NOOIT de zware
        recompute (dagelijkse_check) of de roster-fetch (_atleten) aan."""
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        monkeypatch.setattr(_bel, "laad_stand", lambda: _stand(TODAY))
        called = {"recompute": False, "roster": False}
        monkeypatch.setattr(_bel, "dagelijkse_check",
                            lambda *a, **k: called.__setitem__("recompute", True) or _stand(TODAY))
        monkeypatch.setattr(_tp, "_atleten",
                            lambda: called.__setitem__("roster", True) or [])
        r = _tp.signalen(force=False)
        assert r["fs"] is True and r["totaal"] == 1 and r["hoog"] == 1
        assert called == {"recompute": False, "roster": False}   # fast path blokkeert niet

    def test_2_fresh_stand_is_vers(self, monkeypatch):
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        monkeypatch.setattr(_bel, "laad_stand", lambda: _stand(TODAY))
        r = _tp.signalen(force=False)
        assert r["vers"] is True and r["stale"] is False and r["datum"] == TODAY

    def test_3_stale_but_valid_direct_bruikbaar(self, monkeypatch):
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        monkeypatch.setattr(_bel, "laad_stand", lambda: _stand(YESTERDAY))
        r = _tp.signalen(force=False)
        assert r["stale"] is True and r["vers"] is False
        assert r["totaal"] == 1                                   # oude stand blijft bruikbaar

    def test_4_unknown_geen_verzonnen_waarde(self, monkeypatch):
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        monkeypatch.setattr(_bel, "laad_stand", lambda: {})       # geen stand
        r = _tp.signalen(force=False)
        assert r.get("pending") is True and r["items"] == [] and r["datum"] is None

    def test_5_force_recomputet(self, monkeypatch):
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        monkeypatch.setattr(_tp, "_atleten", lambda: [])
        hit = {"n": 0}
        def fake_check(*a, **k):
            hit["n"] += 1
            return _stand(TODAY)
        monkeypatch.setattr(_bel, "dagelijkse_check", fake_check)
        r = _tp.signalen(force=True)
        assert hit["n"] == 1 and r["vers"] is True                # force = expliciete recompute

    def test_6_fast_read_wacht_niet_op_trage_recompute(self, monkeypatch):
        """Onafhankelijkheid: zelfs met een 'hangende' recompute keert de fast-read
        meteen terug — hij roept hem niet eens aan."""
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        monkeypatch.setattr(_bel, "laad_stand", lambda: _stand(TODAY))
        def zou_hangen(*a, **k):
            raise AssertionError("fast-read mag de trage recompute NOOIT aanroepen")
        monkeypatch.setattr(_bel, "dagelijkse_check", zou_hangen)
        monkeypatch.setattr(_tp, "_atleten", zou_hangen)
        assert _tp.signalen(force=False)["totaal"] == 1


# ══ Roster-memo (P1) — TeamAthleteList dedup ═══════════════════════════════
class TestRosterMemo:
    def _fake_get(self, counter):
        def _get(path, *a, **k):
            if path == "TeamAthleteList":
                counter["n"] += 1
                return {"data": [{"groups": [{"name": "A", "athletes": [
                    {"user_key": "u1", "first_name": "X", "last_name": "Y"}]}]}]}
            return {"data": {}}
        return _get

    def test_7_roster_gememoiseerd_binnen_ttl(self, monkeypatch):
        _fs.reset_roster_cache()
        c = {"n": 0}
        monkeypatch.setattr(_fs, "_get", self._fake_get(c))
        a1 = _fs.get_athletes()
        a2 = _fs.get_athletes()
        assert len(a1) == 1 and len(a2) == 1
        assert c["n"] == 1                                        # 2 calls → 1 netwerkfetch

    def test_8_refresh_omzeilt_memo(self, monkeypatch):
        _fs.reset_roster_cache()
        c = {"n": 0}
        monkeypatch.setattr(_fs, "_get", self._fake_get(c))
        _fs.get_athletes()
        _fs.get_athletes(refresh=True)
        assert c["n"] == 2

    def test_9_lege_fetch_wordt_niet_gecachet(self, monkeypatch):
        _fs.reset_roster_cache()
        c = {"n": 0}
        def _get(path, *a, **k):
            c["n"] += 1
            return {"data": []}                                    # lege roster
        monkeypatch.setattr(_fs, "_get", _get)
        _fs.get_athletes(); _fs.get_athletes()
        assert c["n"] == 2                                        # niet gecachet → retry

    def test_10_by_group_deelt_dezelfde_memo(self, monkeypatch):
        _fs.reset_roster_cache()
        c = {"n": 0}
        monkeypatch.setattr(_fs, "_get", self._fake_get(c))
        _fs.get_athletes()
        g = _fs.get_athletes_by_group()
        assert "A" in g and c["n"] == 1                           # by_group leidt uit memo af

    def test_11_reset_leegt_memo(self, monkeypatch):
        _fs.reset_roster_cache()
        c = {"n": 0}
        monkeypatch.setattr(_fs, "_get", self._fake_get(c))
        _fs.get_athletes()
        _fs.reset_roster_cache()
        _fs.get_athletes()
        assert c["n"] == 2

    def test_12_geen_gedeelde_mutatie_via_memo(self, monkeypatch):
        _fs.reset_roster_cache()
        monkeypatch.setattr(_fs, "_get", self._fake_get({"n": 0}))
        a1 = _fs.get_athletes()
        a1.append({"user_key": "MUT"})                            # caller muteert zijn lijst
        a2 = _fs.get_athletes()
        assert len(a2) == 1                                       # memo niet vervuild


# ══ AI-duiding parallel (P3) — barrier-bewijs (niet serieel) ═══════════════
class TestDuidingParallel:
    def test_13_duiding_draait_parallel(self, monkeypatch):
        import ai_feedback
        N = 4
        barrier = threading.Barrier(N, timeout=4)
        reached = []
        def fake_duiding(naam, sig, notes=""):
            barrier.wait()                                        # serieel → timeout → BrokenBarrier
            reached.append(naam)
            return "ok"
        monkeypatch.setattr(ai_feedback, "belasting_duiding", fake_duiding)
        res = [{"user_key": f"u{i}", "naam": f"A{i}", "signalen": ["x"]} for i in range(N)]
        monkeypatch.setattr(_bel, "check_alle", lambda *a, **k: res)
        monkeypatch.setattr(_bel.intake_store, "load_belasting", lambda: {})
        monkeypatch.setattr(_bel.intake_store, "save_belasting", lambda *a, **k: None)
        monkeypatch.setattr(_bel.intake_store, "load_on_hold", lambda: {})
        monkeypatch.setattr(_bel.intake_store, "load_admin_clients", lambda: {})
        out = _bel.dagelijkse_check([], forceer=True)
        assert len(reached) == N                                  # allen concurrent bij de barrier
        assert all(r.get("duiding") == "ok" for r in out["resultaten"])

    def test_14_duiding_fout_is_per_atleet_geisoleerd(self, monkeypatch):
        import ai_feedback
        def soms_stuk(naam, sig, notes=""):
            if naam == "A1":
                raise RuntimeError("AI hapert")
            return "ok"
        monkeypatch.setattr(ai_feedback, "belasting_duiding", soms_stuk)
        res = [{"user_key": f"u{i}", "naam": f"A{i}", "signalen": ["x"]} for i in range(3)]
        monkeypatch.setattr(_bel, "check_alle", lambda *a, **k: res)
        monkeypatch.setattr(_bel.intake_store, "load_belasting", lambda: {})
        monkeypatch.setattr(_bel.intake_store, "save_belasting", lambda *a, **k: None)
        monkeypatch.setattr(_bel.intake_store, "load_on_hold", lambda: {})
        monkeypatch.setattr(_bel.intake_store, "load_admin_clients", lambda: {})
        out = _bel.dagelijkse_check([], forceer=True)
        duidingen = {r["naam"]: r["duiding"] for r in out["resultaten"]}
        assert duidingen["A1"] == "" and duidingen["A0"] == "ok" and duidingen["A2"] == "ok"


# ══ Home fast-read blijft snel (P5) — geen _bereken op leespad ═════════════
class TestHomeFastRead:
    def test_15_cockpit_read_roept_bereken_niet(self, monkeypatch):
        monkeypatch.setattr(_home, "_heeft_token", lambda: True)
        snap = {"fs": True, "atleten": 3, "prioriteit": [], "belasting": {"totaal": 0, "hoog": 0}}
        monkeypatch.setattr(_home, "_current", lambda: snap)
        monkeypatch.setattr(_home, "_apply_handled_overlay", lambda s: s)
        monkeypatch.setattr(_home, "_apply_feedback_overlay", lambda s, **k: s)
        def zwaar(*a, **k):
            raise AssertionError("fast-read mag _bereken NIET aanroepen")
        monkeypatch.setattr(_home, "_bereken", zwaar)
        r = _home.cockpit(refresh=False)
        assert r.get("cached") is True and r.get("atleten") == 3

    def test_16_belasting_vandaag_leest_stand_1x_bij_vers(self, monkeypatch):
        # Verse stand → geen recompute, en de stand wordt niet 3× geladen.
        import types
        loads = {"n": 0}
        fake = types.SimpleNamespace()
        fake.laad_stand = lambda: (loads.__setitem__("n", loads["n"] + 1)
                                   or {"datum": TODAY, "resultaten": [], "afgehandeld": {}})
        fake.zichtbare_resultaten = lambda d: d.get("resultaten", [])
        fake.dagelijkse_check = lambda *a, **k: (_ for _ in ()).throw(AssertionError("geen recompute bij vers"))
        monkeypatch.setitem(sys.modules, "belasting", fake)
        assert _home._belasting_vandaag([]) == []
        assert loads["n"] == 1                                    # 1× geladen (was 2-3×)


# ══ Timing-instrumentatie (P7) — opt-in / no-op ════════════════════════════
class TestPerfTimer:
    def test_17_timer_noop_zonder_gate(self, monkeypatch):
        monkeypatch.delenv("BEBETTER_PERF_TIMING", raising=False)
        t = _perf.Timer()
        with t.step("x"):
            pass
        assert t.result() is None                                 # geen overhead/output

    def test_18_timer_meet_met_gate(self, monkeypatch):
        monkeypatch.setenv("BEBETTER_PERF_TIMING", "1")
        t = _perf.Timer()
        with t.step("stap"):
            pass
        res = t.result()
        assert res is not None and "stap" in res and isinstance(res["stap"], int)


# ══ Contract / regressie ═══════════════════════════════════════════════════
class TestContractGuards:
    def test_19_teampuls_fast_read_en_reconcile_in_frontend(self):
        body = _fn("laadTeampuls")
        assert "laadBriefing(force)" in body                      # briefing parallel, niet serieel erna
        assert "?force=true" in body and "tpRenderSignalen" in body
        # stale/pending → achtergrond-reconcile
        assert "r.stale" in body and "r.pending" in body

    def test_20_signalen_freshness_contract_shape(self, monkeypatch):
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        monkeypatch.setattr(_bel, "laad_stand", lambda: _stand(TODAY))
        r = _tp.signalen(force=False)
        for k in ("fs", "items", "datum", "hoog", "totaal", "vers", "stale"):
            assert k in r

    def test_21_zichtbare_semantiek_ongewijzigd(self, monkeypatch):
        # Handled/zichtbaar-semantiek intact: een afgehandelde stand toont niet.
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        morgen = (date.today() + timedelta(days=1)).isoformat()
        stand = _stand(TODAY)
        stand["afgehandeld"] = {"u1": {"tot": morgen, "ernst": "hoog"}}
        monkeypatch.setattr(_bel, "laad_stand", lambda: stand)
        r = _tp.signalen(force=False)
        assert r["totaal"] == 0                                   # afgehandeld → niet zichtbaar

    def test_22_geen_nieuwe_persistente_store(self):
        # De perf-laag mag geen store/DB introduceren.
        src = open(os.path.join(_ROOT, "pwa", "perf.py")).read()
        for verboden in ("open(", "requests", "json.dump", "sqlite", "save_"):
            assert verboden not in src

    def test_23_sw_versie_opgehoogd(self):
        import re
        sw = open(os.path.join(_ROOT, "pwa", "static", "sw.js")).read()
        m = re.search(r"bebetter-shell-v(\d+)", sw)
        assert m and int(m.group(1)) >= 94
