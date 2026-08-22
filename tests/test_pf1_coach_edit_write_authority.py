"""PF-1 — Coach-edit is de enige waarheid voor de FinalSurge-write (Class A / Finding 4).

Bewijst dat een handmatige numerieke coach-edit (planned_km/planned_min) LETTERLIJK
naar FinalSurge wordt geschreven en dat de oude AI-description die waarde nooit meer
opnieuw bepaalt — ook de WorkoutBuilder-steps mogen daarna geen tegenstrijdige
meeteenheid dragen. Ongewijzigde rijen houden exact het bewezen Builder-pad.

We toetsen op het write-pad zelf (`import_to_finalsurge`) met gemockte FS-writes en
een gemockte `generate_builder_steps` (geen AI, geen netwerk), plus het doordragen van
de `measure_edited`-vlag door `_to_write_row` en een source-guard op de frontend.

    python3 -m pytest tests/test_pf1_coach_edit_write_authority.py -q
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import schema_builder as SB


# ── Harness ──────────────────────────────────────────────────────────────────
class _Capture:
    """Vangt de FS-writes (workout + builder) en de generate_builder_steps-calls."""
    def __init__(self):
        self.workouts = []          # list of save_workout kwargs
        self.builders = []          # list of save_workout_builder kwargs
        self.gen_calls = []         # descriptions waarvoor de Builder-AI is aangeroepen


def _install(monkeypatch, cap, steps_for=None):
    """steps_for(desc, op_tijd) -> target_options (of []); default leidt km/min uit de tekst."""
    import time
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)

    def _fake_gen(workout_name, description, zone_type="pace", activity_type="Run", op_tijd=False):
        cap.gen_calls.append(description)
        if steps_for is not None:
            return steps_for(description, op_tijd)
        # Default-stub: description-driven (zoals de echte builder-AI) — leidt de eenheid
        # + het getal LETTERLIJK uit de beschrijving af, onafhankelijk van op_tijd. Zo
        # ontstaat een echte km/tijd-mismatch als de coach van eenheid wisselde.
        import re
        d = description.lower()
        mkm = re.search(r"([\d.]+)\s*km", d)
        mmin = re.search(r"([\d.]+)\s*min", d)
        if mkm:
            return [{"steps": [{"durationType": "DISTANCE", "durationDist": float(mkm.group(1))}]}]
        if mmin:
            val = float(mmin.group(1)); mm = int(val); ss = int(round((val - mm) * 60))
            return [{"steps": [{"durationType": "TIME", "duration": f"{mm}:{ss:02d}"}]}]
        return []

    monkeypatch.setattr(SB, "generate_builder_steps", _fake_gen)
    # import_to_finalsurge doet intern `import fs_client` → patch de echte module.
    import fs_client
    monkeypatch.setattr(fs_client, "save_workout",
                        lambda **kw: cap.workouts.append(kw) or {"new_workout_key": "WK1"})
    monkeypatch.setattr(fs_client, "save_workout_builder",
                        lambda **kw: cap.builders.append(kw) or {"success": True})


def _row(**over):
    r = {"date": "2026-09-01", "name": "Duurloop", "description": "40 min rustig",
         "activity_type": "Run", "planned_km": None, "planned_min": None, "measure_edited": False}
    r.update(over)
    return r


def _write(monkeypatch, row, op_tijd=False, steps_for=None):
    cap = _Capture()
    _install(monkeypatch, cap, steps_for=steps_for)
    ok, errs, berrs = SB.import_to_finalsurge(
        athlete_key="A", workouts=[row], zone_type="pace", fill_builder=True, op_tijd=op_tijd)
    return cap, ok, errs, berrs


# ── 1. Ongewijzigde rij houdt het bewezen Builder-gedrag ─────────────────────
def test_1_unedited_tijd_behoudt_builder(monkeypatch):
    row = _row(description="40 min rustig", planned_min=40, measure_edited=False)
    cap, ok, errs, berrs = _write(monkeypatch, row, op_tijd=True)
    assert ok == 1 and not errs and not berrs
    assert cap.gen_calls == ["40 min rustig"]              # Builder-AI is aangeroepen
    assert len(cap.builders) == 1                          # structured steps geschreven
    assert cap.workouts[0]["planned_duration_min"] == 40   # builder-afgeleide tijd


def test_9_unedited_afstand_geen_regressie(monkeypatch):
    row = _row(name="Duurloop", description="8 km rustig", planned_km=8, measure_edited=False)
    cap, ok, errs, berrs = _write(monkeypatch, row, op_tijd=False)
    assert ok == 1 and not berrs
    assert len(cap.builders) == 1
    assert cap.workouts[0]["planned_distance_km"] == 8     # builder-afgeleide afstand
    assert cap.workouts[0]["planned_duration_min"] is None


# ── 2/3/8. Coach edit 40 min → 8 km: coachwaarde wint, geen conflict ─────────
def test_2_edit_naar_km_schrijft_exacte_coachwaarde(monkeypatch):
    row = _row(description="40 min rustig", planned_km=8, planned_min=40, measure_edited=True)
    cap, ok, errs, berrs = _write(monkeypatch, row, op_tijd=False)
    assert ok == 1 and not errs and not berrs
    assert cap.workouts[0]["planned_distance_km"] == 8     # exact de coach-km
    assert cap.workouts[0]["planned_duration_min"] is None


def test_3_edit_naar_km_geen_conflicterende_builder(monkeypatch):
    row = _row(description="40 min rustig", planned_km=8, planned_min=40, measure_edited=True)
    cap, ok, errs, berrs = _write(monkeypatch, row, op_tijd=False)
    assert cap.gen_calls == []                             # GEEN AI-call voor edited rij
    assert cap.builders == []                              # geen structured steps → geen 40-min-truth
    assert not berrs                                       # bewuste degrade is geen fout


def test_8_coachwaarde_wint_altijd_van_description(monkeypatch):
    # description zou 8 km afleiden; coach zette 5 km → 5 moet naar FS, niet 8.
    row = _row(description="8 km opbouw", planned_km=5, measure_edited=True)
    cap, *_ = _write(monkeypatch, row, op_tijd=False)
    assert cap.workouts[0]["planned_distance_km"] == 5
    assert cap.builders == []


# ── 4. Omgekeerd: 8 km → 50 min (tijdsschema) ────────────────────────────────
def test_4_edit_naar_min_schrijft_exacte_coachwaarde(monkeypatch):
    row = _row(description="8 km rustig", planned_km=8, planned_min=50, measure_edited=True)
    cap, ok, errs, berrs = _write(monkeypatch, row, op_tijd=True)
    assert ok == 1 and not berrs
    assert cap.workouts[0]["planned_duration_min"] == 50   # exact de coach-minuten
    assert cap.workouts[0]["planned_distance_km"] is None  # tijdsschema
    assert cap.gen_calls == [] and cap.builders == []


# ── 5. Decimalen blijven behouden (geen stille round naar hele km) ───────────
def test_5_decimale_edit_niet_afgerond(monkeypatch):
    row = _row(description="40 min rustig", planned_km=8.5, measure_edited=True)
    cap, *_ = _write(monkeypatch, row, op_tijd=False)
    assert cap.workouts[0]["planned_distance_km"] == 8.5   # niet 8 en niet 9


def test_5b_decimale_edit_bereikt_fs_als_2dp(monkeypatch):
    # save_workout (echt, niet gemockt hier) rondt op 2 decimalen — FS ondersteunt dat.
    import fs_client
    captured = {}
    monkeypatch.setattr(fs_client, "_post", lambda *a, **k: captured.update(payload=a[1]) or {"success": True})
    fs_client.save_workout(user_key="A", workout_date="2026-09-01", name="X",
                           planned_distance_km=8.5)
    assert captured["payload"]["Activity"]["planned_amount"] == 8.5


# ── 6. measure_edited overleeft frontend → API → publish → write row ─────────
def test_6_to_write_row_draagt_measure_edited_door(monkeypatch):
    import schema_core
    assert schema_core._to_write_row({"date": "d", "name": "n", "planned_km": 8,
                                      "measure_edited": True})["measure_edited"] is True
    assert schema_core._to_write_row({"date": "d", "name": "n"})["measure_edited"] is False


def test_6b_frontend_stuurt_measure_edited():
    src = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
    body = src.split("function sbRowsPayload", 1)[1].split("return out", 1)[0]
    assert "measure_edited:" in body                       # in de payload
    assert "sbMeasureEdited" in src                        # berekend tegen _orig
    calc = src.split("function sbMeasureEdited", 1)[1].split("\nfunction ", 1)[0]
    assert "_orig" in calc and "planned_km" in calc and "planned_min" in calc


# ── 7. Naam/beschrijving blijven behouden ────────────────────────────────────
def test_7_naam_en_description_behouden(monkeypatch):
    row = _row(name="Rustige duurloop", description="40 min rustig", planned_km=8, measure_edited=True)
    cap, *_ = _write(monkeypatch, row, op_tijd=False)
    assert cap.workouts[0]["name"] == "Rustige duurloop"
    assert cap.workouts[0]["description"] == "40 min rustig"   # tekst blijft als context


# ── Invariant — één workout draagt nooit twee tegenstrijdige meetwaarheden ───
def _measure_conflict(wkw, builders):
    """True als de top-level meetwaarde botst met wat de builder-steps optellen."""
    b = next((x for x in builders), None)
    if not b:
        return False                                       # geen steps → per definitie coherent
    steps = b.get("target_options") or []
    bkm = SB._calc_builder_distance_km(steps)
    bmin = SB._calc_builder_duration_min(steps)
    km, mn = wkw.get("planned_distance_km"), wkw.get("planned_duration_min")
    if km is not None and bkm is not None and abs(float(km) - float(bkm)) > 0.05:
        return True
    if mn is not None and bmin is not None and abs(float(mn) - float(bmin)) > 0.5:
        return True
    return False


def test_invariant_geen_dubbele_conflicterende_truth(monkeypatch):
    cases = [
        (_row(description="40 min rustig", planned_min=40, measure_edited=False), True),   # unedited tijd
        (_row(description="8 km rustig", planned_km=8, measure_edited=False), False),      # unedited afstand
        (_row(description="40 min rustig", planned_km=8, planned_min=40, measure_edited=True), False),  # edit→km
        (_row(description="8 km rustig", planned_km=8, planned_min=50, measure_edited=True), True),     # edit→min
    ]
    for row, op_tijd in cases:
        cap, *_ = _write(monkeypatch, row, op_tijd=op_tijd)
        assert not _measure_conflict(cap.workouts[0], cap.builders), row


# ── Backward-compat vangnet — stale client (geen measure_edited-vlag) ────────
# De backend detecteert de coach-edit zelf door de ingediende waarde te vergelijken
# met wat de al-gegenereerde builder-steps opleveren (geen extra AI-call).
def _stale_row(**over):
    r = _row(**over)
    r.pop("measure_edited", None)                          # stale v81-client stuurt de vlag niet
    return r


def test_bc1_stale_client_min_naar_km(monkeypatch):
    # description zegt tijd, coach zette afstand, vlag ontbreekt → 8 km wint, geen Builder.
    row = _stale_row(description="40 min rustig", planned_km=8, planned_min=40)
    cap, ok, errs, berrs = _write(monkeypatch, row, op_tijd=False)
    assert ok == 1 and not errs and not berrs
    assert cap.gen_calls == ["40 min rustig"]             # exact één AI-call (als een gewone rij)
    assert cap.builders == []                             # geen tegenstrijdige steps
    assert cap.workouts[0]["planned_distance_km"] == 8
    assert cap.workouts[0]["planned_duration_min"] is None


def test_bc2_stale_client_km_naar_min(monkeypatch):
    row = _stale_row(description="8 km rustig", planned_km=8, planned_min=50)
    cap, ok, errs, berrs = _write(monkeypatch, row, op_tijd=True)
    assert ok == 1 and not berrs
    assert cap.builders == []
    assert cap.workouts[0]["planned_duration_min"] == 50
    assert cap.workouts[0]["planned_distance_km"] is None


def test_bc3_coherent_zonder_vlag_behoudt_builder(monkeypatch):
    # submitted == builder-derived → geen edit → bestaand structured Builder-pad blijft.
    row = _stale_row(description="8 km rustig", planned_km=8)
    cap, ok, errs, berrs = _write(monkeypatch, row, op_tijd=False)
    assert ok == 1 and not berrs
    assert len(cap.builders) == 1                          # steps blijven geschreven
    assert cap.workouts[0]["planned_distance_km"] == 8


def test_bc4_kleine_rounding_geen_valse_edit(monkeypatch):
    # 8.05 vs builder 8 → binnen tolerantie → geen edit → Builder-pad blijft.
    row = _stale_row(description="8 km rustig", planned_km=8.05)
    cap, *_ = _write(monkeypatch, row, op_tijd=False)
    assert len(cap.builders) == 1                          # niet als edit behandeld
    assert cap.workouts[0]["planned_distance_km"] == 8     # coherent → builder-waarde


def test_bc5_decimale_afwijking_zonder_vlag_coach_wint(monkeypatch):
    # 8.5 vs builder 8 → buiten tolerantie → coachwaarde wint, geen Builder, geen round.
    row = _stale_row(description="8 km rustig", planned_km=8.5)
    cap, *_ = _write(monkeypatch, row, op_tijd=False)
    assert cap.builders == []
    assert cap.workouts[0]["planned_distance_km"] == 8.5   # exact, niet afgerond naar 8


def test_bc6_expliciete_vlag_blijft_zonder_ai_call(monkeypatch):
    # measure_edited=True kortsluit de Builder-AI volledig (anders dan het server-vangnet).
    row = _row(description="40 min rustig", planned_km=8, measure_edited=True)
    cap, *_ = _write(monkeypatch, row, op_tijd=False)
    assert cap.gen_calls == []                             # GEEN AI-call
    assert cap.builders == []
    assert cap.workouts[0]["planned_distance_km"] == 8


# ── 6/§6. Production-equivalent: inspecteer de EXACTE FinalSurge-payloads ────
def _capture_posts(monkeypatch):
    """Vang elke echte FS _post (endpoint, payload) — bewijst wat FinalSurge ontvangt."""
    import fs_client, time
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
    posts = []
    monkeypatch.setattr(fs_client, "_post",
                        lambda endpoint, payload, params=None: posts.append((endpoint, payload, params))
                        or {"success": True, "new_workout_key": "WK1"})
    return posts


def test_acceptance_min_naar_km_payload(monkeypatch):
    posts = _capture_posts(monkeypatch)
    row = _row(name="Duurloop", description="40 min rustig", planned_km=8, planned_min=40, measure_edited=True)
    SB.import_to_finalsurge(athlete_key="A", workouts=[row], zone_type="pace",
                            fill_builder=True, op_tijd=False)
    endpoints = [p[0] for p in posts]
    assert endpoints == ["WorkoutSave"]                       # GEEN WorkoutBuilderSave
    act = posts[0][1]["Activity"]
    assert act["planned_amount"] == 8                         # exact coach-km + km-unit
    assert act["planned_amount_type"] == "km"
    assert act["planned_duration"] is None                    # geen tegenstrijdige 40-min-truth
    assert posts[0][1]["description"] == "40 min rustig"      # tekst blijft context


def test_acceptance_km_naar_min_payload(monkeypatch):
    posts = _capture_posts(monkeypatch)
    row = _row(name="Duurloop", description="8 km rustig", planned_km=8, planned_min=50, measure_edited=True)
    SB.import_to_finalsurge(athlete_key="A", workouts=[row], zone_type="pace",
                            fill_builder=True, op_tijd=True)
    endpoints = [p[0] for p in posts]
    assert endpoints == ["WorkoutSave"]                       # GEEN WorkoutBuilderSave
    act = posts[0][1]["Activity"]
    assert act["planned_duration"] == 50 * 60                 # exact coach-minuten (sec)
    assert act["planned_amount"] is None                      # geen tegenstrijdige 8-km-truth


# ── Meerdere rijen tegelijk: alleen de edited rij degradeert ─────────────────
def test_gemengde_batch_isoleert_de_edit(monkeypatch):
    cap = _Capture()
    _install(monkeypatch, cap)
    rows = [
        _row(date="2026-09-01", description="8 km rustig", planned_km=8, measure_edited=False),
        _row(date="2026-09-03", description="40 min rustig", planned_km=6, measure_edited=True),
    ]
    ok, errs, berrs = SB.import_to_finalsurge(
        athlete_key="A", workouts=rows, zone_type="pace", fill_builder=True, op_tijd=False)
    assert ok == 2 and not errs and not berrs
    assert len(cap.builders) == 1                          # alleen de unedited rij kreeg steps
    assert cap.gen_calls == ["8 km rustig"]                # edited rij deed geen AI-call
    assert cap.workouts[1]["planned_distance_km"] == 6     # coachwaarde exact
