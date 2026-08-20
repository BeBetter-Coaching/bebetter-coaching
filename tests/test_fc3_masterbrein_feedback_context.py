"""FC-3 — Masterbrein-context rijker naar Feedback: race/goal/tijd + complaint-lifecycle.

Bewijst: (A) deterministische race/event-tijd uit de canonieke `goal.race`-truth ('over N
dagen', nooit door AI geraden, UNKNOWN bij onbetrouwbare datum); (B) één eventwaarheid cross-
consumer (Schema/Dossier/Feedback lezen dezelfde `goal.race`-evidence); (C) blanket
vooruitblikverbod vervangen; (D/E) rijkere klacht-lifecycle met coachperspectief zonder
diagnose. Geen nieuwe engine, geen history-capture.

    python3 -m pytest tests/test_fc3_masterbrein_feedback_context.py -q
"""
import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

from brain import adapter, projections, eventtime
from brain import state as _state
from brain.models import SourceHealth

TODAY = date(2026, 8, 20)          # donderdag 20 augustus 2026


def _d(n):
    return (TODAY - timedelta(days=n)).isoformat()


def _health(*, training_log=True, zones=True, intake=True, coach_notes=True):
    h = []
    for src, ok in (("intake", intake), ("coach_notes", coach_notes), ("coach_memory", True),
                    ("on_hold", True), ("garmin", True), ("belasting", True),
                    ("fs.training_log", training_log), ("fs.labels", True), ("fs.zones", zones)):
        h.append(SourceHealth(source=src, available=ok,
                              last_success=(TODAY.isoformat() if ok else ""),
                              error=("" if ok else "geen bron")))
    return h


def _log():
    log = []
    for wi in range(4):
        log.append({"date": _d(wi * 7 + 1), "actual_km": 8.0, "completed": True, "activity_type": "Run"})
        log.append({"date": _d(wi * 7 + 4), "actual_km": 6.0, "completed": True, "activity_type": "Run"})
    return log


def _raw(intake=None, notes=None, log=None):
    return {"intake": intake if intake is not None else {"doel": "10km"},
            "intake_ts": _d(30), "notes": notes or [], "profiel": "", "on_hold": None,
            "garmin": "", "belasting": None, "training_log": log if log is not None else _log(),
            "labels": [], "zones": {}}


def _ctx(intake=None, notes=None, log=None, health=None, today=TODAY):
    raw = _raw(intake, notes, log)
    st = _state.assemble("A", "Lisa", raw, health or _health(), today)
    return adapter.feedback_context(st, "", today), st


# ════════════════════════════════════════════════════════════════════════════
# A — event/tijd (eventtime + projectie)
# ════════════════════════════════════════════════════════════════════════════
class TestEventTime:
    def test_1_vandaag(self):
        assert eventtime.relative_event(TODAY.isoformat(), TODAY)["status"] == "TODAY"

    def test_2_morgen(self):
        r = eventtime.relative_event((TODAY + timedelta(days=1)).isoformat(), TODAY)
        assert r["status"] == "TOMORROW" and r["label"] == "morgen"

    def test_3_over_2_dagen(self):
        r = eventtime.relative_event((TODAY + timedelta(days=2)).isoformat(), TODAY)
        assert r["status"] == "IN_N_DAYS" and r["days"] == 2 and r["label"] == "over 2 dagen"

    def test_4_verleden(self):
        r = eventtime.relative_event((TODAY - timedelta(days=3)).isoformat(), TODAY)
        assert r["status"] == "PAST" and r["days"] == -3

    def test_5_onbekende_datum(self):
        assert eventtime.relative_event("20 sep halve marathon", TODAY)["status"] == "UNKNOWN"
        assert eventtime.relative_event("volgende maand", TODAY)["status"] == "UNKNOWN"

    def test_8_donderdag_plus_zaterdag_over_2_dagen(self):
        # donderdag 20 aug + zaterdag 22 aug → exact "over 2 dagen"
        r = eventtime.relative_event("2026-08-22", date(2026, 8, 20))
        assert r["label"] == "over 2 dagen" and r["days"] == 2

    def test_dd_mm_yyyy_parse(self):
        assert eventtime.relative_event("22-08-2026", date(2026, 8, 20))["days"] == 2

    def test_geen_jaartal_is_unknown(self):
        assert eventtime.parse_reliable_date("22-08") is None      # geen jaar → geen gok


