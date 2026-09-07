"""Feedback Field Round — 7 september 2026 (F1-F6).

Zes veldbevindingen uit een echte ronde over ~20 atleten, elk eerst bewezen en daarna minimaal
gerepareerd. Zie `docs/audits/FEEDBACK_FIELD_ROUND_2026-09-07.md` voor de root causes.

  F1  hot-queue-timeout was terminaal terwijl de server doorwerkte (client, app.js)
  F2  RECURRING-klacht sloeg de leeftijdstoets over → 27 dagen oude klacht als levende context
  F3  één korte positieve afsluiter, uitsluitend bij ExecutionFit ON_TARGET
  F4  `vandaag` over een training van een andere dag (3 oorzaken)
  F5  cross-sport contaminatie: de snelste activiteit van de dag werd de sessie-uitvoering
  F6  ongeplande uitgevoerde runs zonder reactie — PRODUCTBESLISSING, niet geïmplementeerd

    python3 -m pytest tests/test_feedback_field_round_2026_09_07.py -q
"""
import os
import subprocess
import sys
from datetime import date, timedelta

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback
import feedback_atoms as fa
import feedback_facts as ff
import fs_client
import feedback_core
import metric_authority as MA
from brain import adapter, complaints, recency
from brain import state as _state
from brain.models import SourceHealth

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()

# productiebaseline waarop deze ronde is gebouwd
_BASE = "9a506cd"

HR = [{"num": i, "naam": "z", "low": lo, "high": hi} for i, (lo, hi) in
      enumerate([(110, 130), (130, 145), (145, 169), (169, 179), (179, 200)], 1)]


def _fn(name: str) -> str:
    """Body van één JS-functie (brace-matching)."""
    i = _APP.index(name)
    j = _APP.index("{", i)
    d = 0
    for k in range(j, len(_APP)):
        if _APP[k] == "{":
            d += 1
        elif _APP[k] == "}":
            d -= 1
            if d == 0:
                return _APP[i:k + 1]
    raise AssertionError(name)


# ══════════════════════════════════════════════════════════════════════════════
# F1 — een hot-queue-timeout is geen serverfout
# ══════════════════════════════════════════════════════════════════════════════
class TestF1QueueTimeout:
    """De executable state-machine-bewijzen staan in tests/js/feedback_startup.test.mjs
    (S1 + S1b), die via test_feedback_startup_browser.py in de suite draait. Hier leggen we
    het CONTRACT in de bron vast zodat het niet stil terug kan glijden."""

    def test_f1_deadline_abort_is_niet_terminaal(self):
        body = _fn("async function fbEnter()")
        # De timeout-tak toont de wacht-shell i.p.v. de foutkaart en valt NIET uit fbEnter.
        assert "fbRenderColdWaiting();" in body
        assert "queue_hot_timeout_soft" in body

    def test_f1_echte_netwerkfout_blijft_fail_closed(self):
        body = _fn("async function fbEnter()")
        assert 'if (!q.timedOut) { fbRenderError("network"); return; }' in body

    def test_f1_achtergrondrefresh_wordt_altijd_bereikt(self):
        """Vóór de fix stond er één `return` die fbRefresh() oversloeg. De enige `return` die
        nu nog in de geen-respons-tak zit, is die van de ECHTE netwerkfout."""
        body = _fn("async function fbEnter()")
        blok = body[body.index("if (!r) {"):body.index("else if (!r.fs)")]
        assert blok.count("return;") == 1
        assert body.rstrip().endswith("fbRefresh();                                        // achtergrond: verse sweep\n}")

    def test_f1_refresh_houdt_zijn_terminale_vangnet(self):
        """Faalt óók de achtergrond-refresh, dan slaat het alsnog terminaal om — het P0-contract
        'nooit een oneindig skeleton' blijft dus staan, alleen één stap later."""
        body = _fn("async function fbRefresh()")
        assert "if (FB.pendingInitial && !FB.items.length) fbRenderError(" in body

    def test_f1_geen_extra_generatie_of_queue_call(self):
        """De fix voegt geen enkele request toe: nog steeds één hot + één refresh, en fbGen
        blijft de enige plek die /api/feedback/generate aanroept."""
        body = _fn("async function fbEnter()")
        assert body.count("fbQueueGet(") == 1 and body.count("fbRefresh()") == 1
        assert _APP.count('jpost("/api/feedback/generate"') == 1


