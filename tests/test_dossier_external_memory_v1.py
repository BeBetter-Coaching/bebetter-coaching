"""Dossier / External Memory v1 — verklarende coachgeheugenlaag bovenop canonical truth.

Geen tweede intelligentie-engine: Dossier projecteert bestaande AthleteState-evidence,
belasting-stand en intake. Kernpunten van deze milestone:

  P0 — complaints internal compute failure structureel opgelost. Root cause (repro):
       een vrije-tekst intakeklacht die `_vind` niet als gelabelde klacht herkende viel
       terug op `[{"": ""}]` (een DICT), waardoor `_area(re.search(...))` een TypeError
       gooide → hele complaints-stage viel om → onterecht "interne fout" + klacht
       onzichtbaar in Dossier terwijl Home/Teampuls hem toonden. Fix: sentinel "" i.p.v.
       een dict → onbekende klacht wordt tóch een 'onbekend'-melding (blijft zichtbaar).
  Coherentie — complaint + belasting komen uit DEZELFDE canonical bron als Home/Teampuls
       (brain-evidence + de gedeelde belasting-stand). Teampuls-observatie is óók zichtbaar
       als hij al is afgehandeld, mét de reden (verklaart 'waarom niet op Home').
  Partial-context — een falende stage is stage-lokaal (`build_diagnostic`) en wist de rest
       van het dossier nooit.
  Doelen/planning — compacte projectie uit goal-evidence + laatst geconfigureerd blok.

    python3 -m pytest tests/test_dossier_external_memory_v1.py -q
"""
import os
import sys
from datetime import date

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()

from brain import complaints as _complaints    # noqa: E402
from brain import state as _bstate             # noqa: E402
import dossier_cockpit as _dc                  # noqa: E402
from brain.models import ACTIVE, RECENT, RECURRING, RESOLVED, SourceHealth   # noqa: E402


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


TODAY = date(2026, 8, 25)


def _grp(evs):
    return [e for e in evs if e.key.startswith("complaint.") and not e.key.startswith("complaint.mention")]


# ══ P0 — complaints correctness (root cause) ═══════════════════════════════
class TestComplaintsCorrectness:
    def test_1_vrije_tekst_klacht_geen_crash_wel_zichtbaar(self):
        raw = {"intake": {"huidige_klachten": "voelt zich al weken niet lekker"}, "intake_ts": "2026-08-20"}
        out = _complaints.build(raw, "uk", TODAY)          # mag NIET throwen
        g = _grp(out)
        assert g and g[0].value == "onbekend"              # klacht blijft zichtbaar als 'onbekend'

    def test_2_gelabelde_klacht_classificeert(self):
        raw = {"intake": {"huidige_klachten": "pijn in de knie"}, "intake_ts": "2026-08-24"}
        g = _grp(_complaints.build(raw, "uk", TODAY))
        assert g and g[0].value == "knie" and g[0].status == ACTIVE

    def test_3_active_blijft_active_zonder_resolved(self):
        raw = {"notes": [{"datum": "2026-08-24", "tekst": "last van de knie"}]}
        g = _grp(_complaints.build(raw, "uk", TODAY))
        assert g and g[0].status in (ACTIVE, RECENT, RECURRING) and g[0].status != RESOLVED

    def test_4_afwezigheid_nieuwe_mention_is_niet_resolved(self):
        # Alleen een oude melding, geen 'hersteld'-tekst → nooit automatisch RESOLVED.
        raw = {"notes": [{"datum": "2026-05-01", "tekst": "last van de kuit"}]}
        g = _grp(_complaints.build(raw, "uk", TODAY))
        assert g and g[0].status != RESOLVED

    def test_5_expliciet_resolved_wordt_resolved(self):
        raw = {"notes": [{"datum": "2026-06-01", "tekst": "pijn in de knie"},
                         {"datum": "2026-08-20", "tekst": "knie is helemaal hersteld"}]}
        g = _grp(_complaints.build(raw, "uk", TODAY))
        assert g and g[0].status == RESOLVED

    def test_6_known_empty_geen_error(self):
        assert _complaints.build({"intake": {"huidige_klachten": ""}}, "uk", TODAY) == []

    def test_7_area_defensief_tegen_non_string(self):
        assert _dc  # module import
        assert _complaints._area({"x": 1}) == "onbekend"   # nooit een TypeError


