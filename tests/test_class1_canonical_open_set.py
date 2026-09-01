"""Class 1 — Home/Feedback single canonical open-set truth (Correctness Round 2).

Er mag voor "welke coach-acties staan open?" nog maar ÉÉN canonieke waarheid bestaan:
`feedback_core.canonical_open_actions()` uit de gedeelde queue-snapshot + skip/post-
reconciliatie. Home-tegel, Feedback-lijst én de Prioriteiten-afhandeling leiden daaruit af
(parity by construction). Een koude/ongeldige queue mag NOOIT een bevroren integer als
'actueel' presenteren; post/skip mag geen volledige Home-sweep forceren alleen om de teller
te corrigeren.

    python3 -m pytest tests/test_class1_canonical_open_set.py -q
"""
import os
import sys
from datetime import date, datetime, timedelta

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import feedback_core as FC
import home_core


# ── Bouwers ──────────────────────────────────────────────────────────────────
def _wk(wid, notes=False, felt=False, effort=False, athlete_ts=""):
    thread = [{"van": "atleet", "tekst": "x", "timestamp": athlete_ts}] if athlete_ts else []
    return {"workout_key": wid, "athlete_key": "A", "workout_date": "2026-08-20",
            "athlete_name": "Lisa", "workout_name": "Duurloop",
            "athlete_groups": ["Getting Better"],
            "post_notes": ("n" if notes else ""), "felt": (1 if felt else None),
            "effort": (1 if effort else None), "thread": thread}


def _qsnap(*wids, gepost=0, volle_over=None, berekend=None):
    """Volwaardige queue-snapshot met sorteerbare items (via `_queue_item`).
    Recente `berekend` → FRESH (geldig ÉN vers); geef expliciet een oude waarde voor STALE."""
    volle = {w: _wk(w) for w in wids}
    if volle_over:
        volle.update(volle_over)
    items = [FC._queue_item(w, volle[w]) for w in wids]
    ber = berekend or datetime.now().isoformat(timespec="seconds")
    return {"fs": True, "items": items, "_volle": volle, "gepost": gepost,
            "berekend": ber, "datum": "2026-08-20"}


def _skip(athlete_ts="", notes=False, felt=False, effort=False):
    return {"athlete_ts": athlete_ts, "notes": notes, "felt": felt, "effort": effort}


def _now(delta_min=0):
    return (datetime.now() - timedelta(minutes=delta_min)).isoformat(timespec="seconds")


def _home_snap(wachten, gepost=0, berekend="2026-01-01T09:00:00"):
    # `berekend` default is bewust OUD (verlopen) → home-snapshot geldt niet als recent,
    # tenzij een test expliciet een verse waarde meegeeft.
    tot = wachten + gepost
    return {"fs": True, "atleten": 30, "groepen": 3,
            "team": {"actie": 0, "aandacht": 0, "rustig": 30},
            "feedback": {"wachten": wachten, "gepost": gepost,
                         "pct": int(gepost / tot * 100) if tot else 100},
            "prioriteit": [], "prioriteit_totaal": 0,
            "berekend": berekend, "datum": "2026-08-20"}


@pytest.fixture
def env(monkeypatch):
    skips = {"map": {}}
    monkeypatch.setattr(FC.intake_store, "load_skipped", lambda: dict(skips["map"]))
    monkeypatch.setattr(FC.intake_store, "save_skipped",
                        lambda sk: (skips.__setitem__("map", dict(sk)) or (True, "")))
    monkeypatch.setattr(FC.intake_store, "save_feedback_queue", lambda s: (True, ""))
    monkeypatch.setattr(FC.intake_store, "load_feedback_queue", lambda: {})
    monkeypatch.setattr(FC, "heeft_token", lambda: True)
    monkeypatch.setattr(home_core, "_heeft_token", lambda: True)
    monkeypatch.setattr(home_core.intake_store, "load_home_handled", lambda: {})
    durable = {"snap": {}}
    monkeypatch.setattr(home_core.intake_store, "load_home_snapshot", lambda: durable["snap"])
    monkeypatch.setattr(home_core.intake_store, "save_home_snapshot",
                        lambda d: (durable.__setitem__("snap", d) or (True, "")))
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
    FC._cache.clear()
    home_core._MEM = {}
    yield {"skips": skips, "durable": durable}
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
    FC._cache.clear()
    home_core._MEM = {}