class TestEventProjection:
    def test_over_2_dagen_in_context(self):
        block, _ = _ctx({"doel": "halve marathon", "wedstrijddatum": "2026-08-22"})
        assert "over 2 dagen" in block["prompt_block"]
        assert block["event"]["status"] == "IN_N_DAYS" and block["event"]["days"] == 2
        assert "reken de tijd NIET zelf uit" in block["prompt_block"]

    def test_6_geen_event_geen_fictieve_context(self):
        block, _ = _ctx({"doel": "10km"})                          # geen wedstrijddatum
        assert block["event"]["status"] == "UNKNOWN"
        assert "afspraak" not in block["prompt_block"].lower()

    def test_5b_vrije_tekst_datum_geen_vooruitblik(self):
        block, _ = _ctx({"doel": "loop", "wedstrijddatum_tekst": "ergens in het najaar"})
        assert block["event"]["status"] == "UNKNOWN"
        assert "over" not in block["prompt_block"].lower().split("belasting")[0] or \
               "afspraak" not in block["prompt_block"].lower()

    def test_verleden_event_geen_toekomst(self):
        block, _ = _ctx({"doel": "loop", "wedstrijddatum": "2026-08-10"})   # 10 dagen geleden
        assert block["event"]["status"] == "PAST"
        assert "afspraak" not in block["prompt_block"].lower()   # geen vooruitblik-regel


# ════════════════════════════════════════════════════════════════════════════
# B — één eventwaarheid cross-consumer
# ════════════════════════════════════════════════════════════════════════════
class TestCrossConsumer:
    def test_7_zelfde_racedatum_schema_dossier_feedback(self):
        st = _state.assemble("A", "Lisa",
                             _raw({"doel": "HM", "wedstrijddatum": "2026-08-22"}), _health(), TODAY)

        def _race_val(proj):
            return next((e.get("value") for e in (proj.get("evidence") or [])
                         if e.get("key") == "goal.race"), None)
        fb = _race_val(projections.for_feedback(st))
        sc = _race_val(projections.for_schema(st))
        do = _race_val(projections.for_dossier(st))
        assert fb == sc == do == "2026-08-22"                # dezelfde canonieke truth overal

    def test_schema_en_feedback_geen_divergentie(self, monkeypatch):
        # Schema-consumer (planning_defaults) én Feedback-consumer (feedback_context) leiden
        # de racedatum af uit DEZELFDE goal.race-truth → nooit verschillende datums.
        import intake_store
        from brain import snapshot as _bs
        ik = {"doel": "HM", "wedstrijddatum": "2026-08-22", "athlete_name": "Lisa"}
        monkeypatch.setattr(intake_store, "load_intakes", lambda: {"A": dict(ik)})
        monkeypatch.setattr(intake_store, "load_laatste_intakes", lambda: {})
        monkeypatch.setattr(_bs, "load_snapshot", lambda k: None)
        schema_date = adapter.planning_defaults("A", TODAY).get("wedstrijddatum")
        block, _ = _ctx(ik)                                  # Feedback-context uit dezelfde intake
        assert schema_date == "2026-08-22"
        assert block["event"]["date"] == "2026-08-22" and block["event"]["status"] == "IN_N_DAYS"

    def test_evidence_wijziging_propageert_zonder_raw_parallelpad(self):
        # één wijziging in de typed goal.race-evidence → alle drie projecties volgen
        st = _state.assemble("A", "Lisa",
                             _raw({"doel": "HM", "wedstrijddatum": "2026-09-01"}), _health(), TODAY)
        for proj in (projections.for_feedback(st), projections.for_schema(st),
                     projections.for_dossier(st)):
            assert any(e.get("key") == "goal.race" and e.get("value") == "2026-09-01"
                       for e in (proj.get("evidence") or []))


# ════════════════════════════════════════════════════════════════════════════
# C — blanket vooruitblikverbod vervangen + AI raadt niet
# ════════════════════════════════════════════════════════════════════════════
class TestPromptContract:
    def _sys(self):
        import ai_feedback
        return ai_feedback.SYSTEM_PROMPT

    def test_10_blanket_verbod_verwijderd(self):
        s = self._sys()
        assert "Kijk NIET op eigen houtje vooruit" in s
        assert "Noem een wedstrijd/race ALLEEN als de atleet" not in s   # oude blanket-regel weg

    def test_9_ai_mag_datum_niet_zelf_berekenen(self):
        s = self._sys()
        assert "reken de tijd tot een event NOOIT zelf uit" in s
        assert "Neem de meegegeven aanduiding LETTERLIJK over" in s


# ════════════════════════════════════════════════════════════════════════════
# D/E — complaint-lifecycle rijker + coachperspectief
# ════════════════════════════════════════════════════════════════════════════
def _note(days_ago, tekst):
    return {"datum": _d(days_ago), "tekst": tekst}