# ══════════════════════════════════════════════════════════════════════════════
# F2 — klacht-recency in de Feedback-context
# ══════════════════════════════════════════════════════════════════════════════
TODAY = date(2026, 9, 7)                                  # maandag 7 september 2026


def _d(n):
    return (TODAY - timedelta(days=n)).isoformat()


def _health():
    return [SourceHealth(source=s, available=True, last_success=TODAY.isoformat())
            for s in ("intake", "coach_notes", "coach_memory", "on_hold", "garmin", "belasting",
                      "fs.training_log", "fs.labels", "fs.zones")]


def _log_met_klacht(dagen):
    """Trainingslog met een klachtmelding op elk van `dagen` dagen geleden."""
    log = []
    for wi in range(4):
        log.append({"date": _d(wi * 7 + 2), "actual_km": 8.0, "completed": True, "activity_type": "Run"})
    for n in dagen:
        log.append({"date": _d(n), "actual_km": 6.0, "completed": True, "activity_type": "Run",
                    "post_notes": "last van mijn knie", "workout_key": f"w{n}"})
    return log


def _ctx(dagen):
    raw = {"intake": {"doel": "10km"}, "intake_ts": _d(60), "notes": [], "profiel": "",
           "on_hold": None, "garmin": "", "belasting": None,
           "training_log": _log_met_klacht(dagen), "labels": [], "zones": {}}
    st = _state.assemble("A", "Lisa", raw, _health(), TODAY)
    return adapter.feedback_context(st, "", TODAY)


class TestF2KlachtRecency:
    def test_f2_root_cause_recurring_negeert_leeftijd(self):
        """Reproductie van de veldcase: klacht 04-08 + 11-08, beoordeeld op 07-09. De lifecycle
        zet RECURRING op FREQUENTIE, vóór elke leeftijdstoets — dat is de oorzaak."""
        raw = {"notes": [], "training_log": [
            {"date": "2026-08-04", "post_notes": "last van mijn knie", "workout_key": "A"},
            {"date": "2026-08-11", "post_notes": "knie voelt nog gevoelig", "workout_key": "B"}]}
        grp = [e for e in complaints.build(raw, "A", TODAY) if e.key == "complaint.knie"][0]
        assert grp.status == "RECURRING" and grp.detail["last_seen_days"] == 27

    def test_f2_oude_niet_actuele_klacht_verdwijnt(self):
        """27 dagen oud (> COMPLAINT_RECENT) → niet meer in de Feedback-context, en dus ook
        geen ACTUEEL-signaal-instructie meer."""
        ctx = _ctx([34, 27])
        assert ctx["complaint_areas"] == []
        assert "knie" not in ctx["prompt_block"].lower()
        assert "ACTUEEL signaal" not in ctx["prompt_block"]

    def test_f2_actieve_klacht_blijft(self):
        ctx = _ctx([3])
        assert "knie" in ctx["complaint_areas"]
        assert "knie" in ctx["prompt_block"].lower()
        assert "knie" in ctx["complaint_new"]

    def test_f2_recurring_met_recente_melding_blijft(self):
        """Terugkerend blijft terugkerend zolang het ook ACTUEEL is (laatste melding binnen 21d)."""
        ctx = _ctx([30, 5])
        assert "knie" in ctx["complaint_areas"]
        assert "Terugkerende klacht" in ctx["prompt_block"]

    def test_f2_grens_precies_op_het_recente_venster(self):
        assert recency.COMPLAINT_RECENT.days == 21
        assert "knie" in _ctx([40, 21])["complaint_areas"]        # exact op de grens → nog mee
        assert _ctx([40, 22])["complaint_areas"] == []            # één dag erbuiten → weg

    def test_f2_lifecycle_zelf_ongewijzigd(self):
        """De fix zit in de Feedback-projectie, niet in de klacht-lifecycle: Home/Dossier
        moeten een terugkerend patroon juist wél blijven zien."""
        src = open(os.path.join(_ROOT, "pwa", "brain", "complaints.py")).read()
        assert "elif is_recurring:\n            status = RECURRING" in src
        proj = open(os.path.join(_ROOT, "pwa", "brain", "projections.py")).read()
        assert "(_is_complaint_group(e) and e.status in (ACTIVE, RECURRING))" in proj   # for_home

    def test_f2_onbekende_leeftijd_wordt_niet_stil_weggefilterd(self):
        assert adapter._complaint_is_current({"status": "RECURRING", "detail": {}}) is True
        assert adapter._complaint_is_current({"status": "ACTIVE", "detail": {"last_seen_days": 99}}) is True


