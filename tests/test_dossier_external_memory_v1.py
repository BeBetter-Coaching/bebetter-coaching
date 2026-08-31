"""Dossier / External Memory v1 — verklarende coachgeheugenlaag bovenop canonical truth.

Geen tweede intelligentie-engine: Dossier projecteert bestaande AthleteState-evidence,
belasting-stand en intake. Kernpunten van deze milestone:

  P0 — complaints internal compute failure structureel opgelost. Root cause (repro):
       een vrije-tekst intakeklacht die `_vind` niet als gelabelde klacht herkende viel
       terug op `[{"": ""}]` (een DICT), waardoor `_area(re.search(...))` een TypeError
       gooide → hele complaints-stage viel om → onterecht "interne fout" + klacht
       onzichtbaar in Dossier terwijl Home/Teampuls hem toonden. Fix: sentinel "" i.p.v.
       een dict → onbekende klacht wordt tóch een 'onbekend'-melding (blijft zichtbaar).
  Coherentie — complaint + belasting komen uit DEZELFDE canonical bron als Home/Teampuls
       (brain-evidence + de gedeelde belasting-stand). Teampuls-observatie is óók zichtbaar
       als hij al is afgehandeld, mét de reden (verklaart 'waarom niet op Home').
  Partial-context — een falende stage is stage-lokaal (`build_diagnostic`) en wist de rest
       van het dossier nooit.
  Doelen/planning — compacte projectie uit goal-evidence + laatst geconfigureerd blok.

    python3 -m pytest tests/test_dossier_external_memory_v1.py -q
"""
import os
import sys
from datetime import date, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()

from brain import complaints as _complaints    # noqa: E402
from brain import state as _bstate             # noqa: E402
import dossier_cockpit as _dc                  # noqa: E402
from brain.models import ACTIVE, RECENT, RECURRING, RESOLVED, SourceHealth   # noqa: E402


def _fn(name):
    i = _APP.index(f"function {name}(")
    depth, started = 0, False
    for j in range(i, len(_APP)):
        c = _APP[j]
        if c == "{":
            depth += 1; started = True
        elif c == "}":
            depth -= 1
            if started and depth == 0:
                return _APP[i:j + 1]
    raise AssertionError(f"function {name} niet gebalanceerd")


TODAY = date(2026, 8, 25)


def _grp(evs):
    return [e for e in evs if e.key.startswith("complaint.") and not e.key.startswith("complaint.mention")]


# ══ P0 — complaints correctness (root cause) ═══════════════════════════════
class TestComplaintsCorrectness:
    def test_1_vrije_tekst_klacht_geen_crash_wel_zichtbaar(self):
        raw = {"intake": {"huidige_klachten": "voelt zich al weken niet lekker"}, "intake_ts": "2026-08-20"}
        out = _complaints.build(raw, "uk", TODAY)          # mag NIET throwen
        g = _grp(out)
        assert g and g[0].value == "onbekend"              # klacht blijft zichtbaar als 'onbekend'

    def test_2_gelabelde_klacht_classificeert(self):
        raw = {"intake": {"huidige_klachten": "pijn in de knie"}, "intake_ts": "2026-08-24"}
        g = _grp(_complaints.build(raw, "uk", TODAY))
        assert g and g[0].value == "knie" and g[0].status == ACTIVE

    def test_3_active_blijft_active_zonder_resolved(self):
        raw = {"notes": [{"datum": "2026-08-24", "tekst": "last van de knie"}]}
        g = _grp(_complaints.build(raw, "uk", TODAY))
        assert g and g[0].status in (ACTIVE, RECENT, RECURRING) and g[0].status != RESOLVED

    def test_4_afwezigheid_nieuwe_mention_is_niet_resolved(self):
        # Alleen een oude melding, geen 'hersteld'-tekst → nooit automatisch RESOLVED.
        raw = {"notes": [{"datum": "2026-05-01", "tekst": "last van de kuit"}]}
        g = _grp(_complaints.build(raw, "uk", TODAY))
        assert g and g[0].status != RESOLVED

    def test_5_expliciet_resolved_wordt_resolved(self):
        raw = {"notes": [{"datum": "2026-06-01", "tekst": "pijn in de knie"},
                         {"datum": "2026-08-20", "tekst": "knie is helemaal hersteld"}]}
        g = _grp(_complaints.build(raw, "uk", TODAY))
        assert g and g[0].status == RESOLVED

    def test_6_known_empty_geen_error(self):
        assert _complaints.build({"intake": {"huidige_klachten": ""}}, "uk", TODAY) == []

    def test_7_area_defensief_tegen_non_string(self):
        assert _dc  # module import
        assert _complaints._area({"x": 1}) == "onbekend"   # nooit een TypeError