class TestComplaints:
    def test_11_active_verschilt_van_recent(self):
        act, _ = _ctx(notes=[_note(3, "pijn in de knie na de duurloop")])       # ACTIVE (<=7d)
        rec, _ = _ctx(notes=[_note(15, "pijn in de knie na de duurloop")])      # RECENT (8-21d)
        assert "actieve klacht" in act["prompt_block"].lower()
        assert "recent gemelde klacht" in rec["prompt_block"].lower()
        assert act["prompt_block"] != rec["prompt_block"]

    def test_12_recurring_bevat_frequentie_en_recency(self):
        notes = [_note(3, "pijn in de knie"), _note(20, "knie doet weer pijn"),
                 _note(40, "last van de knie")]
        block, _ = _ctx(notes=notes)
        pb = block["prompt_block"].lower()
        assert "terugkerende klacht" in pb
        assert "x gemeld" in pb and "d geleden" in pb          # frequentie + recency zichtbaar

    def test_13_historical_komt_niet_in_feedback(self):
        block, _ = _ctx(notes=[_note(60, "pijn in de knie")])   # >21d, 1x → HISTORICAL
        assert "knie" not in block["prompt_block"].lower()

    def test_14_resolved_niet_als_actief(self):
        notes = [_note(20, "pijn in de knie"), _note(2, "knie is helemaal hersteld, geen pijn meer")]
        block, _ = _ctx(notes=notes)
        assert "actieve klacht rond knie" not in block["prompt_block"].lower()

    def test_15_geen_klacht_evidence_geen_claim(self):
        block, _ = _ctx(notes=[])
        assert "klacht" not in block["prompt_block"].lower()   # geen harde uitspraak zonder evidence

    def test_16_coachperspectief_zonder_diagnose(self):
        block, _ = _ctx(notes=[_note(3, "pijn in de knie")])
        pb = block["prompt_block"].lower()
        assert "coachperspectief" in pb and "geen diagnose" in pb
        assert "diagnose:" not in pb                           # geeft geen diagnose

    def test_17_goed_is_goed_lichte_klacht_geen_zware_waarschuwing(self):
        block, _ = _ctx(notes=[_note(15, "pijn in de knie")])  # 1x recent → mild
        pb = block["prompt_block"].lower()
        assert "recent gemelde klacht" in pb
        assert "professionele beoordeling" not in pb           # geen escalatie bij lichte melding
        assert "nog geen reden tot aanpassing" in pb

    def test_18_terugkerend_krijgt_concreter_advies(self):
        notes = [_note(3, "pijn in de knie"), _note(25, "knie doet pijn")]
        block, _ = _ctx(notes=notes)
        pb = block["prompt_block"].lower()
        assert "terugkerende klacht" in pb
        assert "concreter opvolgadvies" in pb and "professionele beoordeling" in pb


# ════════════════════════════════════════════════════════════════════════════
# G — conversation parity onaangetast; beide generators delen de rijkere context
# ════════════════════════════════════════════════════════════════════════════
class TestConversationParity:
    def test_19_20_dispatch_onveranderd(self):
        import feedback_core as FC
        assert FC.feedback_mode([]) == FC.INITIAL_ANALYSIS
        thread = [{"van": "coach", "tekst": "wat speelt er?"}, {"van": "atleet", "tekst": "moe"}]
        assert FC.feedback_mode(thread) == FC.FOLLOW_UP_REPLY

    def test_21_22_beide_generators_delen_context(self):
        src = open(os.path.join(_ROOT, "ai_feedback.py")).read()
        # event/complaint-context zit in brein_context → gedeelde _build_workout_context
        assert src.count("_build_workout_context(") >= 2
        assert "brein_context" in src


# ════════════════════════════════════════════════════════════════════════════
# K — production-equivalent acceptance
# ════════════════════════════════════════════════════════════════════════════
class TestAcceptance:
    def test_scenario1_race_over_2_dagen(self):
        # vandaag donderdag 20 aug, race zaterdag 22 aug
        block, st = _ctx({"doel": "halve marathon", "wedstrijddatum": "2026-08-22"})
        assert block["event"]["status"] == "IN_N_DAYS" and block["event"]["days"] == 2
        assert "over 2 dagen" in block["prompt_block"]
        assert "morgen" not in block["prompt_block"]
        # dezelfde race-truth zit ook in AthleteState (voor Schema/Dossier)
        assert any(e.key == "goal.race" and e.value == "2026-08-22" for e in st.evidence)

    def test_scenario2_recurring_knieklacht(self):
        notes = [_note(2, "pijn in de knie na training"), _note(12, "knie doet weer pijn"),
                 _note(30, "last van mijn knie")]
        block, _ = _ctx(notes=notes)
        pb = block["prompt_block"].lower()
        assert "terugkerende klacht rond knie" in pb          # RECURRING
        assert "x gemeld" in pb and "d geleden" in pb          # recency/frequentie
        assert "coachperspectief" in pb and "concreter opvolgadvies" in pb  # concreet, niet enkel "in de gaten houden"
        assert "geen diagnose" in pb                           # niet diagnostisch