# ══════════════════════════════════════════════════════════════════════════════
# F3 — één korte positieve afsluiter bij aantoonbaar goede uitvoering
# ══════════════════════════════════════════════════════════════════════════════
def _hrblok(z):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 1, "distUnit": "km",
            "target": [{"targetType": "hr zone", "zone": z}]}


def _beslis(monkeypatch, *, laps, comments=(), post_notes="lekker gelopen", diag=None):
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: [_hrblok(2)])
    monkeypatch.setattr(fs_client, "get_athlete_zones",
                        lambda ak: {"zone_type": "hartslag", "zones_text": "z", "zones": HR})
    w = {"workout_type": "run", "workout_key": "W", "athlete_key": "AK",
         "post_notes": post_notes, "athlete_comments": list(comments),
         "details": {"has_structured_workout": True, "description": "rustige duurloop",
                     "Activities": [{"hr_avg": 138, "pace_display": "5:30", "Laps": laps}]}}
    if diag:
        w["_brein_diag"] = diag
    return fa.build_decision(w)


_ON = [{"amount": 1, "hr_avg": 138} for _ in range(8)]
_BOVEN = [{"amount": 1, "hr_avg": 138} for _ in range(5)] + [{"amount": 1, "hr_avg": 175} for _ in range(3)]


class TestF3PositieveAfsluiter:
    def test_f3_goede_uitvoering_krijgt_een_korte_afsluiter(self, monkeypatch):
        d = _beslis(monkeypatch, laps=_ON)
        assert d["status"] == fa.AUTO_SAFE
        assert d["execution_fit"]["category"] == fa.ON_TARGET
        assert "positive_close" in [a["id"] for a in d["atoms"]]
        assert d["text"].endswith("Goed gedaan.")

    def test_f3_afsluiter_staat_altijd_als_laatste_zin(self, monkeypatch):
        d = _beslis(monkeypatch, laps=_ON)
        zinnen = [z for z in d["text"].split(". ") if z.strip()]
        assert zinnen[-1].rstrip(".") == "Goed gedaan"
        assert fa._ORDER["close"] == max(fa._ORDER.values())

    def test_f3_matige_uitvoering_krijgt_geen_lof(self, monkeypatch):
        d = _beslis(monkeypatch, laps=_BOVEN)
        assert d["execution_fit"]["category"] != fa.ON_TARGET
        assert "positive_close" not in [a["id"] for a in d["atoms"]]
        assert "Goed gedaan" not in d["text"]

    def test_f3_geen_lof_bij_klacht(self, monkeypatch):
        d = _beslis(monkeypatch, laps=_ON, post_notes="mijn scheen zeurde",
                    diag={"complaint_areas": ["scheen"], "complaint_new": ["scheen"]})
        assert "complaint_scheen" in [a["id"] for a in d["atoms"]]
        assert "positive_close" not in [a["id"] for a in d["atoms"]]

    def test_f3_geen_lof_bij_afwezigheidsmelding(self, monkeypatch):
        d = _beslis(monkeypatch, laps=_ON, comments=["kan er volgende week niet bij zijn"])
        assert "attendance" in [a["id"] for a in d["atoms"]]
        assert "positive_close" not in [a["id"] for a in d["atoms"]]

    def test_f3_geen_lof_bij_open_vraag(self, monkeypatch):
        d = _beslis(monkeypatch, laps=_ON, post_notes="wat vond je van mijn cadans?")
        assert "positive_close" not in [a["id"] for a in d["atoms"]]

    def test_f3_hooguit_een_afsluiter(self, monkeypatch):
        d = _beslis(monkeypatch, laps=_ON)
        assert d["text"].count("Goed gedaan") == 1
        assert [a["id"] for a in d["atoms"]].count("positive_close") == 1

    def test_f3_copy_blijft_kort(self, monkeypatch):
        d = _beslis(monkeypatch, laps=_ON)
        zinnen = [z for z in d["text"].replace("! ", ". ").split(". ") if z.strip()]
        assert 2 <= len(zinnen) <= 4

    def test_f3_afsluiter_kan_nooit_zelf_auto_safe_maken(self):
        """`close` telt niet als `content`, dus een reactie die verder niets bewijsbaars heeft
        wordt er niet door naar AUTO_SAFE getild."""
        src = open(os.path.join(_ROOT, "feedback_atoms.py")).read()
        blok = src[src.index("    content = [a for a in atoms"):src.index("    text = assemble(atoms)")]
        assert '"close"' not in blok
        assert '("correction", "observation", "plan_execution", "answer")' in blok

    def test_f3_atoom_haalt_de_bestaande_guards(self, monkeypatch):
        """De afsluiter passeert `_final_is_atoms_only` én `validate_draft` — anders had
        de defense-in-depth de case naar REVIEW_REQUIRED geduwd."""
        d = _beslis(monkeypatch, laps=_ON)
        assert fa._final_is_atoms_only(d["text"], d["atoms"])
        assert ff.validate_draft(d["text"], is_running=True)["ok"]


