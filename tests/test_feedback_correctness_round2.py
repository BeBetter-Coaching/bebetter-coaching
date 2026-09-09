"""Feedback Correctness Round 2 — atleetopmerking eerst, klachtrecentie, en een gate die
alleen echte fouten tegenhoudt.

Drie live-gemelde symptomen, alle drie gereproduceerd vóór de fix:

  1. 'Concept geblokkeerd — inhoudelijke controle niet gehaald.' De CopyQuality-opschoning
     (`feedback_copy.clean_draft`) schrapte een APPLICATION-OWNED feitzin die de fail-closed
     validator (`feedback_facts.validate_draft`) VERBATIM eist. Twee contracten uit
     verschillende builds botsten: schreef het model zelf een variant van de klacht-check-in,
     dan won die en verdween de app-zin — waarna het inhoudelijk PRIMA concept blokkeerde.
  2. Een AUTO_SAFE-concept bestaat uitsluitend uit DATA-atomen over de training. Het bericht
     van de atleet stuurde de beslissing alleen via vraag/afwezigheid/lichaamsdeel; al het
     andere was onzichtbaar. 'Niet fit, hoofdpijn, toch gelopen' leverde daarom letterlijk
     dezelfde tekst op als géén bericht: 'Op hartslag bleef je netjes binnen het rustige
     bereik. Goed gedaan.'
  3. De ACTUEEL-signaal-escalatie in de Masterbrein-promptcontext vuurde op ELKE klacht in de
     context (ook een puur TERUGKEREND patroon zonder recente melding) en sprak daarmee de
     klacht-guard twee zinnen eerder rechtstreeks tegen — waarna een klacht van weken terug
     opnieuw in de reactie belandde.

Alles draait door de ECHTE functies: `feedback_core.genereer`, de echte atoom-beslissing, de
echte brain-keten (complaints -> for_feedback -> feedback_context). Alleen de LLM en de
FinalSurge/gather-bron zijn gestubd; er zit geen shim om het verdachte pad heen.

    python3 -m pytest tests/test_feedback_correctness_round2.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

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
from brain import adapter                                   # noqa: E402

TODAY = date(2026, 9, 9)

HR = [{"num": i, "naam": "z", "low": lo, "high": hi} for i, (lo, hi) in
      enumerate([(110, 130), (130, 145), (145, 169), (169, 179), (179, 200)], 1)]
ZONES = {"zone_type": "hartslag", "zones_text": "z", "zones": HR}


def _hrblok(z=2):
    return {"intensity": "ACTIVE", "durationType": "DISTANCE", "durationDist": 1,
            "distUnit": "km", "target": [{"targetType": "hr zone", "zone": z}]}


_RUSTIG = [{"amount": 1, "hr_avg": 128, "pace_display": "5:40"} for _ in range(6)]


def _workout(bericht="", **kw):
    w = {"workout_type": "run", "workout_key": "W1", "athlete_key": "AK",
         "athlete_name": "Sanne de Vries", "athlete_first_name": "Sanne",
         "workout_name": "Duurloop", "thread": [],
         "workout_date": TODAY.isoformat(), "post_notes": bericht, "athlete_comments": [],
         "details": {"has_structured_workout": True, "description": "rustige duurloop",
                     "Activities": [{"hr_avg": 128, "pace_display": "5:40", "Laps": _RUSTIG}]}}
    w.update(kw)
    return w


def _beslis(monkeypatch, w, builder=None):
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: builder or [_hrblok()])
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: ZONES)
    return fa.build_decision(w)


def _genereer(monkeypatch, w, llm_uit, builder=None, brein=""):
    """Het ECHTE productiepad (`feedback_core.genereer`); alleen LLM + FinalSurge gestubd."""
    feedback_core._cache.clear()
    feedback_core._cache[w["workout_key"]] = w
    feedback_core._GEN_STATUS.pop(w["workout_key"], None)
    monkeypatch.setattr(feedback_core, "_brein_context", lambda x: brein)
    monkeypatch.setattr(feedback_core, "_timeline_rows", lambda x: [])
    monkeypatch.setattr(feedback_core, "_refresh_thread", lambda x: None)
    monkeypatch.setattr(feedback_core, "_session_context", lambda x: "")
    monkeypatch.setattr(feedback_core, "_ensure_details", lambda wid: None)
    monkeypatch.setattr(fs_client, "get_workout_builder", lambda wk, ak: builder or [_hrblok()])
    monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: ZONES)
    monkeypatch.setattr(fs_client, "get_fastest_activity_on_day", lambda *a, **k: None)
    monkeypatch.setattr(ai_feedback, "_generate_text", lambda **kw: llm_uit)
    tekst = feedback_core.genereer(w["workout_key"])
    return tekst, feedback_core.last_generation_status(w["workout_key"])


# ══════════════════════════════════════════════════════════════════════════════
# A — inhoudelijke atleetreactie stuurt het concept (data blijft ondersteunend)
# ══════════════════════════════════════════════════════════════════════════════
NIET_FIT = "Voelde me niet fit vandaag, hoofdpijn, toch maar gelopen."


class TestAInhoudelijkeReactie:
    def test_rustige_data_plus_melding_is_niet_automatisch_verstuurbaar(self, monkeypatch):
        """Het gemelde geval. De data is netjes, maar een bericht dat alleen de hartslag
        prijst is geen antwoord op 'niet fit, hoofdpijn'."""
        d = _beslis(monkeypatch, _workout(NIET_FIT))
        assert d["status"] == fa.REVIEW_REQUIRED
        assert "athlete_message_unaddressed" in d["reasons"]

    def test_zonder_de_melding_is_precies_dezelfde_training_wel_auto_safe(self, monkeypatch):
        """Bewijst dat het aan het BERICHT ligt en niet aan de trainingsdata: vóór de fix
        gaven beide gevallen letterlijk dezelfde tekst."""
        d = _beslis(monkeypatch, _workout(""))
        assert d["status"] == fa.AUTO_SAFE
        assert "hartslag" in d["text"].lower()

    def test_de_generatie_krijgt_de_opdracht_om_op_de_atleet_aan_te_sluiten(self):
        blok = ob.build(modality="hartslag", shares={"Z1": 95, "Z2": 5}, athlete_text=NIET_FIT)
        assert "BERICHT-VERPLICHTINGEN" in blok["prompt_block"]
        assert "startpunt van je reactie" in blok["prompt_block"]
        assert "ONDERSTEUNEND bewijs" in blok["prompt_block"]

    def test_samengestelde_klachtwoorden_worden_herkend(self):
        """'hoofdpijn' viel door `\\bpijn\\b` buiten élke herkenning; het Nederlands plakt de
        klacht aan het lichaamsdeel. Een woordgrens die het echte vocabulaire uitsluit is een
        fout in de grens — geen reden om woorden te gaan opsommen."""
        for woord in ("hoofdpijn", "spierpijn", "buikpijn", "pijn"):
            # bewust ZONDER omringende triggerwoorden ('last van' zit zelf ook in het patroon),
            # anders zou de test slagen zonder dat het klachtwoord herkend wordt
            zin = f"onderweg kreeg ik {woord} en toen werd het zwaar"
            assert ob._PAIN_RE.search(zin), woord
            assert fc.classify_intent(zin)["complaint_active"], woord
        assert not ob._PAIN_RE.search("onderweg ging het prima en het liep soepel")

    def test_eind_tot_eind_reageert_het_concept_op_de_atleet(self, monkeypatch):
        tekst, status = _genereer(
            monkeypatch, _workout(NIET_FIT),
            "Vervelend dat je je niet fit voelde; knap dat je toch bent gegaan.")
        assert status == "REVIEW_REQUIRED"
        assert "niet fit" in tekst.lower()


# ══════════════════════════════════════════════════════════════════════════════
# B — positieve reactie: aansluiten, data mag ondersteunen
# ══════════════════════════════════════════════════════════════════════════════
BETER = "Ging een stuk beter dan vorige week, het liep redelijk soepel."


class TestBPositieveReactie:
    def test_positieve_melding_gaat_ook_langs_de_coach(self, monkeypatch):
        d = _beslis(monkeypatch, _workout(BETER))
        assert d["status"] == fa.REVIEW_REQUIRED
        assert "athlete_message_unaddressed" in d["reasons"]

    def test_concept_sluit_aan_en_mag_de_data_gebruiken(self, monkeypatch):
        tekst, _ = _genereer(monkeypatch, _workout(BETER),
                             "Fijn dat het soepeler liep dan vorige week. Je hartslag bleef "
                             "netjes in het rustige bereik, precies de bedoeling.")
        assert "soepeler" in tekst.lower()                    # sluit aan op de atleet
        assert "hartslag" in tekst.lower()                    # data mag ondersteunen

    def test_korte_beleefdheid_blijft_gewoon_auto_safe(self, monkeypatch):
        """'lekker gelopen' is geen inhoudelijke melding; dat mag de bestaande snelle route
        niet dichtzetten (anders wordt élke reactie review-werk)."""
        assert _beslis(monkeypatch, _workout("lekker gelopen"))["status"] == fa.AUTO_SAFE
        assert fc.is_substantive("lekker gelopen") is False
        assert fc.is_substantive(NIET_FIT) is True


# ══════════════════════════════════════════════════════════════════════════════
# C — geen commentaar: de training/gebeurtenis mag gewoon leiden
# ══════════════════════════════════════════════════════════════════════════════
class TestCGeenCommentaar:
    def test_zonder_bericht_leidt_de_data(self, monkeypatch):
        d = _beslis(monkeypatch, _workout(""))
        assert d["status"] == fa.AUTO_SAFE and d["text"]
        assert fc.classify_intent("")["primary"] == fc.REVIEW_DATA

    def test_zonder_bericht_geen_erkenningsopening(self):
        atomen = [fa._atom("fit", "Op hartslag bleef je netjes binnen het rustige bereik.",
                           "plan_execution", 60)]
        assert "Dank je voor je bericht" not in fa.safe_fallback(atomen, "")


# ══════════════════════════════════════════════════════════════════════════════
# D/E/F — klachtcontext volgt de CANONIEKE lifecycle, niet een eigen definitie
# ══════════════════════════════════════════════════════════════════════════════
def _state(meldingen_dagen_geleden, tekst="Achillespees gevoelig."):
    log = [{"date": (TODAY - timedelta(days=d)).isoformat(), "post_notes": tekst,
            "workout_key": f"w{d}", "completed": True, "actual_km": 10}
           for d in meldingen_dagen_geleden]
    raw = {"intake": {"athlete_name": "X"}, "intake_ts": "2026-01-10", "notes": [], "profiel": "",
           "garmin": "", "on_hold": None, "labels": [], "belasting": None, "training_log": log}
    state, _ = adapter.build_state("uk", TODAY, gather_fn=lambda uk, today=None: (raw, []))
    return state


class TestKlachtRecentie:
    def test_D_oude_inactieve_klacht_komt_niet_terug(self):
        """Eén melding van ~1,5 maand terug → HISTORICAL → geen klachtcontext."""
        ctx = adapter.feedback_context(_state([45]), "", TODAY)
        assert ctx["complaint_areas"] == [] and ctx["complaint_new"] == []
        assert "achilles" not in ctx["prompt_block"].lower()

    def test_D_terugkerend_zonder_recente_melding_stuurt_de_reactie_niet(self):
        """Het gemelde geval: eerste melding ~1,5 maand terug, laatste 20 dagen terug. De
        klacht mag als ACHTERGROND blijven staan (met de 'vraag er niet naar'-guard), maar de
        ACTUEEL-escalatie ('laat dit je reactie mee sturen') mag NIET vuren — die sprak de
        guard twee zinnen eerder rechtstreeks tegen en droeg de oude klacht opnieuw binnen."""
        ctx = adapter.feedback_context(_state([45, 20]), "", TODAY)
        assert ctx["complaint_areas"] == ["achilles"]         # achtergrond: wel bekend
        assert ctx["complaint_new"] == []                     # canoniek NIET actueel
        assert "Vraag NIET actief naar een bestaande klacht" in ctx["prompt_block"]
        assert "LET OP" not in ctx["prompt_block"]

    def test_D_niet_actuele_klacht_forceert_geen_check_in(self):
        assert ob._signal_section([], False, True, False) == ""

    def test_E_actuele_klacht_mag_de_reactie_wel_sturen(self):
        for dagen, status in (([3], "ACTIVE"), ([15], "RECENT")):
            ctx = adapter.feedback_context(_state(dagen), "", TODAY)
            assert ctx["complaint_new"] == ["achilles"], status
            assert "LET OP" in ctx["prompt_block"], status

    def test_E_actieve_klacht_bij_zware_sessie_houdt_de_check_in_verplichting(self):
        """De Douwe-lock (v3/v4) blijft: actieve klacht + zware sessie → neutrale check-in."""
        sec = ob._signal_section(["scheen"], False, True, False)
        assert "ACTIEVE klacht" in sec and "check-in" in sec and "scheen" in sec

    def test_E_de_verplichting_leest_de_canonieke_actuele_set(self):
        bron = open(os.path.join(_ROOT, "ai_feedback.py")).read()
        assert '_ob_complaints = _ob_diag.get("complaint_new") or []' in bron
        assert '_ob_diag.get("complaint_areas")' not in bron

    def test_F_atleet_noemt_de_klacht_nu_zelf_dan_wel_meenemen(self, monkeypatch):
        """Ook zonder canonieke actualiteit: noemt de atleet hem NU, dan hoort hij erbij."""
        w = _workout("mijn achillespees voelde vandaag weer wat gevoelig")
        w["_brein_diag"] = {"complaint_areas": ["achilles"], "complaint_new": []}
        d = _beslis(monkeypatch, w)
        assert "complaint_achillespees" in [a["id"] for a in d["atoms"]]

    def test_F_bericht_met_klacht_krijgt_een_expliciete_verplichting(self):
        blok = ob.build(modality="hartslag", shares={"Z1": 95, "Z2": 5},
                        athlete_text="mijn achillespees voelde weer wat gevoelig")
        assert "noemt zelf pijn/klacht" in blok["prompt_block"]

    def test_geen_tweede_definitie_van_actueel(self):
        """De actualiteit komt uit AthleteState; Feedback bouwt er geen eigen begrip naast."""
        for pad in ("feedback_atoms.py", "feedback_obligations.py", "ai_feedback.py"):
            bron = open(os.path.join(_ROOT, pad)).read()
            assert "COMPLAINT_RECENT" not in bron and "last_seen_days" not in bron


# ══════════════════════════════════════════════════════════════════════════════
# G — quality gate: echte fouten blijven eruit, correcte concepten niet
# ══════════════════════════════════════════════════════════════════════════════
_KNIE = "Hou ook even in de gaten hoe je knie hierop reageert."


def _pack_met_klacht():
    return ff.build_fact_pack(workout_type="run", complaint_line=ff.complaint_sentence(["knie"]))


class TestGQualityGate:
    def test_correct_concept_werd_geblokkeerd_door_de_opschoning(self):
        """REPRODUCTIE + fix. Het model schrijft zelf een klacht-check-in; de app voegt de
        VERPLICHTE zin toe; de opschoning zag twee zinnen over hetzelfde onderwerp en gooide
        de APP-zin weg; de validator miste 'm en blokkeerde een inhoudelijk correct concept."""
        pack = _pack_met_klacht()
        spine = ff.assemble_spine("Fijn dat je toch gelopen hebt. Hou goed in de gaten hoe je "
                                  "knie hierop reageert.", pack)
        zonder = fc.clean_draft(spine)                        # oude aanroep = het oude gedrag
        assert ff.validate_draft(zonder, is_running=True, mandatory=pack["mandatory"])["ok"] is False
        met = fc.clean_draft(spine, protected=[m["sentence"] for m in pack["mandatory"]])
        assert ff.validate_draft(met, is_running=True, mandatory=pack["mandatory"])["ok"] is True
        assert met.count("in de gaten hoe je knie") == 1      # en géén dubbele zin

    def test_eind_tot_eind_blokkeert_een_correct_concept_niet_meer(self, monkeypatch):
        """Het gemelde symptoom door het ECHTE productiepad: actieve klacht + zware sessie geeft
        een VERPLICHTE check-in-zin; het model schrijft er zelf ook een. Vóór de fix schrapte de
        opschoning de app-zin en blokkeerde de validator een inhoudelijk correct concept."""
        # Een open vraag stuurt de case naar het LLM-pad (daar leeft de fact-pack); de actieve
        # klacht + zware sessie levert daar de VERPLICHTE check-in-zin.
        w = _workout("Mijn knie voelde onderweg wat gevoelig, is dat erg?", effort=8)
        w["_brein_diag"] = {"complaint_areas": ["knie"], "complaint_new": ["knie"],
                            "load_active": False}
        tekst, status = _genereer(
            monkeypatch, w,
            "Fijn dat het verder prima ging. Hou goed in de gaten hoe je knie hierop reageert.")
        assert status == "REVIEW_REQUIRED"
        assert _KNIE in tekst, tekst                          # de verplichte zin overleeft verbatim
        assert tekst.count("in de gaten hoe je knie") == 1    # en staat er niet dubbel in
        # Cruciaal: het CONCEPT ZELF is behouden, niet stilletjes vervangen door het veilige
        # terugvalconcept. Zonder deze assertie maskeert de terugval de regressie volledig.
        assert "Fijn dat het verder prima ging" in tekst
        assert not tekst.startswith(fa._ACK_TEXT)
        assert ff.validate_draft(tekst, is_running=True,
                                 mandatory=(w.get("_fact_pack") or {}).get("mandatory"))["ok"]

    def test_variant_van_de_verplichte_zin_wijkt_ongeacht_de_volgorde(self):
        pack = _pack_met_klacht()
        spine = ff.assemble_spine("Sterk. hou ook even in de gaten hoe je knie hierop reageert!", pack)
        uit = fc.clean_draft(spine, protected=[m["sentence"] for m in pack["mandatory"]])
        assert _KNIE in uit and uit.count("in de gaten hoe je knie") == 1

    def test_opschoning_blijft_systeemtaal_en_dubbels_schrappen(self):
        assert "blokkoppeling" not in fc.clean_draft(
            "Mooi. De blokkoppeling was niet strak. Sterk hoor.", protected=[_KNIE])
        assert fc.clean_draft("Mooi gedaan. Mooi gedaan. Tot snel.") == "Mooi gedaan. Tot snel."

    def test_echte_inhoudelijke_fout_wordt_nog_steeds_geblokkeerd(self):
        for fout, soort in (("Prima herstel na gisteren.", "content"),
                            ("Sterke rit vandaag.", "sport"),
                            ("Je zat 56% in Z3.", "content")):
            r = ff.validate_draft(fout, is_running=True)
            assert r["ok"] is False and r["kind"] == soort, fout

    def test_blokkade_levert_een_bruikbaar_veilig_concept(self, monkeypatch):
        """De LLM schrijft een verboden relatieve dag → terecht geblokkeerd. De coach houdt
        geen lege composer over maar een deterministisch concept uit eigen materiaal."""
        tekst, status = _genereer(monkeypatch, _workout(NIET_FIT),
                                  "Prima herstel na gisteren, sterk gedaan.")
        assert status == "REVIEW_REQUIRED"
        assert "gisteren" not in tekst.lower()
        assert ff.validate_draft(tekst, is_running=True)["ok"] is True
        assert tekst.startswith("Dank je voor je bericht")     # athlete-first, geen data-lof vooraan

    def test_terugval_prijst_de_hartslag_niet_automatisch(self):
        atomen = [fa._atom("fit", "Op hartslag bleef je netjes binnen het rustige bereik.",
                           "plan_execution", 60),
                  fa._atom("positive_close", "Goed gedaan.", "close", 10)]
        uit = fa.safe_fallback(atomen, NIET_FIT)
        assert "Goed gedaan" not in uit                        # geen automatische lof
        assert uit.startswith("Dank je voor je bericht")

    def test_terugval_verzint_niets_en_gebruikt_alleen_eigen_materiaal(self):
        uit = fa.safe_fallback([fa._atom("fit", "Op hartslag bleef je rustig.", "plan_execution", 60)],
                               NIET_FIT, [{"sentence": _KNIE}])
        for zin in [z.strip() for z in uit.split(". ") if z.strip()]:
            assert zin.rstrip(".") in (fa._ACK_TEXT.rstrip("."), "Op hartslag bleef je rustig",
                                       _KNIE.rstrip("."))

    def test_zonder_atomen_maar_met_bericht_blijft_er_een_neutrale_reactie(self, monkeypatch):
        """Niets bewijsbaars over de training (niet-run: geen atomen) én een afgekeurd concept.
        Dan nog steeds geen lege composer: een korte neutrale reactie die de melding erkent —
        precies wat er NIET mag gebeuren is automatisch de hartslag/zone gaan prijzen."""
        tekst, status = _genereer(monkeypatch, _workout(NIET_FIT, workout_type="ride"),
                                  "Prima herstel na gisteren.")
        assert status == "REVIEW_REQUIRED"
        assert tekst == fa._ACK_TEXT
        assert "hartslag" not in tekst.lower() and "zone" not in tekst.lower()

    def test_zonder_enig_materiaal_blokkeert_het_alsnog(self, monkeypatch):
        """Geen atomen, geen feiten én geen atleetbericht → er is werkelijk niets betrouwbaars
        te zeggen. Dan verzint de app niets en blijft de blokkade staan."""
        with pytest.raises(ValueError) as e:
            _genereer(monkeypatch, _workout("", workout_type="ride"),
                      "Prima herstel na gisteren.")
        assert "geblokkeerd" in str(e.value).lower()

    def test_goed_concept_passeert_ongewijzigd(self, monkeypatch):
        goed = "Fijn dat je je er doorheen hebt gezet ondanks dat rotgevoel."
        tekst, _ = _genereer(monkeypatch, _workout(NIET_FIT), goed)
        assert tekst == goed


