"""Run-only plan-uitvoeringsafwijkingen — gemiste geplande run + extra ongeplande run.

PRODUCTREGEL: dit zijn coachrelevante feiten ONAFHANKELIJK van atleetcommentaar, maar
alleen als het feit betrouwbaar is en alleen voor HARDLOPEN.

BEWEZEN OORZAKEN VAN DE ONZICHTBAARHEID (zie de delivery-report):
  1. Feedback-queue: `is_skipped` (verleden, niet gedaan, geen input) en `is_data_only`
     (uitgevoerd, ongepland, geen input) komen in `fs_client.get_workouts_needing_feedback`
     alleen door de pre-filter met `include_data_only=True` — en de PWA-queue gebruikt de
     default False. De `include_unplanned_reactions`-probe laat een ongeplande run wél in
     fase 2, maar de comment-filter eist dan een ECHTE atleet-comment.
  2. Longitudinaal: er bestond geen gemiste-sessie-concept. Een gemiste run verdween
     anoniem in het 8-weekse `training.compliance`-percentage en verscheen bovendien
     misleidend als `training.distance_deviation` van -100% ('veel korter gelopen' i.p.v.
     'niet gelopen'). Een ongeplande run leverde helemaal geen per-sessie-evidence:
     `distance_deviation` geeft None zonder `planned_km`.

INSERTIEPUNT: `brain.derive.all()` op de run-only log, volgens de BESTAANDE per-workout
conventie `training.distance_deviation.<workout_key>`. Geen nieuwe store, geen tweede
engine, geen matching tussen plan en uitvoering (FinalSurge draagt beide in één record).
"""
import os
import subprocess
import sys
from datetime import date, timedelta

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_ROOT, os.path.join(_ROOT, "pwa")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dossier_cockpit as _dc                  # noqa: E402
from brain import derive as _derive            # noqa: E402
from brain import projections as _proj         # noqa: E402

TODAY = date(2026, 9, 6)


def _entry(dagen, **kw):
    """Eén trainingslog-regel in de vorm van `fs_client.get_training_log`."""
    e = {"date": (TODAY + timedelta(days=dagen)).isoformat(),
         "workout_key": f"w{dagen}", "name": "Duurloop", "description": "",
         "activity_type": "Hardlopen", "planned_km": None, "planned_min": None,
         "actual_km": 0.0, "actual_min": None, "completed": False, "is_race": False,
         "post_notes": "", "felt": None, "effort": None}
    e.update(kw)
    return e


def _evs(entries, today=TODAY):
    return _derive.all({"training_log": entries}, "u1", today, [])


def _keys(entries, today=TODAY):
    """Alleen de PER-SESSIE events; het aggregaat heeft zijn eigen tests."""
    return [e.key for e in _evs(entries, today)
            if e.key.startswith(("training.run_missed.", "training.run_unplanned."))]


class _St:
    athlete_key, naam, overall = "u1", "Test", "ATTENTION"

    def __init__(self, evs):
        self.evidence, self.conflicts, self.source_gaps = evs, [], []

    def get(self, cid):
        return next((e for e in self.evidence if e.id == cid), None)


# ══ T1/T2 — gemiste geplande run, nooit de toekomst ══════════════════════════
class TestGemisteRun:
    def test_t1_verleden_gepland_niet_gedaan_zonder_commentaar(self):
        evs = _evs([_entry(-3, planned_km=12.0)])
        mis = [e for e in evs if e.key.startswith("training.run_missed.")]
        assert len(mis) == 1
        e = mis[0]
        assert e.value == "missed"
        assert e.observed_at == (TODAY - timedelta(days=3)).isoformat()
        assert e.workout_key == "w-3"                       # per-workout identiteit
        assert e.detail["planned_km"] == 12.0 and e.detail["naam"] == "Duurloop"
        assert e.detail["actual_km"] is None                # niets uitgevoerd → niets claimen
        assert e.provenance == ["fs.training_log"]          # provenance/bron

    def test_gepland_op_duur_of_beschrijving_telt_ook(self):
        assert _keys([_entry(-2, planned_min=45)]) == ["training.run_missed.w-2"]
        assert _keys([_entry(-2, description="5x1000m Z4")]) == ["training.run_missed.w-2"]

    def test_t2_toekomst_is_nooit_gemist(self):
        assert _keys([_entry(+1, planned_km=10.0)]) == []
        assert _keys([_entry(+7, planned_km=10.0)]) == []

    def test_vandaag_is_nooit_gemist(self):
        """De dag loopt nog — een niet-uitgevoerde geplande run van vandaag is geen feit."""
        assert _keys([_entry(0, planned_km=10.0)]) == []

    def test_uitgevoerde_geplande_run_is_niet_gemist(self):
        assert _keys([_entry(-3, planned_km=10.0, completed=True, actual_km=10.0)]) == []

    def test_race_valt_buiten_scope(self):
        assert _keys([_entry(-3, planned_km=21.1, is_race=True)]) == []