# 1 — home snapshot=6 + canonical open-set=0 → Home 0
def test_1_snapshot6_openset0_home_toont_0(env):
    FC._QUEUE_MEM = _qsnap("W1", "W2", "W3", "W4", "W5", "W6")
    env["skips"]["map"] = {w: _skip() for w in ("W1", "W2", "W3", "W4", "W5", "W6")}
    home_core._MEM = _home_snap(6)
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 0


# 2 — queue cold/invalid → oude integer niet stil als actueel
def test_2_cold_queue_geen_stille_oude_integer(env):
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
    home_core._MEM = _home_snap(6)
    fb = home_core.cockpit(refresh=False)["feedback"]
    assert fb.get("wachten") != 6 and fb.get("wachten") is None and fb.get("stale") is True


# 3 — skip/post → Home tile binnen fast-read correct
def test_3a_skip_fast_read_correct(env):
    FC._QUEUE_MEM = _qsnap("W1", "W2")
    env["skips"]["map"] = {"W1": _skip()}
    home_core._MEM = _home_snap(2)
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 1


def test_3b_post_fast_read_correct(env):
    FC._QUEUE_MEM = _qsnap("W1", "W2")
    FC._cache["W1"] = _wk("W1")
    home_core._MEM = _home_snap(2)
    FC._verwijder_uit_queue("W1")                    # = wat plaats() ná een post doet
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 1