# ══════════════════════════════════════════════════════════════════════════════
# F4 — relatieve dagtaal
# ══════════════════════════════════════════════════════════════════════════════
class TestF4Dagtaal:
    def test_f4a_sessieblok_noemt_de_trainingsdag_niet_vandaag(self):
        """Het same-day-sessieblok beschrijft de TRAININGSdag, niet de generatiedag; met het
        woord 'vandaag' erin kreeg het model op maandag 'vandaag' aangereikt over een
        zondagsessie."""
        src = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        blok = src[src.index("def _session_context("):src.index("def _brein_gate")] \
            if "def _brein_gate" in src else src[src.index("def _session_context("):]
        blok = blok[:blok.index("\ndef ", 10)]
        assert "vandaag meerdere hardloop-registraties" not in blok
        assert "op de dag van deze training meerdere hardloop-registraties" in blok

    def test_f4b_generatiedatum_is_tijdzonebewust(self):
        """`ai_feedback` gebruikt niet langer de naïeve serverdatum maar dezelfde
        tijdzone-bewuste generatiedatum als de rest van de generatie."""
        src = open(os.path.join(_ROOT, "ai_feedback.py")).read()
        assert "from feedback_core import _generation_date as _gen_date" in src
        assert "\n    _today = date.today()\n" not in src      # de naïeve toplevel-regel is weg

    def test_f4b_zondagtraining_op_maandag_is_geen_same_day(self, monkeypatch):
        """Gedragsbewijs: met de tijdzone-bewuste generatiedatum op maandag krijgt een
        zondagtraining GEEN 'op de dag van de training zelf'-instructie meer."""
        import intake_store
        monkeypatch.setattr(feedback_core, "_generation_date", lambda: date(2026, 9, 7))
        monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda *a, **k: None)
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda *a, **k: {})
        monkeypatch.setattr(fs_client, "get_workout_builder", lambda *a, **k: [])
        monkeypatch.setattr(intake_store, "garmin_context_text", lambda *a, **k: "")
        wd = {"athlete_name": "T", "athlete_first_name": "T", "athlete_key": "A",
              "workout_key": "W", "workout_name": "Duurloop", "workout_date": "2026-09-06",
              "post_notes": "x", "workout_type": "run",
              "details": {"has_structured_workout": False,
                          "Activities": [{"planned_amount": 10.0, "amount": 10.0,
                                          "pace_display": "5:30", "hr_avg": 150}]}}
        ctx, _ = ai_feedback._build_workout_context(wd)
        assert "op de dag van de training zelf" not in ctx
        assert "Vandaag (wanneer jij reageert): maandag 7 september 2026" in ctx

    def test_f4b_generation_date_is_europe_amsterdam(self):
        import inspect
        src = inspect.getsource(feedback_core._generation_date)
        assert 'ZoneInfo("Europe/Amsterdam")' in src
        assert isinstance(feedback_core._generation_date(), date)

    def test_f4c_vandaag_over_andere_dag_wordt_geblokkeerd(self):
        t = "Je duurloop zag er vandaag prima uit."
        assert ff.validate_draft(t, is_running=True, workout_is_today=False)["ok"] is False
        assert ff.validate_draft(t, is_running=True,
                                 workout_is_today=False)["detail"] == "relative_day:vandaag"

    def test_f4c_same_day_mag_vandaag_zeggen(self):
        t = "Je duurloop zag er vandaag prima uit."
        assert ff.validate_draft(t, is_running=True, workout_is_today=True)["ok"] is True
        assert ff.validate_draft(t, is_running=True)["ok"] is True      # default = same-day

    def test_f4c_zondag_bekeken_op_maandag_is_nooit_vandaag(self, monkeypatch):
        """Volledige poort door het productiepad: `_validate_or_block` leidt `workout_is_today`
        af uit de trainingsdatum vs. de tijdzone-bewuste generatiedatum."""
        monkeypatch.setattr(feedback_core, "_generation_date", lambda: date(2026, 9, 7))  # maandag
        w = {"workout_date": "2026-09-06", "workout_type": "run"}                          # zondag
        with pytest.raises(ValueError):
            feedback_core._validate_or_block(w, "Mooie duurloop vandaag.", "INITIAL_ANALYSIS")
        w_today = {"workout_date": "2026-09-07", "workout_type": "run"}
        feedback_core._validate_or_block(w_today, "Mooie duurloop vandaag.", "INITIAL_ANALYSIS")

    def test_f4c_onbekende_datum_blokkeert_niet(self, monkeypatch):
        monkeypatch.setattr(feedback_core, "_generation_date", lambda: date(2026, 9, 7))
        feedback_core._validate_or_block({"workout_date": "", "workout_type": "run"},
                                         "Mooie duurloop vandaag.", "INITIAL_ANALYSIS")

    def test_f4_v6_dagwoord_lock_blijft_staan(self):
        """BEWUSTE afwijking van het acceptatiecriterium 'previous day mag gisteren': v6 is een
        gelockt productbesluit (athlete-facing géén relatieve dagwoorden, verwijzen via de
        BETEKENIS). Die regel is strenger dan F4 vraagt en haalt F4's doel volledig."""
        for woord in ("gisteren", "eergisteren", "morgen", "overmorgen"):
            r = ff.validate_draft(f"Je liep {woord} sterk.", is_running=True, workout_is_today=True)
            assert r["ok"] is False and r["detail"] == "relative_day"

    def test_f4_client_datumlabel_ongewijzigd(self):
        """Feedback's eigen queue-labels (Vandaag/Gisteren) zijn client-side en correct; die
        blijven ongemoeid."""
        body = _fn("function fbDateLabel(d)")
        assert 'return "Vandaag"' in body and 'return "Gisteren"' in body


