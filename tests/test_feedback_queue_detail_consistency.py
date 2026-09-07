"""Feedback — queue/detail-consistentie (Michael-case, 7 sep 2026).

Eén sessie-identiteit moet overal dezelfde waarheid geven: zegt de wachtrij `Reactie` met een
atleetcitaat, dan moet het detail voor DIEZELFDE workout_key dat bericht ook tonen.

Root cause (zie docs/audits/FEEDBACK_QUEUE_DETAIL_MICHAEL_2026-09-07.md): `_herstel_cache` liet
`_cache` de queue-snapshot alleen in LIDMAATSCHAP volgen (`setdefault`), niet in INHOUD. De
queue-items worden elke sweep vers gebouwd, maar `_cache[wid]` bleef het object van de EERSTE
sweep die de workout zag. Kwam atleet-input binnen NADAT de workout al in de queue stond, dan
las `detail()` uit dat bevroren object.

    python3 -m pytest tests/test_feedback_queue_detail_consistency.py -q
"""
import os
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import feedback_core as FC
import fs_client as FS

_BASE = "3f12f53"                                        # productie waarop deze fix is gebouwd

WID = "W-MICHAEL"
BERICHT = "Voelde mij goed. Nuchter gelopen en het liep soepel."


def _workout(wid=WID, *, thread=None, post_notes="", comments=None, felt=None, effort=None,
             naam="Michael ter Horst", voornaam="Michael", datum="2026-09-07",
             workout="Fartlek race prep"):
    return {"workout_key": wid, "athlete_key": "AK", "athlete_name": naam,
            "athlete_first_name": voornaam, "workout_date": datum, "workout_name": workout,
            "workout_type": "run", "post_notes": post_notes,
            "athlete_comments": list(comments or []), "thread": list(thread or []),
            "felt": felt, "effort": effort}


def _atleet_thread(tekst, naam="Michael"):
    """Exact de thread-vorm die fs_client.build_thread oplevert voor een post-workout-notitie."""
    return [{"tekst": tekst, "van": "atleet", "naam": naam, "timestamp": "", "_display": False}]


def _snap(*workouts):
    volle = {w["workout_key"]: w for w in workouts}
    return {"fs": True, "_volle": volle,
            "items": [FC._queue_item(wid, w) for wid, w in volle.items()],
            "berekend": "2026-09-07T09:00:00", "datum": "2026-09-07"}


def _item(snap, wid):
    return next(i for i in snap["items"] if i["id"] == wid)


@pytest.fixture(autouse=True)
def _schone_cache():
    FC._cache.clear()
    yield
    FC._cache.clear()


# ══════════════════════════════════════════════════════════════════════════════
# De bewezen root cause — en dat hij weg is
# ══════════════════════════════════════════════════════════════════════════════
class TestRootCause:
    def test_build_thread_maakt_divergentie_binnen_een_record_onmogelijk(self):
        """Waarom het GEEN bronveld-verschil is: `post_notes` staat altijd als eerste
        thread-item, dus 'notitie gevuld terwijl de thread leeg is' bestaat niet binnen één
        record. Queue en detail kunnen op hetzelfde object niet uit elkaar lopen."""
        thread = FS.build_thread([], BERICHT, "Michael", "COACH")
        w = _workout(thread=thread, post_notes=BERICHT)
        assert FC._categorie(w)[0] == "reactie"
        assert FC._gesprek(w)                                  # detail toont hetzelfde bericht

    def test_late_atleet_input_gaf_reactie_in_de_rij_maar_leeg_detail(self):
        """DE case: sweep A ziet een uitgevoerde geplande training zonder tekst, Michael schrijft
        daarna zijn notitie, sweep B leest die wél. Vóór de fix bleef `_cache` op het object van
        sweep A staan en toonde het detail 'Geen bericht van de atleet'."""
        snap_a = _snap(_workout())
        FC._herstel_cache(snap_a)
        assert _item(snap_a, WID)["categorie"] == "uitgevoerd"
        assert FC._gesprek(FC._cache[WID]) == []

        snap_b = _snap(_workout(thread=_atleet_thread(BERICHT), post_notes=BERICHT))
        FC._herstel_cache(snap_b)

        item = _item(snap_b, WID)
        gecachet = FC._cache[WID]
        assert item["categorie"] == "reactie" and item["preview"].startswith("Voelde mij goed")
        # de invariant: detail ziet exact hetzelfde bericht als de rij citeert
        assert [m["tekst"] for m in FC._gesprek(gecachet)] == [BERICHT]
        assert FC._categorie(gecachet)[0] == "reactie"
        assert item["heeft_thread"] is True

    def test_serkan_esther_pad_blijft_werken(self):
        """Wie de queue binnenkomt MET een bericht was nooit stuk; dat pad mag niet veranderen."""
        snap = _snap(_workout(wid="W-SERKAN", thread=_atleet_thread("Ging lekker!", "Serkan"),
                              post_notes="Ging lekker!", naam="Serkan D", voornaam="Serkan"))
        FC._herstel_cache(snap)
        assert _item(snap, "W-SERKAN")["categorie"] == "reactie"
        assert [m["tekst"] for m in FC._gesprek(FC._cache["W-SERKAN"])] == ["Ging lekker!"]


