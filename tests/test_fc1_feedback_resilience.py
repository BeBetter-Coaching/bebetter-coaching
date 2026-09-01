"""FC-1 — Feedback runtime resilience + correcte FinalSurge relationship identity.

Twee P0's uit System Coherence Gate v1:
  1. `_cache` is process-local en kan na deploy/recycle leeg zijn; genereer/plaats
     herstelden (anders dan detail) niet → "Training niet meer in beeld" tot refresh.
     Fix: één gedeelde `get_or_restore_workout` (cache → durable-restore → skip/afwezig-guard).
  2. Per-post live `coach_athlete_key`-lookup kon None worden → reset met `user_key`
     (verkeerde sleutel). Fix: gecachete roster-map (`fs_client.coach_athlete_key_for`),
     nooit een `user_key`-gok; reset overslaan als de echte sleutel onbekend is.

    python3 -m pytest tests/test_fc1_feedback_resilience.py -q
"""
import os
import sys
import threading

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import intake_store
import fs_client
import feedback_core as FC


def _workout(wid="W1", **over):
    w = {"workout_key": wid, "athlete_key": "A", "athlete_name": "Lisa",
         "workout_name": "Duurloop", "workout_date": "2026-08-12", "workout_type": "run",
         "thread": []}
    w.update(over)
    return w


