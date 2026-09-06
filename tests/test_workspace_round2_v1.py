"""Athlete Workspace cleanup ronde 2 — server-side regressietests.

Drie bewezen restfouten uit de targeted recheck van `39a6529`:

A. TOEKOMST als GEMIST. `prio_trainingen` toetste op `w["has_actual_data"]`, en dat veld is
   aantoonbaar onbetrouwbaar: `fs_client.is_executed_workout` documenteert dat FinalSurge
   het óók op true zet voor GEPLANDE (structured) workouts die nog niet gelopen zijn. De
   `gepland`-tak werd daardoor overgeslagen en de toekomstige sessie viel door naar de
   score-tak (amount 0 ⇒ score 0 ⇒ 'gemist').

B. ONBEKEND als NUL. `athlete_context.training_summary` geeft alleen `{}` bij een volledig
   leeg hardlooplog; mét historie maar zónder runs in de laatste 4 weken levert het
   km_per_week=0.0, runs_per_week=0 en trend='stabiel' als ACTIEVE evidence. De leeslaag
   las 'niet-None' als 'bekend' en toonde dat als een meting — waarna een rustige
   alles-bij-stand volgde.

C. Signaal/actie-mismatch. `coach_read._attention` labelde het belasting-item met de EERSTE
   bronzin (bv. "Noemt in notities: last van · 31-08") in plaats van de canonieke hoofdreden,
   waardoor 'Aandacht nu' als klacht las terwijl de actie 'Belasting gezien' was.

Het gedrag van de frontend (contextprimaat, badge, actie) staat in
tests/js/workspace_cleanup.test.mjs.
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
TODAY = date.today()


def _w(dagen: int, *, status="", has_actual=False, km_planned=10.0, km_actual=0.0, stats=False):
    """Workout zoals FinalSurge 'm levert. `status` = workout_status_text ('Planned'/'Completed')."""
    return {"workout_date": (TODAY + timedelta(days=dagen)).isoformat(),
            "name": "Duurloop", "is_race": False, "description": "60 min rustig",
            "has_actual_data": has_actual, "workout_status_text": status, "has_stats": stats,
            "Activities": [{"name": "Duurloop", "planned_amount": km_planned,
                            "planned_duration": 0, "amount": km_actual, "duration": 0}]}


def _ev(key, value, status="ACTIVE", eid=None):
    return {"key": key, "value": value, "status": status, "id": eid or ("ev-" + key),
            "domain": "load", "observed_at": "", "detail": {}, "truth_type": "derived",
            "source": "fs.training_log", "strength": "HIGH"}


# ══ A — toekomst is nooit GEMIST ═════════════════════════════════════════════
class TestToekomstIsGepland:
    @pytest.fixture(autouse=True)
    def _fs(self, monkeypatch):
        self.rows = []
        monkeypatch.setattr(_home, "_heeft_token", lambda: True)
        monkeypatch.setattr(_home.FS, "get_workouts_deduped", lambda uk, s, e: list(self.rows))

    def test_root_cause_has_actual_data_is_onbetrouwbaar(self):
        """De aanleiding, expliciet vastgelegd: FinalSurge zet `has_actual_data` óók op
        true voor een geplande, nog niet gelopen structured workout."""
        toekomst = _w(+1, status="Planned", has_actual=True)
        assert toekomst["has_actual_data"] is True          # ← wat de oude toets zag
        assert _home.FS.is_executed_workout(toekomst) is False   # ← de canonieke waarheid

    def test_t1_toekomstige_sessie_is_gepland(self):
        # Exact de auditcase: structured workout met has_actual_data=True op een datum ná vandaag.
        self.rows = [_w(+1, status="Planned", has_actual=True),
                     _w(+3, status="Planned", has_actual=True),
                     _w(+6, status="Planned", has_actual=True)]
        st = [t["status"] for t in _home.prio_trainingen("u1", vooruit=7)["trainingen"]]
        assert st == ["gepland", "gepland", "gepland"], st

    def test_t1b_vandaag_nog_niet_gedaan_is_gepland(self):
        self.rows = [_w(0, status="Planned", has_actual=True)]
        assert _home.prio_trainingen("u1", vooruit=7)["trainingen"][0]["status"] == "gepland"

    def test_t2_verstreken_zonder_uitvoering_is_gemist(self):
        self.rows = [_w(-2, status="Planned", has_actual=True),
                     _w(-1, status="", has_actual=False)]
        st = [t["status"] for t in _home.prio_trainingen("u1", vooruit=7)["trainingen"]]
        assert st == ["gemist", "gemist"], st

    def test_t3_uitgevoerd_blijft_gedaan_of_half(self):
        self.rows = [_w(-3, status="Completed", has_actual=True, km_actual=10.0),
                     _w(-2, status="Completed", has_actual=True, km_actual=3.0)]
        st = [t["status"] for t in _home.prio_trainingen("u1", vooruit=7)["trainingen"]]
        assert st == ["gedaan", "half"], st

    def test_t4_telling_en_rijen_komen_overeen(self):
        """Eelco-case: 2 echt gemist + 3 toekomstig. De blokken mogen niet 5 'gemist' tonen."""
        self.rows = [_w(-4, status="Planned", has_actual=True),      # gemist
                     _w(-2, status="Planned", has_actual=True),      # gemist
                     _w(+1, status="Planned", has_actual=True),
                     _w(+3, status="Planned", has_actual=True),
                     _w(+5, status="Planned", has_actual=True)]
        rows = _home.prio_trainingen("u1", vooruit=7)["trainingen"]
        assert sum(1 for r in rows if r["status"] == "gemist") == 2
        assert sum(1 for r in rows if r["status"] == "gepland") == 3

    def test_home_blijft_byte_identiek(self):
        """LOCK: Home vraagt geen `vooruit` en houdt exact het oude venster + statussen,
        ook als FinalSurge een toekomstig item zou meesturen."""
        self.rows = [_w(-3, status="Completed", has_actual=True, km_actual=10.0),
                     _w(-1, status="Planned", has_actual=True),
                     _w(+2, status="Planned", has_actual=True)]
        st = [t["status"] for t in _home.prio_trainingen("u1")["trainingen"]]
        assert "gepland" not in st
        assert st == ["gedaan", "gemist", "gemist"]

    def test_gebruikt_de_canonieke_predikaat(self):
        src = open(os.path.join(_ROOT, "pwa", "home_core.py")).read()
        blok = src[src.index("def prio_trainingen("):src.index('"van": start.isoformat()')]
        assert "FS.is_executed_workout(w)" in blok
        assert 'datum >= vandaag_iso and not w.get("has_actual_data")' not in blok


