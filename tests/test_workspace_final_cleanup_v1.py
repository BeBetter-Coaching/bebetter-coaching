"""Athlete Workspace final cleanup — server-side regressietests.

Hoofdblokker: klachtselectie zette een OUDE terugkerende klacht boven een ACTUELE actieve
klacht. Oorzaak: `dossier_cockpit._attention` gaf elke klacht `rank=0` en sorteerde
daarbinnen alleen op STRENGTH — en die as staat precies omgekeerd op de klinische
prioriteit. Een terugkerende klacht heeft per definitie ≥2 meldingen en is dus altijd
MEDIUM (`_STRENGTH_RANK` 1), terwijl een verse actieve klacht met één atleetmelding LOW is
(niet in de map → 9). Zie `pwa/brain/complaints.py`: status volgt uit recency/herhaling,
strength uit coachbevestiging of ≥2 meldingen.

Frontendgedrag (dedupe, secundaire actie, venster-labels, schema-feit) staat in
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

import dossier_cockpit as _dc                  # noqa: E402
import home_core as _home                      # noqa: E402
from brain.models import (ACTIVE, HIGH, LOW, MEDIUM, RECENT, RECURRING,  # noqa: E402
                          DERIVED, Evidence)

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_DS = open(os.path.join(_ROOT, "pwa", "static", "design-system.css")).read()
TODAY = date.today()


class _St:
    def __init__(self, evs):
        self.evidence, self.conflicts, self.source_gaps = evs, [], []

    def get(self, cid):
        return next((e for e in self.evidence if e.id == cid), None)


def _klacht(area, status, strength, datum):
    return Evidence(key=f"complaint.{area}", domain="health", value=area, truth_type=DERIVED,
                    status=status, strength=strength, source="derived", source_kind="derived",
                    observed_at=datum, athlete_key="u1",
                    detail={"area": area, "dates": [datum]})


def _ev(key, value, status=ACTIVE, strength=MEDIUM, domain="load"):
    return Evidence(key=key, domain=domain, value=value, truth_type=DERIVED, status=status,
                    strength=strength, source="derived", source_kind="derived",
                    observed_at="2026-09-05", athlete_key="u1", detail={})


# ══ P0 — klachtselectie op status, dan datum ═════════════════════════════════
class TestKlachtPrioriteit:
    def test_root_cause_terugkerend_is_altijd_sterker(self):
        """De aanleiding, expliciet: terugkerend ⇒ ≥2 meldingen ⇒ MEDIUM; een verse actieve
        klacht met één melding is LOW. Op strength alleen wint de oude dus altijd."""
        assert _dc._STRENGTH_RANK.get(MEDIUM) < _dc._STRENGTH_RANK.get(LOW, 9)

    def test_t1_actief_boven_terugkerend(self):
        cards = _dc._attention(_St([
            _klacht("pijn", RECURRING, MEDIUM, "2026-08-14"),
            _klacht("scheen", ACTIVE, LOW, "2026-08-23"),
        ]))
        assert [c["status"] for c in cards] == [ACTIVE, RECURRING]
        assert "scheen" in cards[0]["title"]

    def test_t2_binnen_status_nieuwste_eerst(self):
        cards = _dc._attention(_St([
            _klacht("a", ACTIVE, LOW, "2026-08-23"),
            _klacht("b", ACTIVE, LOW, "2026-08-31"),
            _klacht("c", RECURRING, MEDIUM, "2026-08-14"),
            _klacht("d", RECURRING, MEDIUM, "2026-08-21"),
        ]))
        assert [c["datum"] for c in cards] == ["2026-08-31", "2026-08-23", "2026-08-21", "2026-08-14"]

    def test_t3_douwe_actieve_klacht_staat_bovenaan(self):
        """De exacte auditcase (14/21 aug terugkerend, 23/31 aug actief)."""
        cards = _dc._attention(_St([
            _klacht("pijn", RECURRING, MEDIUM, "2026-08-14"),
            _klacht("stijf", RECURRING, MEDIUM, "2026-08-21"),
            _klacht("scheen", ACTIVE, LOW, "2026-08-23"),
            _klacht("last van", ACTIVE, LOW, "2026-08-31"),
        ]))
        klachten = [c for c in cards if c["kind"] == "complaint"]
        assert klachten[0]["status"] == ACTIVE and "last van" in klachten[0]["title"]
        assert klachten[1]["status"] == ACTIVE and "scheen" in klachten[1]["title"]
        # De actieve klachten kunnen niet meer achter de terugkerende verdwijnen.
        assert all(k["status"] == RECURRING for k in klachten[2:])

    def test_t4_actieve_klacht_stuurt_de_cta(self):
        """Matthijs: de eerste klachtkaart bepaalt de primaire actie in de Workspace."""
        cards = _dc._attention(_St([
            _klacht("knie", RECURRING, MEDIUM, "2026-07-20"),
            _klacht("kuit", ACTIVE, LOW, "2026-09-02"),
        ]))
        eerste = next(c for c in cards if c["kind"] == "complaint")
        assert eerste["status"] == ACTIVE
        # De client leest de servervolgorde en hersorteert niet.
        i = _APP.index("function wsContextSignalen(")
        blok = _APP[i:i + 1200]
        assert ".sort(" not in blok

    def test_t10_urgente_klacht_boven_herstel_druk(self):
        cards = _dc._attention(_St([
            _ev("recovery.rpe_trend", "zwaarder", strength=HIGH, domain="recovery"),
            _klacht("hamstring", ACTIVE, LOW, "2026-09-04"),
        ]))
        assert cards[0]["kind"] == "complaint"
        assert any(c["kind"] == "recovery_neg" for c in cards)

    def test_overige_kaartvolgorde_ongewijzigd(self):
        """De sub-rank raakt alleen klachten; andere soorten houden rank+strength."""
        cards = _dc._attention(_St([
            _ev("zones.structural_over", "ZONE_REVIEW_CANDIDATE", strength=LOW, domain="zones"),
            _ev("load.signal", "hoog", strength=MEDIUM),
        ]))
        assert [c["kind"] for c in cards] == ["load_signal", "zone_review"]


# ══ P1 — Herstel onder druk stroomt door ═════════════════════════════════════
class TestHerstelDruk:
    def test_t9_recovery_neg_is_een_workspace_contextsignaal(self):
        cards = _dc._attention(_St([_ev("recovery.feeling_trend", "slechter",
                                        strength=MEDIUM, domain="recovery")]))
        assert cards and cards[0]["kind"] == "recovery_neg"
        assert cards[0]["title"] == "Herstel onder druk"
        i = _APP.index("const _WS_CTX_KIND = {")
        blok = _APP[i:_APP.index("function wsUniekeSignalen(")]
        assert "recovery_neg:" in blok and 'soort: "herstel"' in blok

    def test_geen_nieuwe_inferentie(self):
        """Alleen doorgeven wat de canonieke attention al zegt — geen eigen drempel."""
        i = _APP.index("const _WS_CTX_KIND = {")
        blok = _APP[i:_APP.index("function wsUniekeSignalen(")]
        for verboden in ("rpe", "zwaarder", "slechter", "> ", "< "):
            assert verboden not in blok, f"eigen afleiding in de client: {verboden}"


# ══ P1 — dedupe: één semantisch signaal, één eenheid ═════════════════════════
class TestDedupe:
    def test_t5_geen_apart_contextblok_meer(self):
        assert 'id="ws-ctx"' not in _APP
        assert ".ws-ctx{" not in _DS
        i = _APP.index("function wsSignalenHtml(")
        blok = _APP[i:i + 900]
        assert "<small>" in blok                       # detail hoort BIJ het signaal

    def test_dedupe_helper_is_de_enige_regel(self):
        assert _APP.count("function wsUniekeSignalen(") == 1
        i = _APP.index("function wsDeepContext(")
        assert "wsUniekeSignalen(ctx.concat(st.attn || []))" in _APP[i:i + 1400]


# ══ P1 — vensters expliciet ══════════════════════════════════════════════════
class TestVensters:
    def test_root_cause_vensters_verschillen_echt(self):
        """De belastinggrafiek telt `d > vandaag-7` (7 dagen); het trainingsblok start ÓP
        `vandaag-7` en loopt vooruit. Ze zijn bewust verschillend, dus labelen we ze."""
        bel = open(os.path.join(_ROOT, "belasting.py")).read()
        assert "grens_7d = vandaag - timedelta(days=7)" in bel and "if d > grens_7d:" in bel
        hc = open(os.path.join(_ROOT, "pwa", "home_core.py")).read()
        assert "start = today - timedelta(days=7)" in hc

    def test_t6_trainingsblok_stuurt_zijn_venster_mee(self, monkeypatch):
        monkeypatch.setattr(_home, "_heeft_token", lambda: True)
        monkeypatch.setattr(_home.FS, "get_workouts_deduped", lambda uk, s, e: [])
        r = _home.prio_trainingen("u1", vooruit=7)
        assert r["van"] == (TODAY - timedelta(days=7)).isoformat()
        assert r["tot"] == (TODAY + timedelta(days=7)).isoformat()

    def test_t6b_client_labelt_beide_scopes(self):
        assert "uitgevoerd + gepland" in _APP
        assert "runs in dit venster" in _APP           # scope bij het runs-getal
        assert "gemiddelde over de laatste 4 weken (hardlopen)" in _APP   # fallback-venster
        assert "Belasting — laatste 7 dagen" in _APP   # LOCK: kop grafiek ongewijzigd


# ══ P1 — doel ≠ actief schema ════════════════════════════════════════════════
class TestDoelVersusSchema:
    def test_t7_schema_feit_los_van_het_doel(self):
        assert "function wsSchemaFeit(" in _APP
        i = _APP.index("function wsSchemaFeit(")
        blok = _APP[i:i + 1400]
        assert '"Actief schema"' in blok
        assert "sc.einddatum" in blok and "days_left" in blok      # einddatum/dagen als bekend
        assert "st.gepland" in blok                                # anders: geplande sessies
        assert 'id="ws-schema-feit"' in _APP

    def test_geen_extra_call_voor_het_schema_feit(self):
        i = _APP.index("function wsSchemaFeit(")
        blok = _APP[i:i + 1400]
        assert "api(" not in blok and "fetch(" not in blok

    def test_doel_lege_staat_gaat_alleen_over_het_doel(self):
        """De lege staat spreekt alleen over het DOEL; het schema-feit staat er los onder,
        zodat 'geen doel' nooit meer leest als 'geen plan'."""
        i = _APP.index("Nog geen doel vastgelegd")
        copy = _APP[i:_APP.index("</p></div>`", i)]
        assert "schema" not in copy.lower()
        assert "race- of trainingsdoel" in copy
        # en het schema-feit hangt aan een EIGEN slot, buiten die lege staat
        assert _APP.index('id="ws-schema-feit"') > _APP.index("</p></div>`", i)


# ══ P2 — rustdag + secundaire actie ══════════════════════════════════════════
def _w(dagen, naam="Duurloop", p_km=10.0, status="Planned", uitgevoerd=False, amount=0.0):
    return {"workout_date": (TODAY + timedelta(days=dagen)).isoformat(), "name": naam,
            "is_race": False, "description": "x", "has_actual_data": True,
            "workout_status_text": "Completed" if uitgevoerd else status,
            "Activities": [{"name": naam, "planned_amount": p_km, "planned_duration": 0,
                            "amount": amount, "duration": 0}]}


class TestRustEnTweedeActie:
    @pytest.fixture(autouse=True)
    def _fs(self, monkeypatch):
        self.rows = []
        monkeypatch.setattr(_home, "_heeft_token", lambda: True)
        monkeypatch.setattr(_home.FS, "get_workouts_deduped", lambda uk, s, e: list(self.rows))

    def test_t12_rustdag_is_geen_uitgevoerde_training(self):
        """Zonder gepland volume/duur gaf de score-tak 1.0 ⇒ 'GEDAAN' voor een rustdag."""
        self.rows = [_w(-1, "Rust", 0.0), _w(+2, "Rust", 0.0)]
        st = [t["status"] for t in _home.prio_trainingen("u1", vooruit=7)["trainingen"]]
        assert st == ["rust", "rust"]

    def test_rustherkenning_is_streng(self):
        # Wél gepland volume onder een rust-naam → géén rustdag (data spreekt zichzelf tegen).
        self.rows = [_w(+1, "Rust", 8.0)]
        assert _home.prio_trainingen("u1", vooruit=7)["trainingen"][0]["status"] == "gepland"
        # Uitgevoerd onder een rust-naam → gewoon de bestaande score-tak.
        self.rows = [_w(-1, "Rust", 0.0, uitgevoerd=True)]
        assert _home.prio_trainingen("u1", vooruit=7)["trainingen"][0]["status"] == "gedaan"
        # Een gewone training heet geen rust.
        self.rows = [_w(+1, "Duurloop", 0.0)]
        assert _home.prio_trainingen("u1", vooruit=7)["trainingen"][0]["status"] == "gepland"

    def test_home_blijft_byte_identiek(self):
        self.rows = [_w(-1, "Rust", 0.0), _w(-2, "Duurloop", 10.0)]
        st = [t["status"] for t in _home.prio_trainingen("u1")["trainingen"]]
        assert "rust" not in st

    def test_t11_tweede_actie_blijft_bereikbaar(self):
        assert "function wsTweedeActie(" in _APP
        i = _APP.index("function wsTweedeActie(")
        blok = _APP[i:i + 800]
        assert 'a.soort !== (top || {}).soort' in blok        # ander soort dan de primaire
        assert "wsActieBtn(tweede" in blok
        assert '"Ook open"' in blok or "Ook open" in blok
        assert ".ws-next-2{" in _DS


# ══ Locks ════════════════════════════════════════════════════════════════════
class TestLocks:
    def test_t13_t14_ronde2_statusmodel_en_unknown_guard(self):
        assert 'const wsStaat = attn.length ? "aandacht" : (belStand ? "rustig" : "onbekend")' in _APP
        mag = _APP[_APP.index("function wsMagRustig("):]
        assert "!!lc.known" in mag[:400] and "!st.insufficient" in mag[:400]
        assert "Geen belastingstand bekend." in _APP
        assert "FS.is_executed_workout(w)" in open(os.path.join(_ROOT, "pwa", "home_core.py")).read()

    def test_t15_t16_t17_schema_deeplink_routing(self):
        assert "function openSchemaMode(" in _APP and "function openDossierEvent(" in _APP
        assert 'const h = "#" + view + "/" + encodeURIComponent(user_key);' in _APP
        assert _APP.count("function applyRoute") == 1
        assert "Nieuw schema bouwen" in _APP
        i = _APP.index("async function openDossierCockpit(")
        assert "dcSelectEvent(wrap, _ev)" in _APP[i:i + 2600]

    def test_t18_home_en_teampuls_ongemoeid(self):
        diff = subprocess.run(["git", "diff", "--name-only", "f1246dd", "--"],
                              cwd=_ROOT, capture_output=True, text=True).stdout.split()
        for verboden in ("belasting.py", "pwa/teampuls_core.py", "pwa/athlete_context.py",
                         "pwa/coach_read.py"):
            assert verboden not in diff, f"gelockte module aangeraakt: {verboden}"

    def test_t19_feedback_onaangeraakt(self):
        diff = subprocess.run(["git", "diff", "--name-only", "f1246dd", "--"],
                              cwd=_ROOT, capture_output=True, text=True).stdout.split()
        verboden = {"ai_feedback.py", "feedback_atoms.py", "feedback_copy.py",
                    "feedback_facts.py", "feedback_obligations.py", "metric_authority.py",
                    "pwa/feedback_core.py", "pwa/feedback_week.py"}
        assert not verboden.intersection(diff)

    def test_geen_nieuwe_store_of_engine(self):
        dc = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()
        assert "save_" not in dc and "intake_store" not in dc
        # het schema-feit en de vensters komen uit bestaande payloads, geen extra endpoint
        api = open(os.path.join(_ROOT, "pwa", "api.py")).read()
        assert api.count("@app.get(\"/api/home/prio/{user_key}/trainingen\")") == 1
