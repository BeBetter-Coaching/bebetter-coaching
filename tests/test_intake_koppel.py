"""Intake correctness — Fase 1 herstelronde (punten B en E).

Dekt:
  • B — e-mail is zichtbaar in het dossier wanneer de bron hem bevat (en niet
    'terugverzonnen' wanneer niet).
  • E — PWA-koppelstap ('nieuw:naam' → FinalSurge user_key) zodat Schema én
    Masterbrein de intake gaan zien; non-destructieve history (niets verdwijnt
    stil bij koppelen of opnieuw overnemen).

    python3 -m pytest tests/test_intake_koppel.py -q
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import intake_store
import intake_core
import dossier_core


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Isoleer alle intake-stores naar tmp (lokale JSON, geen GitHub)."""
    monkeypatch.setattr(intake_store, "_gh_token", lambda: "")
    for attr, naam in [
        ("_INTAKES_LOCAL", "intakes.json"),
        ("_INTAKE_ARCHIEF_LOCAL", "intakes_archief.json"),
        ("_INTAKE_INBOX_LOCAL", "intake_inbox.json"),
        ("_LAATSTE_INTAKE_LOCAL", "laatste_intakes.json"),
    ]:
        monkeypatch.setattr(intake_store, attr, str(tmp_path / naam), raising=False)
    return intake_store


# ── B — e-mail zichtbaar in dossier ─────────────────────────────────────────
class TestEmailZichtbaar:
    def test_email_in_dossier_velden(self, store):
        store.save_intakes({"U1": {"athlete_name": "Lisa", "doel": "10 km",
                                   "email": "lisa@example.com", "updated_at": "2026-08-16"}})
        dos = dossier_core.get_dossier("U1")
        labels = {v["label"]: v["waarde"] for v in dos["velden"]}
        assert labels.get("E-mail") == "lisa@example.com"

    def test_geen_email_geen_veld(self, store):
        # Bron zonder e-mail → geen 'E-mail'-veld (niets terugverzinnen).
        store.save_intakes({"U2": {"athlete_name": "Bram", "doel": "5 km",
                                   "updated_at": "2026-08-16"}})
        dos = dossier_core.get_dossier("U2")
        assert "E-mail" not in {v["label"] for v in dos["velden"]}


# ── E — PWA-koppelstap + non-destructieve history ───────────────────────────
def _nieuw(store, naam="Sanne de Vries", **velden):
    key = "nieuw:" + naam.lower().replace(" ", "_")
    rec = {"athlete_name": naam, "doel": "marathon", "email": "s@x.nl",
           "updated_at": "2026-08-10", **velden}
    intakes = store.load_intakes()
    intakes[key] = rec
    store.save_intakes(intakes)
    return key


class TestKoppel:
    def test_koppel_maakt_zichtbaar_voor_schema_masterbrein(self, store):
        nk = _nieuw(store)
        ok, err, naam = intake_core.link_intake(nk, "FS_USER_9")
        assert ok, err
        intakes = store.load_intakes()
        # nieuw:-record weg, user_key-record aanwezig
        assert nk not in intakes
        assert intakes["FS_USER_9"]["doel"] == "marathon"
        assert intakes["FS_USER_9"]["gekoppeld_op"]
        # exact wat Schema/Masterbrein lezen: nieuwste_intake op user_key
        gezien = store.nieuwste_intake(store.load_intakes().get("FS_USER_9"),
                                       store.load_laatste_intakes().get("FS_USER_9"))
        assert gezien and gezien["email"] == "s@x.nl"

    def test_koppel_weigert_ongeldige_input(self, store):
        nk = _nieuw(store)
        assert intake_core.link_intake("FS_X", "FS_USER_9")[0] is False   # bron niet 'nieuw:'
        assert intake_core.link_intake(nk, "")[0] is False                # geen doel-key
        assert intake_core.link_intake(nk, "nieuw:iemand")[0] is False    # doel geen echt account
        # bron bestaat nog steeds — niets stuk
        assert nk in store.load_intakes()

    def test_koppel_over_bestaande_intake_archiveert(self, store):
        # Doel-account heeft al een (oude) intake → mag niet stil verdwijnen.
        store.save_intakes({"FS_USER_9": {"athlete_name": "Sanne", "doel": "oud doel",
                                          "updated_at": "2025-01-01"}})
        nk = _nieuw(store, doel="nieuw doel")
        ok, err, _ = intake_core.link_intake(nk, "FS_USER_9")
        assert ok, err
        # current = de nieuwe intake
        assert store.load_intakes()["FS_USER_9"]["doel"] == "nieuw doel"
        # oude intake bewaard in archief onder dezelfde key
        arch = store.load_intake_archief().get("FS_USER_9", [])
        assert len(arch) == 1 and arch[0]["doel"] == "oud doel"
        assert arch[0]["_archief_reden"] == "vervangen_bij_koppelen"

    def test_historie_in_dossier(self, store):
        store.save_intakes({"FS_USER_9": {"athlete_name": "Sanne", "doel": "oud doel",
                                          "updated_at": "2025-01-01"}})
        nk = _nieuw(store, doel="nieuw doel")
        intake_core.link_intake(nk, "FS_USER_9")
        dos = dossier_core.get_dossier("FS_USER_9")
        assert len(dos["historie"]) == 1
        assert dos["historie"][0]["doel"] == "oud doel"
        assert dos["historie"][0]["reden"] == "vervangen_bij_koppelen"


class TestOpnieuwOvernemen:
    def test_retake_archiveert_vorige(self, store):
        inbox = {"20260810120000-aaaaaa": {"naam": "Sanne de Vries", "doel": "eerste",
                                           "email": "s@x.nl", "status": "nieuw",
                                           "ingezonden": "2026-08-10T12:00"}}
        store.save_intake_inbox(inbox)
        ok, _, _ = intake_core.inbox_take("20260810120000-aaaaaa")
        assert ok
        key = "nieuw:sanne_de_vries"
        assert store.load_intakes()[key]["doel"] == "eerste"
        assert not store.load_intake_archief().get(key)      # nog niks te archiveren

        # tweede inzending zelfde naam → oude niet stil overschrijven
        inbox2 = store.load_intake_inbox()
        inbox2["20260812090000-bbbbbb"] = {"naam": "Sanne de Vries", "doel": "tweede",
                                           "status": "nieuw", "ingezonden": "2026-08-12T09:00"}
        store.save_intake_inbox(inbox2)
        ok2, _, _ = intake_core.inbox_take("20260812090000-bbbbbb")
        assert ok2
        assert store.load_intakes()[key]["doel"] == "tweede"           # current = nieuwste
        arch = store.load_intake_archief().get(key, [])
        assert len(arch) == 1 and arch[0]["doel"] == "eerste"          # vorige bewaard