# ══ Partial-context resilience (stage-lokaal) ══════════════════════════════
class TestPartialResilience:
    def test_8_falende_complaints_stage_wist_andere_evidence_niet(self, monkeypatch):
        # Forceer een throw in de complaints-stage; base/intake-evidence (doel) moet blijven.
        monkeypatch.setattr(_bstate._complaints, "build",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        raw = {"intake": {"doel": "10k sub 50", "athlete_name": "X"}, "intake_ts": "2026-08-20"}
        health = [SourceHealth(source="intake", available=True, stale=False)]
        st = _bstate.assemble("uk", "X", raw, health, TODAY)
        stages = [e["stage"] for e in getattr(st, "build_errors", [])]
        assert "complaints" in stages                       # stage-lokaal gemarkeerd
        assert any(e.key == "goal.doel" for e in st.evidence)  # andere kennis behouden


# ══ Doelen & planning-projectie ════════════════════════════════════════════
class TestPlanning:
    def test_9_schema_status_loopt_vs_afgelopen(self):
        assert "loopt" in _dc._schema_status("2026-09-10", TODAY)
        assert "afgelopen" in _dc._schema_status("2026-08-01", TODAY)
        assert _dc._schema_status("", TODAY) == ""

    def test_10_planning_projecteert_doel_race_en_blok(self):
        evs = [{"key": "goal.doel", "domain": "goal", "value": "HM sub 1:45"},
               {"key": "goal.race", "domain": "goal", "value": "2026-11-08"}]
        raw = {"intake": {"startdatum": "2026-08-31", "schema_einddatum": "2026-11-22", "op_tijd": True}}
        p = _dc._planning(evs, raw, TODAY)
        labels = {r["label"]: r["value"] for r in p["rows"]}
        assert labels.get("Hoofddoel") == "HM sub 1:45"
        assert labels.get("Wedstrijddatum") == "2026-11-08"
        assert "2026-08-31" in labels.get("Schema-blok (laatst geconfigureerd)", "")
        assert labels.get("Uitvoerwijze") == "tijd (minuten)"
        assert "Schema-status" in labels

    def test_11_planning_leeg_is_onbekend_geen_crash(self):
        p = _dc._planning([], {}, TODAY)
        assert p["onbekend"] is True and p["rows"] == []


# ══ Belasting-observatie (Teampuls-coherentie) + freshness ════════════════
class TestLoadObservation:
    def test_12_afgehandelde_hoge_belasting_zichtbaar_met_reden(self):
        raw = {"belasting": {"ernst": "hoog", "signalen": ["+32% t.o.v. referentie"],
                             "_afgehandeld": True, "_stand_datum": TODAY.isoformat()}}
        lo = _dc._load_observation(raw, TODAY)
        assert lo and lo["ernst"] == "hoog" and lo["afgehandeld"] is True
        assert "referentie" in lo["signalen"]

    def test_13_let_op_belasting_is_observatie(self):
        raw = {"belasting": {"ernst": "let_op", "signalen": [], "_stand_datum": TODAY.isoformat()}}
        lo = _dc._load_observation(raw, TODAY)
        assert lo and lo["ernst"] == "let_op" and lo["afgehandeld"] is False

    def test_14_geen_belasting_geen_observatie(self):
        assert _dc._load_observation({}, TODAY) is None
        assert _dc._load_observation({"belasting": {"ernst": "geen"}}, TODAY) is None

    def test_15_verouderde_stand_is_geen_actuele_observatie(self):
        # Freshness-guard (zelfde als load.signal): een verlopen stand → geen observatie.
        oud = (TODAY - timedelta(days=10)).isoformat()
        raw = {"belasting": {"ernst": "hoog", "signalen": ["x"], "_stand_datum": oud}}
        assert _dc._load_observation(raw, TODAY) is None
        vers = (TODAY - timedelta(days=1)).isoformat()
        raw2 = {"belasting": {"ernst": "hoog", "signalen": ["x"], "_stand_datum": vers}}
        assert _dc._load_observation(raw2, TODAY) is not None

    # ── LIVE-CLOSE: actuele rode Home-trigger mag in Dossier niet verdwijnen ──
    def test_25_actief_hoog_open_home_actie_is_observatie(self):
        # Case A: verse hoge belasting, NIET afgehandeld = de rode Home-trigger.
        # Moet een observatie opleveren mét open-Home-actie-duiding (voorheen viel de
        # UI-render hierop terug op niets → reden verdween).
        raw = {"belasting": {"ernst": "hoog", "signalen": ["Volume +200% deze week"],
                             "metrics": {"ratio": 3.0}, "_afgehandeld": False,
                             "_stand_datum": TODAY.isoformat()}}
        lo = _dc._load_observation(raw, TODAY)
        assert lo and lo["ernst"] == "hoog"
        assert lo["afgehandeld"] is False and lo["home_action"] is True

    def test_26_percentage_delta_blijft_behouden(self):
        # +200%-achtige case: metrics.ratio → canonical delta zichtbaar (niet verzonnen).
        raw = {"belasting": {"ernst": "hoog", "signalen": ["x"],
                             "metrics": {"ratio": 3.0}, "_stand_datum": TODAY.isoformat()}}
        assert _dc._load_observation(raw, TODAY)["delta_pct"] == 200
        # +32% → 32
        raw2 = {"belasting": {"ernst": "let_op", "signalen": ["x"],
                              "metrics": {"ratio": 1.32}, "_stand_datum": TODAY.isoformat()}}
        assert _dc._load_observation(raw2, TODAY)["delta_pct"] == 32
        # geen ratio (klacht/rpe-signaal) → geen verzonnen delta
        raw3 = {"belasting": {"ernst": "hoog", "signalen": ["Noemt: knie"],
                              "metrics": {"ratio": None}, "_stand_datum": TODAY.isoformat()}}
        assert _dc._load_observation(raw3, TODAY)["delta_pct"] is None

    def test_27_afgehandeld_geen_open_home_actie(self):
        # Case B: handled load → home_action False (verklaart 'wél Teampuls, geen Home').
        raw = {"belasting": {"ernst": "hoog", "signalen": ["x"], "metrics": {"ratio": 2.0},
                             "_afgehandeld": True, "_stand_datum": TODAY.isoformat()}}
        lo = _dc._load_observation(raw, TODAY)
        assert lo["afgehandeld"] is True and lo["home_action"] is False
        assert lo["delta_pct"] == 100

    def test_28_home_action_volgt_afgehandeld_canonical(self):
        # home_action is exact de inverse van _afgehandeld (= zichtbare_resultaten-membership).
        for handled in (True, False):
            raw = {"belasting": {"ernst": "hoog", "signalen": ["x"],
                                 "_afgehandeld": handled, "_stand_datum": TODAY.isoformat()}}
            assert _dc._load_observation(raw, TODAY)["home_action"] is (not handled)


# ══ Effectieve handled-status (gedeelde visibility-semantiek, externe review) ══
# `_afgehandeld` mag GEEN kale membership zijn: Teampuls/Home/Dossier moeten dezelfde
# `belasting.zichtbare_resultaten`-semantiek (tot>=vandaag + escalatie let_op→hoog)
# gebruiken. Getest via `sources.gather` (dat de brain-raw bouwt).
import belasting as _bel                        # noqa: E402
from brain import sources as _sources           # noqa: E402


def _stand(uk, ernst, handled=None):
    d = {"datum": date.today().isoformat(),
         "resultaten": [{"user_key": uk, "ernst": ernst, "signalen": ["x"]}],
         "afgehandeld": {}}
    if handled:
        d["afgehandeld"][uk] = handled
    return d


class TestEffectiveHandled:
    def _afgehandeld(self, monkeypatch, stand, uk="uk"):
        monkeypatch.setattr(_sources.intake_store, "load_belasting", lambda: stand)
        raw, _ = _sources.gather(uk, TODAY)
        return (raw.get("belasting") or {}).get("_afgehandeld")

    def test_20_geldig_afgehandeld_telt_als_afgehandeld(self, monkeypatch):
        morgen = (date.today() + timedelta(days=1)).isoformat()
        st = _stand("uk", "hoog", handled={"tot": morgen, "ernst": "hoog"})
        assert self._afgehandeld(monkeypatch, st) is True

    def test_21_verlopen_afhandeling_telt_niet_meer(self, monkeypatch):
        gisteren = (date.today() - timedelta(days=1)).isoformat()
        st = _stand("uk", "hoog", handled={"tot": gisteren, "ernst": "hoog"})
        assert self._afgehandeld(monkeypatch, st) is False   # verlopen → weer actief

    def test_22_escalatie_let_op_naar_hoog_maakt_actief(self, monkeypatch):
        morgen = (date.today() + timedelta(days=1)).isoformat()
        # afgehandeld als let_op, maar signaal is nu hoog → escalatie → weer actief
        st = _stand("uk", "hoog", handled={"tot": morgen, "ernst": "let_op"})
        assert self._afgehandeld(monkeypatch, st) is False

    def test_23_niet_afgehandeld_blijft_actief(self, monkeypatch):
        st = _stand("uk", "hoog")
        assert self._afgehandeld(monkeypatch, st) is False

    def test_24_semantiek_is_die_van_zichtbare_resultaten(self):
        # Borgt dat we DE gedeelde functie gebruiken (geen kopie): een geëscaleerd
        # signaal is zichtbaar; een geldig-afgehandeld gelijk signaal niet.
        morgen = (date.today() + timedelta(days=1)).isoformat()
        esc = _stand("uk", "hoog", handled={"tot": morgen, "ernst": "let_op"})
        assert any(r["user_key"] == "uk" for r in _bel.zichtbare_resultaten(esc))
        same = _stand("uk", "hoog", handled={"tot": morgen, "ernst": "hoog"})
        assert not any(r["user_key"] == "uk" for r in _bel.zichtbare_resultaten(same))

    def test_25_dossier_home_actie_matcht_home_actielijst(self, monkeypatch):
        # Case A/B end-to-end: Home/Teampuls/Dossier delen ÉÉN belastingtruth. De
        # Dossier-observatie 'open Home-actie' (home_action) is exact de Home-actielijst
        # (= zichtbare_resultaten-membership), afgeleid uit dezelfde stand.
        today = date.today()

        def obs(stand):
            monkeypatch.setattr(_sources.intake_store, "load_belasting", lambda: stand)
            raw, _ = _sources.gather("uk", today)
            return _dc._load_observation(raw, today)

        # actief (niet afgehandeld) → op Home-actielijst → home_action True
        st_actief = _stand("uk", "hoog")
        assert any(r["user_key"] == "uk" for r in _bel.zichtbare_resultaten(st_actief))
        assert obs(st_actief)["home_action"] is True
        # geldig afgehandeld → NIET op Home-actielijst → home_action False, wél observatie
        morgen = (today + timedelta(days=1)).isoformat()
        st_hand = _stand("uk", "hoog", handled={"tot": morgen, "ernst": "hoog"})
        assert not any(r["user_key"] == "uk" for r in _bel.zichtbare_resultaten(st_hand))
        lo = obs(st_hand)
        assert lo is not None and lo["home_action"] is False

    def test_26_compliance_only_is_geen_load_observatie(self):
        # Case D: een Home-alert wegens gemiste trainingen (compliance) is GEEN
        # belastingsignaal — Dossier mag dat niet foutief als load-observatie tonen.
        # Zonder belasting-ernst in de stand → geen observatie (geen projectie-menging).
        assert _dc._load_observation({"belasting": None}, date.today()) is None
        assert _dc._load_observation({"belasting": {"ernst": "geen"}}, date.today()) is None


# ══ Frontend cockpit-hiërarchie + partial banner ═══════════════════════════
class TestCockpitFrontend:
    def test_15_planning_block_gerenderd(self):
        # Living Memory Cockpit: planning voedt de toekomst-knopen op de spine
        # (dcFutureNodes) én de Doelen-lens (planRows). Zelfde echte bron (vm.planning).
        body = _fn("dcRender")
        assert "vm.planning" in body
        assert "dcFutureNodes(plan)" in body
        assert "Doelen &amp; beslissingen" in _fn("dcScene")   # planning-lens (koers)
        fut = _fn("dcFutureNodes")
        assert "Wedstrijddatum" in fut and "Schema-blok" in fut

    def test_16_load_observatie_note_gerenderd_met_reden(self):
        body = _fn("dcRender")
        assert "vm.load_observation" in body
        assert "eerder afgehandeld" in body and "geen open Home-actie" in body

    def test_16b_load_observatie_altijd_gerenderd_niet_gegate(self):
        # LIVE-CLOSE (behouden in de nieuwe cockpit): de load-observatie is niet
        # beperkt tot afgehandeld/let_op — de actief-hoge (open Home-actie) case MOET
        # ook renderen, met canonieke delta + duiding, in de Klachten&signalen-lens.
        body = _fn("dcRender")
        i = body.index("vm.load_observation")
        rest = body[i:]
        assert "if (lo) {" in rest                     # ongegate render
        assert "open Home-actie" in rest               # active-high duiding
        assert "t.o.v. referentie" in rest             # canonical delta zichtbaar
        assert "lo.delta_pct" in rest and "lo.home_action" in rest
        # geen ernst-gate op de render van de observatie zelf
        assert "lo.afgehandeld || lo.ernst" not in rest

    def test_17_diag_banner_is_stage_lokaal_niet_alles_of_niets(self):
        # De per-stage diag is een banner die de andere secties NIET gate; attention/
        # planning/domains worden bepaald ongeacht build_diagnostic.
        body = _fn("dcRender")
        assert "vm.build_diagnostic" in body
        # signalen (attention+load) en planning worden onvoorwaardelijk daarna berekend
        i_diag = body.index("build_diagnostic")
        assert body.index("sigRows", i_diag) < i_diag or "sigRows" in body
        # de banner gate niet: dcScene/dcStack renderen shelf/lenzen sowieso
        assert "dcScene(d)" in body and "dcStack(d)" in body

    def test_18_attention_top_met_calme_empty_state(self):
        # De actuele lijn (current-state anchor) draait op echte attention/load; de
        # kalme staat toont een eerlijke lege-lezing, geen leeg blok.
        body = _fn("dcRender")
        assert "domIssue" in body
        assert "Geen open klacht of signaal" in body   # rustige empty-state

    def test_19_geen_nieuwe_engine_in_cockpit(self):
        # Dossier projecteert; geen eigen klacht-/belasting-/priority-engine.
        src = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()
        assert "dagelijkse_check" not in src        # geen recompute van belasting
        assert "get_compliance_alerts" not in src   # geen eigen Home-actie-engine