# ══ T3 — extra ongeplande run ════════════════════════════════════════════════
class TestExtraRun:
    def test_t3_uitgevoerd_zonder_planning_zonder_commentaar(self):
        evs = _evs([_entry(-1, completed=True, actual_km=7.4, name="Losse duurloop")])
        ex = [e for e in evs if e.key.startswith("training.run_unplanned.")]
        assert len(ex) == 1
        assert ex[0].value == "unplanned"
        assert ex[0].detail["actual_km"] == 7.4 and ex[0].detail["naam"] == "Losse duurloop"
        assert ex[0].workout_key == "w-1"

    def test_met_planning_is_niet_extra(self):
        assert _keys([_entry(-1, planned_km=8.0, completed=True, actual_km=8.0)]) == []
        assert _keys([_entry(-1, description="rustige duurloop", completed=True, actual_km=8.0)]) == []

    def test_niet_uitgevoerd_en_ongepland_levert_niets(self):
        """Geen plan én geen uitvoering = geen feit om te melden."""
        assert _keys([_entry(-1)]) == []


# ══ T4 — uitsluitend hardlopen ═══════════════════════════════════════════════
class TestAlleenHardlopen:
    @pytest.mark.parametrize("sport", ["Fietsen", "Cycling", "Wandelen", "Walking", "Hiking",
                                       "Krachttraining", "Strength", "Zwemmen", "HYROX",
                                       "Rust", "Recovery", "Yoga"])
    def test_t4_andere_sporten_leveren_geen_afwijking(self, sport):
        assert _keys([_entry(-3, activity_type=sport, planned_km=20.0)]) == []
        assert _keys([_entry(-1, activity_type=sport, completed=True, actual_km=20.0)]) == []

    def test_onbekende_sport_levert_geen_claim(self):
        """`dossier._is_run` neemt een leeg type bewust mee voor VOLUME; voor een uitspraak
        over een afwijking is dat te ruim — bij twijfel claimen we niets."""
        assert _keys([_entry(-3, activity_type="", planned_km=10.0)]) == []
        assert _keys([_entry(-1, activity_type="", completed=True, actual_km=8.0)]) == []
        assert _derive._expliciete_run({"activity_type": "Hardlopen"}) is True
        assert _derive._expliciete_run({"activity_type": "Trailrunning"}) is True
        assert _derive._expliciete_run({"activity_type": ""}) is False

    def test_gemengde_dag_houdt_alleen_de_run(self):
        evs = _keys([_entry(-3, planned_km=12.0),
                     _entry(-3, workout_key="c1", activity_type="Fietsen", planned_km=60.0),
                     _entry(-3, workout_key="k1", activity_type="Krachttraining",
                            completed=True, description="full body")])
        assert evs == ["training.run_missed.w-3"]


# ══ T5/T6 — commentaar is niet nodig en dupliceert niet ══════════════════════
class TestCommentaarOnafhankelijk:
    def test_t5_zichtbaar_zonder_commentaar(self):
        zonder = _keys([_entry(-3, planned_km=12.0), _entry(-1, completed=True, actual_km=7.0)])
        assert zonder == ["training.run_missed.w-3", "training.run_unplanned.w-1"]

    def test_t5b_met_commentaar_exact_dezelfde_events(self):
        met = _keys([_entry(-3, planned_km=12.0, post_notes="Kon niet, werk liep uit.", felt=3),
                     _entry(-1, completed=True, actual_km=7.0, post_notes="Even los gelopen.")])
        assert met == ["training.run_missed.w-3", "training.run_unplanned.w-1"]

    def test_t6_geen_tweede_event_voor_dezelfde_training(self):
        """Een gemiste run heeft planned_km met actual 0 en zou anders ÓÓK als
        `distance_deviation` van -100% verschijnen: twee events, één training."""
        evs = _evs([_entry(-3, planned_km=12.0)])
        per_workout = [e.key for e in evs if e.key.endswith(".w-3")]
        assert per_workout == ["training.run_missed.w-3"]
        assert not [e for e in evs if e.key.startswith("training.distance_deviation.")]

    def test_normale_afwijking_blijft_bestaan(self):
        """Een uitgevoerde run die materieel korter was, blijft gewoon een afstandsafwijking."""
        evs = _evs([_entry(-3, planned_km=12.0, completed=True, actual_km=8.0)])
        assert [e.key for e in evs if e.key.endswith(".w-3")] == ["training.distance_deviation.w-3"]