# ══════════════════════════════════════════════════════════════════════════════
# De invariant, over sweeps en categorieën heen
# ══════════════════════════════════════════════════════════════════════════════
def _consistent(snap, wid):
    """De invariant uit de opdracht: rij en detail geven dezelfde waarheid."""
    item, w = _item(snap, wid), FC._cache[wid]
    cat, preview = FC._categorie(w)
    if item["categorie"] != cat:
        return False
    if item["categorie"] == "reactie":
        return bool(FC._gesprek(w)) and item["preview"] == preview
    return True


class TestInvariant:
    def test_sessie_gekoppeld_bericht_in_rij_en_detail(self):
        snap = _snap(_workout(thread=_atleet_thread(BERICHT), post_notes=BERICHT))
        FC._herstel_cache(snap)
        assert _consistent(snap, WID)
        assert BERICHT in _item(snap, WID)["preview"] or _item(snap, WID)["preview"] in BERICHT

    def test_bericht_van_andere_workout_badget_deze_case_niet(self):
        """Sessie-identiteit: de preview komt uitsluitend uit dit workout-record. Een reactie op
        een ANDERE training van dezelfde atleet mag deze case nooit `Reactie` maken."""
        stil = _workout(wid="W-STIL", workout="Rustige duurloop")
        praat = _workout(wid="W-PRAAT", thread=_atleet_thread(BERICHT), post_notes=BERICHT,
                         workout="Fartlek race prep")
        snap = _snap(stil, praat)
        FC._herstel_cache(snap)
        assert _item(snap, "W-STIL")["categorie"] == "uitgevoerd"
        assert _item(snap, "W-STIL")["preview"] == ""
        assert FC._gesprek(FC._cache["W-STIL"]) == []
        assert _item(snap, "W-PRAAT")["categorie"] == "reactie"
        assert all(_consistent(snap, w) for w in ("W-STIL", "W-PRAAT"))

    def test_data_only_uitgevoerde_case_blijft_uitgevoerd(self):
        snap = _snap(_workout())
        FC._herstel_cache(snap)
        assert _item(snap, WID)["categorie"] == "uitgevoerd"
        # ook ná een tweede sweep zonder nieuwe input
        snap2 = _snap(_workout())
        FC._herstel_cache(snap2)
        assert _item(snap2, WID)["categorie"] == "uitgevoerd"
        assert _consistent(snap2, WID)

    def test_gevoel_case_blijft_gevoel(self):
        snap = _snap(_workout(felt=3))
        FC._herstel_cache(snap)
        assert _item(snap, WID)["categorie"] == "gevoel"
        assert _consistent(snap, WID)

    def test_refresh_behoudt_consistentie_over_meerdere_sweeps(self):
        """Elke opeenvolgende sweep-toestand moet de invariant houden — ook als de atleet er
        gaandeweg een tweede bericht bij schrijft."""
        toestanden = [
            _workout(),
            _workout(felt=3),
            _workout(thread=_atleet_thread(BERICHT), post_notes=BERICHT, felt=3),
            _workout(thread=_atleet_thread(BERICHT) + [
                {"tekst": "Nog een vraagje over zaterdag", "van": "atleet",
                 "naam": "Michael", "timestamp": "2026-09-07T10:00:00"}],
                post_notes=BERICHT, comments=["Nog een vraagje over zaterdag"], felt=3),
        ]
        verwacht = ["uitgevoerd", "gevoel", "reactie", "reactie"]
        for w, cat in zip(toestanden, verwacht):
            snap = _snap(w)
            FC._herstel_cache(snap)
            assert _item(snap, WID)["categorie"] == cat
            assert _consistent(snap, WID)
        assert len(FC._gesprek(FC._cache[WID])) == 2      # beide berichten in het detail

    def test_coach_antwoord_in_de_thread_blijft_zichtbaar_in_detail(self):
        thread = _atleet_thread(BERICHT) + [
            {"tekst": "Mooi, ga zo door.", "van": "coach", "naam": "jij",
             "timestamp": "2026-09-07T11:00:00"}]
        snap = _snap(_workout(thread=thread, post_notes=BERICHT))
        FC._herstel_cache(snap)
        gesprek = FC._gesprek(FC._cache[WID])
        assert [m["coach"] for m in gesprek] == [False, True]
        assert _item(snap, WID)["categorie"] == "reactie"   # badge blijft op het ATLEET-bericht


