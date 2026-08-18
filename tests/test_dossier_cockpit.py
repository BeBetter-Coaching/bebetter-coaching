"""Dossier Fase B v1 — read-only cockpit view-model.

Borgt de drie 10s-scenario's (§15), read-only (geen history-write bij capture OFF),
dynamische domein-open (§12-C), recency-only 'recent veranderd' (§12-D) en lichte
provenance per claim (§12-E). Alles via de ECHTE brain-pipeline met geïnjecteerde
gather (geen netwerk).

    python3 -m pytest tests/test_dossier_cockpit.py -q
"""
import os
import sys
from datetime import date, timedelta

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

from brain import snapshot as SNAP
from brain import sources as SRC
from brain import history_store as HS
from brain.models import SourceHealth
import dossier_cockpit as DC

TODAY = date(2026, 8, 17)


def _d(days_ago):
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _run(days_ago, km=10):
    return {"date": _d(days_ago), "workout_key": f"w{days_ago}", "completed": True,
            "actual_km": km, "planned_km": km, "actual_min": km * 6, "is_race": False,
            "post_notes": ""}


def _health(tl=True):
    return [SourceHealth(source="fs.training_log", available=tl, error="" if tl else "geen sessie"),
            SourceHealth(source="fs.zones", available=True), SourceHealth(source="intake", available=True)]


def _raw(klacht="", log=None, notes=None):
    ik = {"athlete_name": "Testatleet", "naam": "Test", "doel": "10 EM < 70 min",
          "huidige_klachten": klacht, "huidig_volume": "30 km/week", "loopervaring": "3 jaar",
          "referentie_prestatie": "5k 24:30", "blessurehistorie": "kuit 2023",
          "trainingsdagen": "di/do/za", "slaap": "7-8u", "coach_notitie": "rustig opbouwen",
          "updated_at": TODAY.isoformat()}
    return {"intake": ik, "intake_ts": TODAY.isoformat(), "notes": notes or [], "profiel": "",
            "on_hold": None, "garmin": "", "belasting": None, "training_log": log or [],
            "labels": [], "zones": {}}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(SNAP, "load_snapshot", lambda k: None)
    monkeypatch.setattr(SNAP, "save_snapshot", lambda s: None)
    # capture OFF (default) → geen history; identity-resolver zonder FS
    monkeypatch.setattr(DC, "_identity", lambda key, st: (getattr(st, "naam", "") or key, ""))


def _patch_gather(monkeypatch, raw, health):
    monkeypatch.setattr(SRC, "gather", lambda k, today=None: (raw, health))


# ── Scenario 1 — gezonde/stabiele atleet (echte load, geen klacht) ───────────
def test_scenario1_stabiel(monkeypatch):
    log = [_run(i * 2 + 1, km=10) for i in range(10)]          # ~10 runs over 4 wk
    _patch_gather(monkeypatch, _raw("", log=log), _health(True))
    vm = DC.cockpit("K", today=TODAY)
    assert vm["status"]["overall"] in ("STABLE", "GOOD")
    assert vm["status"]["reliability"]["level"] == "green"
    assert vm["attention"] == []
    assert vm["attention_domains"] == []                        # geen kunstmatig open domein
    assert vm["timeline"]["empty_reason"] == "capture_off"


def test_scenario1_te_weinig_data_geen_vals_stabiel(monkeypatch):
    _patch_gather(monkeypatch, _raw("", log=[]), _health(True))
    vm = DC.cockpit("K", today=TODAY)
    assert vm["status"]["overall"] == "INSUFFICIENT_DATA"       # nooit vals 'stabiel'
    assert vm["status"]["insufficient"] is True
    assert vm["attention"] == []


# ── Scenario 2 — één duidelijke klacht (bronnen vers) ────────────────────────
def test_scenario2_klacht(monkeypatch):
    log = [_run(i * 2, km=10) for i in range(35)]              # dicht log ~10 wk → geen interruptie-ruis
    _patch_gather(monkeypatch, _raw("pijn in de knie sinds deze week", log=log), _health(True))
    vm = DC.cockpit("K", today=TODAY)
    assert vm["status"]["overall"] == "ATTENTION"
    assert vm["status"]["reliability"]["level"] == "green"
    kinds = [c["kind"] for c in vm["attention"]]
    assert "complaint" in kinds
    comp = next(c for c in vm["attention"] if c["kind"] == "complaint")
    assert comp["opens"] == "gezondheid" and "knie" in comp["title"]
    assert vm["attention_domains"] == ["gezondheid"]
    gez = next(d for d in vm["domains"] if d["key"] == "gezondheid")
    assert gez["open"] is True and not gez["onbekend"]
    # single fresh ACTIVE klacht = géén pseudo-history in Z2 (recency-only)
    assert vm["changes"] == []