# ══ T7/T8 — stabiele identiteit, geen duplicaten bij herbouw ═════════════════
class TestIdentiteit:
    def test_t7_herhaalde_build_levert_dezelfde_ids(self):
        log = [_entry(-3, planned_km=12.0), _entry(-1, completed=True, actual_km=7.0)]
        pre = ("training.run_missed.", "training.run_unplanned.")
        a = {e.id for e in _evs(log) if e.key.startswith(pre)}
        b = {e.id for e in _evs(log) if e.key.startswith(pre)}
        assert a == b and len(a) == 2

    def test_t8_identiteit_hangt_aan_workout_en_datum(self):
        evs = _evs([_entry(-3, planned_km=12.0)])
        e = next(x for x in evs if x.key.startswith("training.run_missed."))
        assert e.key.endswith("w-3") and e.id
        # zelfde training, andere naam/nota → zelfde identiteit (geen duplicaat)
        e2 = next(x for x in _evs([_entry(-3, planned_km=12.0, name="Andere titel",
                                          post_notes="x")])
                  if x.key.startswith("training.run_missed."))
        assert e2.id == e.id

    def test_zonder_workout_key_valt_terug_op_de_datum(self):
        assert _keys([_entry(-3, workout_key="", planned_km=10.0)]) == \
            [f"training.run_missed.{(TODAY - timedelta(days=3)).isoformat()}"]


# ══ T9 — Dossier ═════════════════════════════════════════════════════════════
class TestDossier:
    def _dump(self, entries):
        return _proj._dump(_evs(entries))

    def test_t9_beide_soorten_staan_in_de_belastbaarheid_kaart(self):
        dump = self._dump([_entry(-3, planned_km=12.0),
                           _entry(-1, completed=True, actual_km=7.4, name="Losse duurloop")])
        kaart = next(c for c in _dc._domains(dump, set()) if c["key"] == "belastbaarheid")
        labels = {r["label"]: r["value"] for r in kaart["regels"]}
        assert "Geplande hardlooptraining gemist" in labels
        assert "Extra hardlooptraining (niet gepland)" in labels
        assert "12.0 km" in labels["Geplande hardlooptraining gemist"]
        assert "7.4 km" in labels["Extra hardlooptraining (niet gepland)"]

    def test_nooit_de_ruwe_enum_als_coachtekst(self):
        dump = self._dump([_entry(-3, planned_km=12.0)])
        kaart = next(c for c in _dc._domains(dump, set()) if c["key"] == "belastbaarheid")
        for r in kaart["regels"]:
            assert r["value"] not in ("missed", "unplanned")

    def test_dossier_projectie_draagt_alle_evidence(self):
        keys = [e["key"] for e in _proj._dump(_evs([_entry(-3, planned_km=12.0)]))]
        assert "training.run_missed.w-3" in keys

    def test_herhaald_missen_wordt_een_aandachtskaart(self):
        evs = _evs([_entry(-3, planned_km=12.0), _entry(-5, planned_km=10.0)])
        kaarten = _dc._attention(_St(evs))
        rm = [c for c in kaarten if c["kind"] == "run_missed"]
        assert rm and "2 geplande hardlooptrainingen gemist" == rm[0]["title"]
        assert rm[0]["opens"] == "belastbaarheid"

    def test_een_keer_missen_blijft_informatief(self):
        """Geen alarm bij één gemiste run — hij staat wél in de Belastbaarheid-kaart."""
        evs = _evs([_entry(-3, planned_km=12.0)])
        assert not [c for c in _dc._attention(_St(evs)) if c["kind"] == "run_missed"]
        dump = _proj._dump(evs)
        kaart = next(c for c in _dc._domains(dump, set()) if c["key"] == "belastbaarheid")
        assert any(r["label"] == "Geplande hardlooptraining gemist" for r in kaart["regels"])

    def test_extra_run_veroorzaakt_nooit_alarm(self):
        evs = _evs([_entry(-1, completed=True, actual_km=7.0),
                    _entry(-2, workout_key="x2", completed=True, actual_km=6.0)])
        assert not [c for c in _dc._attention(_St(evs))
                    if c["kind"] in ("run_missed", "load_signal")]