# ══════════════════════════════════════════════════════════════════════════════
# Wat de fix expliciet NIET mag breken
# ══════════════════════════════════════════════════════════════════════════════
class TestGeenNevenschade:
    def test_object_identiteit_blijft_behouden(self):
        """Reden 1 waarom `setdefault` er stond: een al uitgedeelde referentie moet meelopen."""
        FC._herstel_cache(_snap(_workout()))
        ref = FC._cache[WID]
        FC._herstel_cache(_snap(_workout(thread=_atleet_thread(BERICHT), post_notes=BERICHT)))
        assert FC._cache[WID] is ref                       # zelfde object …
        assert ref["post_notes"] == BERICHT                # … met verse inhoud

    def test_lazy_geladen_details_blijven_staan(self):
        """Reden 2: `_ensure_details` haalt de laps één keer op; die mogen niet elke sweep weg."""
        FC._herstel_cache(_snap(_workout()))
        FC._cache[WID]["details"] = {"Activities": [{"amount": 8.0}]}
        FC._herstel_cache(_snap(_workout(thread=_atleet_thread(BERICHT), post_notes=BERICHT)))
        assert FC._cache[WID]["details"] == {"Activities": [{"amount": 8.0}]}

    def test_verse_details_winnen_van_oude(self):
        FC._herstel_cache(_snap(_workout()))
        FC._cache[WID]["details"] = {"Activities": [{"amount": 8.0}]}
        vers = _workout(thread=_atleet_thread(BERICHT), post_notes=BERICHT)
        vers["details"] = {"Activities": [{"amount": 9.9}]}
        FC._herstel_cache(_snap(vers))
        assert FC._cache[WID]["details"] == {"Activities": [{"amount": 9.9}]}

    def test_snapshot_raakt_niet_vervuild_met_lazy_details(self):
        """Geheugengrens uit de Render-ronde: de durable snapshot mag de laps niet meedragen."""
        FC._herstel_cache(_snap(_workout()))
        vers = _workout(thread=_atleet_thread(BERICHT), post_notes=BERICHT)
        snap = _snap(vers)
        FC._herstel_cache(snap)
        FC._cache[WID]["details"] = {"Activities": [{"amount": 8.0}]}
        assert "details" not in vers                        # `_volle` blijft schoon
        assert "details" not in FC._persist_payload(snap)["_volle"][WID]

    def test_pruning_grens_blijft_intact(self):
        """De cachegrens uit render-memory-bounded-caches-v1: uit de snapshot = uit de cache."""
        FC._herstel_cache(_snap(_workout(wid="W-A"), _workout(wid="W-B")))
        assert set(FC._cache) == {"W-A", "W-B"}
        FC._herstel_cache(_snap(_workout(wid="W-A")))
        assert set(FC._cache) == {"W-A"}

    def test_lege_snapshot_prunet_niet(self):
        FC._herstel_cache(_snap(_workout()))
        FC._herstel_cache({"_volle": {}, "items": []})
        assert WID in FC._cache                             # geen destructieve leegloop

    def test_geen_dubbele_entries(self):
        snap = _snap(_workout(wid="W-A"), _workout(wid="W-B"))
        FC._herstel_cache(snap)
        FC._herstel_cache(snap)
        assert len(FC._cache) == 2
        assert len(snap["items"]) == len({i["id"] for i in snap["items"]})

    def test_volgorde_en_categorie_ranking_onaangeraakt(self):
        assert FC._CAT_RANK == {"reactie": 0, "gevoel": 1, "uitgevoerd": 2}
        src = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        blok = src[src.index("def _queue_public("):src.index("def _diag(")]
        assert '(i.get("datum") or "")' in blok
        assert '_GROEP_RANK.get(i.get("groep"), 9)' in blok
        assert '_CAT_RANK.get(i["categorie"], 9)' in blok

    def test_sorteervolgorde_gedrag_ongewijzigd(self):
        """Gedragsbewijs dat de sortering niet verschuift: datum eerst, dan groep, dan categorie."""
        snap = {"items": [
            {"id": "c", "datum": "2026-09-07", "groep": "comfort", "categorie": "reactie",
             "athlete_ts": "", "naam": "C"},
            {"id": "a", "datum": "2026-09-05", "groep": "comfort", "categorie": "uitgevoerd",
             "athlete_ts": "", "naam": "A"},
            {"id": "b", "datum": "2026-09-07", "groep": "comfort", "categorie": "gevoel",
             "athlete_ts": "", "naam": "B"},
        ], "gepost": 0}
        uit = FC._queue_public(snap, cached=True)
        assert [i["id"] for i in uit["items"]] == ["a", "c", "b"]


