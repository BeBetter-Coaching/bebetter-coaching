"""Athlete Workspace targeted cleanup — server-side regressietests.

De gedragstests voor de frontend (drie-standen-model, primaire actie, load-context,
dossier-deeplink, trainingsblok) staan in tests/js/workspace_cleanup.test.mjs. Hier: de
serverkant van dezelfde punten plus de locks die deze build NIET mag raken.

Kern van de bewezen oorzaak: de Workspace-shell leest alleen de belasting-STAND, en die
bevat per ontwerp UITSLUITEND gevlagde atleten (`belasting.check_alle` geeft None terug
zodra `analyse_belasting` geen signaal vindt). Bekende belasting van een atleet zonder
signaal stond dus niet in de stand en werd als 'Geen belastingstand bekend' getoond,
terwijl dezelfde AthleteState km/week, runs/week en trend wél kent.
"""
import os
import subprocess
import sys
from datetime import date, timedelta

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_ROOT, os.path.join(_ROOT, "pwa")):
    if p not in sys.path:
        sys.path.insert(0, p)

import coach_read as _cr                       # noqa: E402
import dossier_cockpit as _dc                  # noqa: E402
import home_core as _home                      # noqa: E402

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_HTML = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()
TODAY = date.today()


def _ev(key, value, status="ACTIVE", eid=None, observed_at="", detail=None):
    return {"key": key, "value": value, "status": status, "id": eid or ("ev-" + key),
            "domain": "load", "observed_at": observed_at, "detail": detail or {},
            "truth_type": "derived", "source": "fs.training_log", "strength": "HIGH"}


# ══ T1 — bekende belasting eindigt niet als UNKNOWN ══════════════════════════
class TestBekendeBelastingNietUnknown:
    def test_oorzaak_de_stand_bevat_alleen_gevlagde_atleten(self, monkeypatch):
        """Bewijs van de root cause: een atleet die niet in de stand staat levert
        `actief: False` + geen km — precies de bron van 'Geen belastingstand bekend'."""
        stand = {"datum": TODAY.isoformat(), "afgehandeld": {}, "resultaten": [
            {"user_key": "gevlagd", "naam": "A", "ernst": "let_op", "signalen": ["Volume +20%"],
             "metrics": {"km_recent": 48.0, "km_basis_week": 40.0, "runs_recent": []}}]}
        bel = _cr._athlete_belasting("sophie", stand=stand)
        assert bel["actief"] is False
        assert bel.get("km_recent") is None          # → de UI toont de UNKNOWN-zin

    def test_canonieke_state_kent_de_belasting_wel(self):
        evs = [_ev("load.km_per_week", 33.4), _ev("load.runs_per_week", 4.0),
               _ev("load.trend", "opbouwend")]
        lc = _dc._load_context(evs)
        assert lc["known"] is True
        assert lc["km_per_week"] == 33.4 and lc["runs_per_week"] == 4.0
        assert lc["trend"] == "opbouwend"
        assert lc["stale"] is False

    def test_echt_onbekend_blijft_onbekend(self):
        lc = _dc._load_context([_ev("goal.doel", "10 km")])
        assert lc["known"] is False
        assert lc["km_per_week"] is None and lc["interruption"] is None

    def test_stale_evidence_wordt_als_zodanig_gemarkeerd(self):
        lc = _dc._load_context([_ev("load.km_per_week", 30.0, status="STALE")])
        assert lc["known"] is True and lc["stale"] is True

    def test_geen_tweede_load_engine(self):
        """`_load_context` geeft evidence door; het rekent niets uit en leidt geen
        percentage af — `coach_read.load_metric` blijft de enige %-bron."""
        src = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()
        i = src.index("def _load_context(")
        body = src[i:src.index("def _domains(", i)]
        code = body.split('"""')[2]                   # alleen de uitvoerbare regels
        for verboden in ("load_metric", "sum(", "round(", "ratio", " / "):
            assert verboden not in code, f"berekening in _load_context: {verboden}"

    def test_cockpit_payload_draagt_load_context(self):
        src = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()
        assert '"load_context": _load_context(dossier_evs),' in src

    def test_frontend_vult_alleen_het_unknown_slot(self):
        i = _APP.index("function wsVulLoadContext(")
        blok = _APP[i:i + 1200]
        assert 'const slot = $("#ws-load-ctx");' in blok
        assert "if (!slot) return;" in blok            # echte stand → grafiek/kaart ongemoeid
        assert "if (!lc.known) return;" in blok        # echt onbekend → LOCK-zin blijft


