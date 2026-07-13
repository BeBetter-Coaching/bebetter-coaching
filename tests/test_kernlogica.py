"""Tests op de pure kernlogica — precies de functies die eerder kapot zijn geweest.

Draaien met:  python3 -m pytest tests/ -q
Geen netwerk, geen secrets nodig: alles is pure logica.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import admin
import belasting
import dossier
import fs_client
import schema_builder


# ---------------------------------------------------------------------------
# fs_client — uitvoeringsdetectie, km-normalisatie, groep-uitsluiting
# ---------------------------------------------------------------------------

class TestIsExecutedWorkout:
    def test_planned_status_is_niet_uitgevoerd(self):
        # has_actual_data is onbetrouwbaar: true bij geplande structuurtrainingen
        w = {"workout_status_text": "Planned", "has_actual_data": True}
        assert fs_client.is_executed_workout(w) is False

    def test_done_status_is_uitgevoerd(self):
        assert fs_client.is_executed_workout({"workout_status_text": "Completed"}) is True

    def test_geen_status_maar_stats(self):
        assert fs_client.is_executed_workout({"workout_status_text": "", "has_stats": True}) is True

    def test_completion_boven_nul(self):
        assert fs_client.is_executed_workout({"workout_completion": "0.8"}) is True

    def test_corrupte_completion_valt_terug(self):
        assert fs_client.is_executed_workout({"workout_completion": "n/a"}) is False


class TestNormKm:
    def test_meters_naar_km(self):
        assert fs_client._norm_km(5000, "m") == 5.0

    def test_mijlen_naar_km(self):
        assert fs_client._norm_km(3.1, "mi") == 4.99

    def test_km_blijft_km(self):
        assert fs_client._norm_km(10, "km") == 10

    def test_onbekende_eenheid_aanname_km(self):
        assert fs_client._norm_km(8, None) == 8

    def test_corrupt_en_leeg(self):
        assert fs_client._norm_km("abc", "km") is None
        assert fs_client._norm_km(None, "km") is None


class TestGroupIsExcluded:
    def test_los_schema_varianten(self):
        assert fs_client.group_is_excluded("1. Los trainingsschema", ["los schema"]) is True
        assert fs_client.group_is_excluded("Losse schema's", ["los schema"]) is True

    def test_echte_groep_blijft(self):
        assert fs_client.group_is_excluded("Getting Better", ["los schema"]) is False

    def test_leeg(self):
        assert fs_client.group_is_excluded("", ["los schema"]) is False
        assert fs_client.group_is_excluded("Comfort", []) is False


class TestDetectRaceType:
    def test_marathon_niet_halve(self):
        assert fs_client.detect_race_type("Marathon Rotterdam") == "Marathon"

    def test_halve_marathon(self):
        assert fs_client.detect_race_type("Halve marathon Oss") == "Halve marathon"

    def test_onbekend_is_race(self):
        assert fs_client.detect_race_type("Kermisloop") == "Race"


# ---------------------------------------------------------------------------
# schema_builder — CSV-parsing en builder-berekeningen
# ---------------------------------------------------------------------------

CSV_VOORBEELD = """Date,ActivityType,WorkoutName,PlannedTimeMinutes,PlannedDistance,mi/km/m/y,WorkoutDescription
06/29/2026,Run,Duurloop,,10,km,Rustige duurloop Z2
06/30/2026,Rest,,,,,
07/01/2026,Run,Intervallen,45,,km,5x 800m Z4
kapotte datum,Run,Fout,,5,km,ongeldige rij
07/02/2026,Run,Mijlenloop,,3.1,mi,Test in mijlen
"""


class TestParseCsvText:
    def test_datum_mmddyyyy_naar_iso(self):
        rows = schema_builder.parse_csv_text(CSV_VOORBEELD)
        assert rows[0]["date"] == "2026-06-29"

    def test_rustdag_zonder_naam_overgeslagen(self):
        rows = schema_builder.parse_csv_text(CSV_VOORBEELD)
        assert all(r["activity_type"] != "Rest" for r in rows)

    def test_ongeldige_datum_overgeslagen(self):
        rows = schema_builder.parse_csv_text(CSV_VOORBEELD)
        assert all(r["name"] != "Fout" for r in rows)

    def test_mijlen_omgezet_en_afgerond(self):
        rows = schema_builder.parse_csv_text(CSV_VOORBEELD)
        mijlen = next(r for r in rows if r["name"] == "Mijlenloop")
        assert mijlen["planned_km"] == 5  # 3.1 mi = 4.99 km → afgerond 5

    def test_tijd_als_float(self):
        rows = schema_builder.parse_csv_text(CSV_VOORBEELD)
        interval = next(r for r in rows if r["name"] == "Intervallen")
        assert interval["planned_min"] == 45.0

    def test_csv_in_markdown_blok(self):
        omhuld = f"Hier je schema:\n```csv\n{CSV_VOORBEELD}```\nSucces!"
        assert len(schema_builder.parse_csv_text(omhuld)) == len(
            schema_builder.parse_csv_text(CSV_VOORBEELD))


class TestWeekdagen:
    def test_afkortingen_en_voluit(self):
        assert schema_builder._parse_weekdagen("di / zo") == [1, 6]
        assert schema_builder._parse_weekdagen("dinsdag en zondag") == [1, 6]
        assert schema_builder._parse_weekdagen("ma, wo, vr, zo") == [0, 2, 4, 6]

    def test_volgorde_en_ontdubbeling(self):
        assert schema_builder._parse_weekdagen("zondag, dinsdag, dinsdag") == [1, 6]

    def test_geen_valse_match_binnen_woord(self):
        # 'ma' mag niet matchen binnen 'maximaal'; leeg = geen dagen
        assert schema_builder._parse_weekdagen("maximaal drie keer") == []
        assert schema_builder._parse_weekdagen("") == []


class TestZoneVanWaarde:
    HR = [
        {"num": 1, "naam": "Herstel", "low": 100, "high": 130},
        {"num": 2, "naam": "Duurloop", "low": 130, "high": 150},
        {"num": 3, "naam": "Tempo", "low": 150, "high": 165},
    ]

    def test_hartslag_147_is_zone2(self):
        # dé bug: 147 bpm werd als Z1 geschreven
        assert fs_client.zone_van_waarde(self.HR, 147, is_pace=False)["num"] == 2

    def test_ondergrens_inclusief(self):
        assert fs_client.zone_van_waarde(self.HR, 130, is_pace=False)["num"] == 2

    def test_boven_alles_pakt_hoogste(self):
        assert fs_client.zone_van_waarde(self.HR, 185, is_pace=False)["num"] == 3

    def test_tempo_seconden_per_km(self):
        pace = [
            {"num": 1, "naam": "Rustig", "low": 360, "high": 720},   # 6:00-12:00
            {"num": 2, "naam": "Duur", "low": 330, "high": 360},     # 5:30-6:00
        ]
        assert fs_client.zone_van_waarde(pace, 367, is_pace=True)["num"] == 1  # 6:07
        assert fs_client.zone_van_waarde(pace, 345, is_pace=True)["num"] == 2  # 5:45

    def test_leeg_geeft_none(self):
        assert fs_client.zone_van_waarde([], 147, is_pace=False) is None
        assert fs_client.zone_van_waarde(self.HR, None, is_pace=False) is None


class TestZoneOmzetten:
    def _builder(self):
        # WU (pace_zone Z1) + repeat[interval pace_zone Z4 / wandel-herstel vaste pace]
        return [{
            "name": "Interval", "target": "pace",
            "steps": [
                {"type": "step", "target": [
                    {"targetType": "pace_zone", "zone": 1},
                    {"targetType": "open", "zone": 0}]},
                {"type": "repeat", "repeats": 5, "target": [], "data": [
                    {"type": "step", "target": [
                        {"targetType": "pace_zone", "zone": 4},
                        {"targetType": "open", "zone": 0}]},
                    {"type": "step", "name": "wandelen", "target": [
                        {"targetType": "pace", "targetLow": "10:00", "targetHigh": "12:00"},
                        {"targetType": "open", "zone": 0}]},
                ]},
            ],
        }]

    def test_tempo_naar_hartslag(self):
        opts, n = fs_client.convert_builder_target_type(self._builder(), naar="hr")
        assert n == 2  # de twee pace_zone-doelen (Z1 + Z4), niet het wandel-pacedoel
        assert opts[0]["target"] == "hr"
        # zone-nummers ongewijzigd
        assert opts[0]["steps"][0]["target"][0] == {"targetType": "hr_zone", "zone": 1}
        rep = opts[0]["steps"][1]
        assert rep["data"][0]["target"][0]["targetType"] == "hr_zone"
        assert rep["data"][0]["target"][0]["zone"] == 4
        # wandel-herstel blijft een vaste pace, geen hartslag
        assert rep["data"][1]["target"][0]["targetType"] == "pace"

    def test_al_op_hartslag_geen_wijziging(self):
        hr = [{"name": "x", "target": "hr", "steps": [
            {"type": "step", "target": [{"targetType": "hr_zone", "zone": 2}]}]}]
        _, n = fs_client.convert_builder_target_type(hr, naar="hr")
        assert n == 0  # niets om te zetten

    def test_hartslag_naar_tempo(self):
        hr = [{"name": "x", "target": "hr", "steps": [
            {"type": "step", "target": [{"targetType": "hr_zone", "zone": 3}]}]}]
        opts, n = fs_client.convert_builder_target_type(hr, naar="tempo")
        assert n == 1 and opts[0]["target"] == "pace"
        assert opts[0]["steps"][0]["target"][0]["targetType"] == "pace_zone"


class TestBuilderBerekeningen:
    def test_parse_duration(self):
        assert schema_builder._parse_duration_to_min("45:00") == 45
        assert schema_builder._parse_duration_to_min("1:05:00") == 65
        assert schema_builder._parse_duration_to_min("03:30") == 3.5
        assert schema_builder._parse_duration_to_min("kapot") == 0.0

    def test_totaaltijd_met_repeat(self):
        # 10min wu + 5x(2min+1min) + 5min cd = 30 min
        opts = [{"steps": [
            {"type": "step", "durationType": "TIME", "duration": "10:00"},
            {"type": "repeat", "repeats": 5, "data": [
                {"type": "step", "durationType": "TIME", "duration": "02:00"},
                {"type": "step", "durationType": "TIME", "duration": "01:00"}]},
            {"type": "step", "durationType": "TIME", "duration": "05:00"},
        ]}]
        assert schema_builder._calc_builder_duration_min(opts) == 30

    def test_afstandsschema_geeft_geen_tijd(self):
        opts = [{"steps": [{"type": "step", "durationType": "DISTANCE", "durationDist": 5.0}]}]
        assert schema_builder._calc_builder_duration_min(opts) is None

    def test_totaalafstand_met_repeat(self):
        # 1.5km wu + 5x(0.8+0.4) + 1.5km cd = 9 km
        opts = [{"steps": [
            {"type": "step", "durationType": "DISTANCE", "durationDist": 1.5},
            {"type": "repeat", "repeats": 5, "data": [
                {"type": "step", "durationType": "DISTANCE", "durationDist": 0.8},
                {"type": "step", "durationType": "DISTANCE", "durationDist": 0.4}]},
            {"type": "step", "durationType": "DISTANCE", "durationDist": 1.5},
        ]}]
        assert schema_builder._calc_builder_distance_km(opts) == 9


# ---------------------------------------------------------------------------
# admin — KOR, pakketten, prijzen, omzet-categorisatie, matching
# ---------------------------------------------------------------------------

class TestKorProjectie:
    def test_leeg(self):
        p = admin.kor_projectie({})
        assert p["huidig"] == 0.0 and p["resterend"] == admin.KOR_GRENS

    def test_stand_en_resterend(self):
        p = admin.kor_projectie({"2026-05": 10000.0, "2026-06": 12000.0})
        assert p["huidig"] == 12000.0
        assert p["resterend"] == 8000.0
        assert p["gepasseerd"] is False
        assert p["datum_grens"] is not None  # stijgende trend → projectiedatum

    def test_gepasseerd(self):
        p = admin.kor_projectie({"2026-06": 21000.0})
        assert p["gepasseerd"] is True


class TestPakketEnPrijs:
    def test_pakket_van_groep(self):
        assert admin.pakket_van_groep("1. Los trainingsschema") == "Los Schema"
        assert admin.pakket_van_groep("Start to Run groep A") == "Start to Run"
        assert admin.pakket_van_groep("Wandelclub") == "—"

    def test_eigen_prijs_override(self):
        ath = {"user_key": "a", "group": "Comfort"}
        adm = {"a": {"prijs_override": 45}}
        assert admin.klant_prijs(ath, adm, admin.PAKKET_PRIJZEN_STD) == 45.0

    def test_gratis_is_nul(self):
        ath = {"user_key": "a", "group": "Comfort"}
        adm = {"a": {"gratis": True}}
        assert admin.klant_prijs(ath, adm, admin.PAKKET_PRIJZEN_STD) == 0.0

    def test_standaard_pakketprijs(self):
        ath = {"user_key": "a", "group": "Comfort"}
        assert admin.klant_prijs(ath, {}, admin.PAKKET_PRIJZEN_STD) == 55

    def test_jaaromzet_telt_gratis_niet_mee(self):
        aths = [{"user_key": "a", "group": "Comfort"}, {"user_key": "b", "group": "Comfort"}]
        adm = {"a": {"status": "Actief"}, "b": {"status": "Actief", "gratis": True}}
        assert admin.geschatte_jaaromzet(aths, adm, admin.PAKKET_PRIJZEN_STD) == 55 * 13


class TestMaandomzet:
    def test_cumulatief_naar_maand(self):
        cum = {"2026-01": 1000.0, "2026-02": 2500.0, "2026-03": 4000.0}
        mo = admin.jaar_maandomzet(cum, 2026)
        assert mo == {1: 1000.0, 2: 1500.0, 3: 1500.0}
        assert round(sum(mo.values()), 2) == 4000.0  # som maanden == cumulatieve eindstand

    def test_prognose_gemiddelde_laatste_drie(self):
        prog = admin.prognose_maanden({1: 100.0, 2: 200.0, 3: 300.0, 4: 400.0})
        assert prog[5] == 300.0  # gem. van 200/300/400
        assert set(prog) == set(range(5, 13))


class TestFactuurCategorie:
    def test_clinics_op_naam_en_omschrijving(self):
        assert admin.factuur_categorie("Gemeente Oss", "wat dan ook") == "Clinics"
        assert admin.factuur_categorie("Optimum Change", "") == "Clinics"
        assert admin.factuur_categorie("Bedrijf X", "bedrijfstraining van tilburg") == "Clinics"

    def test_lactaat_vs_strippenkaart_op_omschrijving_niet_bedrag(self):
        # beide kunnen €135 zijn — de omschrijving beslist
        assert admin.factuur_categorie("Jan", "Lactaatmeting", 135) == "Lactaatmetingen"
        assert admin.factuur_categorie("Piet", "Strippenkaart 2x", 135) == "Strippenkaarten"

    def test_coaching_pakketnamen_en_afkortingen(self):
        assert admin.factuur_categorie("Anouk", "Start to run") == "Coaching"
        for afk in ("STR", "GB", "HP"):
            assert admin.factuur_categorie("X", afk) == "Coaching"

    def test_onbekend_is_overig(self):
        assert admin.factuur_categorie("Klaas", "iets vaags") == "Overig"

    def test_omzet_per_categorie_slaat_concept_over(self):
        fac = [
            {"naam": "A", "omschrijving": "Comfort", "bedrag": 55, "status": "published"},
            {"naam": "B", "omschrijving": "Comfort", "bedrag": 999, "status": "concept"},
        ]
        assert admin.omzet_per_categorie(fac) == {"Coaching": 55.0}


class TestKlantMatching:
    ATHS = [
        {"user_key": "d", "name": "Doutzen Schmidt", "first_name": "Doutzen",
         "last_name": "Schmidt", "email": "jeroenschmidt78@hotmail.com"},
        {"user_key": "r", "name": "Dave De Rijder", "first_name": "Dave",
         "last_name": "De Rijder", "email": "mail@davederijder.nl"},
    ]

    def test_achternaam_kern_zonder_tussenvoegsels(self):
        assert admin._achternaam_kern("De Rijder") == {"rijder"}
        assert admin._achternaam_kern("Van Hamersveld") == {"hamersveld"}

    def test_match_op_email_bij_andere_betaler(self):
        c = {"naam": "Jeroen Schmidt", "email": "jeroenschmidt78@hotmail.com"}
        assert admin.match_contact_fs(c, self.ATHS) == "Doutzen Schmidt"

    def test_match_op_achternaam_zonder_tussenvoegsel(self):
        c = {"naam": "Dave Rijder", "email": ""}
        assert admin.match_contact_fs(c, self.ATHS) == "Dave De Rijder"

    def test_clinic_contact_matcht_niet(self):
        assert admin.match_contact_fs({"naam": "Gemeente Oss", "email": ""}, self.ATHS) == ""

    def test_niet_gefactureerd_slaat_gratis_en_vooruitbetaald_over(self):
        aths = self.ATHS + [{"user_key": "n", "name": "Nieuwe Klant", "first_name": "Nieuwe",
                             "last_name": "Klant", "email": "n@x.nl"}]
        adm = {"d": {"status": "Actief", "gratis": True},
               "r": {"status": "Actief", "vooruitbetaald_tot": "2099-12-31"},
               "n": {"status": "Actief"}}
        namen = [a["name"] for a in admin.niet_gefactureerde_klanten(aths, adm, [
            {"naam": "Iemand Anders", "status": "sent"}])]
        assert namen == ["Nieuwe Klant"]


# ---------------------------------------------------------------------------
# dossier — hardloop-km filtering (de 5526km-bug)
# ---------------------------------------------------------------------------

class TestRunKm:
    def test_fiets_telt_niet_mee(self):
        assert dossier._run_km({"activity_type": "Fietsen", "actual_km": 40}) == 0.0

    def test_hardlopen_telt(self):
        assert dossier._run_km({"activity_type": "Hardlopen", "actual_km": 12.5}) == 12.5

    def test_sanity_cap_boven_100km(self):
        assert dossier._run_km({"activity_type": "Hardlopen", "actual_km": 5526}) == 0.0

    def test_corrupt_is_nul(self):
        assert dossier._run_km({"activity_type": "Hardlopen", "actual_km": "kapot"}) == 0.0

    def test_onbekend_type_telt_als_run(self):
        assert dossier._is_run({"activity_type": ""}) is True


# ---------------------------------------------------------------------------
# belasting — de vier signaalregels
# ---------------------------------------------------------------------------

def _run_entry(dagen_geleden: int, km: float, felt=None, effort=None, notes=""):
    from datetime import date, timedelta
    return {"date": (date.today() - timedelta(days=dagen_geleden)).isoformat(),
            "activity_type": "Hardlopen", "actual_km": km, "completed": True,
            "felt": felt, "effort": effort, "post_notes": notes}


def _stabiele_basis(km_per_run=5.0, felt=3, effort=5):
    """4 weken basis: 3 runs/week in dagen 8-35 (buiten het recente venster)."""
    return [_run_entry(d, km_per_run, felt=felt, effort=effort)
            for d in (9, 11, 13, 16, 18, 20, 23, 25, 27, 30, 32, 34)]


class TestBelasting:
    def test_stabiel_geen_signaal(self):
        log = _stabiele_basis() + [_run_entry(d, 5.0, felt=3, effort=5) for d in (1, 3, 5)]
        assert belasting.analyse_belasting(log) is None

    def test_volumesprong_geeft_signaal(self):
        # basis 15 km/wk, recente week 24 km = +60% → hoog
        log = _stabiele_basis() + [_run_entry(d, 8.0) for d in (1, 3, 5)]
        res = belasting.analyse_belasting(log)
        assert res is not None and "volume" in res["codes"]
        assert res["ernst"] == "hoog"  # ratio 1.6 >= 1.5

    def test_starter_met_lage_basis_niet_geflagd(self):
        # basis onder 10 km/wk: opbouwer, verdubbeling is dan geen alarm
        log = ([_run_entry(d, 2.0) for d in (9, 16, 23, 30, 32)]
               + [_run_entry(d, 4.0) for d in (1, 3)])
        assert belasting.analyse_belasting(log) is None

    def test_gevoel_zakt(self):
        log = _stabiele_basis(felt=2) + [
            _run_entry(d, 5.0, felt=4) for d in (1, 3, 5)]  # 2.0 → 4.0
        res = belasting.analyse_belasting(log)
        assert res is not None and "gevoel" in res["codes"]

    def test_klachtwoorden_in_notities(self):
        log = _stabiele_basis() + [
            _run_entry(2, 5.0, notes="Beetje pijn aan mijn achillespees vandaag")]
        res = belasting.analyse_belasting(log)
        assert res is not None and "klachten" in res["codes"]
        assert any(k.startswith("pijn (achilles)") for k in res["metrics"]["klachten"])

    def test_klacht_ouder_dan_week_telt_niet(self):
        # notitie van 11 dagen geleden is geen actueel signaal meer
        log = _stabiele_basis() + [
            _run_entry(11, 5.0, notes="Beetje pijn aan mijn achillespees")]
        res = belasting.analyse_belasting(log)
        assert res is None or "klachten" not in res["codes"]

    def test_wandeling_lopen_telt_niet_als_hardloopkm(self):
        # FinalSurge noemt wandelen 'Lopen' — 12,78 km wandelen is geen run-volume
        assert dossier._is_run({"activity_type": "Lopen"}) is False
        assert dossier._is_run({"activity_type": "Hardlopen"}) is True
        assert dossier._is_run({"activity_type": "Trail Run"}) is True
        assert dossier._run_km({"activity_type": "Lopen", "actual_km": 12.78}) == 0.0
        wandeling = _run_entry(1, 12.78)
        wandeling["activity_type"] = "Lopen"
        log = _stabiele_basis() + [_run_entry(1, 4.13), _run_entry(3, 3.88), wandeling]
        res = belasting.analyse_belasting(log)
        if res is not None:
            assert res["metrics"]["km_recent"] == 8.0  # niet 20.8
            assert all(r["km"] != 12.8 for r in res["metrics"]["runs_recent"])

    def test_twee_signalen_is_hoog(self):
        log = _stabiele_basis(felt=2) + [
            _run_entry(d, 5.0, felt=4, notes="last van mijn knie") for d in (1, 3, 5)]
        res = belasting.analyse_belasting(log)
        assert res["ernst"] == "hoog" and len(res["codes"]) >= 2

    def test_fietskm_telt_niet_mee_in_volume(self):
        log = _stabiele_basis()
        log += [_run_entry(d, 5.0) for d in (1, 3, 5)]
        # dikke fietsweek erbovenop mag géén volumesignaal geven
        for d in (1, 2, 4):
            e = _run_entry(d, 60.0)
            e["activity_type"] = "Fietsen"
            log.append(e)
        assert belasting.analyse_belasting(log) is None

    def test_klachten_negaties_tellen_niet(self):
        # de bug: positieve berichten ("geen pijn", "pijnvrij") gaven klacht-signalen
        assert belasting._vind_klachten("Beetje pijn aan mijn knie vandaag") == ["pijn (knie)"]
        assert belasting._vind_klachten("Geen pijn meer gevoeld, ging lekker!") == []
        assert belasting._vind_klachten("Helemaal pijnvrij gelopen vandaag") == []
        assert belasting._vind_klachten("De pijn is gelukkig weg") == []
        assert belasting._vind_klachten("Knie voelde prima, lekker gelopen") == []
        assert belasting._vind_klachten("Nauwelijks last van mijn kuit") == []
        assert belasting._vind_klachten("Last van mijn achillespees na het lopen") == ["last van (achilles)"]

    def test_zelfde_run_dubbel_gesynct_telt_een_keer(self):
        # planned workout (afgerond) + losse horloge-sync = dezelfde run
        entries = [
            {"date": "2026-07-01", "name": "Duurloop Z2", "activity_type": "Hardlopen",
             "actual_km": 10.0, "completed": True, "felt": 2, "effort": 5, "post_notes": ""},
            {"date": "2026-07-01", "name": "", "activity_type": "Hardlopen",
             "actual_km": 10.1, "completed": True, "felt": None, "effort": None, "post_notes": ""},
            {"date": "2026-07-02", "name": "Intervallen", "activity_type": "Hardlopen",
             "actual_km": 8.0, "completed": True, "felt": 3, "effort": 7, "post_notes": ""},
        ]
        uit = belasting._ontdubbel_entries(entries)
        runs = [e for e in uit if e.get("actual_km")]
        assert len(runs) == 2                       # 10 km telt één keer
        assert sum(e["actual_km"] for e in runs) == 18.0
        assert any(e["name"] == "Duurloop Z2" for e in runs)  # variant mét naam wint

    def test_twee_echte_runs_zelfde_dag_blijven(self):
        entries = [
            {"date": "2026-07-01", "name": "Ochtendloop", "activity_type": "Hardlopen",
             "actual_km": 8.0, "completed": True, "felt": None, "effort": None, "post_notes": ""},
            {"date": "2026-07-01", "name": "Avondloop", "activity_type": "Hardlopen",
             "actual_km": 5.0, "completed": True, "felt": None, "effort": None, "post_notes": ""},
        ]
        assert len(belasting._ontdubbel_entries(entries)) == 2

    def test_gezien_dempt_en_escalatie_doorbreekt(self, monkeypatch):
        import intake_store
        monkeypatch.setattr(intake_store, "save_belasting", lambda d: (True, ""))
        from datetime import date, timedelta
        data = {"datum": date.today().isoformat(),
                "resultaten": [{"user_key": "a", "naam": "X", "ernst": "let_op",
                                "signalen": ["s"], "codes": ["volume"]}],
                "afgehandeld": {}}
        # markeer gezien → onzichtbaar
        data = belasting.markeer_gezien(data, "a", "let_op")
        assert belasting.zichtbare_resultaten(data) == []
        # escalatie naar hoog → weer zichtbaar ondanks 'gezien'
        data["resultaten"][0]["ernst"] = "hoog"
        assert len(belasting.zichtbare_resultaten(data)) == 1


# ---------------------------------------------------------------------------
# KOR → btw-omschakeling (1 aug 2026)
# ---------------------------------------------------------------------------

class TestBtwOmschakeling:
    def test_factuur_omzet_kor_periode_is_incl(self):
        import rompslomp_client as rc
        f = {"datum": "2026-07-15", "bedrag": 55.0, "bedrag_excl": 55.0, "bedrag_incl": 55.0}
        assert rc.factuur_omzet(f) == 55.0
        assert rc.factuur_btw(f) == 0.0  # KOR: geen btw, ook al zou er een verschil staan

    def test_factuur_omzet_btw_periode_is_excl(self):
        import rompslomp_client as rc
        f = {"datum": "2026-08-05", "bedrag": 66.55, "bedrag_excl": 55.0, "bedrag_incl": 66.55}
        assert rc.factuur_omzet(f) == 55.0
        assert rc.factuur_btw(f) == 11.55

    def test_btw_stand_kwartaal(self):
        from datetime import date
        facturen = [
            {"datum": "2026-07-10", "bedrag": 100, "bedrag_excl": 100, "bedrag_incl": 100,
             "status": "published"},  # KOR → telt niet
            {"datum": "2026-08-05", "bedrag": 121, "bedrag_excl": 100, "bedrag_incl": 121,
             "status": "published"},  # Q3
            {"datum": "2026-10-02", "bedrag": 60.5, "bedrag_excl": 50, "bedrag_incl": 60.5,
             "status": "published"},  # Q4
            {"datum": "2026-08-09", "bedrag": 121, "bedrag_excl": 100, "bedrag_incl": 121,
             "status": "concept"},    # concept → telt niet
        ]
        s = admin.btw_stand(facturen, vandaag=date(2026, 10, 15))
        assert s["btw_totaal"] == 31.5           # 21 + 10.5
        assert s["omzet_excl"] == 150.0
        assert s["kwartaal"] == "Q4" and s["btw_kwartaal"] == 10.5
        assert "januari" in s["aangifte_label"]  # Q4-aangifte in januari

    def test_potjes_advies(self):
        p = admin.potjes_advies(omzet_netto_ytd=18000, kosten_ytd=2000, ib_pct=45,
                                buffer_pct=10, btw_pot=500)
        assert p["kosten_ytd"] == 2000.0
        assert p["winst"] == 16000.0
        assert p["ib_pot"] == 7200.0             # 45% — winst bovenop loondienst
        assert p["buffer"] == 1600.0
        assert p["btw_pot"] == 500.0
        assert p["prive"] == 7200.0              # winst − ib − buffer
        assert p["ib_pot"] + p["buffer"] + p["prive"] == p["winst"]

    def test_potjes_geen_negatieve_winst(self):
        p = admin.potjes_advies(1000, 3000, 45, 10, 0)
        assert p["winst"] == 0.0 and p["prive"] == 0.0

    def test_kosten_grootboek_herkenning(self):
        import rompslomp_client as rc
        assert rc._path_is_kosten("Kosten.Overige kosten.Diversen") is True
        assert rc._path_is_kosten("Omzet.Overig") is False
        assert rc._is_kosten_account({"type": "expense"}) is True
        assert rc._is_kosten_account({"type": "revenue", "path": "Omzet"}) is False

    def test_uitgave_telt_als_kost(self):
        # balans-uitgaven (voorraad) tellen niet mee als kosten — net als de W&V
        import rompslomp_client as rc
        kost = {"type_account": {"type": "costs", "path": "profit.costs.selling.representation"}}
        voorraad = {"type_account": {"type": "balance", "path": "activa.current_assets.stock"}}
        assert rc._uitgave_telt_als_kost(kost) is True
        assert rc._uitgave_telt_als_kost(voorraad) is False
        assert rc._uitgave_telt_als_kost({}) is True  # onbekend → meetellen

    def test_gesplitste_boeking_telt_alleen_kostenregel(self):
        # Vier echte voorbeelden: alleen de kostenregel telt, privé/beperkt deel valt af
        import rompslomp_client as rc
        montimar = {"invoice_lines": [
            {"price_with_vat": "128.00", "account_path": "profit.costs.selling.representation"},
            {"price_with_vat": "32.00", "account_path": "passiva.equity.partner_1"}]}
        marktkraam = {"invoice_lines": [
            {"price_with_vat": "143.05", "account_path": "profit.costs.selling.marketing"},
            {"price_with_vat": "35.76", "account_path": "passiva.equity.partner_1"}]}
        autowas = {"invoice_lines": [
            {"price_with_vat": "27.50", "account_path": "profit.costs.car.car_costs"},
            {"price_with_vat": "27.49", "account_path": "passiva.equity.partner_1"}]}
        assert rc._uitgave_kosten_bedrag(montimar) == 128.00      # niet 160
        assert rc._uitgave_kosten_bedrag(marktkraam) == 143.05    # niet 178,81
        assert rc._uitgave_kosten_bedrag(autowas) == 27.50        # niet 54,99
        # De vier voorbeelden samen: 122,74 minder dan de bankbedragen
        bank = 160.00 + 178.81 + 54.99 + 54.99
        kost = sum(rc._uitgave_kosten_bedrag(x) for x in
                   (montimar, marktkraam, autowas, autowas))
        assert round(bank - kost, 2) == 122.74

    def test_enkele_kostenregel_ongewijzigd(self):
        import rompslomp_client as rc
        # normale uitgave met één kostenregel blijft volledig meetellen
        item = {"type_account": {"type": "costs", "path": "profit.costs.other_costs.subscriptions"},
                "invoice_lines": [{"price_with_vat": "32.07",
                                   "account_path": "profit.costs.other_costs.subscriptions"}]}
        assert rc._uitgave_kosten_bedrag(item) == 32.07

    def test_regel_zonder_rekening_volgt_uitgave(self):
        import rompslomp_client as rc
        # regel zonder account -> beslist op uitgave-niveau (fallback, oud gedrag)
        kost = {"type_account": {"type": "costs", "path": "profit.costs.x"},
                "invoice_lines": [{"price_with_vat": "50.00"}]}
        voorraad = {"type_account": {"type": "balance", "path": "activa.current_assets.stock"},
                    "invoice_lines": [{"price_with_vat": "50.00"}]}
        assert rc._uitgave_kosten_bedrag(kost) == 50.00
        assert rc._uitgave_kosten_bedrag(voorraad) == 0.0

    def test_uitgave_bedrag_uit_invoice_lines(self):
        # expenses-endpoint: bedragen zitten in de regels, niet op het hoofdniveau
        import rompslomp_client as rc
        uitgave = {"date": "2026-06-21", "invoice_lines": [
            {"price_with_vat": "18.81", "price_without_vat": "15.55"},
            {"price_per_unit": "6.52", "quantity": "2.0"},   # geen totaalvelden
        ]}
        assert rc._uitgave_bedrag(uitgave) == 31.85           # 18.81 + 13.04
        # direct veld op hoofdniveau wint als het er wél is
        assert rc._uitgave_bedrag({"price_with_vat": "52.50"}) == 52.50
        assert rc._uitgave_bedrag({"invoice_lines": []}) == 0.0

    def test_categorie_omzet_excl_na_omschakeling(self):
        fac = [
            {"naam": "A", "omschrijving": "Comfort", "datum": "2026-07-01",
             "bedrag": 55, "bedrag_excl": 55, "bedrag_incl": 55, "status": "published"},
            {"naam": "B", "omschrijving": "Comfort", "datum": "2026-08-10",
             "bedrag": 66.55, "bedrag_excl": 55, "bedrag_incl": 66.55, "status": "published"},
        ]
        per = admin.omzet_per_categorie(fac)
        assert per == {"Coaching": 110.0}  # 55 incl (KOR) + 55 excl (btw)


# ---------------------------------------------------------------------------
# briefing — week-aggregatie
# ---------------------------------------------------------------------------

class TestBriefingAggregatie:
    def _atleet(self, naam, group, entries, races=()):
        return {"naam": naam, "group": group, "entries": entries, "races": list(races)}

    def test_kerncijfers_en_stille_atleten(self):
        import briefing
        per = [
            self._atleet("Anna", "Comfort", [
                {"completed": True, "activity_type": "Hardlopen", "actual_km": 10, "felt": 2},
                {"completed": True, "activity_type": "Hardlopen", "actual_km": 5, "felt": 4},
                {"completed": False, "activity_type": "Hardlopen", "actual_km": None, "felt": None},
            ]),
            self._atleet("Bram", "Premium", [], races=[]),
            self._atleet("Cas", "Comfort", [
                {"completed": True, "activity_type": "Fietsen", "actual_km": 40, "felt": 3},
            ], races=["Stadsloop 10k"]),
        ]
        s = briefing.aggregeer_week(per)
        assert s["n_trainingen"] == 3            # niet-uitgevoerde telt niet
        assert s["km_totaal"] == 15              # fiets-km tellen niet als hardloop-km
        assert s["stil"] == ["Bram"]
        assert s["n_actief"] == 2 and s["n_atleten"] == 3
        assert s["gevoel_gem"] == 3.0            # (2+4+3)/3
        assert s["races_gedaan"] == ["Cas — Stadsloop 10k"]
        assert s["groepen"]["Comfort"] == {"n": 3, "atleten": 2}

    def test_leeg(self):
        import briefing
        s = briefing.aggregeer_week([])
        assert s["n_trainingen"] == 0 and s["stil"] == [] and s["gevoel_gem"] is None

    def test_week_label_formaat(self):
        import briefing
        from datetime import date
        assert briefing.week_label(date(2026, 7, 3)) == "2026-W27"


# ---------------------------------------------------------------------------
# ai_feedback.update_athlete_profiel — vangnetten (gemockte AI)
# ---------------------------------------------------------------------------

class TestProfielVangnet:
    @staticmethod
    def _mock_ai(monkeypatch, antwoord: str):
        import ai_feedback
        resp = type("R", (), {"content": [type("T", (), {"text": antwoord})()]})
        monkeypatch.setattr(ai_feedback, "create_message", lambda **k: resp)
        return ai_feedback

    def test_normaal_antwoord_wordt_profiel(self, monkeypatch):
        af = self._mock_ai(monkeypatch, "Heeft last van haar achillespees. Houdt van data.")
        out = af.update_athlete_profiel("oud", "ging goed", "mooi gedaan")
        assert "achillespees" in out

    def test_ontspoord_lang_antwoord_behoudt_oud_profiel(self, monkeypatch):
        af = self._mock_ai(monkeypatch, "x" * 2000)
        assert af.update_athlete_profiel("oud profiel", "a", "c") == "oud profiel"

    def test_leeg_antwoord_behoudt_oud_profiel(self, monkeypatch):
        af = self._mock_ai(monkeypatch, "")
        assert af.update_athlete_profiel("oud profiel", "a", "c") == "oud profiel"


# ---------------------------------------------------------------------------
# fs_client.get_training_log — parallelle lap-fetch (gemockte API)
# ---------------------------------------------------------------------------

class TestTrainingLogLaps:
    def test_laps_parallel_toegevoegd_en_fouten_niet_blokkerend(self, monkeypatch):
        from datetime import date, timedelta
        vandaag = date.today().isoformat()
        gisteren = (date.today() - timedelta(days=1)).isoformat()

        def fake_workouts(user_key, start, end):
            return [
                {"workout_date": vandaag, "key": "w1", "name": "Intervallen",
                 "workout_status_text": "Completed",
                 "Activities": [{"amount": 8, "amount_type": "km"}]},
                {"workout_date": gisteren, "key": "w2", "name": "Duurloop",
                 "workout_status_text": "Completed",
                 "Activities": [{"amount": 10, "amount_type": "km"}]},
                {"workout_date": gisteren, "key": "w3", "name": "Gepland",
                 "workout_status_text": "Planned", "Activities": []},
            ]

        def fake_details(workout_key, user_key):
            if workout_key == "w2":
                raise RuntimeError("API-fout mag laps nooit blokkeren")
            return {"Activities": [{"Laps": [
                {"distance_display": "1 km", "pace_display": "4:30", "hr_avg": 165}]}]}

        monkeypatch.setattr(fs_client, "get_workouts_deduped", fake_workouts)
        monkeypatch.setattr(fs_client, "get_workout_details", fake_details)

        log = {e["name"]: e for e in fs_client.get_training_log("user", months=1)}
        assert log["Intervallen"]["laps"] == [{"dist": "1 km", "pace": "4:30", "hr": 165}]
        assert log["Duurloop"]["laps"] == []      # fout → lege laps, geen crash
        assert log["Gepland"]["laps"] == []       # niet uitgevoerd → geen detail-fetch