# ══════════════════════════════════════════════════════════════════════════════
# Scope
# ══════════════════════════════════════════════════════════════════════════════
class TestLocks:
    def _diff(self):
        return subprocess.run(["git", "diff", "--name-only", _BASE, "--"],
                              cwd=_ROOT, capture_output=True, text=True).stdout.split()

    def test_alleen_feedback_core_en_de_notitie_gewijzigd(self):
        verwacht = {"pwa/feedback_core.py",
                    "docs/audits/FEEDBACK_QUEUE_DETAIL_MICHAEL_2026-09-07.md"}
        onverwacht = [f for f in self._diff() if f not in verwacht and not f.startswith("tests/")]
        assert not onverwacht, f"buiten scope gewijzigd: {onverwacht}"

    def test_alleen_herstel_cache_geraakt(self):
        """Elke gewijzigde regel in feedback_core valt binnen `_herstel_cache`."""
        import re
        src = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        d = subprocess.run(["git", "diff", "-U0", _BASE, "--", "pwa/feedback_core.py"],
                           cwd=_ROOT, capture_output=True, text=True).stdout
        regels = src.splitlines()
        start = next(i for i, r in enumerate(regels, 1) if r.startswith("def _herstel_cache("))
        eind = next(i for i, r in enumerate(regels, 1) if i > start and r.startswith("def ")) - 1
        for m in re.finditer(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", d, re.M):
            eerste, n = int(m.group(1)), int(m.group(2) or 1)
            if n == 0:
                continue
            assert start <= eerste and eerste + n - 1 <= eind, \
                f"feedback_core gewijzigd buiten _herstel_cache: regels {eerste}-{eerste + n - 1}"

    def test_categorie_en_gesprek_letterlijk_ongewijzigd(self):
        src = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        assert "def _categorie(w: dict) -> tuple[str, str]:" in src
        assert 'return "reactie", berichten[0][:90]' in src
        assert 'out.append({"coach": m.get("van") == "coach",' in src
        assert '"heeft_thread": bool(_gesprek(w)),' in src

    def test_generatie_en_write_pad_onaangeraakt(self):
        src = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        for anker in ("def genereer(", "def plaats(", "def overslaan(",
                      "_verwijder_uit_queue(", "def get_or_restore_workout(",
                      "_validate_or_block(w, tekst, mode)", "_refresh_thread(w)"):
            assert anker in src

    def test_geen_nieuwe_store_of_fetch_in_de_fix(self):
        src = open(os.path.join(_ROOT, "pwa", "feedback_core.py")).read()
        blok = src[src.index("def _herstel_cache("):src.index("# ── Diagnostiek")]
        for verboden in ("FS.", "requests", "open(", "intake_store", "global "):
            assert verboden not in blok, f"nieuwe afhankelijkheid in de fix: {verboden}"