def _durable(wid="W1", **over):
    """Valide durable queue-snapshot met de workout in `_volle` (restore-bron)."""
    w = _workout(wid, **over)
    return {"fs": True, "items": [{"id": wid, "naam": "Lisa", "workout": "Duurloop"}],
            "_volle": {wid: w}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Token-loze, lokale skip-store; schone process-state (cache/mem/relatie-map)."""
    monkeypatch.setattr(intake_store, "_gh_token", lambda: "", raising=False)
    monkeypatch.setattr(intake_store, "_SKIPPED_LOCAL", str(tmp_path / "skipped.json"),
                        raising=False)
    FC._cache.clear()
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
    fs_client._COACH_ATHLETE_MAP = {}
    # genereer/plaats-randzaken neutraliseren (geen netwerk); kern = restore + identity
    monkeypatch.setattr(FC, "_ensure_details", lambda wid: None)
    monkeypatch.setattr(FC, "_refresh_thread", lambda w: None)
    monkeypatch.setattr(FC, "_brein_context", lambda w: "")
    monkeypatch.setattr(FC, "_home_invalidate_feedback", lambda: None)
    yield
    FC._cache.clear()
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
    fs_client._COACH_ATHLETE_MAP = {}


def _stub_ai(monkeypatch):
    import ai_feedback
    monkeypatch.setattr(ai_feedback, "generate_feedback", lambda w: "CONCEPT")
    monkeypatch.setattr(ai_feedback, "generate_reply", lambda w, t: "REPLY")


def _stub_post(monkeypatch):
    monkeypatch.setattr(fs_client, "post_comment", lambda **kw: {"ok": True}, raising=False)
    monkeypatch.setattr(fs_client, "get_athletes", lambda: [], raising=False)


# ════════════════════════════════════════════════════════════════════════════
# Cache lifecycle (1–8)
# ════════════════════════════════════════════════════════════════════════════
class TestCacheLifecycle:
    def test_1_cache_gevuld_werkt(self, env, monkeypatch):
        _stub_ai(monkeypatch); _stub_post(monkeypatch)
        FC._cache["W1"] = _workout()
        assert FC.genereer("W1") == "CONCEPT"
        assert FC.plaats("W1", "netjes") is True

    def test_2_lege_cache_durable_herstelt_generate(self, env, monkeypatch):
        _stub_ai(monkeypatch)
        monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: _durable())
        assert "W1" not in FC._cache
        assert FC.genereer("W1") == "CONCEPT"            # herstelt uit durable en werkt
        assert FC._cache.get("W1") is not None           # cache is gerepopuleerd

    def test_3_lege_cache_durable_herstelt_post(self, env, monkeypatch):
        _stub_post(monkeypatch)
        monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: _durable())
        assert FC.plaats("W1", "netjes") is True           # herstelt uit durable en post slaagt
        assert "W1" not in FC._cache                        # ná post canoniek afgehandeld (re-post-guard)

    def test_4_detail_gebruikt_dezelfde_helper(self, env, monkeypatch):
        monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: _durable())
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: {}, raising=False)
        data = FC.detail("W1")
        assert data.get("err") != "Training niet in beeld — ververs de queue."
        assert FC._cache.get("W1") is not None            # via get_or_restore_workout hersteld

    def test_5_geskipte_workout_niet_gereactiveerd(self, env, monkeypatch):
        _stub_ai(monkeypatch); _stub_post(monkeypatch)
        monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: _durable())
        # canoniek overgeslagen, atleet gaf geen nieuwe input → blijft skip
        monkeypatch.setattr(intake_store, "load_skipped",
                            lambda: {"W1": {"athlete_ts": "", "notes": False,
                                            "felt": False, "effort": False}})
        with pytest.raises(ValueError):
            FC.genereer("W1")
        with pytest.raises(ValueError):
            FC.plaats("W1", "netjes")
        assert FC.detail("W1").get("err") == "Training niet in beeld — ververs de queue."

    def test_6_verdwenen_workout_geen_resurrectie(self, env, monkeypatch):
        _stub_ai(monkeypatch); _stub_post(monkeypatch)
        # durable bevat W1 NIET (gepost/verwijderd → uit de sweep)
        monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: _durable("ANDERS"))
        with pytest.raises(ValueError):
            FC.genereer("W1")
        with pytest.raises(ValueError):
            FC.plaats("W1", "netjes")
        assert "W1" not in FC._cache                       # niet opnieuw tot leven gewekt

    def test_7_procesrecycle_open_flow_blijft_bruikbaar(self, env, monkeypatch):
        _stub_ai(monkeypatch); _stub_post(monkeypatch)
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: {}, raising=False)
        # simuleer recycle: zowel _cache als _QUEUE_MEM leeg, alleen durable over
        FC._cache.clear(); FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
        monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: _durable())
        # de nog-openstaande workout is ná recycle gewoon bruikbaar: detail + genereer + post
        assert FC.detail("W1").get("err") != "Training niet in beeld — ververs de queue."
        assert FC.genereer("W1") == "CONCEPT"
        assert FC.plaats("W1", "netjes") is True            # terminale actie (verwijdert daarna canoniek)

    def test_8_concurrent_restore_geen_dubbele_entry(self, env, monkeypatch):
        monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: _durable())
        results, errors = [], []

        def _restore():
            try:
                results.append(FC.get_or_restore_workout("W1"))
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=_restore) for _ in range(12)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        assert all(r is not None and r.get("workout_key") == "W1" for r in results)
        # één consistente cache-entry, identity onveranderd
        assert FC._cache["W1"].get("workout_key") == "W1"
        assert len({id(r) for r in results}) == 1          # allemaal dezelfde entry


# ════════════════════════════════════════════════════════════════════════════
# Relationship key (9–13)
# ════════════════════════════════════════════════════════════════════════════
def _capture_reset(monkeypatch):
    """Vang de CoachAthleteResetCounter-sleutel(s) waarmee gereset wordt."""
    calls = []
    monkeypatch.setattr(fs_client, "_post", lambda *a, **k: {}, raising=False)

    def _get(endpoint, params=None):
        if endpoint == "CoachAthleteResetCounter":
            calls.append((params or {}).get("coach_athlete_key"))
        return {}
    monkeypatch.setattr(fs_client, "_get", _get, raising=False)
    return calls


class TestRelationshipKey:
    def test_9_echte_key_reset_exact(self, env, monkeypatch):
        monkeypatch.setattr(fs_client, "get_athletes",
                            lambda: [{"user_key": "A", "coach_athlete_key": "REL-A"}])
        calls = _capture_reset(monkeypatch)
        key = fs_client.coach_athlete_key_for("A")
        assert key == "REL-A"
        fs_client.post_comment(workout_key="W", user_key="A", comment="x", coach_athlete_key=key)
        assert calls == ["REL-A"]                          # reset exact met de relatiesleutel

    def test_10_transiente_fs_fout_map_blijft(self, env, monkeypatch):
        monkeypatch.setattr(fs_client, "get_athletes",
                            lambda: [{"user_key": "A", "coach_athlete_key": "REL-A"}])
        assert fs_client.coach_athlete_key_for("A") == "REL-A"   # map opgebouwd
        def _boom():
            raise RuntimeError("FS throttled")
        monkeypatch.setattr(fs_client, "get_athletes", _boom)
        assert fs_client.coach_athlete_key_for("A") == "REL-A"   # cache blijft bruikbaar

    def test_11_onbekende_key_nooit_user_key(self, env, monkeypatch):
        monkeypatch.setattr(fs_client, "get_athletes", lambda: [])   # roster (tijdelijk) leeg
        calls = _capture_reset(monkeypatch)
        key = fs_client.coach_athlete_key_for("A")
        assert key is None                                 # geen gok
        fs_client.post_comment(workout_key="W", user_key="A", comment="x", coach_athlete_key=key)
        assert calls == []                                 # GEEN reset, zeker niet met user_key
        assert "A" not in calls

    def test_12_verkeerde_athlete_niet_gereset(self, env, monkeypatch):
        # roster-fallback: coach_athlete_key == user_key (echte relatie onbekend)
        monkeypatch.setattr(fs_client, "get_athletes",
                            lambda: [{"user_key": "A", "coach_athlete_key": "A"}])
        calls = _capture_reset(monkeypatch)
        key = fs_client.coach_athlete_key_for("A")
        assert key is None                                 # user_key-fallback → None
        fs_client.post_comment(workout_key="W", user_key="A", comment="x", coach_athlete_key=key)
        assert calls == []

    def test_13_streamlit_pwa_mapping_parity(self, env, monkeypatch):
        roster = [{"user_key": "A", "coach_athlete_key": "REL-A"},
                  {"user_key": "B", "coach_athlete_key": "REL-B"}]
        monkeypatch.setattr(fs_client, "get_athletes", lambda: roster)
        pwa_map = fs_client.build_coach_athlete_map(refresh=True)
        streamlit_map = {a["user_key"]: a.get("coach_athlete_key") for a in roster}
        assert pwa_map == streamlit_map                    # zelfde bron/semantiek


# ════════════════════════════════════════════════════════════════════════════
# Client-wiring (source-guards) — gerichte recovery, geen loop, primitives hergebruikt
# ════════════════════════════════════════════════════════════════════════════
class TestClientWiring:
    def _js(self):
        return open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()

    def test_recovery_alleen_op_stale_err(self):
        js = self._js()
        assert "function fbIsStaleErr(r)" in js
        assert "/in beeld/i.test(r.err)" in js             # alleen de specifieke not-found-respons

    def test_recovery_geen_loop_en_hergebruikt_primitives(self):
        js = self._js()
        assert "if (FB.recovering) return false" in js     # geen refresh-loop
        assert "await fbRefresh()" in js                   # bestaande queue-refresh
        assert 'fbOpen(id, "stale_recover")' in js         # her-open dezelfde workout

    def test_recovery_bedraad_in_gen_en_send(self):
        js = self._js()
        # beide actietakken triggeren de gerichte recovery i.p.v. een dode kaart
        assert js.count("fbStaleRecover(id)") >= 2

    def test_backend_helper_in_alle_drie(self):
        src = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        # detail/genereer/plaats gebruiken exact dezelfde restore-route
        assert src.count("get_or_restore_workout(") >= 4   # 1 def + 3 aanroepen
        assert "coach_athlete_key=FS.coach_athlete_key_for(ak)" in src


# ════════════════════════════════════════════════════════════════════════════
# Re-post-guard — stale durable snapshot + reeds geposte workout ≠ opnieuw postbaar
# ════════════════════════════════════════════════════════════════════════════
def _durable_store(monkeypatch, wid="W1"):
    """Stateful durable: save schrijft terug zodat een 'recycle' de bijgewerkte snapshot ziet."""
    store = {"snap": _durable(wid)}
    monkeypatch.setattr(intake_store, "load_feedback_queue", lambda: store["snap"])

    def _save(s):
        store["snap"] = s
        return (True, "")
    monkeypatch.setattr(intake_store, "save_feedback_queue", _save)
    return store


class TestRePostGuard:
    """Het gate-scenario: W1 in durable, coach post succesvol, durable nog niet ge-sweept
    (bevat W1), process recycle → W1 mag NIET opnieuw postbaar/genereerbaar worden."""

    def test_post_verwijdert_workout_uit_durable(self, env, monkeypatch):
        _stub_post(monkeypatch)
        store = _durable_store(monkeypatch)
        FC._QUEUE_MEM = dict(store["snap"]); FC._cache["W1"] = _workout()
        assert FC.plaats("W1", "netjes") is True
        assert "W1" not in (store["snap"].get("_volle") or {})       # canoniek uit durable
        assert all(it.get("id") != "W1" for it in store["snap"].get("items", []))
        assert "W1" not in FC._cache                                  # en uit de warme cache

    def test_stale_durable_na_recycle_geen_repost(self, env, monkeypatch):
        _stub_post(monkeypatch); _stub_ai(monkeypatch)
        store = _durable_store(monkeypatch)
        FC._QUEUE_MEM = dict(store["snap"]); FC._cache["W1"] = _workout()
        assert FC.plaats("W1", "eerste") is True                      # 1e post slaagt
        FC._cache.clear(); FC._QUEUE_MEM = {}; FC._SKIP_MEM = None                         # process recycle
        with pytest.raises(ValueError):                              # 2e post onmogelijk
            FC.plaats("W1", "tweede")
        with pytest.raises(ValueError):                             # generate ook geblokkeerd
            FC.genereer("W1")

    def test_within_process_geen_repost(self, env, monkeypatch):
        _stub_post(monkeypatch)
        store = _durable_store(monkeypatch)
        FC._QUEUE_MEM = dict(store["snap"]); FC._cache["W1"] = _workout()
        assert FC.plaats("W1", "eerste") is True
        with pytest.raises(ValueError):                             # zelfde proces, geen recycle
            FC.plaats("W1", "tweede")

    def test_client_reset_verandert_niets(self, env, monkeypatch):
        # browserrefresh/client-reset is irrelevant: server-side durable is leidend + schoon
        _stub_post(monkeypatch)
        store = _durable_store(monkeypatch)
        FC._QUEUE_MEM = dict(store["snap"]); FC._cache["W1"] = _workout()
        FC.plaats("W1", "eerste")
        assert "W1" not in (store["snap"].get("_volle") or {})
        FC._cache.clear(); FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
        with pytest.raises(ValueError):
            FC.plaats("W1", "opnieuw")

    def test_echt_open_workout_na_recycle_blijft_werken(self, env, monkeypatch):
        # regressie: een NIET-geposte, nog openstaande workout blijft ná recycle bruikbaar
        _stub_post(monkeypatch); _stub_ai(monkeypatch)
        _durable_store(monkeypatch, "W2")
        FC._cache.clear(); FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
        assert FC.genereer("W2") == "CONCEPT"
        assert FC.plaats("W2", "netjes") is True

    def test_skip_semantiek_intact(self, env, monkeypatch):
        # skip blijft de andere canonieke not-found-reden, los van de post-guard
        _stub_post(monkeypatch)
        _durable_store(monkeypatch)
        FC._cache.clear(); FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
        monkeypatch.setattr(intake_store, "load_skipped",
                            lambda: {"W1": {"athlete_ts": "", "notes": False,
                                            "felt": False, "effort": False}})
        with pytest.raises(ValueError):
            FC.plaats("W1", "netjes")