# ══ T2 — UNKNOWN mag nooit RUSTIG worden ═════════════════════════════════════
class TestUnknownIsGeenRust:
    def test_drie_expliciete_standen(self):
        body = _APP[_APP.index("function wsRender("):]
        assert 'const belStand = bel.km_recent != null;' in body[:6000]
        assert 'attn.length ? "aandacht" : (belStand ? "rustig" : "onbekend")' in body[:6000]

    def test_geruststelling_hangt_niet_aan_afwezige_data(self):
        i = _APP.index("const nextBody = topAttn")
        blok = _APP[i:i + 900]
        assert "Geen directe actie — alles bij." in blok
        assert 'wsStaat === "rustig"' in blok
        assert "Te weinig om op te oordelen" in blok

    def test_opwaardering_vereist_autoritatieve_bron(self):
        i = _APP.index("function wsHefOnbekendOp(")
        blok = _APP[i:i + 700]
        assert "if (st.insufficient) return;" in blok


# ══ T5 — trainingsblok: recent + komend, Home byte-identiek ══════════════════
def _w(datum, has_actual, km_planned=10.0, km_actual=0.0):
    return {"workout_date": datum, "name": "Duurloop", "is_race": False,
            "has_actual_data": has_actual, "description": "60 min rustig",
            "Activities": [{"name": "Duurloop", "planned_amount": km_planned,
                            "planned_duration": 0, "amount": km_actual, "duration": 0}]}


class TestTrainingsblok:
    @pytest.fixture(autouse=True)
    def _fs(self, monkeypatch):
        self.gevraagd = {}

        def _dedup(uk, start, end):
            self.gevraagd["range"] = (start, end)
            return [
                _w((TODAY - timedelta(days=3)).isoformat(), True, 10.0, 10.0),   # gedaan
                _w((TODAY - timedelta(days=2)).isoformat(), True, 10.0, 3.0),    # half
                _w((TODAY - timedelta(days=1)).isoformat(), False, 10.0, 0.0),   # gemist
                _w((TODAY + timedelta(days=2)).isoformat(), False, 18.0, 0.0),   # gepland
            ]
        monkeypatch.setattr(_home.FS, "get_workouts_deduped", _dedup)
        monkeypatch.setattr(_home, "_heeft_token", lambda: True)

    def test_home_gedrag_is_ongewijzigd(self):
        """Home vraagt geen `vooruit` → exact het oude venster en de oude statussen."""
        r = _home.prio_trainingen("u1")
        start, end = self.gevraagd["range"]
        assert start == TODAY - timedelta(days=7) and end == TODAY - timedelta(days=1)
        assert {t["status"] for t in r["trainingen"]} == {"gedaan", "half", "gemist"}
        assert "gepland" not in {t["status"] for t in r["trainingen"]}

    def test_workspace_ziet_recent_en_komend(self):
        r = _home.prio_trainingen("u1", vooruit=7)
        start, end = self.gevraagd["range"]
        assert start == TODAY - timedelta(days=7) and end == TODAY + timedelta(days=7)
        st = [t["status"] for t in r["trainingen"]]
        assert st == ["gedaan", "half", "gemist", "gepland"]      # chronologisch

    def test_toekomstige_sessie_is_gepland_niet_gemist(self):
        r = _home.prio_trainingen("u1", vooruit=7)
        toekomst = [t for t in r["trainingen"] if t["datum"] > TODAY.isoformat()]
        assert toekomst and all(t["status"] == "gepland" for t in toekomst)

    def test_een_enkele_finalsurge_read(self, monkeypatch):
        n = {"c": 0}
        orig = _home.FS.get_workouts_deduped

        def _tel(uk, s, e):
            n["c"] += 1
            return orig(uk, s, e)
        monkeypatch.setattr(_home.FS, "get_workouts_deduped", _tel)
        _home.prio_trainingen("u1", vooruit=7)
        assert n["c"] == 1                                        # geen tweede engine/call

    def test_endpoint_is_opt_in(self):
        api = open(os.path.join(_ROOT, "pwa", "api.py")).read()
        assert "def home_prio_trainingen(user_key: str, vooruit: int = 0)" in api
        assert "vooruit=vooruit" in api


