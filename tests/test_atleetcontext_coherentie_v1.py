"""Atleetcontext-coherentie — Schema Verlengen deelt de klachtwaarheid.

Productie draait `BEBETTER_SCHEMA_BRAIN=v2` (roadmap, commit 56b55fe). In die modus
bouwde Schema zijn AthleteState met een EIGEN `adapter.build_state()`, terwijl
Workspace, Dossier, Teampuls, Home en de Feedback-context hem via de canonieke
read-laag (`athlete_read`) delen. Twee builds van dezelfde waarheid lopen uiteen
zodra één ervan een bron mist: de gedeelde read serveert dan MEM/LKG (klacht blijft
staan), Schema bouwde vers en degradeerde — en dan ontbreekt in Verlengen een klacht
die geen enkele andere view kwijt was.

De client-bewijzen voor Feedback → atleetroutes staan in
tests/js/athlete_continuity.test.mjs (scenario's 7-12).
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "pwa")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import athlete_context as AC                                   # noqa: E402
import athlete_read as AR                                      # noqa: E402
import schema_core as SC                                       # noqa: E402
from brain import adapter, complaints, projections, sources     # noqa: E402

_APP = (_ROOT / "pwa" / "static" / "app.js").read_text(encoding="utf-8")
VANDAAG = date(2026, 9, 8)


def _raw(log=None, notes=None, belasting=None):
    return {
        "intake": {"athlete_name": "Douwe van Dijk"}, "intake_ts": "2026-01-10",
        "notes": notes or [], "profiel": "", "garmin": "", "on_hold": None, "labels": [],
        "belasting": belasting,
        "training_log": log if log is not None else [],
    }


_ACHILLES = {"date": "2026-09-06", "post_notes": "Achillespees gevoelig na de duurloop.",
             "workout_key": "w1", "completed": True, "actual_km": 12}


def _klachten(ctx):
    return (ctx.get("health") or {}).get("actuele_klachten") or []


def _v2(monkeypatch):
    monkeypatch.setattr(AC, "schema_brain_mode", lambda: "v2")
    AR.reset()


# ══════════════════════════════════════════════════════════════════════════════
# 1 — Schema deelt de canonieke AthleteState met de andere views
# ══════════════════════════════════════════════════════════════════════════════
class TestGedeeldeKlachtwaarheid:
    def test_schema_leest_dezelfde_state_als_de_andere_views(self, monkeypatch):
        _v2(monkeypatch)
        raw = _raw(log=[_ACHILLES])
        gedeeld = AR.get_state("douwe", VANDAAG, gather_fn=lambda uk, today=None: (raw, []))
        groepen = [e.key for e in gedeeld.state.evidence
                   if e.key.startswith("complaint.") and not e.key.startswith("complaint.mention.")]
        assert "complaint.achilles" in groepen, "voorwaarde: de gedeelde state kent de klacht"

        ctx = AC.build_athlete_context("douwe", "Douwe van Dijk", VANDAAG)
        kl = _klachten(ctx)
        assert kl and "achilles" in kl[0]["tekst"].lower(), f"Schema mist de klacht: {kl}"
        assert kl[0]["datum"] == "2026-09-06"

    def test_douwe_scenario_klacht_verdwijnt_niet_bij_bronuitval(self, monkeypatch):
        """De gemelde case: de andere views tonen de actieve achillesklacht, Verlengen niet.
        Reproductie: de gedeelde read heeft een gezonde state; op het moment dat Schema
        leest is de trainingslog-bron weg. Met een eigen build degradeert Schema en
        verdwijnt de klacht; via de gedeelde read blijft hij staan."""
        _v2(monkeypatch)
        raw = _raw(log=[_ACHILLES])
        AR.get_state("douwe", VANDAAG, gather_fn=lambda uk, today=None: (raw, []))

        def kapot(uk, today=None):
            r = _raw(log=[])
            return r, [sources.SourceHealth(source="fs.training_log", available=False, error="timeout")]

        # Een EIGEN build op dat moment verliest de klacht — dat was het oude Schema-pad.
        eigen, _ = adapter.build_state("douwe-eigen", VANDAAG, gather_fn=kapot)
        eigen_ctx = adapter.to_legacy_context(eigen, _raw(log=[]), VANDAAG)
        assert not _klachten(eigen_ctx), "voorwaarde: een eigen degraderende build verliest de klacht"

        # Schema leest nu de gedeelde state en houdt hem wel.
        kl = _klachten(AC.build_athlete_context("douwe", "Douwe van Dijk", VANDAAG))
        assert kl and "achilles" in kl[0]["tekst"].lower(), f"Verlengen mist de klacht opnieuw: {kl}"

    def test_klacht_bereikt_de_herijking_van_verlengen(self, monkeypatch):
        """Weergave-eind: het herijkingsitem dat Verlengen toont."""
        _v2(monkeypatch)
        AR.get_state("douwe", VANDAAG, gather_fn=lambda uk, today=None: (_raw(log=[_ACHILLES]), []))
        items, _ = SC._herijking("douwe", {"athlete_name": "Douwe van Dijk"}, {})
        klacht = [i for i in items if i["sleutel"] == "klacht"]
        assert klacht, f"geen klachtitem in de herijking: {[i['sleutel'] for i in items]}"
        assert "achilles" in klacht[0]["actueel"].lower()
        assert klacht[0]["kritiek"] is True

    def test_recente_klacht_blijft_naast_oudere_entries(self, monkeypatch):
        """Douwe-achtig: een verse actieve klacht mag niet verdwijnen terwijl oudere
        klachtentries wel zichtbaar zijn."""
        _v2(monkeypatch)
        raw = _raw(
            log=[_ACHILLES,
                 {"date": "2026-08-25", "post_notes": "Kuit gevoelig.", "workout_key": "w0"}],
            notes=[{"datum": "2026-08-20", "tekst": "Knie pijn besproken."}],
        )
        AR.get_state("douwe", VANDAAG, gather_fn=lambda uk, today=None: (raw, []))
        kl = _klachten(AC.build_athlete_context("douwe", "", VANDAAG))
        tekst = " | ".join(k["tekst"].lower() for k in kl)
        assert "achilles" in tekst, f"de verse klacht ontbreekt: {kl}"
        assert len(kl) >= 2, f"oudere entries verdwenen: {kl}"
        assert kl[0]["datum"] == "2026-09-06", "nieuwste bovenaan"

    def test_geen_parallelle_klachtimplementatie(self):
        """Schema leidt geen eigen klachtstatus af; de lifecycle blijft in brain/complaints."""
        bron = (_ROOT / "pwa" / "schema_core.py").read_text(encoding="utf-8")
        assert "_vind_klachten" not in bron and "complaint" not in bron.lower()
        herijking = bron[bron.index("def _herijking"):bron.index("def _verleng_vragen")]
        assert 'health.get("actuele_klachten")' in herijking, "één bron voor de klachtlijst"


# ══════════════════════════════════════════════════════════════════════════════
# 2 — de gedeelde read mag het v2-contract niet oprekken
# ══════════════════════════════════════════════════════════════════════════════
class TestContract:
    def test_zonder_bruikbare_gedeelde_read_valt_schema_terug_op_eigen_build(self, monkeypatch):
        """Pure LKG levert geen `raw`; de passthrough-velden (intake/garmin/notities) komen
        daaruit. Dan liever de eigen build dan een half gevulde context."""
        _v2(monkeypatch)

        class _Leeg:
            state, raw = object(), None
        monkeypatch.setattr(AR, "get_state", lambda *a, **k: _Leeg())
        gebruikt = {}

        def _bc(uk, naam="", today=None):
            gebruikt["eigen"] = True
            return {"naam": naam, "health": {}}

        def _tlc(*a, **k):                      # mag hier NIET worden aangeroepen
            gebruikt["mapper"] = True
            raise AssertionError("to_legacy_context aangeroepen zonder raw")
        monkeypatch.setattr(adapter, "build_context", _bc)
        monkeypatch.setattr(adapter, "to_legacy_context", _tlc)
        AC.build_athlete_context("douwe", "Douwe", VANDAAG)
        assert not gebruikt.get("mapper"), "zonder raw mag de mapper niet draaien"
        assert gebruikt.get("eigen"), "zonder raw hoort Schema zijn eigen build te doen"

    def test_leesfout_valt_terug_op_eigen_build_niet_op_v1(self, monkeypatch):
        """v2 kent GEEN stille terugval naar legacy; een kapotte leeslaag mag dat niet
        introduceren."""
        _v2(monkeypatch)

        def _stuk(*a, **k):
            raise RuntimeError("leeslaag stuk")
        monkeypatch.setattr(AR, "get_state", _stuk)
        gebruikt = {}

        def _bc(uk, naam="", today=None):
            gebruikt["eigen"] = True
            return {"naam": naam}
        monkeypatch.setattr(adapter, "build_context", _bc)
        monkeypatch.setattr(AC, "_build_legacy", lambda *a, **k: {"LEGACY": True})
        ctx = AC.build_athlete_context("douwe", "Douwe", VANDAAG)
        assert gebruikt.get("eigen") and "LEGACY" not in ctx

    def test_legacy_modus_blijft_het_v1_pad(self, monkeypatch):
        monkeypatch.setattr(AC, "schema_brain_mode", lambda: "legacy")
        monkeypatch.setattr(AC, "_build_legacy", lambda *a, **k: {"V1": True})
        assert AC.build_athlete_context("douwe", "", VANDAAG).get("V1") is True

    def test_naam_blijft_expliciet_overschrijfbaar(self, monkeypatch):
        _v2(monkeypatch)
        AR.get_state("douwe", VANDAAG, gather_fn=lambda uk, today=None: (_raw(log=[_ACHILLES]), []))
        assert AC.build_athlete_context("douwe", "Andere Naam", VANDAAG)["naam"] == "Andere Naam"


# ══════════════════════════════════════════════════════════════════════════════
# 3 — client: Feedback draagt zijn case-atleet mee
# ══════════════════════════════════════════════════════════════════════════════
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
    raise AssertionError(sig)


class TestFeedbackContext:
    def test_terugval_kent_de_feedback_case(self):
        f = _fn("function _shownAthleteKey(")
        assert 'if (view === "feedback")' in f
        assert "FB.sel" in f and "athlete_key" in f

    def test_feedback_blijft_een_globale_route(self):
        """Geen ident in de feedback-route, geen derde routesegment."""
        assert '_ATHLETE_CTX_VIEWS = new Set([..._ATHLETE_VIEWS, "workspace"])' in _APP
        assert '"feedback"' not in _fn("function activeAthleteKey(")
        assert 'const _ATHLETE_VIEWS = new Set(["atleten", "schema", "dossier"])' in _APP
