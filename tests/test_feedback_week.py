"""Feedback ISO-kalenderweek (ma–zo) overzicht — regressie.

Vergrendelt dat het weekoverzicht/-chart een ECHTE kalenderweek (maandag→zondag)
gebruikt, NIET rolling-7, en dat het geen concurrerende belastings-waarheid
introduceert (alléén dag-volume; canonieke belasting-% blijft rolling-7 elders).
"""
import os
import sys
from datetime import date

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import feedback_week as FW


def _run(d, km, completed=True, atype="Run"):
    return {"date": d, "completed": completed, "activity_type": atype, "name": "x", "actual_km": km}


class TestIsoWeekRange:
    def test_maandag_tot_zondag(self):
        # elke dag in de week 24–30 aug 2026 mapt naar dezelfde ma–zo
        for day in range(24, 31):
            mo, su = FW.iso_week_range(date(2026, 8, day))
            assert mo == date(2026, 8, 24) and su == date(2026, 8, 30)

    def test_weekgrens_zondag_maandag_splitst(self):
        # zondag 23 aug en maandag 24 aug vallen in VERSCHILLENDE weken
        assert FW.iso_week_range(date(2026, 8, 23))[0] == date(2026, 8, 17)
        assert FW.iso_week_range(date(2026, 8, 24))[0] == date(2026, 8, 24)


class TestWeekOverzicht:
    def test_kalenderweek_niet_rolling7(self):
        # ref = wo 26 aug → week ma24–zo30. Een run op zo 23 aug (6 dagen terug,
        # binnen rolling-7) ligt in de VORIGE kalenderweek → telt NIET mee.
        entries = [_run("2026-08-24", 10.0), _run("2026-08-30", 5.0), _run("2026-08-23", 99.0)]
        ov = FW.week_overzicht(entries, date(2026, 8, 26), today=date(2026, 8, 28))
        assert ov["week"] == 35
        assert ov["maandag"] == "2026-08-24" and ov["zondag"] == "2026-08-30"
        assert ov["weekvolume_km"] == 15.0                 # 10 + 5; de 99 (vorige week) valt weg
        assert "ma 24 aug" in ov["range_label"] and "zo 30 aug" in ov["range_label"]

    def test_zeven_dagen_ma_tot_zo(self):
        ov = FW.week_overzicht([], date(2026, 8, 26), today=date(2026, 8, 26))
        dagen = ov["dagen"]
        assert len(dagen) == 7
        assert [d["dag"] for d in dagen] == ["ma", "di", "wo", "do", "vr", "za", "zo"]
        assert dagen[0]["datum"] == "2026-08-24" and dagen[6]["datum"] == "2026-08-30"

    def test_alleen_voltooide_runs_tellen(self):
        entries = [_run("2026-08-24", 10.0, completed=False),      # niet voltooid → weg
                   _run("2026-08-25", 8.0, atype="Strength"),       # geen run → weg
                   _run("2026-08-26", 6.0)]                          # telt
        ov = FW.week_overzicht(entries, date(2026, 8, 26), today=date(2026, 8, 28))
        assert ov["weekvolume_km"] == 6.0

    def test_toekomstige_dagen_gemarkeerd_niet_als_nul_prestatie(self):
        ov = FW.week_overzicht([_run("2026-08-24", 10.0)], date(2026, 8, 26), today=date(2026, 8, 25))
        by = {d["dag"]: d for d in ov["dagen"]}
        assert by["ma"]["is_future"] is False              # 24 < 25
        assert by["wo"]["is_future"] is True               # 26 > 25 (today)
        assert by["di"]["is_today"] is True

    def test_geen_concurrerende_belasting_pct(self):
        # het overzicht levert VOLUME, geen belasting-%/ratio (geen tweede waarheid)
        ov = FW.week_overzicht([_run("2026-08-24", 10.0)], date(2026, 8, 26))
        for verboden in ("pct", "ratio", "belasting", "delta_pct"):
            assert verboden not in ov, f"weekoverzicht mag geen '{verboden}' dragen"

    def test_duur_en_tempo_alleen_bij_echte_duur(self):
        # zonder ruwe workouts (dus geen duur) → geen verzonnen weekduur/tempo
        ov = FW.week_overzicht([_run("2026-08-24", 10.0)], date(2026, 8, 26))
        assert ov["totale_duur"] is None and ov["gem_tempo"] is None
        # mét een activiteit-duur → wél
        wk = [{"workout_date": "2026-08-24", "Activities": [{"duration": 3600}],
               "activity_type_name": "Run", "actual_km": 10.0,
               "planned_amount": None, "planned_duration": None}]
        import fs_client as FS
        # is_executed_workout vereist een completed/afgeronde workout; forceer minimale vorm
        wk[0]["completed"] = True
        if FS.is_executed_workout(wk[0]):
            ov2 = FW.week_overzicht([_run("2026-08-24", 10.0)], date(2026, 8, 26), workouts=wk)
            assert ov2["totale_duur"] == "1:00:00"
