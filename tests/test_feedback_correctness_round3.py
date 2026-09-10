"""Feedback Correctness Round 3 — nuttig, in de eigen stem van de coach, en kort (10 sep 2026).

Drie live-gemelde symptomen, alle drie eerst gereproduceerd op het ECHTE pad:

  1. Bij een inhoudelijke atleetreactie kwam er als concept alleen
     'Dank je voor je bericht, ik neem mee wat je over deze training schrijft.'
     `safe_fallback` bouwde uitsluitend uit de eigen ATOMEN van de app. Had een training geen
     bruikbare atomen (geen structuur, geen laps), dan bleef letterlijk die ene neutrale zin
     over — terwijl de atleet net drie dingen had gemeld.
  2. 'dit is een beslissing die de coach zelf met je door moet nemen voordat hij iets aanpast
     in het schema.' De systeemprompt zette de schrijver NAAST de coach ('je schrijft namens
     een hardloopcoach ... de coach heet Jip ... neem zijn TOON over') en zei nergens dat je
     de coach BENT. Noch `clean_draft` noch `validate_draft` had er een regel over: beide
     lieten die zin ongemoeid door.
  3. Concepten van negen zinnen over voeding, taper, herstel én een schemawijziging. Lengte
     was uitsluitend een promptinstructie, in een prompt vol voorwaardelijke 'noem dit ook'-
     regels plus een bindend verplichtingenblok. Niets in de deterministische keten begrensde
     de lengte, en de aankondiging 'we passen je lange duurloop aan' werd nergens getoetst.

Round 2 blijft gelden en staat hieronder onder F expliciet opnieuw vast.

    python3 -m pytest tests/test_feedback_correctness_round3.py -q
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
_RUSTIG = [{"amount": 1, "hr_avg": 128, "pace_display": "5:40"} for _ in range(6)]


def _hrblok(z=2):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 1,
            "distUnit": "km", "target": [{"targetType": "hr zone", "zone": z}]}


def _workout(bericht="", leeg=False, **kw):
    """`leeg=True` = een training zonder bruikbare uitvoeringsdata → geen atomen."""
    details = ({"has_structured_workout": False, "description": "",
                "Activities": [{"hr_avg": None, "pace_display": "", "Laps": []}]} if leeg else
               {"has_structured_workout": True, "description": "rustige duurloop",
                "Activities": [{"hr_avg": 128, "pace_display": "5:40", "Laps": _RUSTIG}]})
    w = {"workout_type": "run", "workout_key": "W1", "athlete_key": "AK",
         "athlete_name": "Sanne de Vries", "athlete_first_name": "Sanne",
         "workout_name": "Duurloop", "thread": [],
         "workout_date": TODAY.isoformat(), "post_notes": bericht, "athlete_comments": [],
         "details": details}
    w.update(kw)
    return w


def _genereer(monkeypatch, w, llm_uit, builder=None):
    """Het ECHTE productiepad (`feedback_core.genereer`); alleen LLM + FinalSurge gestubd."""
    feedback_core._cache.clear()
    feedback_core._cache[w["workout_key"]] = w
    feedback_core._GEN_STATUS.pop(w["workout_key"], None)
    monkeypatch.setattr(feedback_core, "_brein_context", lambda x: "")
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


# De acceptancecase uit de opdracht: rommelige training, gel, en een vraag over de volgende dag.
CASE1 = ("Gel viel niet goed, ik moest halverwege omdraaien en versnellen lukte niet. "
         "Kan ik morgen Z1 doen?")
CASE1_ZONDER_VRAAG = "Gel viel niet goed, ik moest halverwege omdraaien en versnellen lukte niet."
# Een concept dat de validator afkeurt (RUN mag geen 'rit' heten) → het terugvalpad in.
AFGEKEURD = "Fijne rit gehad zo te horen, mooi gedaan."


# ══════════════════════════════════════════════════════════════════════════════
# A — minimum usefulness: nooit alleen een bedankzin bij een inhoudelijk bericht
# ══════════════════════════════════════════════════════════════════════════════
class TestAMinimumUsefulness:
    def test_het_gemelde_geval_reproduceert_zonder_de_fix(self):
        """Bewijs van de oorzaak: zonder citaat blijft er precies één neutrale zin over."""
        assert fa.safe_fallback([], CASE1_ZONDER_VRAAG, citeer=False) == fa._ACK_TEXT

    def test_terugval_noemt_een_concreet_punt_uit_het_bericht(self):
        uit = fa.safe_fallback([], CASE1_ZONDER_VRAAG)
        assert uit != fa._ACK_TEXT
        assert "gel viel niet goed" in uit.lower()

    def test_alleen_een_bedankzin_is_een_leeg_concept(self):
        assert fc.is_generieke_erkenning(fa._ACK_TEXT) is True
        assert fc.is_generieke_erkenning("Bedankt voor je bericht!") is True
        assert fc.is_generieke_erkenning("Dank je voor je bericht. Op hartslag bleef je rustig.") is False
        assert fc.is_generieke_erkenning("Dat ging lastig zo te horen.") is False

    def test_volledige_pijplijn_geeft_geen_lege_erkenning_meer(self, monkeypatch):
        """Het live-gemelde geval, end to end: inhoudelijk bericht + afgekeurd concept +
        een training zonder bruikbare data."""
        tekst, status = _genereer(monkeypatch, _workout(CASE1_ZONDER_VRAAG, leeg=True),
                                  AFGEKEURD, builder=[])
        assert status == "REVIEW_REQUIRED"
        assert not fc.is_generieke_erkenning(tekst)
        assert "gel viel niet goed" in tekst.lower()

    def test_een_geldig_maar_leeg_concept_wordt_alsnog_opgewaardeerd(self, monkeypatch):
        """Een bedankzin die de validator gewoon HAALT is ook niet goed genoeg."""
        tekst, _ = _genereer(monkeypatch, _workout(CASE1_ZONDER_VRAAG, leeg=True),
                             "Dank je voor je bericht.", builder=[])
        assert not fc.is_generieke_erkenning(tekst)
        assert "gel viel niet goed" in tekst.lower()

    def test_zonder_inhoudelijk_bericht_blijft_alles_zoals_het_was(self, monkeypatch):
        """Geen atleettekst → geen opening, geen opwaardering: data mag leiden."""
        assert fa.safe_fallback([], "") == ""
        assert fa.safe_fallback([], "top") == ""

    def test_citaat_is_letterlijk_en_wordt_niet_geinterpreteerd(self):
        for zin in fc.kernpunten(CASE1):
            assert zin.rstrip(".") in CASE1 or zin.endswith("...")


# ══════════════════════════════════════════════════════════════════════════════
# B — een vraag van de atleet blijft niet liggen
# ══════════════════════════════════════════════════════════════════════════════
class TestBVraag:
    def test_een_vraag_wint_van_de_rest_van_het_bericht(self):
        assert fc.kernpunten(CASE1)[0] == "Kan ik morgen Z1 doen?"

    def test_de_terugval_zet_een_vraag_om_in_een_vervolgstap(self):
        uit = fa.safe_fallback([], "Kan ik deze week nog een lange duurloop doen?")
        assert "Kan ik deze week nog een lange duurloop doen?" in uit
        assert "samen" in uit.lower()                       # voorwaardelijke stap, geen toezegging

    def test_een_vraag_die_zelf_een_guard_raakt_kost_de_inhoud_niet(self, monkeypatch):
        """'morgen' botst met de dagwoord-guard. Dan pakt de terugval de VOLGENDE zin uit
        hetzelfde bericht — niet de generieke bedankzin."""
        tekst, _ = _genereer(monkeypatch, _workout(CASE1, leeg=True), AFGEKEURD, builder=[])
        assert "morgen" not in tekst.lower()                # guard blijft gelden
        assert not fc.is_generieke_erkenning(tekst)
        assert "gel viel niet goed" in tekst.lower()

    def test_de_generatie_krijgt_de_opdracht_de_vraag_te_beantwoorden(self):
        blok = ob.build(modality="hartslag", shares={"Z1": 95}, athlete_text=CASE1)
        assert "directe vraag" in blok["prompt_block"]


# ══════════════════════════════════════════════════════════════════════════════
# C — coachstem: nooit over 'de coach' als derde persoon
# ══════════════════════════════════════════════════════════════════════════════
GEMELD = ("Dit is een beslissing die de coach zelf met je door moet nemen voordat hij "
          "iets aanpast in het schema.")


class TestCCoachstem:
    def test_het_gemelde_geval_wordt_herkend(self):
        assert fc.derde_persoon_coach(GEMELD) is True

    def test_eerste_persoon_blijft_ongemoeid(self):
        for goed in ("Ik wil dit eerst met je bespreken voordat ik iets verander.",
                     "Als je coach wil ik hier eerst even naar kijken.",
                     "Ik ben je coach, dus ik kijk mee.",
                     "Laten we hier samen naar kijken."):
            assert fc.derde_persoon_coach(goed) is False, goed
            assert fc.naar_coachstem(goed) == goed

    def test_de_intentie_blijft_behouden_bij_omzetting(self):
        """Niet schrappen maar OMZETTEN: de bedoeling (eerst samen bespreken) blijft staan,
        nu in directe coachstem."""
        uit = fc.naar_coachstem(GEMELD)
        assert not fc.derde_persoon_coach(uit)
        assert uit == fc.COACH_DELEGATIE_ZIN
        assert uit.lower().startswith("laten we") and "samen" in uit.lower()

    def test_omliggende_zinnen_blijven_staan(self):
        t = "Mooi gelopen zo te horen. " + GEMELD + " Hou het verder rustig."
        uit = fc.naar_coachstem(t)
        assert uit.startswith("Mooi gelopen zo te horen.")
        assert uit.endswith("Hou het verder rustig.")
        assert not fc.derde_persoon_coach(uit)

    def test_meerdere_derdepersoonszinnen_worden_er_samen_een(self):
        t = "De coach kan dit aanpassen. Bespreek dit verder met je coach."
        assert fc.naar_coachstem(t) == fc.COACH_DELEGATIE_ZIN

    def test_de_validator_is_het_fail_closed_vangnet(self):
        assert ff.validate_draft(GEMELD, is_running=True)["detail"] == "coach_derde_persoon"
        assert ff.validate_draft(fc.COACH_DELEGATIE_ZIN, is_running=True)["ok"] is True

    def test_volledige_pijplijn_levert_coachstem(self, monkeypatch):
        """De pijplijn moet OMZETTEN, niet blokkeren: de bedoeling van de zin blijft staan.
        Zonder de omzetting in `clean_draft` zou de validator hem afkeuren en verdween de
        inhoud in het terugvalconcept — dan is de coachstem wel goed maar de intentie weg."""
        tekst, _ = _genereer(monkeypatch, _workout(CASE1_ZONDER_VRAAG), GEMELD)
        assert not fc.derde_persoon_coach(tekst)
        assert "de coach" not in tekst.lower()
        assert fc.COACH_DELEGATIE_ZIN in tekst              # intentie behouden, niet weggegooid

    def test_de_prompt_legt_de_rol_structureel_vast(self):
        """De echte oorzaak zat in de rolbeschrijving, niet in een ontbrekende filter."""
        for prompt in (ai_feedback.SYSTEM_PROMPT, ai_feedback._NONRUN_SYSTEM):
            assert "IK-VORM" in prompt
            assert "je coach" in prompt                     # expliciet als VERBOD benoemd
        assert "JIJ BENT" in ai_feedback.SYSTEM_PROMPT
        assert "namens een hardloopcoach" not in ai_feedback.SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════════════════════════
# D — kort en gefocust
# ══════════════════════════════════════════════════════════════════════════════
LANG = ("Dank je voor je uitgebreide bericht. Het klinkt als een rommelige sessie en dat is "
        "vervelend. Op hartslag bleef je netjes in het rustige bereik, rond de 128 slagen. "
        "Wat betreft de gel, voeding is iets om rustig mee te experimenteren, want je maag "
        "moet er aan wennen en dat kost weken. Ik zou kleinere hoeveelheden proberen en die "
        "spreiden over de duur. Een rustige sessie kan prima, maar houd er rekening mee dat "
        "we in de taperfase zitten. Daarnaast is herstel nu belangrijker dan extra prikkels, "
        "dus slaap en voeding verdienen aandacht. Laat het weten als er iets verandert.")


class TestDLengte:
    def test_een_uitgelopen_concept_wordt_teruggebracht_tot_de_kern(self, monkeypatch):
        assert len(_zinnen(LANG)) == 8
        tekst, _ = _genereer(monkeypatch, _workout(CASE1_ZONDER_VRAAG), LANG)
        assert len(_zinnen(tekst)) <= 5

    def test_de_slotzin_blijft_altijd_staan(self, monkeypatch):
        """Daar zit de vervolgstap of de check-in; een bericht dat abrupt ophoudt is erger."""
        tekst, _ = _genereer(monkeypatch, _workout(CASE1_ZONDER_VRAAG), LANG)
        assert tekst.rstrip().endswith("Laat het weten als er iets verandert.")

    def test_een_normale_reactie_wordt_niet_aangeraakt(self, monkeypatch):
        kort = ("Dat klinkt als een rommelige sessie. Fijn dat je toch bent gegaan. "
                "Hou het de komende dagen rustig.")
        tekst, _ = _genereer(monkeypatch, _workout(CASE1_ZONDER_VRAAG), kort)
        assert tekst.strip() == kort.strip()

    def test_verplichte_feitzinnen_verhogen_de_ruimte(self):
        """Complexere cases hebben per constructie meer verplichte zinnen en krijgen dus meer
        ruimte — geen vaste tekenlimiet die een nuttig antwoord afkapt."""
        vrij = "Een. Twee. Drie. Vier. Vijf. Zes. Zeven."
        assert len(_zinnen(fc.clean_draft(vrij))) == 5
        met_feiten = "Een. Feit A. Twee. Drie. Vier. Vijf. Zes. Feit B. Zeven."
        uit = fc.clean_draft(met_feiten, protected=["Feit A.", "Feit B."])
        assert len(_zinnen(uit)) == 9                       # niets geschrapt
        assert "Feit A." in uit and "Feit B." in uit

    def test_geen_tekenlimiet_in_de_opschoning(self):
        """Een harde cap zou een nuttig antwoord middenin afkappen; er wordt op ZINNEN gesneden."""
        bron = open(os.path.join(_ROOT, "feedback_copy.py")).read()
        start = bron.index("def _focus(")
        blok = bron[start:bron.index("\ndef ", start + 1)]
        assert "[:_" not in blok and "len(text)" not in blok

    def test_de_prompt_zegt_dat_verplichtingen_geen_inhoudsopgave_zijn(self):
        assert "GEEN inhoudsopgave" in ai_feedback.SYSTEM_PROMPT
        assert "mini-rapport" in ai_feedback.SYSTEM_PROMPT
        blok = ob.build(modality="hartslag", shares={"Z1": 95}, athlete_text=CASE1)
        assert "geen inhoudsopgave" in blok["prompt_block"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# E — geen overclaim over het plan
# ══════════════════════════════════════════════════════════════════════════════
class TestEOverclaim:
    def test_een_aangekondigde_schemawijziging_wordt_geblokkeerd(self):
        for claim in ("We passen je lange duurloop aan zodat je fris aan de start staat.",
                      "Ik verplaats die training in je schema.",
                      "Je taper moet starten.",
                      "We schrappen de intervaltraining uit je programma."):
            assert ff.plan_toezegging(claim) is True, claim
            assert ff.validate_draft(claim, is_running=True)["detail"] == "plan_toezegging"

    def test_voorwaardelijke_coachtaal_blijft_gewoon_toegestaan(self):
        for goed in ("Als we je schema aanpassen laat ik het weten.",
                     "Ik zou het schema voorlopig laten staan.",
                     "Misschien verplaatsen we die duurloop, laten we het even bekijken.",
                     "Laten we dit eerst samen doornemen voordat we iets veranderen."):
            assert ff.plan_toezegging(goed) is False, goed
            assert ff.validate_draft(goed, is_running=True)["ok"] is True, goed

    def test_de_coach_krijgt_alsnog_een_bruikbaar_concept(self, monkeypatch):
        """Blokkeren mag nooit eindigen in een lege composer."""
        tekst, status = _genereer(
            monkeypatch, _workout(CASE1_ZONDER_VRAAG),
            LANG.replace("Laat het weten als er iets verandert.",
                         "We passen je lange duurloop aan zodat je fris aan de start staat."))
        assert status == "REVIEW_REQUIRED"
        assert not ff.plan_toezegging(tekst)
        assert not fc.is_generieke_erkenning(tekst)

    def test_de_prompt_verbiedt_de_aankondiging_ook_structureel(self):
        assert "als besloten feit" in ai_feedback.SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════════════════════════
# F — Round 2 blijft staan
# ══════════════════════════════════════════════════════════════════════════════
NIET_FIT = "Voelde me niet fit vandaag, hoofdpijn, toch maar gelopen."


class TestFRound2Blijft:
    def _beslis(self, monkeypatch, w, builder=None):
        monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: builder or [_hrblok()])
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: ZONES)
        return fa.build_decision(w)

    def test_athlete_first_inhoudelijk_bericht_gaat_naar_review(self, monkeypatch):
        d = self._beslis(monkeypatch, _workout(NIET_FIT))
        assert d["status"] == fa.REVIEW_REQUIRED
        assert "athlete_message_unaddressed" in d["reasons"]

    def test_zonder_bericht_mag_data_leiden(self, monkeypatch):
        d = self._beslis(monkeypatch, _workout(""))
        assert d["status"] == fa.AUTO_SAFE and "hartslag" in d["text"].lower()

    def test_historische_klacht_komt_niet_spontaan_terug(self):
        """De signaal-verplichting vuurt alleen op de canoniek ACTUELE klachtenset."""
        stil = ob.build(modality="hartslag", shares={"Z1": 95}, athlete_text="",
                        complaint_areas=[], intensity_high=True)
        assert "ACTIEVE klacht" not in stil["prompt_block"]

    def test_actuele_klacht_mag_neutraal_mee(self):
        blok = ob.build(modality="hartslag", shares={"Z1": 95}, athlete_text="",
                        complaint_areas=["knie"], intensity_high=True)
        assert "ACTIEVE klacht (knie)" in blok["prompt_block"]
        assert "geen diagnose" in blok["prompt_block"]

    def test_de_gate_blokkeert_nog_steeds_echte_fouten(self):
        assert ff.validate_draft("Fijne rit gehad.", is_running=True)["kind"] == "sport"
        assert ff.validate_draft("De blokmatch was niet strak.", is_running=True)["ok"] is False
        assert ff.validate_draft("Je zat 40% in zone 2.", is_running=True)["ok"] is False

    def test_een_correct_concept_komt_er_gewoon_door(self, monkeypatch):
        goed = "Dat klinkt als een rommelige sessie. Hou het de komende dagen rustig."
        tekst, _ = _genereer(monkeypatch, _workout(NIET_FIT), goed)
        assert tekst.strip() == goed.strip()

    def test_de_terugval_prijst_de_hartslag_niet_automatisch(self):
        atomen = [fa._atom("fit", "Op hartslag bleef je netjes binnen het rustige bereik.",
                           "plan_execution", 60),
                  fa._atom("positive_close", "Goed gedaan.", "close", 10)]
        uit = fa.safe_fallback(atomen, NIET_FIT)
        assert "Goed gedaan" not in uit
        assert not uit.startswith("Op hartslag")

    def test_de_erkenning_kan_nooit_zelf_auto_safe_maken(self):
        bron = open(os.path.join(_ROOT, "feedback_atoms.py")).read()
        content = bron[bron.index("    content = [a for a in atoms"):]
        assert '"ack"' not in content.split("status = AUTO_SAFE")[0]