# ══ B — onbekend blijft onbekend (nooit hard nul) ════════════════════════════
class TestOnbekendIsGeenNul:
    def test_root_cause_nul_weken_leveren_actieve_nul_evidence(self):
        """Bewijs van de bron: met historie maar zonder recente runs levert de canonieke
        samenvatting 0/0/'stabiel' — geen meting, wél niet-None."""
        import athlete_context as _ac
        log = [{"date": (TODAY - timedelta(days=90)).isoformat(), "actual_km": 12.0, "completed": True}]
        ts = _ac.training_summary(log, TODAY)
        assert ts.get("km_per_week") == 0
        assert ts.get("runs_per_week") == 0
        assert ts.get("trend") == "stabiel"

    def test_t5_nul_blijft_onbekend_en_wordt_none(self):
        lc = _dc._load_context([_ev("load.km_per_week", 0.0), _ev("load.runs_per_week", 0),
                                _ev("load.trend", "stabiel")])
        assert lc["known"] is False
        assert lc["km_per_week"] is None and lc["runs_per_week"] is None
        assert lc["trend"] is None                       # geen 'stabiel' uit het niets
        assert lc["no_recent_running"] is True           # expliciete, testbare reden

    def test_t12_bekende_belasting_blijft_bekend(self):
        """LOCK: de known-load fallback (Sophie/Eelco/Doutzen) blijft groen."""
        lc = _dc._load_context([_ev("load.km_per_week", 33.4), _ev("load.runs_per_week", 4.0),
                                _ev("load.trend", "opbouwend")])
        assert lc["known"] is True
        assert lc["km_per_week"] == 33.4 and lc["runs_per_week"] == 4.0
        assert lc["trend"] == "opbouwend" and lc["no_recent_running"] is False

    def test_gedeeltelijke_meting_telt_ook(self):
        # runs bekend, km toevallig 0 → nog steeds een meting.
        lc = _dc._load_context([_ev("load.km_per_week", 0.0), _ev("load.runs_per_week", 2)])
        assert lc["known"] is True and lc["runs_per_week"] == 2

    def test_geen_evidence_is_geen_no_recent_running(self):
        lc = _dc._load_context([])
        assert lc["known"] is False and lc["no_recent_running"] is False

    def test_t11_onderbreking_blijft_meekomen(self):
        """Sophie: de bekende onderbreking mag niet wegvallen als de load onbekend is."""
        lc = _dc._load_context([
            _ev("load.km_per_week", 0.0),
            _ev("load.interruption", "laatste 3 weken (bijna) niet getraind", eid="ev-int")])
        assert lc["known"] is False
        assert lc["interruption"]["tekst"] == "laatste 3 weken (bijna) niet getraind"
        assert lc["interruption"]["evidence_id"] == "ev-int"


# ══ C — signaal en actie gaan over hetzelfde ═════════════════════════════════
def _bel_res(ernst, signalen, km_r=26.7, km_b=30.7):
    return {"user_key": "u1", "naam": "Douwe", "ernst": ernst, "signalen": signalen,
            "metrics": {"km_recent": km_r, "km_basis_week": km_b, "runs_recent": []}}