# ══ T6/T7 — schemaroutering ══════════════════════════════════════════════════
class TestSchemaRoutering:
    def test_modus_reist_niet_via_de_route(self):
        """De hash-grammatica (`#<view>/<ident>`) blijft ongewijzigd: de modus loopt via
        een pending-variabele, precies zoals `schemaOpenPending`."""
        i = _APP.index("function openSchemaMode(")
        blok = _APP[i:i + 400]
        assert 'openAthleteModule("schema", user_key)' in blok
        assert "#schema/" not in blok
        assert _APP.count("function openSchemaMode(") == 1

    def test_modus_wordt_precies_een_keer_geconsumeerd(self):
        i = _APP.index("function openSchemaAthlete(")
        blok = _APP[i:i + 400]
        assert "const mode = schemaOpenMode;" in blok
        assert 'schemaOpenMode = "";' in blok
        assert "schemaWerk(a, mode || undefined)" in blok

    def test_verlengen_flow_bestaat_al(self):
        assert "function sbStartVerleng(" in _APP
        assert 'if (mode === "verlengen") sbStartVerleng(a);' in _APP   # bestaande dispatch


# ══ T8 — dossier-deeplink ════════════════════════════════════════════════════
class TestDossierDeeplink:
    def test_event_reist_via_pending_niet_via_de_route(self):
        i = _APP.index("function openDossierEvent(")
        blok = _APP[i:i + 400]
        assert 'openAthleteModule("dossier", user_key)' in blok
        assert "#dossier/" not in blok

    def test_selectie_na_render_en_veilig_bij_onbekend_id(self):
        i = _APP.index("async function openDossierCockpit(")
        blok = _APP[i:i + 2600]
        assert blok.index("dcRender(wrap, r)") < blok.index("dcSelectEvent(wrap, _ev)")
        sel = _APP[_APP.index("function dcSelectEvent("):]
        assert "if (!ev) return;" in sel[:400]                      # onbekend id = no-op


# ══ T10/T11/T12 — locks ══════════════════════════════════════════════════════
class TestLocks:
    def test_routecontract_en_picker_ongewijzigd(self):
        assert '_ATHLETE_VIEWS = new Set(["atleten", "schema", "dossier"])' in _APP
        assert _APP.count("function applyRoute") == 1
        assert _APP.count("function openAthleteModule(") == 1
        assert "function wsLeegRoute(" in _APP
        # geen derde routesegment geïntroduceerd
        assert 'const h = "#" + view + "/" + encodeURIComponent(user_key);' in _APP
        assert "ws-switch" in _HTML and 'id="dc-switch"' in _HTML   # pickers intact

    def test_belastinggrafiek_en_bronnenblok_intact(self):
        assert "function wsLoadInstrument(" in _APP
        i = _APP.index("function wsRender(")
        body = _APP[i:_APP.index("\n// Progressive disclosure", i)]
        assert "wsLoadInstrument(bel)" in body                      # zelfde grafiek
        assert 'srcRow("Belasting", gfr.belasting, sv.belasting)' in body
        assert "Geen belastingstand bekend." in body                # exacte LOCK-zin

    def test_home_en_teampuls_projectie_ongewijzigd(self):
        r = {"user_key": "u1", "naam": "T", "ernst": "hoog", "signalen": ["Volume +60%"],
             "metrics": {"km_recent": 64.0, "km_basis_week": 40.0, "runs_recent": []}}
        s = _home._belasting_signal(r)
        assert s["reden"] == "Belasting hoog · +60% t.o.v. referentie"
        assert s["fingerprint"] == "bhoog" and s["severity"] == 2
        import teampuls_core as _tp
        assert _tp._norm(r)["pct"] == _cr.load_metric(r)["pct"] == 60

    def test_feedback_onaangeraakt(self):
        diff = subprocess.run(["git", "diff", "--name-only", "b7f4749", "--"],
                              cwd=_ROOT, capture_output=True, text=True).stdout.split()
        verboden = {"ai_feedback.py", "feedback_atoms.py", "feedback_copy.py",
                    "feedback_facts.py", "feedback_obligations.py", "metric_authority.py",
                    "pwa/feedback_core.py", "pwa/feedback_week.py"}
        raakt = verboden.intersection(diff)
        assert not raakt, f"Feedback buiten scope, toch aangeraakt: {sorted(raakt)}"

    def test_geen_nieuwe_store_of_truth(self):
        dc = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()
        assert "save_" not in dc and "intake_store" not in dc       # cockpit blijft read-only
        for mod in ("home_core.py", "coach_read.py"):
            src = open(os.path.join(_ROOT, "pwa", mod)).read()
            assert "_NIEUW_CACHE" not in src