# ══════════════════════════════════════════════════════════════════════════════
# H — geen regressie op bestaande Feedback-functionaliteit
# ══════════════════════════════════════════════════════════════════════════════
class TestHGeenRegressie:
    def test_gemiste_en_ongeplande_runs_blijven_zonder_commentaar_zichtbaar(self):
        """Plan-uitvoeringsafwijkingen zijn coachgebeurtenissen op zichzelf; ze mogen niet
        afhangen van een atleetbericht (run-deviations v1)."""
        from brain import derive as _derive, projections
        log = [{"date": (TODAY - timedelta(days=3)).isoformat(), "workout_key": "w-3",
                "name": "Duurloop", "description": "", "activity_type": "Hardlopen",
                "planned_km": 10, "actual_km": 0.0, "completed": False, "post_notes": ""},
               {"date": (TODAY - timedelta(days=1)).isoformat(), "workout_key": "w-1",
                "name": "", "description": "", "activity_type": "Hardlopen",
                "planned_km": None, "actual_km": 8.0, "completed": True, "post_notes": ""}]
        evs = _derive.all({"training_log": log}, "u1", TODAY, [])
        keys = [e.key for e in evs if e.key.startswith(("training.run_missed.",
                                                        "training.run_unplanned."))]
        assert "training.run_missed.w-3" in keys and "training.run_unplanned.w-1" in keys

        class _St:
            athlete_key, naam, overall = "u1", "T", "ATTENTION"
            evidence, conflicts, source_gaps = evs, [], []
        door = [e["key"] for e in projections.for_feedback(_St(), "")["evidence"]]
        assert any(k.startswith("training.run_missed.") for k in door)
        assert any(k.startswith("training.run_unplanned.") for k in door)

    def test_overgeslagen_training_blijft_een_eigen_pad(self):
        """De skip-route raakt de generatie niet: overslaan is queue-state, geen concept."""
        assert hasattr(feedback_core, "overslaan") and hasattr(feedback_core, "genereer")
        bron = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        blok = bron[bron.index("def overslaan("):]
        blok = blok[:blok.index("\ndef ", 1)]
        for term in ("build_decision", "validate_draft", "_validate_or_block", "safe_fallback"):
            assert term not in blok, term

    def test_vervolgreactie_krijgt_geen_feitelijke_ruggengraat_opgedrongen(self, monkeypatch):
        """FOLLOW_UP_REPLY houdt zijn eigen contract: alleen de taal-guards, geen fact-pack."""
        w = _workout("en nu?")
        w["thread"] = [{"rol": "atleet", "tekst": "en nu?"}]
        bron = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        blok = bron[bron.index("    _mandatory = ("):bron.index("    _GEN_STATUS[wid] = status")]
        assert 'if mode != FOLLOW_UP_REPLY else []' in blok
        assert "if decision is not None:" in blok               # terugval alleen op de initiële analyse

    def test_auto_safe_blijft_uitsluitend_uit_geregistreerde_atomen_bestaan(self, monkeypatch):
        d = _beslis(monkeypatch, _workout(""))
        assert d["status"] == fa.AUTO_SAFE
        assert fa._final_is_atoms_only(d["text"], d["atoms"]) is True

    def test_de_erkenning_kan_nooit_zelf_auto_safe_maken(self):
        """`ack` is terugval-materiaal; het telt niet als bewijsbare inhoud."""
        bron = open(os.path.join(_ROOT, "feedback_atoms.py")).read()
        blok = bron[bron.index("    content = [a for a in atoms"):bron.index("    text = assemble(atoms)")]
        assert '"ack"' not in blok