# 4 — tilecorrectie roept geen full _bereken() aan
def test_4_geen_bereken_voor_tile(env, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(home_core, "_bereken", lambda: calls.__setitem__("n", calls["n"] + 1) or {})
    FC._QUEUE_MEM = _qsnap("W1", "W2")
    env["skips"]["map"] = {"W1": _skip(), "W2": _skip()}
    home_core._MEM = _home_snap(2)
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 0
    assert calls["n"] == 0


# 5 — Feedback list en Home count uit dezelfde open-set
def test_5_feedback_en_home_zelfde_open_set(env):
    FC._QUEUE_MEM = _qsnap("W1", "W2", "W3")
    env["skips"]["map"] = {"W2": _skip()}
    lijst = FC.queue(refresh=False)                  # Feedback-lijst
    truth = FC.canonical_open_actions()             # canonieke open-set
    home_core._MEM = _home_snap(3)
    tile = home_core.cockpit(refresh=False)["feedback"]
    assert len(lijst["items"]) == truth["wachten"] == tile["wachten"] == 2
    assert set(truth["open_ids"]) == {"W1", "W3"}


# 6 — cold process + durable state → parity (durable queue is de bron)
def test_6_cold_process_durable_parity(env, monkeypatch):
    durable_q = _qsnap("W1", "W2")
    monkeypatch.setattr(FC.intake_store, "load_feedback_queue", lambda: durable_q)
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None                                # koud proces: geen mem
    env["skips"]["map"] = {"W1": _skip()}
    home_core._MEM = {}
    env["durable"]["snap"] = _home_snap(2)           # stale home-integer zegt 2
    lijst = FC.queue(refresh=False)
    tile = home_core.cockpit(refresh=False)["feedback"]
    assert len(lijst["items"]) == tile["wachten"] == 1   # beide uit de durable queue


# 7 — failed queue rebuild → honest stale/unknown
def test_7_failed_rebuild_honest_stale(env, monkeypatch):
    monkeypatch.setattr(FC.intake_store, "load_feedback_queue", lambda: {})   # durable ontbreekt
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
    home_core._MEM = _home_snap(5)
    assert FC.canonical_open_actions()["status"] == FC.OPEN_UNKNOWN
    fb = home_core.cockpit(refresh=False)["feedback"]
    assert fb.get("stale") is True and fb.get("wachten") is None


# 8 — handle-all → nieuwe sweep zonder ECHTE escalatie → handled rows blijven weg
def test_8_geen_echte_escalatie_blijft_gedempt(env, monkeypatch):
    morgen = (date.today() + timedelta(days=1)).isoformat()
    handled = {"A|compliance": {"status": "gezien", "severity": 3, "tier": "actie",
                                "tot": morgen, "handled_at": date.today().isoformat()}}
    monkeypatch.setattr(home_core.intake_store, "load_home_handled", lambda: handled)
    snap = {"fs": True, "atleten": 5, "prioriteit": [
        {"user_key": "A", "naam": "Anna", "voornaam": "Anna", "tier": "actie", "n_signalen": 1,
         "reden": "5 gemist", "signalen": [{"soort": "compliance", "tier": "actie",
                                            "reden": "5 gemist", "kort": "5 gemist",
                                            "fingerprint": "c5", "severity": 5, "detail": {}, "context": []}]}],
        "prioriteit_totaal": 1, "team": {"actie": 1, "aandacht": 0, "rustig": 4}}
    out = home_core._apply_handled_overlay(snap)     # n_low 3→5 (zwaarder getal, zelfde tier)
    assert [i["user_key"] for i in out["prioriteit"]] == []   # blijft gedempt (geen tier-escalatie)


# 9 — echte tier-escalatie → alleen die rows komen terug
def test_9_echte_tier_escalatie_komt_terug(env, monkeypatch):
    morgen = (date.today() + timedelta(days=1)).isoformat()
    handled = {
        "A|compliance": {"status": "gezien", "severity": 3, "tier": "actie",
                         "tot": morgen, "handled_at": date.today().isoformat()},
        "B|schema": {"status": "gezien", "severity": 1, "tier": "aandacht",
                     "tot": morgen, "handled_at": date.today().isoformat()},
    }
    monkeypatch.setattr(home_core.intake_store, "load_home_handled", lambda: handled)
    snap = {"fs": True, "atleten": 5, "prioriteit": [
        {"user_key": "A", "naam": "Anna", "voornaam": "Anna", "tier": "actie", "n_signalen": 1,
         "reden": "5 gemist", "signalen": [{"soort": "compliance", "tier": "actie", "reden": "x",
                                            "kort": "x", "fingerprint": "c5", "severity": 5,
                                            "detail": {}, "context": []}]},
        {"user_key": "B", "naam": "Bram", "voornaam": "Bram", "tier": "actie", "n_signalen": 1,
         "reden": "schema verlopen", "signalen": [{"soort": "schema", "tier": "actie", "reden": "x",
                                                   "kort": "x", "fingerprint": "s:v", "severity": 2,
                                                   "detail": {}, "context": []}]}],
        "prioriteit_totaal": 2, "team": {"actie": 2, "aandacht": 0, "rustig": 3}}
    out = home_core._apply_handled_overlay(snap)
    keys = [i["user_key"] for i in out["prioriteit"]]
    assert keys == ["B"]     # alleen Bram (aandacht→actie) terug; Anna (actie→actie) gedempt


# 11 — reload/back/navigation verandert truth niet
def test_11_herhaalde_reads_zelfde_truth(env):
    FC._QUEUE_MEM = _qsnap("W1", "W2")
    env["skips"]["map"] = {"W1": _skip()}
    home_core._MEM = _home_snap(2)
    a = home_core.cockpit(refresh=False)["feedback"]["wachten"]
    home_core._MEM = _home_snap(2)                   # 'reload' resimuleert bevroren snapshot
    b = home_core.cockpit(refresh=False)["feedback"]["wachten"]
    assert a == b == 1


# 12 — geen negatieve/dubbele tellingen
def test_12_geen_negatieve_teller(env):
    FC._QUEUE_MEM = _qsnap("W1")
    env["skips"]["map"] = {"W1": _skip(), "W_ghost": _skip()}   # skip buiten de queue
    home_core._MEM = _home_snap(1)
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 0   # niet -1


# 13 — reactivation semantics blijven gelijk
def test_13_reactivation_semantiek(env):
    # geskipte workout met NIEUWE atleet-input komt terug (als in Feedback).
    FC._QUEUE_MEM = _qsnap("W1", volle_over={"W1": _wk("W1", athlete_ts="2026-08-20T12:00:00")})
    env["skips"]["map"] = {"W1": _skip(athlete_ts="2026-08-19T00:00:00")}
    truth = FC.canonical_open_actions()
    home_core._MEM = _home_snap(0)
    tile = home_core.cockpit(refresh=False)["feedback"]
    assert truth["wachten"] == tile["wachten"] == 1


# 10 — "nieuwe" badge = autoritatieve set-diff (client) — source-guard
def test_10_badge_autoritatieve_setdiff_geen_dom():
    src = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
    assert "lastPrioSig" in src                       # diff tegen laatst toegepaste set
    assert "const basis = lastPrioSig || {}" in src
    assert "el.dataset.sig" not in src.split("function cockpitDiffToon")[1].split("}")[0]


# ════════════════════════════════════════════════════════════════════════════
# Freshness-authority (Round 2 correctie): valid ≠ fresh
# ════════════════════════════════════════════════════════════════════════════
def test_fresh_valid_en_recent(env):
    # geldig ÉN recent (berekend binnen TTL) → FRESH met echte count
    FC._QUEUE_MEM = _qsnap("W1", "W2", berekend=_now(1))
    truth = FC.canonical_open_actions()
    assert truth["status"] == FC.OPEN_FRESH and truth["wachten"] == 2


def test_stale_valid_maar_verlopen_draagt_gereconcilieerde_count(env):
    # geldig maar `berekend` verlopen (> 15 min) → STALE, MAAR met de per-read gereconcilieerde
    # count (regressie A: skip/post is ook op een stale snapshot al verwerkt → direct bruikbaar).
    FC._QUEUE_MEM = _qsnap("W1", "W2", berekend=_now(30))
    truth = FC.canonical_open_actions()
    assert truth["status"] == FC.OPEN_STALE
    assert truth["wachten"] == 2 and set(truth["open_ids"]) == {"W1", "W2"}


def test_stale_zonder_berekend_is_niet_fresh(env):
    # geldig maar zónder betrouwbare `berekend` → conservatief STALE (niet FRESH), wél een count
    snap = _qsnap("W1", "W2")
    snap.pop("berekend", None)
    FC._QUEUE_MEM = snap
    truth = FC.canonical_open_actions()
    assert truth["status"] == FC.OPEN_STALE and truth["wachten"] == 2


def test_stale_queue_toont_gereconcilieerde_count_direct(env):
    # verlopen queue → Home toont DIRECT de gereconcilieerde count (skip/post-authoritatief),
    # met alleen een niet-blokkerende achtergrond-refresh-hint (stale), NOOIT verborgen (regressie A).
    FC._QUEUE_MEM = _qsnap("W1", "W2", "W3", berekend=_now(30))
    home_core._MEM = _home_snap(3)                    # oude berekend (default)
    fb = home_core.cockpit(refresh=False)["feedback"]
    assert fb.get("wachten") == 3                      # count direct getoond, niet verborgen
    assert fb.get("stale") is True                     # enkel een achtergrond-refresh-hint


def test_regressie_A_skip_op_stale_queue_home_direct(env, monkeypatch):
    # Round-2 regressie A: 18 open, 1 skip → Home DIRECT 17 in de fast-read, zonder _bereken en
    # zonder 12–20s queue/home-sweep — ook als de queue-snapshot verlopen is (>15 min).
    calls = {"n": 0}
    monkeypatch.setattr(home_core, "_bereken", lambda: calls.__setitem__("n", calls["n"] + 1) or {})
    wids = [f"W{i}" for i in range(18)]
    FC._QUEUE_MEM = _qsnap(*wids, berekend=_now(30))     # geldige maar VERLOPEN snapshot (18 open)
    home_core._MEM = _home_snap(18, berekend=_now(30))
    env["skips"]["map"] = {"W0": _skip()}                # 1 overgeslagen (skipped.json)
    fb = home_core.cockpit(refresh=False)["feedback"]
    assert fb["wachten"] == 17                            # direct correct via de open-set
    assert calls["n"] == 0                                # GEEN _bereken voor de teller
    # reload (koud proces, laadt durable) blijft 17
    home_core._MEM = {}
    env["durable"]["snap"] = _home_snap(18, berekend=_now(30))
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 17


def test_unknown_queue_recente_home_sweep_behoudt_count(env):
    # GEEN geldige queue-snapshot (UNKNOWN) MAAR een recente home-sweep → val terug op die verse
    # home-telling (geen valse 'bijwerken…'). Dit is de `_snap_recent`-fallback, alleen voor UNKNOWN.
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None                                 # ongeldige queue → UNKNOWN
    home_core._MEM = _home_snap(3, berekend=_now(2))
    fb = home_core.cockpit(refresh=False)["feedback"]
    assert fb.get("stale") is False and fb.get("wachten") == 3


def test_post_op_warme_actuele_queue_blijft_fast(env, monkeypatch):
    # post/skip op een WARME, ACTUELE queue blijft fast: FRESH, direct correct, geen _bereken
    calls = {"n": 0}
    monkeypatch.setattr(home_core, "_bereken", lambda: calls.__setitem__("n", calls["n"] + 1) or {})
    FC._QUEUE_MEM = _qsnap("W1", "W2", berekend=_now(1))
    FC._cache["W1"] = _wk("W1")
    home_core._MEM = _home_snap(2)
    FC._verwijder_uit_queue("W1")                     # post (behoudt de recente berekend)
    fb = home_core.cockpit(refresh=False)["feedback"]
    assert fb["wachten"] == 1 and fb.get("stale") is False
    assert calls["n"] == 0                             # geen full Home-sweep


def test_cold_durable_queue_recent_blijft_fast(env, monkeypatch):
    # koud proces + RECENTE durable queue → FRESH zonder warm/sweep
    durable_q = _qsnap("W1", "W2", berekend=_now(2))
    monkeypatch.setattr(FC.intake_store, "load_feedback_queue", lambda: durable_q)
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None
    home_core._MEM = {}
    env["durable"]["snap"] = _home_snap(2, berekend=_now(2))
    assert FC.canonical_open_actions()["status"] == FC.OPEN_FRESH
    fb = home_core.cockpit(refresh=False)["feedback"]
    assert fb["wachten"] == 2 and fb.get("stale") is False


# ════════════════════════════════════════════════════════════════════════════
# Statistiek-coherentie: post verhoogt gepost/pct direct (live finding aug 2026)
# ════════════════════════════════════════════════════════════════════════════
def test_17open_1post_16_1_5pct(env):
    # 17 open, 1 post → 16 open / 1 gepost / 5% afgerond, in DEZELFDE fast-read.
    wids = [f"W{i}" for i in range(17)]
    FC._QUEUE_MEM = _qsnap(*wids, gepost=0)
    FC._cache["W0"] = _wk("W0")
    FC._verwijder_uit_queue("W0")                    # = post-afhandeling (plaats())
    t = FC.canonical_open_actions()
    assert t["status"] == FC.OPEN_FRESH
    assert (t["wachten"], t["gepost"], t["pct"]) == (16, 1, 5)   # int(1/17*100)=5
    home_core._MEM = _home_snap(17)
    fb = home_core.cockpit(refresh=False)["feedback"]
    assert (fb["wachten"], fb["gepost"], fb["pct"]) == (16, 1, 5)  # Home-tegel coherent


def test_twee_posts_count_en_pct(env):
    wids = [f"W{i}" for i in range(17)]
    FC._QUEUE_MEM = _qsnap(*wids, gepost=0)
    for w in ("W0", "W1"):
        FC._cache[w] = _wk(w)
        FC._verwijder_uit_queue(w)
    t = FC.canonical_open_actions()
    assert (t["wachten"], t["gepost"], t["pct"]) == (15, 2, int(2 / 17 * 100))   # 15/2/11


def test_skip_verandert_gepost_niet(env):
    # skip verlaagt alleen de open count; gepost/pct blijven ongemoeid.
    FC._QUEUE_MEM = _qsnap("W0", "W1", "W2", gepost=0)
    FC._cache["W0"] = _wk("W0")
    FC.overslaan("W0")                               # echte skip-route (skipped.json)
    t = FC.canonical_open_actions()
    assert t["wachten"] == 2 and t["gepost"] == 0    # skip telt niet als gepost


def test_retry_post_geen_double_increment(env):
    FC._QUEUE_MEM = _qsnap("W0", "W1", gepost=0)
    FC._cache["W0"] = _wk("W0")
    FC._verwijder_uit_queue("W0")
    FC._verwijder_uit_queue("W0")                    # retry: item al weg → geen 2e increment
    t = FC.canonical_open_actions()
    assert t["wachten"] == 1 and t["gepost"] == 1    # exact één keer


def test_gepost_durable_parity_na_reload(env, monkeypatch):
    dq = {"snap": {}}
    monkeypatch.setattr(FC.intake_store, "save_feedback_queue",
                        lambda s: (dq.__setitem__("snap", s) or (True, "")))
    monkeypatch.setattr(FC.intake_store, "load_feedback_queue", lambda: dq["snap"])
    FC._QUEUE_MEM = _qsnap("W0", "W1", gepost=0)
    FC._cache["W0"] = _wk("W0")
    FC._verwijder_uit_queue("W0")                    # persist (met gepost+1) naar durable
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None                               # koude reload
    t = FC.canonical_open_actions()                 # leest durable
    assert t["status"] == FC.OPEN_FRESH
    assert t["wachten"] == 1 and t["gepost"] == 1    # gepost overleeft reload/cold read