# ══════════════════════════════════════════════════════════════════════════════
# F5 — geen cross-sport contaminatie
# ══════════════════════════════════════════════════════════════════════════════
def _dag(run_pace="6:00", swim=True, bike=False, strength=False):
    ws = [{"key": "W-RUN", "workout_date": "2026-09-07", "has_actual_data": True,
           "activity_type_name": "Run",
           "Activities": [{"pace_display": run_pace, "amount": 4.7, "amount_type": "Kilometers",
                           "activity_type_name": "Run", "Laps": [{"amount": 1.0, "hr_avg": 130}]}]}]
    if swim:
        ws.append({"key": "W-SWIM", "workout_date": "2026-09-07", "has_actual_data": True,
                   "activity_type_name": "Swim",
                   "Activities": [{"pace_display": "2:30", "amount": 0.14, "amount_type": "Kilometers",
                                   "activity_type_name": "Swim", "Laps": [{"amount": 0.05}]}]})
    if bike:
        ws.append({"key": "W-BIKE", "workout_date": "2026-09-07", "has_actual_data": True,
                   "activity_type_name": "Bike",
                   "Activities": [{"pace_display": "1:45", "amount": 32.0, "amount_type": "Kilometers",
                                   "activity_type_name": "Bike", "Laps": []}]})
    if strength:
        ws.append({"key": "W-STR", "workout_date": "2026-09-07", "has_actual_data": True,
                   "activity_type_name": "Strength",
                   "Activities": [{"pace_display": "0:30", "amount": 0.0, "activity_type_name": "Strength"}]})
    return ws