class TestSignaalActieCoherent:
    def test_t9_aandacht_toont_de_hoofdreden_niet_de_bronzin(self, monkeypatch):
        """Douwe: de eerste bronzin is een notitie-signaal; 'Aandacht nu' las daardoor als
        klacht terwijl de knop 'Belasting gezien' zei."""
        res = _bel_res("let_op", ["Noemt in notities: last van · 31-08", "Volume -13%"])
        stand = {"datum": TODAY.isoformat(), "afgehandeld": {}, "resultaten": [res]}
        bel = _cr._athlete_belasting("u1", stand=stand)
        assert bel["reden"] == "Noemt in notities: last van · 31-08"      # bronzin blijft
        assert bel["primair"] == "Belasting let op · -13% t.o.v. referentie"
        attn = _cr._attention({"signalen": []}, bel, {})
        assert attn[0]["soort"] == "belasting"
        assert attn[0]["kort"] == bel["primair"]
        assert "Noemt in notities" not in attn[0]["kort"]

    def test_hoofdreden_is_dezelfde_bron_als_home(self):
        res = _bel_res("hoog", ["Volume +60% laatste 7 dagen"], 64.0, 40.0)
        assert _cr.load_metric(res)["primair"] == _home._belasting_signal(res)["reden"]

    def test_t10_concrete_klacht_komt_uit_de_canonieke_bron(self):
        """Geen nieuwe klachtparser: de cockpit-kaart draagt lichaamsdeel + status + de
        notitiezin al; de Workspace hergebruikt exact die tekst."""
        src = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()
        seg = src[src.index('_c = _card_obj("complaint"'):][:400]
        assert 'f"Klacht: {area} — {st_txt}"' in seg
        i = _APP.index("const _WS_CTX_KIND = {")
        blok = _APP[i:_APP.index("function wsUniekeSignalen(")]
        assert "complaint:" in blok and 'soort: "klacht"' in blok
        assert "c.title" in blok and "c.why" in blok
        assert "regex" not in blok.lower() and "match(" not in blok

    def test_t6_t7_context_forceert_aandacht(self):
        i = _APP.index("function wsDeepContext(")
        blok = _APP[i:i + 1600]
        assert 'const staat = merged.length ? "aandacht"' in blok
        assert "wsMagRustig(r)" in blok
        mag = _APP[_APP.index("function wsMagRustig("):]
        mag = mag[:mag.index("\n}")]
        assert "!!lc.known" in mag and "!st.insufficient" in mag

    def test_t8_context_cta_blijft_bruikbaar(self):
        blok = _APP[_APP.index("function wsActieBtn("):]
        blok = blok[:blok.index("\n}")]
        assert "openDossierEvent(" in blok
        assert "disabled" not in blok


# ══ Locks ════════════════════════════════════════════════════════════════════
class TestLocks:
    def test_t13_t14_routing_en_schema_ongewijzigd(self):
        assert '_ATHLETE_VIEWS = new Set(["atleten", "schema", "dossier"])' in _APP
        assert _APP.count("function applyRoute") == 1
        assert "function openSchemaMode(" in _APP and "function openDossierEvent(" in _APP
        assert 'const h = "#" + view + "/" + encodeURIComponent(user_key);' in _APP
        assert "Nieuw schema bouwen" in _APP and "openSchemaMode('${esc(key)}','verlengen')" in _APP

    def test_grafiek_en_bronnen_en_lockzin_intact(self):
        i = _APP.index("function wsRender(")
        body = _APP[i:_APP.index("\n// Progressive disclosure", i)]
        assert "wsLoadInstrument(bel)" in body
        assert 'srcRow("Belasting", gfr.belasting, sv.belasting)' in body
        assert "Geen belastingstand bekend." in body

    def test_t15_home_en_teampuls_ongemoeid(self):
        r = {"user_key": "u1", "naam": "T", "ernst": "hoog", "signalen": ["Volume +60%"],
             "metrics": {"km_recent": 64.0, "km_basis_week": 40.0, "runs_recent": []}}
        s = _home._belasting_signal(r)
        assert s["reden"] == "Belasting hoog · +60% t.o.v. referentie"
        assert s["fingerprint"] == "bhoog" and s["severity"] == 2
        import teampuls_core as _tp
        assert _tp._norm(r)["pct"] == _cr.load_metric(r)["pct"] == 60
        diff = subprocess.run(["git", "diff", "--name-only", "39a6529", "--"],
                              cwd=_ROOT, capture_output=True, text=True).stdout.split()
        for verboden in ("belasting.py", "pwa/teampuls_core.py", "pwa/athlete_context.py"):
            assert verboden not in diff, f"gelockte module aangeraakt: {verboden}"

    def test_t16_feedback_onaangeraakt(self):
        diff = subprocess.run(["git", "diff", "--name-only", "39a6529", "--"],
                              cwd=_ROOT, capture_output=True, text=True).stdout.split()
        verboden = {"ai_feedback.py", "feedback_atoms.py", "feedback_copy.py",
                    "feedback_facts.py", "feedback_obligations.py", "metric_authority.py",
                    "pwa/feedback_core.py", "pwa/feedback_week.py"}
        raakt = verboden.intersection(diff)
        assert not raakt, f"Feedback buiten scope, toch aangeraakt: {sorted(raakt)}"

    def test_geen_nieuwe_store_of_truth(self):
        dc = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()
        assert "save_" not in dc and "intake_store" not in dc
