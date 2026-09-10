"""Feedback Correctness Round 3.1 — AUTO-VEILIG verdiend, negatie gerespecteerd,
   vraag behouden, atleet rechtstreeks aangesproken, lengte volgt de input (10 sep 2026).

Vier bewezen problemen, alle vier eerst gereproduceerd op het echte pad:

  1. AUTO-VEILIG werd toegekend aan cases die een coachblik verdienen. `build_decision` keek
     alleen naar 'is er bewijsbare inhoud' en 'is de atleettekst geadresseerd'; een vraag kon
     door één generiek zone-antwoord 'beantwoord' worden verklaard, en een klacht-check-in
     telde als adressering. Live: zwaar gevoel + vraag + klacht-check-in → AUTO_SAFE.
  2. NEGATIE werd omgedraaid. De check-in vuurde op een kale substring-match van het
     lichaamsdeel, dus `geen last van bovenbeen en knie` leverde `hou even in de gaten hoe je
     knie hierop reageert` op.
  3. Een MATERIËLE PLANAFWIJKING telde niet mee. `execution_fit` meet of de zones gehaald zijn,
     niet of de training is uitgevoerd zoals gepland: de helft van de geplande afstand op de
     juiste hartslag kwam er door als AUTO_SAFE met `Goed gedaan.`
  4. De atleet werd in de DERDE PERSOON beschreven (`Leuk dat ze haar vriendin ...`), terwijl
     het bericht naar haar toe gaat. Geen enkele laag had daar een regel over.

Plus: de vaste 5-zinnenlimiet uit R3 is vervangen door een inhoudsgestuurd lengtecontract.

    python3 -m pytest tests/test_feedback_correctness_round31.py -q
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import ai_feedback                                          # noqa: E402
import feedback_atoms as fa                                 # noqa: E402
import feedback_copy as fc                                  # noqa: E402
import feedback_core                                        # noqa: E402
import feedback_facts as ff                                 # noqa: E402
import feedback_obligations as ob                           # noqa: E402
import fs_client                                            # noqa: E402

TODAY = date(2026, 9, 10)
HR = [{"num": i, "naam": "z", "low": lo, "high": hi} for i, (lo, hi) in
      enumerate([(110, 130), (130, 145), (145, 169), (169, 179), (179, 200)], 1)]
ZONES = {"zone_type": "hartslag", "zones_text": "z", "zones": HR}

SCHOON = {"complaint_areas": [], "complaint_new": [], "load_active": False, "overall": "READY",
          "has_load": True, "source_gaps": [], "recovery_negative": False, "missed_runs": 0}
KNIE = dict(SCHOON, complaint_areas=["knie"], complaint_new=["knie"])


def _hrblok(z=2):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 1,
            "distUnit": "km", "target": [{"targetType": "hr zone", "zone": z}]}


def _workout(bericht="", diag=None, planned=None, actual=None, leeg=False, **kw):
    n = int(actual) if actual else 6
    laps = [{"amount": 1, "hr_avg": 128, "pace_display": "5:40"} for _ in range(n)]
    act = {"hr_avg": 128, "pace_display": "5:40", "Laps": [] if leeg else laps}
    if leeg:
        act["hr_avg"] = None
    if planned is not None:
        act["planned_amount"] = planned
    if actual is not None:
        act["amount"] = actual
    w = {"workout_type": "run", "workout_key": "W1", "athlete_key": "AK",
         "athlete_name": "Sanne de Vries", "athlete_first_name": "Sanne",
         "workout_name": "Duurloop", "thread": [],
         "workout_date": TODAY.isoformat(), "post_notes": bericht, "athlete_comments": [],
         "details": {"has_structured_workout": not leeg,
                     "description": "" if leeg else "rustige duurloop", "Activities": [act]},
         "_brein_diag": dict(diag if diag is not None else SCHOON)}
    w.update(kw)
    return w


def _beslis(monkeypatch, w, builder=None):
    monkeypatch.setattr(fs_client, "get_workout_builder",
                        lambda wk, ak: builder if builder is not None else [_hrblok()])
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: ZONES)
    return fa.build_decision(w)


def _genereer(monkeypatch, w, llm_uit, builder=None):
    """Het ECHTE productiepad; alleen LLM + FinalSurge gestubd."""
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
    monkeypatch.setattr(fs_client, "get_workout_builder",
                        lambda wk, ak: builder if builder is not None else [_hrblok()])
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: ZONES)
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda *a, **k: None)
    monkeypatch.setattr(ai_feedback, "_generate_text", lambda **kw: llm_uit)
    tekst = feedback_core.genereer(w["workout_key"])
    return tekst, feedback_core.last_generation_status(w["workout_key"])


def _zinnen(t):
    return [z for z in re.split(r"(?<=[.!?])\s+", (t or "").strip()) if z.strip()]


def _heeft_klacht(d):
    return any(a["id"].startswith("complaint_") for a in d["atoms"])


AFGEKEURD = "Fijne rit gehad zo te horen, mooi gedaan."     # RUN-als-'rit' → validator blokkeert


# ══════════════════════════════════════════════════════════════════════════════
# A — een vraag gaat altijd naar REVIEW en blijft in het concept
# ══════════════════════════════════════════════════════════════════════════════
class TestAVraag:
    def test_het_gemelde_geval_gaat_niet_meer_automatisch_de_deur_uit(self, monkeypatch):
        """Zwaar gevoel + negatie + vraag. Vóór R3.1: AUTO_SAFE."""
        d = _beslis(monkeypatch, _workout(
            "Zwaar gevoel vandaag, maar geen last van bovenbeen en knie. Was dit rustig genoeg?",
            diag=KNIE))
        assert d["status"] == fa.REVIEW_REQUIRED
        assert "athlete_question" in d["reasons"]

    def test_een_generiek_zone_antwoord_verklaart_een_vraag_niet_beantwoord(self, monkeypatch):
        """Het antwoord-atoom mag bestaan (de coach kan het gebruiken), maar het mag de vraag
        niet van de reviewstapel halen."""
        d = _beslis(monkeypatch, _workout("Was dit rustig genoeg?"))
        assert d["status"] == fa.REVIEW_REQUIRED
        assert any(a["id"] == "recovery_zone_answer" for a in d["atoms"])

    def test_elke_vraagvorm_telt(self, monkeypatch):
        for vraag in ("Kan ik morgen een lange duurloop doen?",
                      "Moet ik maandag rust nemen?",
                      "Hoe pak ik de volgende training aan?"):
            d = _beslis(monkeypatch, _workout(vraag))
            assert d["status"] == fa.REVIEW_REQUIRED, vraag
            assert "athlete_question" in d["reasons"], vraag

    def test_een_vraag_met_morgen_blijft_in_het_concept(self, monkeypatch):
        """Het dagwoord haalde de hele vraag uit de coachreactie. Een LETTERLIJK toegeschreven
        citaat is geen dagclaim van de coach, dus de vraag blijft nu staan."""
        tekst, status = _genereer(monkeypatch, _workout(
            "Gel viel niet goed en versnellen lukte niet. Kan ik morgen Z1 doen?", leeg=True),
            AFGEKEURD, builder=[])
        assert status == "REVIEW_REQUIRED"
        assert "kan ik morgen z1 doen?" in tekst.lower()
        assert "samen" in tekst.lower()                     # vraagintentie: samen bekijken

    def test_een_vraag_met_een_weekdag_blijft_ook_staan(self, monkeypatch):
        tekst, _ = _genereer(monkeypatch, _workout(
            "Het ging zwaar onderweg. Kan ik maandag de lange duurloop doen?", leeg=True),
            AFGEKEURD, builder=[])
        assert "kan ik maandag de lange duurloop doen?" in tekst.lower()

    def test_de_dagwoordguard_geldt_nog_steeds_voor_coachtekst(self):
        """De uitzondering is smal: alleen binnen aanhalingstekens."""
        assert ff.validate_draft("Ik zou morgen rustig aan doen.", is_running=True)["ok"] is False
        assert ff.validate_draft('Je vraagt: "Kan ik morgen Z1 doen?" Laten we kijken.',
                                 is_running=True)["ok"] is True

    def test_andere_guards_gelden_ook_binnen_een_citaat(self):
        """Sporttaal/interne taal zou de coach alsnog uitspreken — die uitzondering is er niet."""
        assert ff.validate_draft('Je schrijft: "lekker ritje gehad" en dat is mooi.',
                                 is_running=True)["kind"] == "sport"


# ══════════════════════════════════════════════════════════════════════════════
# B — negatie wordt niet omgedraaid
# ══════════════════════════════════════════════════════════════════════════════
class TestBNegatie:
    def test_geen_last_van_knie_geeft_geen_knie_check_in(self, monkeypatch):
        d = _beslis(monkeypatch, _workout("Ging zwaar maar geen last van bovenbeen en knie.",
                                          diag=KNIE))
        assert not _heeft_klacht(d)

    def test_knie_voelde_goed_geeft_geen_check_in(self, monkeypatch):
        d = _beslis(monkeypatch, _workout("Ging zwaar, knie voelde goed.", diag=KNIE))
        assert not _heeft_klacht(d)

    def test_geen_pijn_meer_geeft_geen_check_in(self, monkeypatch):
        d = _beslis(monkeypatch, _workout("Geen pijn meer in mijn knie.", diag=KNIE))
        assert not _heeft_klacht(d)

    def test_actuele_negatie_wint_van_de_canonieke_actieve_klacht(self, monkeypatch):
        """De canonieke state zegt 'knie actief', de atleet zegt vandaag van niet. Voor DEZE
        training is de eigen uitspraak de sterkste bron."""
        stil = _beslis(monkeypatch, _workout("", diag=KNIE))
        ontkend = _beslis(monkeypatch, _workout("Geen last meer van mijn knie.", diag=KNIE))
        assert _heeft_klacht(stil) and not _heeft_klacht(ontkend)

    def test_klacht_vandaag_wel_genoemd_komt_gewoon_mee(self, monkeypatch):
        for melding in ("Mijn knie zeurde onderweg.",
                        "Ging goed maar mijn knie voelde wat gevoelig.",
                        "Last van mijn knie gehad."):
            d = _beslis(monkeypatch, _workout(melding, diag=KNIE))
            assert _heeft_klacht(d), melding

    def test_een_genuanceerd_positief_oordeel_onderdrukt_niets(self, monkeypatch):
        """'goed hersteld MAAR nog wel gevoelig' is geen vrijbrief — ook al staat 'gevoelig'
        niet in enig symptoomvocabulaire."""
        d = _beslis(monkeypatch, _workout("Knie is goed hersteld maar nog wel gevoelig.",
                                          diag=KNIE))
        assert _heeft_klacht(d)

    def test_ontkenning_van_het_ene_deel_raakt_het_andere_niet(self):
        t = "Geen last van mijn knie, wel pijn in mijn kuit."
        assert fc.klacht_ontkracht(t, "knie") is True
        assert fc.klacht_ontkracht(t, "kuit") is False

    def test_bij_twijfel_blijft_de_check_in_staan(self):
        """De onderdrukking mag alleen vuren op AANTOONBARE ontkrachting."""
        for t in ("Mijn knie deed het weer.", "Knie was er ook weer bij.", ""):
            assert fc.klacht_ontkracht(t, "knie") is False, t


# ══════════════════════════════════════════════════════════════════════════════
# C — materiële planafwijking vraagt een coachblik
# ══════════════════════════════════════════════════════════════════════════════
class TestCAfwijking:
    def test_halve_afstand_is_geen_goed_gedaan(self, monkeypatch):
        d = _beslis(monkeypatch, _workout("", planned=12, actual=6))
        assert d["status"] == fa.REVIEW_REQUIRED
        assert "plan_deviation" in d["reasons"]
        assert d["text"] == "" and "Goed gedaan" not in str(d["text"])

    def test_kleine_afwijking_hoeft_niet_naar_review(self, monkeypatch):
        d = _beslis(monkeypatch, _workout("", planned=12, actual=11))     # 8%
        assert d["status"] == fa.AUTO_SAFE

    def test_middelgrote_afwijking_alleen_met_een_tweede_signaal(self, monkeypatch):
        zonder = _beslis(monkeypatch, _workout("", planned=12, actual=10))            # 17%
        met = _beslis(monkeypatch, _workout("", planned=12, actual=10,
                                            diag=dict(SCHOON, recovery_negative=True)))
        assert zonder["status"] == fa.AUTO_SAFE
        assert met["status"] == fa.REVIEW_REQUIRED and "plan_deviation" in met["reasons"]

    def test_gemiste_trainingen_en_belasting_wegen_mee(self, monkeypatch):
        for diag in (dict(SCHOON, missed_runs=2), dict(SCHOON, load_active=True),
                     dict(SCHOON, recovery_negative=True)):
            d = _beslis(monkeypatch, _workout("", diag=diag))
            assert d["status"] == fa.REVIEW_REQUIRED
            assert "context_signal" in d["reasons"]

    def test_de_band_komt_uit_de_ene_centrale_functie(self):
        """Geen tweede drempel: `feedback_core.afwijking` blijft de enige bron."""
        bron = open(os.path.join(_ROOT, "feedback_atoms.py")).read()
        blok = bron[bron.index("_dev_band = \"\""):bron.index("# ── beslissing")]
        assert "from feedback_core import afwijking" in blok
        assert not re.search(r"[<>]=?\s*\d+\s*(#|$)", blok), "eigen percentagedrempel in atoms"

    def test_de_diag_draagt_de_bestaande_signalen_door(self):
        """`recovery_negative` en `missed_runs` worden in de adapter al afgeleid; ze werden
        alleen nooit doorgegeven aan de Feedback-beslissing."""
        ad = open(os.path.join(_ROOT, "pwa", "brain", "adapter.py")).read()
        core = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        for sleutel in ("recovery_negative", "missed_runs"):
            assert f'"{sleutel}"' in ad and f'"{sleutel}"' in core, sleutel


# ══════════════════════════════════════════════════════════════════════════════
# D — AUTO_SAFE blijft bestaan voor de schone case
# ══════════════════════════════════════════════════════════════════════════════
class TestDAutoSafe:
    def test_schone_no_comment_case_blijft_auto_safe(self, monkeypatch):
        d = _beslis(monkeypatch, _workout(""))
        assert d["status"] == fa.AUTO_SAFE
        assert "hartslag" in d["text"].lower()

    def test_elk_van_de_signalen_haalt_auto_safe_weg(self, monkeypatch):
        gevallen = {
            "vraag": _workout("Was dit rustig genoeg?"),
            "klacht": _workout("Mijn knie zeurde onderweg.", diag=KNIE),
            "afwijking": _workout("", planned=12, actual=6),
            "context": _workout("", diag=dict(SCHOON, missed_runs=1)),
        }
        for naam, w in gevallen.items():
            assert _beslis(monkeypatch, w)["status"] == fa.REVIEW_REQUIRED, naam

    def test_auto_safe_blijft_uitsluitend_uit_geregistreerde_atomen_bestaan(self, monkeypatch):
        d = _beslis(monkeypatch, _workout(""))
        assert fa._final_is_atoms_only(d["text"], d["atoms"]) is True


# ══════════════════════════════════════════════════════════════════════════════
# E — de atleet wordt rechtstreeks aangesproken
# ══════════════════════════════════════════════════════════════════════════════
GEMELD_E = "Leuk dat ze haar vriendin een eerste 7 km heeft laten lopen."


class TestEPerspectief:
    def test_het_gemelde_geval_wordt_herkend(self):
        assert fc.derde_persoon_atleet(GEMELD_E) is True

    def test_directe_aanspreekvorm_is_gewoon_goed(self):
        for goed in ("Leuk dat je met je vriendin haar eerste 7 km hebt gelopen.",
                     "Mooi gelopen, lekker rustig gebleven.",
                     "Je vriendin liep sterk, zij hield het tempo goed vast."):
            assert fc.derde_persoon_atleet(goed) is False, goed
            assert ff.validate_draft(goed, is_running=True)["ok"] is True, goed

    def test_de_validator_houdt_het_tegen(self):
        assert ff.validate_draft(GEMELD_E, is_running=True)["detail"] == "atleet_derde_persoon"

    def test_de_coach_krijgt_alsnog_een_bruikbaar_concept(self, monkeypatch):
        tekst, status = _genereer(monkeypatch, _workout(
            "Vandaag met een vriendin gelopen, ging lekker.", leeg=True), GEMELD_E, builder=[])
        assert status == "REVIEW_REQUIRED"
        assert not fc.derde_persoon_atleet(tekst)
        assert not fc.is_generieke_erkenning(tekst)

    def test_de_prompt_legt_de_aanspreekvorm_structureel_vast(self):
        for prompt in (ai_feedback.SYSTEM_PROMPT, ai_feedback._NONRUN_SYSTEM):
            assert '"je"' in prompt and '"ze"' in prompt
        assert "WIE JE AANSPREEKT" in ai_feedback.SYSTEM_PROMPT
        assert "je vriendin" in ai_feedback.SYSTEM_PROMPT   # derde persoon over een ANDER mag


# ══════════════════════════════════════════════════════════════════════════════
# F — de lengte volgt de input
# ══════════════════════════════════════════════════════════════════════════════
LANG = ("Dank je voor je uitgebreide bericht. Het klinkt als een rommelige sessie en dat is "
        "vervelend. Op hartslag bleef je netjes in het rustige bereik, rond de 128 slagen. "
        "Wat betreft de gel, voeding is iets om rustig mee te experimenteren, want je maag "
        "moet er aan wennen en dat kost weken. Ik zou kleinere hoeveelheden proberen en die "
        "spreiden over de duur. Een rustige sessie kan prima, maar houd er rekening mee dat "
        "we in de taperfase zitten. Daarnaast is herstel nu belangrijker dan extra prikkels, "
        "dus slaap en voeding verdienen aandacht. Laat het weten als er iets verandert.")
RIJK = ("Gel viel niet goed en versnellen lukte niet. Mijn kuit voelde stijf na vijf kilometer. "
        "Ik heb slecht geslapen deze week. Kan ik zaterdag toch de lange duurloop doen? "
        "En moet ik iets aan mijn voeding veranderen?")


class TestFLengte:
    def test_er_is_geen_vaste_zinnenlimiet_meer(self):
        bron = open(os.path.join(_ROOT, "feedback_copy.py")).read()
        assert "_VRIJE_ZINNEN" not in bron                  # de harde cap uit R3 is weg
        assert "def _budget(" in bron                       # budget volgt de input

    def test_weinig_input_geeft_een_kort_concept(self):
        assert len(_zinnen(fc.clean_draft(LANG, athlete_text=""))) <= 3
        assert len(_zinnen(fc.clean_draft(LANG, athlete_text="Gel viel niet goed."))) <= 5

    def test_rijke_input_mag_langer_dan_vijf_zinnen(self):
        uit = fc.clean_draft(LANG, athlete_text=RIJK)
        assert len(_zinnen(uit)) > 5
        assert uit.strip() == LANG.strip()                  # geen kunstmatige afkapping

    def test_wat_sneuvelt_is_wat_het_minst_met_de_atleet_te_maken_heeft(self):
        """Coverage vóór brevity: de zin over de gel overleeft als de atleet over de gel schreef."""
        met_gel = fc.clean_draft(LANG, athlete_text="Gel viel niet goed.")
        zonder = fc.clean_draft(LANG, athlete_text="Mijn kuit voelde stijf.")
        assert "gel" in met_gel.lower() and "gel" not in zonder.lower()

    def test_de_slotzin_blijft_altijd_staan(self):
        for ber in ("", "Gel viel niet goed.", RIJK):
            assert fc.clean_draft(LANG, athlete_text=ber).rstrip().endswith(
                "Laat het weten als er iets verandert."), ber

    def test_beschermde_feitzinnen_worden_nooit_gesnoeid(self):
        uit = fc.clean_draft("Een. Feit A. Twee. Drie. Vier. Vijf. Zes. Feit B. Zeven.",
                             protected=["Feit A.", "Feit B."])
        assert "Feit A." in uit and "Feit B." in uit

    def test_de_prompt_zet_dekking_boven_kortheid(self):
        p = ai_feedback.SYSTEM_PROMPT
        assert "DEKKING GAAT VÓÓR KORTHEID" in p
        assert "Weinig input" in p and "langer" in p
        blok = ob.build(modality="hartslag", shares={"Z1": 95}, athlete_text=RIJK)
        assert "nooit wegvallen" in blok["prompt_block"]


# ══════════════════════════════════════════════════════════════════════════════
# G — Round 2 en Round 3 blijven staan
# ══════════════════════════════════════════════════════════════════════════════
class TestGEerdereRondes:
    def test_historische_klacht_komt_niet_spontaan_terug(self, monkeypatch):
        d = _beslis(monkeypatch, _workout("", diag=dict(SCHOON, complaint_areas=["knie"])))
        assert not _heeft_klacht(d)                         # wel in areas, niet in complaint_new

    def test_coachstem_blijft_gelden(self):
        derde = "Dit moet de coach eerst met je bespreken."
        assert ff.validate_draft(derde, is_running=True)["detail"] == "coach_derde_persoon"
        assert fc.naar_coachstem(derde) == fc.COACH_DELEGATIE_ZIN

    def test_overclaim_guard_blijft_gelden(self):
        assert ff.plan_toezegging("We passen je lange duurloop aan.") is True
        assert ff.plan_toezegging("Als we je schema aanpassen laat ik het weten.") is False

    def test_quality_gate_blijft_echte_fouten_blokkeren(self):
        assert ff.validate_draft("Fijne rit gehad.", is_running=True)["kind"] == "sport"
        assert ff.validate_draft("Je zat 40% in zone 2.", is_running=True)["ok"] is False

    def test_terugval_blijft_bruikbaar(self, monkeypatch):
        tekst, status = _genereer(monkeypatch, _workout(
            "Gel viel niet goed en versnellen lukte niet.", leeg=True), AFGEKEURD, builder=[])
        assert status == "REVIEW_REQUIRED"
        assert "gel viel niet goed" in tekst.lower()

    def test_athlete_first_blijft_gelden(self, monkeypatch):
        d = _beslis(monkeypatch, _workout("Voelde me niet fit vandaag, hoofdpijn, toch gelopen."))
        assert d["status"] == fa.REVIEW_REQUIRED

    def test_een_correct_concept_komt_er_gewoon_door(self, monkeypatch):
        goed = "Dat klinkt als een rommelige sessie. Hou het de komende dagen rustig."
        tekst, _ = _genereer(monkeypatch, _workout("Gel viel niet goed onderweg."), goed)
        assert tekst.strip() == goed.strip()