class TestF5CrossSport:
    def test_f5_root_cause_zonder_filter_wint_de_zwemsessie(self, monkeypatch):
        """Bewijs van de oorzaak: zonder sportbegrenzing is de zwemactiviteit 'sneller' en
        wordt zij de uitvoering van de hardloopsessie."""
        monkeypatch.setattr(fs_client, "get_workouts", lambda *a, **k: _dag())
        ongefilterd = fs_client.get_fastest_activity_on_day("A", "2026-09-07")
        assert ongefilterd.get("activity_type_name") == "Swim"
        assert fs_client._pace_to_float("2:30") < fs_client._pace_to_float("6:00") * 0.85

    def test_f5_zwem_kan_geen_run_uitvoering_worden(self, monkeypatch):
        monkeypatch.setattr(fs_client, "get_workouts", lambda *a, **k: _dag())
        act = fs_client.get_fastest_activity_on_day("A", "2026-09-07", "run")
        assert act.get("activity_type_name") == "Run"

    def test_f5_fiets_en_kracht_guards(self, monkeypatch):
        monkeypatch.setattr(fs_client, "get_workouts",
                            lambda *a, **k: _dag(swim=True, bike=True, strength=True))
        act = fs_client.get_fastest_activity_on_day("A", "2026-09-07", "run")
        assert act.get("activity_type_name") == "Run"

    def test_f5_geen_run_op_die_dag_geeft_niets(self, monkeypatch):
        monkeypatch.setattr(fs_client, "get_workouts",
                            lambda *a, **k: [w for w in _dag() if w["key"] != "W-RUN"])
        assert fs_client.get_fastest_activity_on_day("A", "2026-09-07", "run") == {}

    def test_f5_zonder_sport_blijft_gedrag_ongewijzigd(self, monkeypatch):
        """Default `sport=""` is back-compat voor elke aanroeper die geen sport meegeeft."""
        monkeypatch.setattr(fs_client, "get_workouts", lambda *a, **k: _dag(swim=False))
        act = fs_client.get_fastest_activity_on_day("A", "2026-09-07")
        assert act.get("activity_type_name") == "Run"

    def test_f5_snellere_run_op_dezelfde_dag_wint_nog_steeds(self, monkeypatch):
        """De race-bedoeling (wu → race → cd als losse activiteiten) blijft werken binnen de sport."""
        ws = _dag(swim=True)
        ws.append({"key": "W-RACE", "workout_date": "2026-09-07", "has_actual_data": True,
                   "activity_type_name": "Run",
                   "Activities": [{"pace_display": "3:40", "amount": 10.0, "amount_type": "Kilometers",
                                   "activity_type_name": "Run", "Laps": []}]})
        monkeypatch.setattr(fs_client, "get_workouts", lambda *a, **k: ws)
        act = fs_client.get_fastest_activity_on_day("A", "2026-09-07", "run")
        assert act.get("pace_display") == "3:40"

    def test_f5_loopfeedback_blijft_run_only(self, monkeypatch):
        """Volledig productiepad: same-day zwem + herstelloop → de promptcontext bevat de
        LOOPuitvoering (4,7 km) en niet de zwemafstand (0,14 km)."""
        import intake_store
        monkeypatch.setattr(fs_client, "get_workouts", lambda *a, **k: _dag())
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda *a, **k: {})
        monkeypatch.setattr(fs_client, "get_workout_builder", lambda *a, **k: [])
        monkeypatch.setattr(intake_store, "garmin_context_text", lambda *a, **k: "")
        wd = {"athlete_name": "Test Atleet", "athlete_first_name": "Test", "athlete_key": "A",
              "workout_key": "W-RUN", "workout_name": "Herstelloop", "workout_date": "2026-09-07",
              "post_notes": "rustig aan gedaan", "workout_type": "run",
              "details": {"has_structured_workout": False,
                          "Activities": [{"planned_amount": 5.0, "amount": 4.7,
                                          "pace_display": "6:00", "hr_avg": 130,
                                          "activity_type_name": "Run",
                                          "Laps": [{"amount": 1.0, "hr_avg": 130}]}]}}
        ctx, _ = ai_feedback._build_workout_context(wd)
        assert "4.7" in ctx or "4,7" in ctx
        assert "0.14" not in ctx and "0,14" not in ctx
        assert "2:30" not in ctx                                    # geen zwemtempo

    def test_f5_activiteit_met_ander_eigen_type_wordt_ook_verworpen(self, monkeypatch):
        """Defense in depth op het aanroeppunt: draagt de teruggegeven ACTIVITEIT zelf een ander
        type, dan wordt de swap alsnog verworpen."""
        import intake_store
        monkeypatch.setattr(fs_client, "get_fastest_activity_on_day",
                            lambda *a, **k: {"pace_display": "2:30", "amount": 0.14,
                                             "activity_type_name": "Swim"})
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda *a, **k: {})
        monkeypatch.setattr(fs_client, "get_workout_builder", lambda *a, **k: [])
        monkeypatch.setattr(intake_store, "garmin_context_text", lambda *a, **k: "")
        wd = {"athlete_name": "T", "athlete_first_name": "T", "athlete_key": "A",
              "workout_key": "W", "workout_name": "Herstelloop", "workout_date": "2026-09-07",
              "post_notes": "x", "workout_type": "run",
              "details": {"has_structured_workout": False,
                          "Activities": [{"planned_amount": 5.0, "amount": 4.7,
                                          "pace_display": "6:00", "hr_avg": 130}]}}
        ctx, _ = ai_feedback._build_workout_context(wd)
        assert "0.14" not in ctx and "2:30" not in ctx

    def test_f5_metricauthority_ongewijzigd(self):
        """De run-metriekbepaling is niet aangeraakt."""
        assert MA.derive(fs_client._planned_blocks([_hrblok(2)]), "", "run")["primary"] == MA.HR
        assert MA.derive([], "", "run")["primary"] == MA.UNKNOWN
        diff = subprocess.run(["git", "diff", "--name-only", _BASE, "--"],
                              cwd=_ROOT, capture_output=True, text=True).stdout.split()
        assert "metric_authority.py" not in diff

    def test_f5_non_run_pad_ongemoeid(self):
        src = open(os.path.join(_ROOT, "ai_feedback.py")).read()
        assert 'if workout_type != "run":' in src                    # generate_feedback dispatch
        assert "def _build_nonrun_context(" in src