# ══ T10/T11 — Feedback ═══════════════════════════════════════════════════════
class TestFeedback:
    def test_t10_zichtbaar_zonder_commentaar_bij_die_sessie(self):
        evs = _evs([_entry(-3, planned_km=12.0), _entry(-5, planned_km=10.0),
                    _entry(-1, completed=True, actual_km=7.0)])
        fb = _proj.for_feedback(_St(evs), workout_key="w-3")
        keys = [e["key"] for e in fb["evidence"]]
        assert "training.run_missed.w-3" in keys
        assert "training.run_missed.w-5" not in keys      # per-workout gefilterd
        assert "training.run_missed_recent" in keys       # longitudinale context

    def test_extra_run_bij_die_sessie(self):
        evs = _evs([_entry(-1, completed=True, actual_km=7.0)])
        keys = [e["key"] for e in _proj.for_feedback(_St(evs), workout_key="w-1")["evidence"]]
        assert "training.run_unplanned.w-1" in keys

    def test_t11_geen_nieuwe_ranking_of_queue_wijziging(self):
        """De queue-inclusie en -volgorde blijven ongemoeid; alleen de context ziet meer."""
        fsc = open(os.path.join(_ROOT, "fs_client.py")).read()
        assert "def get_workouts_needing_feedback(" in fsc
        assert "include_data_only: bool = False" in fsc          # default onveranderd
        fc = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        assert "include_planned_no_notes=True" in fc and "include_data_only" not in fc
        diff = subprocess.run(["git", "diff", "--name-only", "e4f37f1", "--"],
                              cwd=_ROOT, capture_output=True, text=True).stdout.split()
        assert "fs_client.py" not in diff and "pwa/feedback_core.py" not in diff


# ══ T12 — geen speculatieve matching ═════════════════════════════════════════
class TestGeenSpeculatieveMatching:
    def test_t12_er_wordt_niets_gekoppeld(self):
        """Elk feit komt uit ÉÉN logregel (FinalSurge draagt plan+uitvoering samen).
        Er bestaat dus geen koppel-heuristiek op afstand/titel/tijd."""
        src = open(os.path.join(_ROOT, "pwa", "brain", "derive.py")).read()
        blok = src[src.index("def _plan_afwijking("):src.index("def all(")]
        for verboden in ("abs(", "similar", "match", "dichtst", "candidate", "zip("):
            assert verboden not in blok, f"koppel-heuristiek gevonden: {verboden}"

    def test_losse_run_en_gemiste_run_op_dezelfde_dag_blijven_apart(self):
        """Geen 'die extra run zal die gemiste wel vervangen'-aanname."""
        keys = _keys([_entry(-3, planned_km=12.0),
                      _entry(-3, workout_key="extra", completed=True, actual_km=7.0)])
        assert keys == ["training.run_missed.w-3", "training.run_unplanned.extra"]


# ══ T13/T14/T15 — locks ══════════════════════════════════════════════════════
class TestLocks:
    def _diff(self):
        return subprocess.run(["git", "diff", "--name-only", "e4f37f1", "--"],
                              cwd=_ROOT, capture_output=True, text=True).stdout.split()

    def test_t13_t14_home_teampuls_workspace_ongemoeid(self):
        diff = self._diff()
        for verboden in ("pwa/home_core.py", "pwa/teampuls_core.py", "belasting.py",
                         "pwa/coach_read.py", "pwa/static/app.js", "pwa/static/styles.css",
                         "pwa/static/design-system.css", "pwa/static/index.html",
                         "pwa/static/sw.js"):
            assert verboden not in diff, f"gelockt gebied aangeraakt: {verboden}"

    def test_t15_feedback_generatie_en_copy_ongemoeid(self):
        diff = self._diff()
        verboden = {"ai_feedback.py", "feedback_atoms.py", "feedback_copy.py",
                    "feedback_facts.py", "feedback_obligations.py", "metric_authority.py",
                    "pwa/feedback_core.py", "pwa/feedback_week.py", "fs_client.py"}
        assert not verboden.intersection(diff)

    def test_geen_nieuwe_store_of_engine(self):
        src = open(os.path.join(_ROOT, "pwa", "brain", "derive.py")).read()
        blok = src[src.index("def _plan_afwijking("):]
        assert "save_" not in blok and "intake_store" not in blok
        assert "def get_workouts" not in blok             # geen extra FinalSurge-read

    def test_bounded_venster(self):
        """Geheugenlock: per-sessie-evidence blijft begrensd tot het recency-venster."""
        oud = [_entry(-d, workout_key=f"o{d}", planned_km=10.0) for d in range(25, 60)]
        assert _keys(oud) == []