# ── Scenario 3 — meerdere signalen + source-gap ──────────────────────────────
def test_scenario3_klacht_plus_source_gap(monkeypatch):
    _patch_gather(monkeypatch, _raw("pijn in de knie", log=[]), _health(tl=False))
    vm = DC.cockpit("K", today=TODAY)
    assert vm["status"]["overall"] == "INSUFFICIENT_DATA"
    rel = vm["status"]["reliability"]
    assert rel["level"] == "red" and rel["core_gap"] is True
    kinds = [c["kind"] for c in vm["attention"]]
    assert "complaint" in kinds and "source_gap" in kinds
    gap = next(c for c in vm["attention"] if c["kind"] == "source_gap")
    assert gap["opens"] is None                                 # source-gap opent GÉÉN domein
    assert vm["attention_domains"] == ["gezondheid"]            # alleen de klacht opent een domein
    # geen load-claim die op de uitgevallen bron leunt
    bel = next(d for d in vm["domains"] if d["key"] == "belastbaarheid")
    assert not any(r["label"].startswith("Km/week") for r in bel["regels"])


# ── Read-only garantie ───────────────────────────────────────────────────────
def test_readonly_geen_history_write(monkeypatch, tmp_path):
    # capture staat OFF (default) → cockpit mag NIETS naar de history-store schrijven
    monkeypatch.setattr(HS, "_LOCAL", str(tmp_path / ".athlete_history.json"), raising=False)
    _patch_gather(monkeypatch, _raw("pijn in de knie", log=[]), _health(True))
    DC.cockpit("K", today=TODAY)
    assert HS.count_events("K") == 0
    assert not os.path.exists(str(tmp_path / ".athlete_history.json"))


# ── Provenance (§12-E) + structuur ───────────────────────────────────────────
def test_domeinregels_dragen_lichte_provenance(monkeypatch):
    log = [_run(i * 2 + 1, km=10) for i in range(6)]
    _patch_gather(monkeypatch, _raw("", log=log), _health(True))
    vm = DC.cockpit("K", today=TODAY)
    gevuld = [d for d in vm["domains"] if not d["onbekend"]]
    assert gevuld
    for d in gevuld:
        for r in d["regels"]:
            assert r["prov"]["truth_type"] and r["prov"]["source"]
            assert r["evidence_id"]                             # 'Waarom?'-hook aanwezig


# ── Recency-only 'recent veranderd' (§12-D) ──────────────────────────────────
def test_changes_alleen_bij_echte_recency(monkeypatch):
    # terugkerende klacht (2 gedateerde meldingen) → wél een change; single fresh → niet (zie scen2)
    notes = [{"datum": _d(30), "tekst": "pijn aan de knie"},
             {"datum": _d(3), "tekst": "weer wat last van de knie"}]
    _patch_gather(monkeypatch, _raw("", log=[_run(2)], notes=notes), _health(True))
    vm = DC.cockpit("K", today=TODAY)
    titels = [c["title"] for c in vm["changes"]]
    assert any("knie" in t.lower() for t in titels)
    for c in vm["changes"]:                                     # drop-in-vorm voor echte HistoryEvents
        assert c["derived_from"] == "state" and "transition" in c


# ── Partial-truth resilience (foutklasse A) — cockpit toont partial context ───
def test_cockpit_partial_bij_gefaalde_build_stage(monkeypatch):
    """Eén gefaalde sub-builder (derive) → cockpit blijft ok, toont partial domeinen
    + diagnostic, en géén vals STABLE/GOOD (kerncomponent ontbreekt)."""
    import brain.derive as D
    monkeypatch.setattr(D, "all", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _patch_gather(monkeypatch, _raw("pijn in de knie", log=[]), _health(True))
    vm = DC.cockpit("K", today=TODAY)
    assert vm["ok"] is True                                     # geen totale uitval
    assert any(not d["onbekend"] for d in vm["domains"])       # onafhankelijke intakefacts blijven
    assert vm["build_diagnostic"] and any(e["stage"] == "derive" for e in vm["build_diagnostic"])
    assert vm["status"]["overall"] == "INSUFFICIENT_DATA"      # geen vals oordeel