# ══════════════════════════════════════════════════════════════════════════════
# F6 — PRODUCTBESLISSING: ongeplande uitgevoerde runs zonder reactie
# ══════════════════════════════════════════════════════════════════════════════
class TestF6Productbeslissing:
    def test_f6_niet_geimplementeerd_queue_gates_ongewijzigd(self):
        fsc = open(os.path.join(_ROOT, "fs_client.py")).read()
        assert "include_data_only: bool = False" in fsc              # default onveranderd
        fc = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        assert "include_planned_no_notes=True" in fc
        assert "include_unplanned_reactions=True" in fc
        assert "include_data_only" not in fc                          # PWA-queue vraagt hem niet

    def test_f6_sorteervolgorde_en_categorieen_ongewijzigd(self):
        fc = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        blok = fc[fc.index("def _queue_public("):fc.index("def _diag(")]
        assert '_GROEP_RANK.get(i.get("groep"), 9)' in blok
        assert '_CAT_RANK.get(i["categorie"], 9)' in blok

    def test_f6_dekking_bestaat_al_comment_onafhankelijk(self):
        """De aanbeveling (A — niet toevoegen) rust hierop: een ongeplande uitgevoerde run is
        al canonieke evidence en bereikt Feedback en Dossier zonder atleetcommentaar."""
        derive = open(os.path.join(_ROOT, "pwa", "brain", "derive.py")).read()
        assert "training.run_" in derive and "'missed' if soort == 'missed' else 'unplanned'" in derive
        proj = open(os.path.join(_ROOT, "pwa", "brain", "projections.py")).read()
        assert 'e.key.startswith("training.run_unplanned.")' in proj
        dc = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()
        assert "Extra hardlooptraining (niet gepland)" in dc

    def test_f6_aanbeveling_is_vastgelegd(self):
        doc = open(os.path.join(_ROOT, "docs", "audits",
                                "FEEDBACK_FIELD_ROUND_2026-09-07.md")).read()
        assert "Aanbeveling: **A — niet toevoegen**" in doc
        assert "Niet geïmplementeerd in deze batch." in doc


# ══════════════════════════════════════════════════════════════════════════════
# Locks — de Feedback-architectuur blijft intact, de scope blijft eindig
# ══════════════════════════════════════════════════════════════════════════════
def _diff():
    return subprocess.run(["git", "diff", "--name-only", _BASE, "--"],
                          cwd=_ROOT, capture_output=True, text=True).stdout.split()


