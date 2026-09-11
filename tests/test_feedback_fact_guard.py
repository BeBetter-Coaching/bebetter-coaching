"""Feedback Correctness Fact-Guard (11 sep 2026).

Vier bewezen foutklassen uit de structurele audit van 11 sep (6 natuurlijke cases, 4 fout):

  1. Een hardloopactiviteit werd 'gereden' genoemd. Alleen de prompt verbood dat; de validator
     ving het zelfstandig naamwoord ('rit'), niet het werkwoord.
  2. Een training volledig in Z1 kwam terug als Z2. De prompt gaf de juiste labels, maar niets
     toetste een zoneclaim in de output tegen de gemeten verdeling.
  3. De R3.1-regel 'atleet_derde_persoon' blokkeerde 'als ze [de kuiten] nog gespannen zijn' en
     'hij [de hartslag] zakte naar 130'; Rik kreeg daardoor een terugvalconcept zonder reactie.
  4. Een correcte Z2-duurloop met een Z1-inloop werd tegengesproken: de verplichtingenlaag kreeg
     bij een doorlopende duurloop geen doelzone, en telde een deel ONDER de claim als tegenspraak.

Alles over de echte functies en het echte `genereer`-pad; alleen LLM en FinalSurge gestubd.

    python3 -m pytest tests/test_feedback_fact_guard.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback                                          # noqa: E402
import feedback_copy as fc                                  # noqa: E402
import feedback_core                                        # noqa: E402
import feedback_facts as ff                                 # noqa: E402
import feedback_obligations as ob                           # noqa: E402
import fs_client                                            # noqa: E402

TODAY = date(2026, 9, 11)
# Zelfde grenzen als bij de audit-cases (Luc de Werd / Rick Cornelissen).
HR = [{"num": i, "naam": n, "low": lo, "high": hi} for i, (n, lo, hi) in enumerate(
    [("Easy", 0, 149), ("Marathon", 150, 159), ("Threshold", 160, 169),
     ("Interval", 170, 179), ("Repetition", 180, 190)], 1)]
ZONES = {"zone_type": "hartslag", "zones_text": "z", "zones": HR}
SCHOON = {"complaint_areas": [], "complaint_new": [], "load_active": False, "overall": "READY",
          "has_load": True, "source_gaps": [], "recovery_negative": False, "missed_runs": 0}


def _stap(zone, km=10):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": km,
            "distUnit": "km", "target": [{"targetType": "hr_zone", "zone": zone},
                                         {"targetType": "open", "zone": 0}]}


def _workout(hrs, bericht="", naam="Vlotte duurloop", planned=None, **kw):
    laps = [{"amount": 1.0, "hr_avg": h, "pace_display": "4:50"} for h in hrs]
    act = {"hr_avg": round(sum(hrs) / len(hrs)), "pace_display": "4:50", "Laps": laps,
           "amount": float(len(hrs)), "planned_amount": float(planned or len(hrs))}
    w = {"workout_type": "run", "workout_key": "W1", "athlete_key": "AK",
         "athlete_name": "Luc de Werd", "athlete_first_name": "Luc", "workout_name": naam,
         "thread": [], "workout_date": TODAY.isoformat(), "post_notes": bericht,
         "athlete_comments": [], "details": {"has_structured_workout": True,
                                             "description": f"{naam} | Z2", "Activities": [act]},
         "_brein_diag": dict(SCHOON)}
    w.update(kw)
    return w


VOLLEDIG_Z1 = [128, 130, 131, 129, 130, 132, 128, 130]          # 8 km, elke lap Z1
Z2_MET_INLOOP = [144, 154, 155, 156, 157, 157, 155, 156, 156, 155]   # Luc: 1 km Z1, 9 km Z2
Z2_KORT = [145, 154, 155, 155, 155]                             # Rick: 1 km Z1, 4 km Z2


@pytest.fixture
def fs(monkeypatch):
    stand = {"builder": [_stap(2)]}
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: stand["builder"])
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: ZONES)
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda *a, **k: None)
    return stand


def _context(w):
    ctx, _ = ai_feedback._build_workout_context(w)
    return ctx, w["_fact_pack"]


def _genereer(monkeypatch, w, llm_uit):
    """Het ECHTE productiepad; alleen LLM + FinalSurge gestubd (zie de `fs`-fixture)."""
    feedback_core._cache.clear()
    feedback_core._cache[w["workout_key"]] = w
    feedback_core._GEN_STATUS.pop(w["workout_key"], None)
    diag = w.get("_brein_diag")

    def _bc(x):
        x["_brein_diag"] = diag
        return ""
    monkeypatch.setattr(feedback_core, "_brein_context", _bc)
    monkeypatch.setattr(feedback_core, "_timeline_rows", lambda x: [])
    monkeypatch.setattr(feedback_core, "_refresh_thread", lambda x: None)
    monkeypatch.setattr(feedback_core, "_session_context", lambda x: "")
    monkeypatch.setattr(feedback_core, "_ensure_details", lambda wid: None)
    monkeypatch.setattr(feedback_core, "_generation_date", lambda: TODAY)
    monkeypatch.setattr(ai_feedback, "_generate_text", lambda **kw: llm_uit)
    tekst = feedback_core.genereer(w["workout_key"])
    return tekst, feedback_core.last_generation_status(w["workout_key"])


# ══════════════════════════════════════════════════════════════════════════════
# 1 — hardlopen is nooit rijden of fietsen
# ══════════════════════════════════════════════════════════════════════════════
class TestLooptaal:
    def test_gereden_wordt_gelopen(self):
        uit = fc.clean_draft("Je hebt de vlotte duurloop netjes gereden. Uitgereden in Z1, top.",
                             is_running=True)
        assert "gereden" not in uit.lower()
        assert "netjes gelopen" in uit and "Uitgelopen in Z1" in uit

    def test_gefietst_wordt_ook_gecorrigeerd(self):
        assert "gefietst" not in fc.clean_draft("Goed gefietst vandaag.", is_running=True)

    def test_de_validator_is_het_vangnet(self):
        for t in ("Netjes gereden.", "Je hebt hem mooi uitgereden.", "Goed gefietst."):
            assert ff.validate_draft(t, is_running=True)["detail"] == "gereden", t

    def test_uitzondering_als_de_atleet_zelf_over_fietsen_praat(self):
        atleet = "Na het fietsen nog een rondje gelopen."
        assert ff.validate_draft("Ook nog netjes gereden.", is_running=True,
                                 athlete_message=atleet)["ok"] is True
        assert "gereden" in fc.clean_draft("Ook nog netjes gereden.", athlete_text=atleet,
                                           is_running=True)

    def test_een_echte_fietsactiviteit_in_de_zin_blijft_staan(self):
        zin = "Je mountainbiketocht van zaterdag heb je stevig gereden."
        assert ff.validate_draft(zin, is_running=True)["ok"] is True
        assert fc.clean_draft(zin, is_running=True) == zin

    def test_geen_run_geen_correctie(self):
        assert fc.clean_draft("Netjes gereden.", is_running=False) == "Netjes gereden."

    def test_het_echte_pad_levert_een_gecorrigeerd_concept_geen_terugval(self, monkeypatch, fs):
        w = _workout(Z2_MET_INLOOP, "Weer eens echt lekker gelopen, was wel hoog z2")
        tekst, status = _genereer(monkeypatch, w, "Fijn dat het lekker liep! Je hebt de vlotte "
                                                  "duurloop netjes gereden, op hartslag in Z2.")
        assert "gelopen" in tekst and "gereden" not in tekst
        assert not tekst.startswith("Je schrijft") and not tekst.startswith("Je vraagt")


# ══════════════════════════════════════════════════════════════════════════════
# 2 — een zoneclaim moet kloppen met de gemeten verdeling
# ══════════════════════════════════════════════════════════════════════════════
class TestZoneclaim:
    def _pack(self, shares):
        return ff.build_fact_pack(workout_type="run",
                                  zone_distribution={"modality": "hartslag", "shares": shares})

    def _ok(self, tekst, shares):
        p = self._pack(shares)
        return ff.validate_draft(tekst, is_running=True, mandatory=p["mandatory"],
                                 forbidden_claims=p["forbidden_claims"])

    def test_volledig_z1_mag_nooit_z2_heten(self):
        for claim in ("Je bleef de hele training netjes in Z2 op hartslag.",
                      "Je zat mooi in zone 2.", "De hele duurloop in Z2, precies goed.",
                      "Het was een keurige Z2-loop."):
            r = self._ok(claim, {"Z1": 100})
            assert r["ok"] is False and r["detail"] == "contradiction:zone_claim", claim

    def test_ware_of_niet_toetsbare_zinnen_blijven_toegestaan(self):
        for zin in ("Je bleef netjes in Z1.", "Je bleef mooi binnen Z1-Z2.",
                    "Je kwam niet in Z2, en dat is precies goed.", "Je bleef onder Z2.",
                    "De volgende duurloop mag gerust in Z2.", "Je strides zaten in Z5.",
                    "Qua tempo zat je in Z2.", 'Je schreef "was wel hoog z2", maar het was rustig.'):
            assert self._ok(zin, {"Z1": 100})["ok"] is True, zin

    def test_een_gehaalde_zone_mag_gewoon_genoemd_worden(self):
        assert self._ok("Je zat de hele training in Z2.", {"Z1": 10, "Z2": 90})["ok"] is True

    def test_de_verdeling_is_een_bronfeit_in_de_pack(self, fs):
        _, pack = _context(_workout(VOLLEDIG_Z1, naam="Herstelloop"))
        assert pack["zone_distribution"] == {"modality": "hartslag", "shares": {"Z1": 100}}
        assert any(f["id"] == "zone_claim" for f in pack["forbidden_claims"])

    def test_laps_buiten_de_zones_geven_geen_harde_uitspraak(self):
        assert ff.zone_claim_pattern({"modality": "hartslag",
                                      "shares": {"Z1": 80, "buiten de zones": 20}}) is None

    def test_het_echte_pad_laat_een_valse_zoneclaim_niet_door(self, monkeypatch, fs):
        # Met een vraag gaat de case verplicht naar REVIEW, dus langs de LLM.
        w = _workout(VOLLEDIG_Z1, "Voelde best soepel! Kan ik zo doorgaan?", naam="Herstelloop")
        fs["builder"] = [_stap(1, 8)]
        claim = "Fijn dat het soepel voelde! Je bleef de hele training netjes in Z2 op hartslag."
        tekst, status = _genereer(monkeypatch, w, claim)
        assert "Z2" not in tekst and status == "REVIEW_REQUIRED"
        assert ff.validate_draft(claim, is_running=True,
                                 forbidden_claims=w["_fact_pack"]["forbidden_claims"])["ok"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 3 — 'ze'/'hij' over benen of hartslag wordt niet meer geblokkeerd
# ══════════════════════════════════════════════════════════════════════════════
RIK_NOTITIE = ("Poh deze ging wel lekker zeg. Tempo's lekker hard en constant kunnen houden. "
               "Volgens mij prima tempo? Benen voelen goed. Kuiten beetje gespannen. Wat me opviel "
               "is dat herstel een stuk sneller ging. Misschien minder smakelijk maar merk al paar "
               "weken dat m'n zweet anders ruikt, zou dat kunnen door efficiënter vet verbranding?")
RIK_DRAFT = ("Lekker dat deze zo soepel liep, en je tempo zat er goed in. Over je zweetgeur kan ik "
             "niets met zekerheid zeggen; dat ligt eerder aan wat je eet of drinkt. Het herstel ging "
             "opvallend snel. Hij zakte binnen 200 meter wandelen naar 130. Die kuiten: als ze na de "
             "rustdag nog gespannen zijn, laat het even weten.")


class TestVoornaamwoorden:
    def test_ze_en_hij_over_lichaam_of_hartslag_blokkeren_niet(self):
        for zin in ("Die kuiten: als ze na de rustdag nog gespannen zijn, laat het even weten.",
                    "Het herstel ging snel. Hij zakte binnen 200 meter naar 130.",
                    "De benen deden wat ze moesten doen.",
                    "Beide blokken zaten precies waar ze moesten zitten."):
            assert ff.validate_draft(zin, is_running=True)["ok"] is True, zin

    def test_de_rik_terugval_verdwijnt(self, monkeypatch, fs):
        """Het gemelde geval: een inhoudelijke draft werd geblokkeerd en vervangen door
        'Je vraagt: "Volgens mij prima tempo?" Laten we daar samen even naar kijken.'"""
        w = _workout([139, 148, 159, 163, 144, 161, 166, 146, 148, 148], RIK_NOTITIE,
                     naam="Cruise intervals Z3", athlete_name="Rik van Schaijk",
                     athlete_first_name="Rik")
        fs["builder"] = [_stap(1, 2), {"data": [_stap(3, 1.5), _stap(1, 0.5)]}, _stap(1, 2)]
        tekst, status = _genereer(monkeypatch, w, RIK_DRAFT)
        assert not tekst.startswith("Je vraagt")
        assert "zweetgeur" in tekst and "als ze na de rustdag" in tekst
        assert status == "REVIEW_REQUIRED"

    def test_het_rolcontract_in_de_prompt_blijft(self):
        assert "WIE JE AANSPREEKT" in ai_feedback.SYSTEM_PROMPT
        assert '"ze"' in ai_feedback.SYSTEM_PROMPT and '"ze"' in ai_feedback._NONRUN_SYSTEM

    def test_de_regel_en_zijn_detector_zijn_weg(self):
        assert not hasattr(fc, "derde_persoon_atleet")


# ══════════════════════════════════════════════════════════════════════════════
# 4 — doorlopende duurloop: doelzone uit het plan, alleen 'erboven' spreekt tegen
# ══════════════════════════════════════════════════════════════════════════════
class TestDoelzone:
    def test_doorlopende_z2_duurloop_krijgt_de_doelzone_uit_metric_authority(self, fs):
        """Rick: 1 km Z1 + 4 km Z2, gepland 10 km Z2, geen atleetclaim. Zonder doelzone zei de
        prompt 'verspreid over meerdere zones, kies niet stil één geruststellende zone'."""
        ctx, _ = _context(_workout(Z2_KORT, naam="Rustige duurloop", planned=10))
        assert "de geplande zone 2" in ctx
        assert "verspreid over meerdere zones" not in ctx

    def test_korte_z1_inloop_spreekt_een_correcte_z2_loop_niet_tegen(self, fs):
        """Luc: 'was wel hoog z2', 1 km Z1-inloop + 9 km Z2."""
        ctx, _ = _context(_workout(Z2_MET_INLOOP, "Weer eens echt lekker gelopen, was wel hoog z2"))
        assert "materieel deel in Z1" not in ctx
        assert "NIET met 'Klopt'" not in ctx
        assert "de geplande zone 2" in ctx

    def test_een_deel_boven_de_claim_blijft_een_tegenspraak(self):
        uit = ob.build(modality="hartslag", shares={"Z2": 70, "Z3": 30},
                       planned_target_zones={2}, athlete_text="lekker in z2 gelopen")
        assert "materieel deel in Z3" in uit["prompt_block"]

    def test_een_dominante_zone_onder_de_claim_blijft_ook_een_tegenspraak(self):
        uit = ob.build(modality="hartslag", shares={"Z1": 100},
                       planned_target_zones={2}, athlete_text="was wel hoog z2")
        assert "CONTRADICTED" in uit["prompt_block"]

    def test_de_blokkoppeling_blijft_leidend_waar_die_er_is(self, fs):
        """Gestructureerd werk met een betrouwbare koppeling gebruikt de blokdoelen; de
        MetricAuthority-terugval is alleen voor het geval dat die er niet zijn."""
        import metric_authority as ma
        pb = fs_client._planned_blocks([_stap(1, 2), _stap(3, 3), _stap(1, 2)])
        assert ma.derive(pb)["hr_target_zones"] == [1, 3]


# ══════════════════════════════════════════════════════════════════════════════
# Bestaande guards blijven gelden
# ══════════════════════════════════════════════════════════════════════════════
class TestBestaandeGuards:
    def test_rit_coachstem_en_plantoezegging_blokkeren_nog(self):
        assert ff.validate_draft("Mooie rit!", is_running=True)["detail"] == "rit"
        assert ff.validate_draft("Dat moet de coach met je bespreken.", is_running=True)["detail"] \
            == "coach_derde_persoon"
        assert ff.validate_draft("We passen je schema aan.", is_running=True)["detail"] \
            == "plan_toezegging"

    def test_een_correct_concept_komt_ongewijzigd_door(self, monkeypatch, fs):
        w = _workout(Z2_MET_INLOOP, "Weer eens echt lekker gelopen, was wel hoog z2")
        goed = "Fijn dat het weer eens echt lekker liep! Op hartslag zat je in Z2, zoals gepland."
        tekst, _ = _genereer(monkeypatch, w, goed)
        assert tekst == goed
