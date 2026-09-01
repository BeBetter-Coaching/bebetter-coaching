"""PF-3 — Home ↔ Feedback skip coherence (Class B / Finding 1 + P2 latency).

Home moet na een skip OF post direct dezelfde open-feedbacktruth tonen als Feedback,
zonder de ~26s `_bereken`-rebuild en zonder dat `_revalidate` verloren gaat. De fix:
Home's fast-read reconcilieert de feedbacktegel tegen DEZELFDE canonieke queue-snapshot
+ skip-reconciliatie (`_apply_skips`/`_filter_skipped`) die de Feedback-pagina gebruikt —
geen tweede skiplogica, geen nieuwe store, geen client-delta. Post = `_verwijder_uit_queue`
haalt de workout uit de gedeelde queue → telt ook direct mee.

    python3 -m pytest tests/test_pf3_home_feedback_coherence.py -q
"""
import os
import sys
from datetime import datetime

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import feedback_core as FC
import home_core


def _wk(wid, notes=False, felt=False, effort=False, athlete_ts=""):
    thread = [{"van": "atleet", "tekst": "x", "timestamp": athlete_ts}] if athlete_ts else []
    return {"workout_key": wid, "athlete_key": "A", "workout_date": "2026-08-20",
            "athlete_name": "Lisa", "workout_name": "Duurloop",
            "post_notes": ("n" if notes else ""), "felt": (1 if felt else None),
            "effort": (1 if effort else None), "thread": thread}


def _queue(*wids, gepost=0, volle_over=None, berekend=None):
    volle = {w: _wk(w) for w in wids}
    if volle_over:
        volle.update(volle_over)
    # Recente `berekend` → canonical_open_actions ziet dit als FRESH (geldig ÉN vers).
    ber = berekend or datetime.now().isoformat(timespec="seconds")
    return {"fs": True, "items": [{"id": w} for w in wids], "_volle": volle,
            "gepost": gepost, "berekend": ber, "datum": "2026-08-20"}


def _skip(athlete_ts="", notes=False, felt=False, effort=False):
    return {"athlete_ts": athlete_ts, "notes": notes, "felt": felt, "effort": effort}


def _home_snap(wachten, gepost=0):
    tot = wachten + gepost
    return {"fs": True, "atleten": 30, "groepen": 3,
            "team": {"actie": 0, "aandacht": 0, "rustig": 30},
            "feedback": {"wachten": wachten, "gepost": gepost,
                         "pct": int(gepost / tot * 100) if tot else 100},
            "prioriteit": [], "prioriteit_totaal": 0,
            "berekend": "2026-08-20T09:00:00", "datum": "2026-08-20"}


@pytest.fixture
def env(monkeypatch):
    skips = {"map": {}}
    monkeypatch.setattr(FC.intake_store, "load_skipped", lambda: dict(skips["map"]))
    monkeypatch.setattr(FC.intake_store, "save_skipped",
                        lambda sk: (skips.__setitem__("map", dict(sk)) or (True, "")))
    monkeypatch.setattr(FC.intake_store, "save_feedback_queue", lambda s: (True, ""))
    monkeypatch.setattr(FC.intake_store, "load_feedback_queue", lambda: {})
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


# ════════════════════════════════════════════════════════════════════════════
# Skip → fast-read count (1,2,3,4,13)
# ════════════════════════════════════════════════════════════════════════════
def test_1_beide_geskipt_fastread_nul(env):
    FC._QUEUE_MEM = _queue("W1", "W2")
    env["skips"]["map"] = {"W1": _skip(), "W2": _skip()}
    home_core._MEM = _home_snap(2)                    # snapshot zegt nog 2 open
    out = home_core.cockpit(refresh=False)
    assert out["feedback"]["wachten"] == 0            # fast-read reconcilieert canoniek


