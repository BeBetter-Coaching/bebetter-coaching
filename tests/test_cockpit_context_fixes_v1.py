"""Vier gerichte herstellen na de Races-batch — serverkant + broncontract.

De client-bewijzen (feedbacktegel, athlete-context, verlengen-modus) staan in
tests/js/cockpit_context_fixes.test.mjs. Hier:

  A  home_core  — een ONVOLLEDIGE sweep is geen rustige stand;
  B  athlete_context — een door de ATLEET gemelde klacht (post-notes uit
     FinalSurge) bereikt Schema: zowel de herijking als de generatie-context;
  C/D broncontracten voor de client-fixes.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date, timedelta

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "pwa")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import athlete_context as AC                                  # noqa: E402
import home_core                                              # noqa: E402

_APP = (_ROOT / "pwa" / "static" / "app.js").read_text(encoding="utf-8")


def _fn(sig: str) -> str:
    i = _APP.index(sig)
    j = _APP.index("{", i)
    diep = 0
    for k in range(j, len(_APP)):
        if _APP[k] == "{":
            diep += 1
        elif _APP[k] == "}":
            diep -= 1
            if diep == 0:
                return _APP[i:k + 1]
    raise AssertionError(f"ongebalanceerd: {sig}")


# ══════════════════════════════════════════════════════════════════════════════
# A — Home: 'nog niet berekend' is geen 'niks aan de hand'
# ══════════════════════════════════════════════════════════════════════════════
class TestHomeOnvolledig:
    def test_onvolledige_sweep_zonder_oude_snapshot_is_pending(self, monkeypatch):
        """FS antwoordde, maar de sweep leverde niets bruikbaars (transiënte nullen,
        atleten=0). Dat payload werd ONGEWIJZIGD teruggegeven en las als een echte,
        lege uitkomst: team 0/0/0, prioriteit [], feedback leeg → Home meldde een
        afgeronde, rustige dag terwijl er niets berekend was."""
        kaal = {"fs": True, "atleten": 0, "prioriteit": [],
                "team": {"actie": 0, "aandacht": 0, "rustig": 0},
                "feedback": {"wachten": 0, "gepost": 0, "pct": 100}}
        monkeypatch.setattr(home_core, "_bereken", lambda: kaal)
        monkeypatch.setattr(home_core, "_current", lambda: None)
        uit = home_core.cockpit(refresh=True)

        assert uit.get("pending") is True, "een onvolledige sweep hoort als 'nog bezig' te lezen"
        assert uit.get("prioriteit") is None, "geen berekende lijst = geen lijst"
        assert uit.get("onvolledig") is True, "herkomst blijft traceerbaar"
        # Cruciaal: geen enkel veld waaruit de client 'klaar/rustig' kan afleiden.
        assert "team" not in uit, "geen team-telling → geen 'iedereen bij'"
        assert "feedback" not in uit, "geen feedbacktegel → geen 'alles beoordeeld'"

    def test_zonder_finalsurge_blijft_een_echte_stand(self, monkeypatch):
        """Niet-gekoppeld is wél een echte uitkomst en moet zo blijven lezen."""
        monkeypatch.setattr(home_core, "_bereken", lambda: {"fs": False})
        monkeypatch.setattr(home_core, "_current", lambda: None)
        uit = home_core.cockpit(refresh=True)
        assert uit.get("fs") is False
        assert not uit.get("pending"), "geen koppeling is geen 'nog bezig'"

    def test_geldige_sweep_blijft_ongewijzigd(self, monkeypatch):
        """De fix mag een echte, volledige sweep niet als pending wegzetten."""
        goed = {"fs": True, "atleten": 12, "prioriteit": [],
                "team": {"actie": 0, "aandacht": 0, "rustig": 12},
                "feedback": {"wachten": 0, "gepost": 4, "pct": 100}}
        monkeypatch.setattr(home_core, "_bereken", lambda: goed)
        monkeypatch.setattr(home_core, "_current", lambda: None)
        monkeypatch.setattr(home_core, "_persist", lambda d: None)
        uit = home_core.cockpit(refresh=True)
        assert not uit.get("pending"), "een geldige sweep is een echte stand"
        assert uit.get("atleten") == 12

    def test_oude_snapshot_wint_van_een_mislukte_refresh(self, monkeypatch):
        """Bestaand gedrag: bruikbare oude data niet weggooien."""
        oud = {"fs": True, "atleten": 9, "prioriteit": [], "team": {}, "feedback": {}}
        monkeypatch.setattr(home_core, "_bereken", lambda: {"fs": True, "atleten": 0, "prioriteit": []})
        monkeypatch.setattr(home_core, "_current", lambda: oud)
        monkeypatch.setattr(home_core, "_reconcile", lambda s, **k: s)
        uit = home_core.cockpit(refresh=True)
        assert uit.get("refresh_mislukt") is True and uit.get("atleten") == 9
        assert not uit.get("pending")

    def test_client_leest_ontbrekende_telling_als_onbekend(self):
        f = _fn("function renderFeedbackStrip(")
        assert "if (fbs.wachten == null) {" in f, "geen telling = onbekend, ongeacht 'stale'"
        assert "fbs.stale && fbs.wachten == null" not in f


# ══════════════════════════════════════════════════════════════════════════════
# B — Schema ziet de klacht die de atleet zelf meldde
# ══════════════════════════════════════════════════════════════════════════════
def _raw(log=None, notes=None, intake=None):
    return {"intake": intake or {}, "intake_ts": None, "notes": notes or [], "profiel": "",
            "belasting": None, "garmin": "", "on_hold": None, "labels": {},
            "training_log": log or []}


class TestSchemaKlacht:
    vandaag = date(2026, 9, 8)

    def _klachten(self, ctx):
        return (ctx.get("health") or {}).get("actuele_klachten") or []

    def test_atleet_gemelde_klacht_bereikt_schema(self):
        """Een klacht in de post-notes van een training was zichtbaar in Dossier,
        Workspace en Feedback (die lezen post_notes), maar niet in Schema — dus ook
        niet in de herijking bij Verlengen."""
        raw = _raw(log=[{"date": (self.vandaag - timedelta(days=3)).isoformat(),
                         "post_notes": "Knie doet pijn bij het aanzetten.", "workout_key": "w1"}])
        kl = self._klachten(AC.assemble("u1", "Test", raw, today=self.vandaag))
        assert kl, "de door de atleet gemelde klacht ontbreekt nog steeds"
        assert kl[0]["bron"].startswith("atleet")
        assert "Knie doet pijn" in kl[0]["tekst"]
        assert kl[0]["datum"] == (self.vandaag - timedelta(days=3)).isoformat()

    def test_klacht_staat_ook_in_de_generatie_context(self):
        """Weergave én generatie-input komen uit hetzelfde veld; beide moeten 'm dragen."""
        raw = _raw(log=[{"date": (self.vandaag - timedelta(days=2)).isoformat(),
                         "post_notes": "Last van de achillespees na de duurloop.", "workout_key": "w1"}])
        ctx = AC.assemble("u1", "Test", raw, today=self.vandaag)
        tekst = AC.to_prompt_text(AC.schema_projection(ctx))
        assert "achillespees" in tekst, "de plangeneratie krijgt de klacht niet mee"
        assert "klacht" in tekst.lower()

    def test_negatie_telt_niet_als_klacht(self):
        """Zelfde negatie-bewuste herkenning als het belasting-signaal en brain/complaints."""
        for zin in ("Lekker gelopen, geen pijn.", "De pijn is weg."):
            raw = _raw(log=[{"date": (self.vandaag - timedelta(days=1)).isoformat(),
                             "post_notes": zin, "workout_key": "w1"}])
            assert not self._klachten(AC.assemble("u1", "T", raw, today=self.vandaag)), zin

    def test_oude_melding_valt_buiten_het_venster(self):
        raw = _raw(log=[{"date": (self.vandaag - timedelta(days=60)).isoformat(),
                         "post_notes": "Hamstring stijf.", "workout_key": "w1"}])
        assert not self._klachten(AC.assemble("u1", "T", raw, today=self.vandaag))

    def test_nieuwste_klacht_staat_bovenaan(self):
        raw = _raw(log=[
            {"date": (self.vandaag - timedelta(days=10)).isoformat(), "post_notes": "Kuit gevoelig.", "workout_key": "a"},
            {"date": (self.vandaag - timedelta(days=2)).isoformat(), "post_notes": "Knie doet pijn.", "workout_key": "b"},
        ])
        kl = self._klachten(AC.assemble("u1", "T", raw, today=self.vandaag))
        assert len(kl) == 2
        assert "Knie" in kl[0]["tekst"], "de meest recente melding hoort bovenaan"

    def test_coachnotitie_van_dezelfde_dag_telt_niet_dubbel(self):
        d = (self.vandaag - timedelta(days=2)).isoformat()
        raw = _raw(log=[{"date": d, "post_notes": "Knie doet pijn na de intervallen.", "workout_key": "b"}],
                   notes=[{"datum": d, "tekst": "Knie pijn gemeld na intervaltraining."}])
        kl = self._klachten(AC.assemble("u1", "T", raw, today=self.vandaag))
        assert len(kl) == 1, f"dubbeltelling: {kl}"

    def test_bestaande_bronnen_blijven_werken(self):
        """Coach-notitie en intakeklacht blijven ongewijzigd meelopen."""
        raw = _raw(notes=[{"datum": (self.vandaag - timedelta(days=4)).isoformat(),
                           "tekst": "Klacht aan de knie besproken."}],
                   intake={"huidige_klachten": "Af en toe last van de hiel"})
        kl = self._klachten(AC.assemble("u1", "T", raw, today=self.vandaag))
        bronnen = {k["bron"] for k in kl}
        assert "coach-notitie" in bronnen and "intake" in bronnen
        assert kl[-1]["bron"] == "intake", "de intakeklacht blijft onderaan (minst actueel)"

    def test_zonder_log_geen_verandering(self):
        assert not self._klachten(AC.assemble("u1", "T", _raw(), today=self.vandaag))


# ══════════════════════════════════════════════════════════════════════════════
# C/D — broncontracten voor de client-fixes
# ══════════════════════════════════════════════════════════════════════════════
class TestClientContracten:
    def test_atleten_fallback_leest_een_id_geen_object(self):
        f = _fn("function _shownAthleteKey(")
        assert 'typeof dossierSel === "string"' in f
        assert "dossierSel.key" not in f, "dossierSel is de id zelf, geen object"

    def test_schema_verloop_kiest_de_passende_modus(self):
        assert "function svModus(" in _APP and "function svActieLabel(" in _APP
        rij = _fn("function svItem(")
        assert "openSchemaMode(it.user_key, svModus(it))" in rij
        assert "openAthleteModule(\"schema\"" not in rij, "de modus moet meegaan"

    def test_generieke_schema_ingang_erft_geen_modus(self):
        """Een kale #schema is de algemene ingang; een blijven hangen modus van een
        eerdere, niet-geconsumeerde entry mag daar niet stil meeliften."""
        assert 'schemaOpenPending = ""; schemaOpenMode = ""; sbToonLijst();' in _APP