class TestLocks:
    def test_alleen_verwachte_bestanden_gewijzigd(self):
        verwacht = {
            "ai_feedback.py", "fs_client.py", "feedback_atoms.py", "feedback_facts.py",
            "pwa/feedback_core.py", "pwa/brain/adapter.py",
            "pwa/static/app.js", "pwa/static/sw.js", "pwa/static/index.html",
            "docs/audits/FEEDBACK_FIELD_ROUND_2026-09-07.md",
        }
        onverwacht = [f for f in _diff()
                      if f not in verwacht and not f.startswith("tests/")]
        assert not onverwacht, f"buiten scope gewijzigd: {onverwacht}"

    def test_safety_architectuur_intact(self):
        """v4-v8: MetricAuthority, AUTO_SAFE/REVIEW_REQUIRED, assemble_spine, validate_draft,
        atoms-only en de defense-in-depth blijven bestaan zoals ze waren."""
        fa_src = open(os.path.join(_ROOT, "feedback_atoms.py")).read()
        assert "def _final_is_atoms_only(" in fa_src and "def _passes_guards(" in fa_src
        assert "defense_in_depth_failed" in fa_src
        ff_src = open(os.path.join(_ROOT, "feedback_facts.py")).read()
        assert "def assemble_spine(" in ff_src and "def validate_draft(" in ff_src
        fc_src = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        assert "_validate_or_block(w, tekst, mode)" in fc_src
        assert 'decision.get("status") == "AUTO_SAFE"' in fc_src

    def test_copy_en_intent_laag_onaangeraakt(self):
        diff = _diff()
        for verboden in ("feedback_copy.py", "feedback_obligations.py", "metric_authority.py",
                         "pwa/feedback_week.py"):
            assert verboden not in diff

    def test_geen_nieuwe_store_cache_of_route(self):
        diff = _diff()
        for verboden in ("pwa/api.py", "pwa/home_core.py", "pwa/teampuls_core.py",
                         "pwa/coach_read.py", "pwa/athlete_read.py", "belasting.py",
                         "pwa/brain/derive.py", "pwa/brain/projections.py",
                         "pwa/brain/complaints.py", "pwa/brain/recency.py",
                         "pwa/dossier_cockpit.py", "pwa/schema_core.py", "pwa/races_core.py"):
            assert verboden not in diff, f"buiten scope: {verboden}"
        adap = open(os.path.join(_ROOT, "pwa", "brain", "adapter.py")).read()
        blok = adap[adap.index("def _complaint_is_current("):adap.index("def _klacht_coachregel(")]
        for verboden in ("open(", "requests", "_cache", "global "):
            assert verboden not in blok

    def test_queue_write_pad_onaangeraakt(self):
        """Skip/post/re-post-guard en `is_executed_workout` blijven zoals ze waren."""
        fc = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        for anker in ("def plaats(", "def overslaan(", "_verwijder_uit_queue(",
                      "def get_or_restore_workout("):
            assert anker in fc
        fsc = open(os.path.join(_ROOT, "fs_client.py")).read()
        assert "def is_executed_workout(" in fsc
        # Elke gewijzigde regel in fs_client valt binnen `get_fastest_activity_on_day`.
        # (De hunk-context van git noemt bij de eerste hunk de VOORGAANDE functie, dus we
        # toetsen op regelnummers in het nieuwe bestand, niet op die label-regel.)
        import re
        d = subprocess.run(["git", "diff", "-U0", _BASE, "--", "fs_client.py"],
                           cwd=_ROOT, capture_output=True, text=True).stdout
        regels = fsc.splitlines()
        start = next(i for i, r in enumerate(regels, 1)
                     if r.startswith("def get_fastest_activity_on_day("))
        eind = next(i for i, r in enumerate(regels, 1)
                    if i > start and r.startswith("def ")) - 1
        for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", d, re.M):
            eerste, n = int(m.group(1)), int(m.group(2) or 1)
            if n == 0:                                        # pure verwijdering
                continue
            assert start <= eerste and eerste + n - 1 <= eind, \
                f"fs_client-wijziging buiten get_fastest_activity_on_day: regels {eerste}-{eerste + n - 1}"

    def test_client_versie_gebumpt(self):
        sw = open(os.path.join(_ROOT, "pwa", "static", "sw.js")).read()
        idx = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()
        assert "bebetter-shell-v134" in sw
        assert idx.count("?v=138a") == 3 and "?v=137a" not in idx