def test_2_geen_bereken_nodig_voor_correctie(env, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(home_core, "_bereken", lambda: calls.__setitem__("n", calls["n"] + 1) or {})
    FC._QUEUE_MEM = _queue("W1", "W2")
    env["skips"]["map"] = {"W1": _skip(), "W2": _skip()}
    home_core._MEM = _home_snap(2)
    out = home_core.cockpit(refresh=False)
    assert out["feedback"]["wachten"] == 0
    assert calls["n"] == 0                            # GEEN volledige rebuild voor de teller


def test_3_een_van_twee_geskipt(env):
    FC._QUEUE_MEM = _queue("W1", "W2")
    env["skips"]["map"] = {"W1": _skip()}
    home_core._MEM = _home_snap(2)
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 1


def test_4_duplicate_skip_blijft_correct(env):
    FC._QUEUE_MEM = _queue("W1", "W2")
    env["skips"]["map"] = {"W1": _skip()}             # dezelfde skip idempotent in de map
    home_core._MEM = _home_snap(2)
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 1
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 1  # tweede lezing gelijk


def test_13_geen_negatieve_teller(env):
    FC._QUEUE_MEM = _queue("W1")
    env["skips"]["map"] = {"W1": _skip(), "W_niet_in_queue": _skip()}
    home_core._MEM = _home_snap(1)
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 0   # niet -1


# ════════════════════════════════════════════════════════════════════════════
# Parity met Feedback + post (5,6,12,14)
# ════════════════════════════════════════════════════════════════════════════
def test_5_home_en_feedback_zelfde_open_set(env):
    FC._QUEUE_MEM = _queue("W1", "W2", "W3")
    env["skips"]["map"] = {"W2": _skip()}
    fb = FC.feedback_open_truth()
    home_core._MEM = _home_snap(3)
    out = home_core.cockpit(refresh=False)
    assert out["feedback"]["wachten"] == fb["wachten"] == 2
    assert set(fb["open_ids"]) == {"W1", "W3"}         # dezelfde open-set, niet enkel de count


def test_6_geslaagde_post_verdwijnt_uit_home(env):
    FC._QUEUE_MEM = _queue("W1", "W2")
    FC._cache["W1"] = _wk("W1")
    home_core._MEM = _home_snap(2)
    FC._verwijder_uit_queue("W1")                      # = wat plaats() ná een post doet
    out = home_core.cockpit(refresh=False)
    assert out["feedback"]["wachten"] == 1             # geposte W1 telt niet meer


def test_12_reactivation_semantiek_gelijk_aan_feedback(env):
    # canonieke her-activatie: een geskipte workout met NIEUWE atleet-input komt terug.
    FC._QUEUE_MEM = _queue("W1", volle_over={"W1": _wk("W1", athlete_ts="2026-08-20T12:00:00")})
    env["skips"]["map"] = {"W1": _skip(athlete_ts="2026-08-19T00:00:00")}
    fb = FC.feedback_open_truth()
    home_core._MEM = _home_snap(0)
    out = home_core.cockpit(refresh=False)
    assert fb["wachten"] == 1 and out["feedback"]["wachten"] == 1   # gereactiveerd, als Feedback


def test_14_client_delta_is_geen_authority(env):
    # ongeacht wat de snapshot-integer zegt: de canonieke queue-truth wint.
    FC._QUEUE_MEM = _queue("W1")
    home_core._MEM = _home_snap(99)                    # absurde 'client/stale' waarde
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 1


# ════════════════════════════════════════════════════════════════════════════
# Stale snapshot / reload (7,8)
# ════════════════════════════════════════════════════════════════════════════
def test_7_stale_durable_snapshot_actuele_count(env):
    FC._QUEUE_MEM = _queue("W1", "W2")
    env["skips"]["map"] = {"W1": _skip(), "W2": _skip()}
    home_core._MEM = {}                                # koud proces
    env["durable"]["snap"] = _home_snap(2)            # stale durable zegt 2
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 0


def test_8_reload_verandert_count_niet_terug(env):
    FC._QUEUE_MEM = _queue("W1", "W2")
    env["skips"]["map"] = {"W1": _skip(), "W2": _skip()}
    home_core._MEM = {}
    env["durable"]["snap"] = _home_snap(2)
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 0
    home_core._MEM = {}                                # nog een koude reload
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 0


# ════════════════════════════════════════════════════════════════════════════
# Invalidation / race-veiligheid (9,10,11)
# ════════════════════════════════════════════════════════════════════════════
def test_9_invalidation_zonder_snapshot_niet_verloren(env, monkeypatch):
    home_core._MEM = {}                                # geen snapshot bij invalidation
    env["durable"]["snap"] = {}
    home_core.invalidate_feedback()                   # bumpt seq, verzint geen snapshot
    assert not home_core._valid(home_core._MEM)
    out = home_core.cockpit(refresh=False)
    assert out.get("pending") is True                 # → client triggert refresh
    FC._QUEUE_MEM = _queue()                           # skip verwerkt: 0 open
    monkeypatch.setattr(home_core, "_bereken", lambda: _home_snap(0))
    vers = home_core.cockpit(refresh=True)
    assert vers["feedback"]["wachten"] == 0           # correcte telling, niet verloren


def test_10_concurrente_skip_tijdens_sweep_canoniek_zichtbaar(env, monkeypatch):
    # Class 1: een skip die TIJDENS de sweep binnenkomt heeft GEEN vlag nodig — de fast-read
    # leidt de tegel canoniek uit de open-set af, dus de skip is meteen zichtbaar; de oude
    # sweep-integer wint nooit.
    FC._QUEUE_MEM = _queue("W1", "W2")
    home_core._MEM = _home_snap(2)

    def _bereken_met_skip():
        env["skips"]["map"] = {"W1": _skip(), "W2": _skip()}   # skip tijdens de sweep
        return _home_snap(2)                                    # oude sweep zag nog 2

    monkeypatch.setattr(home_core, "_bereken", _bereken_met_skip)
    home_core.cockpit(refresh=True)
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 0   # queue is leidend


def test_11_post_skip_forceert_geen_bereken(env, monkeypatch):
    # Class 1 (latency): post/skip mag geen volledige Home-sweep afdwingen alleen om de teller
    # te corrigeren — de fast-read overlay doet dat canoniek en goedkoop.
    calls = {"n": 0}
    monkeypatch.setattr(home_core, "_bereken", lambda: calls.__setitem__("n", calls["n"] + 1) or {})
    FC._QUEUE_MEM = _queue("W1", "W2")
    home_core._MEM = _home_snap(2)
    env["skips"]["map"] = {"W1": _skip(), "W2": _skip()}
    FC._home_invalidate_feedback()                    # seam (nu geen geforceerde sweep)
    assert home_core.cockpit(refresh=False)["feedback"]["wachten"] == 0
    assert calls["n"] == 0                             # géén _bereken voor de teller


# ════════════════════════════════════════════════════════════════════════════
# Cold/invalid queue → GEEN bevroren integer als 'actueel' (Class 1, ex-PF-3 inversie)
# ════════════════════════════════════════════════════════════════════════════
def test_geen_geldige_queue_toont_geen_bevroren_integer(env):
    # LIVE-ACCEPTANCE-INVERSIE: onder PF-3 gold "geen queue → frozen Home-integer blijft
    # leidend". Dat contract is fout gebleken (Home toonde 6 terwijl Feedback leeg was).
    # Class 1: een koude/ongeldige queue mag NOOIT de bevroren snapshot-integer als actueel
    # tonen — de tegel degradeert eerlijk naar 'stale', zonder valse precisie.
    FC._QUEUE_MEM = {}; FC._SKIP_MEM = None                                 # geen geldige queue-snapshot
    home_core._MEM = _home_snap(7)
    assert FC.canonical_open_actions()["status"] == "UNKNOWN"
    assert FC.feedback_open_truth() is None
    fb = home_core.cockpit(refresh=False)["feedback"]
    assert fb.get("stale") is True                     # eerlijke onbekend-status
    assert fb.get("wachten") != 7                      # niet de bevroren 7
    assert fb.get("wachten") is None                   # geen valse precisie


def test_overlay_muteert_snapshot_niet(env):
    FC._QUEUE_MEM = _queue("W1")
    env["skips"]["map"] = {"W1": _skip()}
    home_core._MEM = _home_snap(1)
    home_core.cockpit(refresh=False)
    assert home_core._MEM["feedback"]["wachten"] == 1  # overlay is read-only, muteert _MEM niet