# ══ Partial-context resilience (stage-lokaal) ══════════════════════════════
class TestPartialResilience:
    def test_8_falende_complaints_stage_wist_andere_evidence_niet(self, monkeypatch):
        # Forceer een throw in de complaints-stage; base/intake-evidence (doel) moet blijven.
        monkeypatch.setattr(_bstate._complaints, "build",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        raw = {"intake": {"doel": "10k sub 50", "athlete_name": "X"}, "intake_ts": "2026-08-20"}
        health = [SourceHealth(source="intake", available=True, stale=False)]
        st = _bstate.assemble("uk", "X", raw, health, TODAY)
        stages = [e["stage"] for e in getattr(st, "build_errors", [])]
        assert "complaints" in stages                       # stage-lokaal gemarkeerd
        assert any(e.key == "goal.doel" for e in st.evidence)  # andere kennis behouden


# ══ Doelen & planning-projectie ════════════════════════════════════════════
class TestPlanning:
    def test_9_schema_status_loopt_vs_afgelopen(self):
        assert "loopt" in _dc._schema_status("2026-09-10", TODAY)
        assert "afgelopen" in _dc._schema_status("2026-08-01", TODAY)
        assert _dc._schema_status("", TODAY) == ""

    def test_10_planning_projecteert_doel_race_en_blok(self):
        evs = [{"key": "goal.doel", "domain": "goal", "value": "HM sub 1:45"},
               {"key": "goal.race", "domain": "goal", "value": "2026-11-08"}]
        raw = {"intake": {"startdatum": "2026-08-31", "schema_einddatum": "2026-11-22", "op_tijd": True}}
        p = _dc._planning(evs, raw, TODAY)
        labels = {r["label"]: r["value"] for r in p["rows"]}
        assert labels.get("Hoofddoel") == "HM sub 1:45"
        assert labels.get("Wedstrijddatum") == "2026-11-08"
        assert "2026-08-31" in labels.get("Schema-blok (laatst geconfigureerd)", "")
        assert labels.get("Uitvoerwijze") == "tijd (minuten)"
        assert "Schema-status" in labels

    def test_11_planning_leeg_is_onbekend_geen_crash(self):
        p = _dc._planning([], {}, TODAY)
        assert p["onbekend"] is True and p["rows"] == []


# ══ Belasting-observatie (Teampuls-coherentie) ═════════════════════════════
class TestLoadObservation:
    def test_12_afgehandelde_hoge_belasting_zichtbaar_met_reden(self):
        raw = {"belasting": {"ernst": "hoog", "signalen": ["+32% t.o.v. referentie"],
                             "_afgehandeld": True, "_stand_datum": "2026-08-25"}}
        lo = _dc._load_observation(raw)
        assert lo and lo["ernst"] == "hoog" and lo["afgehandeld"] is True
        assert "referentie" in lo["signalen"]

    def test_13_let_op_belasting_is_observatie(self):
        lo = _dc._load_observation({"belasting": {"ernst": "let_op", "signalen": []}})
        assert lo and lo["ernst"] == "let_op" and lo["afgehandeld"] is False

    def test_14_geen_belasting_geen_observatie(self):
        assert _dc._load_observation({}) is None
        assert _dc._load_observation({"belasting": {"ernst": "geen"}}) is None


# ══ Frontend cockpit-hiërarchie + partial banner ═══════════════════════════
class TestCockpitFrontend:
    def test_15_planning_block_gerenderd(self):
        body = _fn("dcRender")
        assert "vm.planning" in body and "dc-planning" in body
        assert "Doelen &amp; planning" in body

    def test_16_load_observatie_note_gerenderd_met_reden(self):
        body = _fn("dcRender")
        assert "vm.load_observation" in body
        assert "eerder afgehandeld" in body and "geen open Home-actie" in body

    def test_17_diag_banner_is_stage_lokaal_niet_alles_of_niets(self):
        # De per-stage diag is een banner die de andere secties NIET gate; attention/
        # planning/domains renderen ongeacht build_diagnostic.
        body = _fn("dcRender")
        assert "vm.build_diagnostic" in body
        # attention en planning worden onvoorwaardelijk daarna nog gerenderd
        i_diag = body.index("build_diagnostic")
        assert body.index("dc-attn", i_diag) > i_diag
        assert body.index("dc-planning", i_diag) > i_diag

    def test_18_attention_top_met_calme_empty_state(self):
        body = _fn("dcRender")
        assert "Aandacht nu" in body
        assert "Geen actiepunten" in body           # rustige empty-state, geen leeg blok

    def test_19_geen_nieuwe_engine_in_cockpit(self):
        # Dossier projecteert; geen eigen klacht-/belasting-/priority-engine.
        src = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()
        assert "dagelijkse_check" not in src        # geen recompute van belasting
        assert "get_compliance_alerts" not in src   # geen eigen Home-actie-engine
