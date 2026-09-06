"""Structurele regressiebescherming voor de bewezen geheugenoorzaak.

Render herstartte de productie-instance na ~512 MB. De benchmark (`tests/memory_bench.py`)
bewees: geen leak, maar ONBEGRENSDE procesglobale caches. `gc.collect()` gaf niets vrij,
het legen van de caches gaf 99,7% vrij. Twee accumulatoren droegen de opbouw:

  1. `feedback_core._cache` — groeide per workout_key die het proces ooit zag; alleen een
     geslaagde post verwijderde er één. Bovendien schreef `_ensure_details` de volledige
     detailpayload (alle laps) op het gecachete object, en dat object werd óók durabel
     weggeschreven.
  2. `athlete_read._MEM` — één entry per ooit bezochte atleet, mét de volledige `raw`
     gather (4 maanden trainingslog + 97 dagen labels), zonder eviction.

Deze tests leggen de GRENZEN vast, niet exacte MB's: cardinaliteit blijft begrensd, oude
generaties worden vrijgegeven, een refresh vervangt in plaats van te stapelen.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_ROOT, os.path.join(_ROOT, "pwa")):
    if p not in sys.path:
        sys.path.insert(0, p)

import athlete_read as AR                                  # noqa: E402
import feedback_core as FC                                 # noqa: E402
import races_core as RC                                    # noqa: E402
import schema_core as SC                                   # noqa: E402


def _w(wid: str, details=None) -> dict:
    return {"workout_key": wid, "athlete_key": "u1", "athlete_name": "Test Atleet",
            "athlete_first_name": "Test", "workout_date": "2026-09-01",
            "workout_name": "Duurloop", "thread": [], "details": details or {}}


def _snap(wids) -> dict:
    return {"fs": True, "berekend": "2026-09-01T09:00:00", "datum": "2026-09-01",
            "items": [{"id": w} for w in wids], "gepost": 0,
            "_volle": {w: _w(w) for w in wids}}


@pytest.fixture(autouse=True)
def _schoon():
    FC._cache.clear()
    FC._GEN_STATUS.clear()
    FC._QUEUE_MEM = {}
    RC._cache.clear()
    SC._WRITE_RECEIPTS.clear()
    AR.reset()
    yield
    FC._cache.clear()
    FC._GEN_STATUS.clear()
    FC._QUEUE_MEM = {}
    RC._cache.clear()
    SC._WRITE_RECEIPTS.clear()
    AR.reset()


# ══ 1. Queue-refresh VERVANGT, stapelt niet ══════════════════════════════════
class TestQueueRefreshVervangt:
    def test_cache_volgt_de_snapshot_en_groeit_niet_mee(self):
        """Dit is de kern van de opbouw: het 7-daagse venster schuift op, dus elke sweep
        levert nieuwe workout_keys. Vroeger bleven de oude er permanent bij staan."""
        for dag in range(10):
            FC._herstel_cache(_snap([f"d{dag}-w{i}" for i in range(20)]))
            assert len(FC._cache) == 20, f"dag {dag}: cache = {len(FC._cache)}"

    def test_cache_is_nooit_groter_dan_de_werkvoorraad(self):
        FC._herstel_cache(_snap([f"a{i}" for i in range(30)]))
        FC._herstel_cache(_snap([f"b{i}" for i in range(12)]))
        volle = len((FC._QUEUE_MEM or {}).get("_volle") or {}) or 12
        assert len(FC._cache) <= max(volle, 12)
        assert set(FC._cache) == {f"b{i}" for i in range(12)}

    def test_al_geladen_details_overleven_een_refresh_binnen_hetzelfde_venster(self):
        """Pruning mag geen refetch-storm veroorzaken: workouts die IN het venster blijven
        houden hun object-identiteit (en dus hun lazy geladen details)."""
        snap = _snap(["w1", "w2"])
        FC._herstel_cache(snap)
        FC._cache["w1"]["details"] = {"Activities": [{"laps": [{"lap": 1}]}]}
        obj = FC._cache["w1"]
        FC._herstel_cache(_snap(["w1", "w2"]))               # zelfde venster, verse objecten
        assert FC._cache["w1"] is obj                        # identiteit behouden
        assert FC._cache["w1"]["details"]                    # geen refetch nodig

    def test_lege_snapshot_prunet_niet(self):
        """Een mislukte/lege sweep mag de cache niet leegtrekken (LKG blijft leidend)."""
        FC._herstel_cache(_snap(["w1", "w2"]))
        FC._herstel_cache({"fs": True, "items": [], "_volle": {}})
        assert set(FC._cache) == {"w1", "w2"}

    def test_generatiestatus_volgt_dezelfde_grens(self):
        FC._herstel_cache(_snap(["w1"]))
        FC._GEN_STATUS["w1"] = "AUTO_SAFE"
        FC._GEN_STATUS["oud"] = "AUTO_SAFE"
        FC._herstel_cache(_snap(["w1"]))
        assert "oud" not in FC._GEN_STATUS                   # verweesde status opgeruimd
        assert FC._GEN_STATUS["w1"] == "AUTO_SAFE"           # actuele status behouden


# ══ 2. Durable snapshot draagt geen lazy detailpayloads ══════════════════════
class TestDurableSnapshotBlijftLicht:
    def test_details_gaan_niet_mee_naar_de_store(self):
        """`_ensure_details` muteert het gedeelde object; zonder deze schoonmaak groeide de
        durable snapshot mee met elke geopende training (gemeten: 1 training = 2× zo groot)
        en laadde een restart die laps meteen terug in het geheugen."""
        snap = _snap(["w1", "w2"])
        snap["_volle"]["w1"]["details"] = {"Activities": [{"laps": [{"lap": i} for i in range(48)]}]}
        payload = FC._persist_payload(snap)
        assert not payload["_volle"]["w1"].get("details")
        assert payload["_volle"]["w1"]["workout_key"] == "w1"       # rest ongewijzigd
        assert payload["items"] == snap["items"]
        # in-memory object blijft ongemoeid (identiteit/details behouden)
        assert snap["_volle"]["w1"]["details"]

    def test_payload_zonder_volle_gaat_ongewijzigd_door(self):
        s = {"fs": True, "items": [], "gepost": 0}
        assert FC._persist_payload(s) is s

    def test_persist_schrijft_de_uitgeklede_payload(self, monkeypatch):
        gezien = {}
        monkeypatch.setattr(FC.intake_store, "save_feedback_queue",
                            lambda snap: (gezien.update(snap), (True, ""))[1])
        snap = _snap(["w1"])
        snap["_volle"]["w1"]["details"] = {"Activities": [1, 2, 3]}
        FC._queue_persist(snap)
        assert not (gezien.get("_volle") or {})["w1"].get("details")
        assert FC._QUEUE_MEM["_volle"]["w1"]["details"]              # in-memory ongewijzigd


# ══ 3. AthleteState hot cache is begrensd ════════════════════════════════════
class _FakeState:
    schema_version = 1
    sources: list = []
    source_gaps: list = []
    built_at = ""

    def __init__(self, key):
        self.athlete_key = key

    def to_dict(self):
        return {"schema_version": 1, "athlete_key": self.athlete_key, "overall": "ok",
                "evidence": [], "conflicts": [], "source_gaps": []}


class TestAthleteStateCacheBegrensd:
    def _bouw(self, monkeypatch, n):
        monkeypatch.setattr(AR._adapter, "build_state",
                            lambda uk, today, gather_fn=None: (_FakeState(uk), {"training_log": [uk] * 50}))
        for i in range(n):
            AR.get_state(f"u{i:03d}")

    def test_bezoek_aan_veel_atleten_groeit_niet_onbeperkt(self, monkeypatch):
        self._bouw(monkeypatch, 80)
        assert len(AR._MEM) <= AR._MAX_ENTRIES, f"_MEM = {len(AR._MEM)}"

    def test_oude_generaties_worden_echt_vrijgegeven(self, monkeypatch):
        """Een geëvicte entry mag geen enkele referentie naar zijn `raw` payload houden —
        dát is wat de 4 maanden trainingslog per atleet vastzette."""
        import gc
        import weakref

        class _Payload(dict):                                 # weakref-baar, gedraagt zich als raw
            pass

        payloads = {}

        def _build(uk, today, gather_fn=None):
            p = _Payload({"training_log": [uk] * 20})
            payloads[uk] = weakref.ref(p)
            return _FakeState(uk), p

        monkeypatch.setattr(AR._adapter, "build_state", _build)
        AR.get_state("eerste")
        for i in range(AR._MAX_ENTRIES + 5):
            AR.get_state(f"vul{i}")
        gc.collect()
        assert "eerste" not in AR._MEM
        assert payloads["eerste"]() is None, "raw van een geëvicte atleet wordt nog vastgehouden"

    def test_recent_gebruikte_atleet_blijft_warm(self, monkeypatch):
        """LRU, geen FIFO: de atleet waar de coach mee bezig is mag er niet uitvallen."""
        self._bouw(monkeypatch, AR._MAX_ENTRIES)
        warm = "u000"
        for i in range(AR._MAX_ENTRIES // 2):
            AR.get_state(warm)                                # blijft in gebruik
            AR.get_state(f"nieuw{i}")
        assert warm in AR._MEM

    def test_eviction_verandert_de_leescontract_semantiek_niet(self, monkeypatch):
        """Uit de cache vallen == nog nooit bezocht: één on-demand build, geen fan-out."""
        builds = []
        monkeypatch.setattr(AR._adapter, "build_state",
                            lambda uk, today, gather_fn=None: (builds.append(uk), (_FakeState(uk), {}))[1])
        AR.get_state("x")
        for i in range(AR._MAX_ENTRIES + 2):
            AR.get_state(f"vul{i}")
        n_voor = len(builds)
        r = AR.get_state("x")                                 # was geëvict → één verse build
        assert len(builds) == n_voor + 1
        assert r.freshness["from"] == "fresh" and r.state is not None

    def test_inflight_blijft_leeg_na_afloop(self, monkeypatch):
        self._bouw(monkeypatch, 10)
        assert AR._INFLIGHT == {}                             # geen achtergebleven futures/events


# ══ 4. Overige procesglobale maps zijn begrensd ══════════════════════════════
class TestOverigeMapsBegrensd:
    def test_races_lookup_is_begrensd(self, monkeypatch):
        monkeypatch.setattr(RC, "heeft_token", lambda: True)
        for ronde in range(6):
            monkeypatch.setattr(RC.FS, "get_upcoming_races", lambda days_ahead=42, _r=ronde: [
                {"workout_key": f"r{_r}-{i}", "athlete_name": "A", "workout_date": "2026-09-10"}
                for i in range(150)])
            RC.komende()
        assert len(RC._cache) <= RC._CACHE_MAX

    def test_write_receipts_zijn_begrensd(self):
        for i in range(SC._RECEIPTS_MAX * 3):
            SC._receipt(f"wid-{i}")
        assert len(SC._WRITE_RECEIPTS) <= SC._RECEIPTS_MAX + 1

    def test_actieve_write_receipt_overleeft_de_pruning(self):
        for i in range(SC._RECEIPTS_MAX * 2):
            SC._receipt(f"wid-{i}")
        r = SC._receipt("actief")
        r["success"].add("sig")
        assert SC._receipt("actief")["success"] == {"sig"}    # idempotency intact


# ══ 5. Structuurcontract — geen onbegrensde accumulatie meer in de code ══════
class TestStructuurcontract:
    def test_herstel_cache_prunet_expliciet(self):
        src = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        i = src.index("def _herstel_cache(")
        blok = src[i:i + 1800]
        assert "_cache.setdefault" in blok                    # identiteit behouden
        assert "_cache.pop(wid, None)" in blok                # én prunen

    def test_state_cache_heeft_een_grens(self):
        src = open(os.path.join(_ROOT, "pwa", "athlete_read.py")).read()
        assert "_MAX_ENTRIES" in src and "def _evict_locked(" in src
        assert "BEBETTER_STATE_CACHE_MAX" in src              # in productie bij te stellen
        assert AR._MAX_ENTRIES >= 1

    def test_benchmark_blijft_bestaan(self):
        """De reproduceerbare meting hoort bij de fix — zonder die meting is een volgende
        regressie weer alleen maar een Render-waarschuwing."""
        p = os.path.join(_ROOT, "tests", "memory_bench.py")
        assert os.path.exists(p)
        src = open(p).read()
        assert "tracemalloc" in src and "gc.collect()" in src
        assert "post_comment" in src                          # write-guard in de stubs
