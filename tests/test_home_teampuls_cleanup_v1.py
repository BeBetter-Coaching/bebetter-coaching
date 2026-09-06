"""Home + Teampuls correctness & UX cleanup — server-side regressietests.

De gedragstests voor de frontend (toast-stack, back-navigatie, deep-link, races-route,
primair signaal in de preview, briefing-leeftijd) staan in
tests/js/home_teampuls_cleanup.test.mjs. Hier: de serverkant van dezelfde vijf punten —
één datumlogica voor de races-chip, de semantiek van de briefing-noemer, en de canonieke
hoofdreden die Home ingeklapt én uitgeklapt toont.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (_ROOT, os.path.join(_ROOT, "pwa")):
    if p not in sys.path:
        sys.path.insert(0, p)

import briefing as B                                   # noqa: E402
import coach_read                                      # noqa: E402
import home_core                                       # noqa: E402
import races_core                                      # noqa: E402

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_CSS = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()
_HTML = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()


# ══ T4 — de races-chip en de Races-pagina delen één datum-/filterlogica ═══════
_RACES = [
    {"workout_key": "w1", "athlete_name": "A", "workout_date": "2026-09-08", "wish_given": False},
    {"workout_key": "w2", "athlete_name": "B", "workout_date": "2026-09-09", "wish_given": True},
    {"workout_key": "w3", "athlete_name": "C", "workout_date": "2026-09-10", "wish_given": False},
]


@pytest.fixture
def fs_races(monkeypatch):
    gevraagd = []

    def _upcoming(days_ahead=42):
        gevraagd.append(days_ahead)
        # buiten het 7-dagenvenster hoort een extra race die de chip NIET telt
        extra = {"workout_key": "w9", "athlete_name": "Z", "workout_date": "2026-10-01",
                 "wish_given": False}
        return list(_RACES) + ([extra] if days_ahead > 7 else [])

    monkeypatch.setattr(races_core.FS, "get_upcoming_races", _upcoming)
    monkeypatch.setattr(races_core, "heeft_token", lambda: True)
    return gevraagd


class TestRacesChipVenster:
    def test_chip_telling_is_venster_plus_zonder_wens(self, fs_races):
        assert races_core.CHIP_DAGEN == 7
        assert races_core.chip_count() == 2          # w1 + w3 (w2 heeft al een wens)
        assert fs_races == [7]                        # exact het chipvenster, niet 42

    def test_bestemming_levert_exact_wat_de_chip_belooft(self, fs_races):
        n = races_core.chip_count()
        r = races_core.komende(days_ahead=races_core.CHIP_DAGEN, alleen_zonder_wens=True)
        assert len(r["items"]) == n                    # zelfde telling, zelfde bron
        assert all(not i["wens_gegeven"] for i in r["items"])
        assert r["dagen"] == 7 and r["alleen_zonder_wens"] is True

    def test_ongefilterde_pagina_blijft_ongewijzigd(self, fs_races):
        r = races_core.komende()                       # zijbalk-ingang
        assert r["dagen"] == 42 and r["alleen_zonder_wens"] is False
        assert len(r["items"]) == 4                    # inclusief de race mét wens én buiten 7d

    def test_home_telt_via_dezelfde_bron(self, fs_races):
        # Home dupliceert de datumlogica niet meer met een eigen FS-aanroep.
        assert "races_core.chip_count()" in open(
            os.path.join(_ROOT, "pwa", "home_core.py")).read()
        assert "get_upcoming_races(7)" not in open(
            os.path.join(_ROOT, "pwa", "home_core.py")).read()

    def test_endpoint_draagt_het_filter(self):
        api = open(os.path.join(_ROOT, "pwa", "api.py")).read()
        assert "def races_lijst(dagen: int = 42, zonder_wens: bool = False)" in api
        assert "alleen_zonder_wens=zonder_wens" in api

    def test_chip_label_belooft_niet_meer_dan_het_telt(self):
        # Het getal is 'races zonder wens in 7 dagen' — het label zegt dat nu ook.
        assert "zonder wens · komende ${RC_CHIP_DAGEN} dgn" in _APP
        assert 'openRaces("7d")' in _APP
        assert "9" not in "RC_CHIP_DAGEN"              # geen hardgecodeerd aantal


# ══ T5 — de briefing-noemer is gelabeld naar zijn echte populatie ════════════
class TestPopulatieLabel:
    def test_noemer_is_de_gefilterde_coaching_populatie(self, monkeypatch):
        """`n_atleten` telt exact de atleten die verzamel_week overhoudt: geen losse
        schema's, geen on-hold, geen opgezegde klanten. Dát is wat het label zegt."""
        athletes = [
            {"user_key": "u1", "name": "Actief", "group": "A", "all_groups": ["A"]},
            {"user_key": "u2", "name": "Stil", "group": "A", "all_groups": ["A"]},
            {"user_key": "u3", "name": "Los", "group": "los schema", "all_groups": ["los schema"]},
            {"user_key": "u4", "name": "OnHold", "group": "A", "all_groups": ["A"]},
            {"user_key": "u5", "name": "Opgezegd", "group": "A", "all_groups": ["A"]},
        ]
        monkeypatch.setattr(B.intake_store, "load_on_hold", lambda: {"u4": {}})
        monkeypatch.setattr(B.intake_store, "load_admin_clients",
                            lambda: {"u5": {"status": "Opgezegd"}})
        monkeypatch.setattr(B.fs_client, "group_is_excluded",
                            lambda g, ex: str(g or "").lower() in ex)
        monkeypatch.setattr(B.fs_client, "get_workouts_deduped",
                            lambda uk, s, e: [{"x": 1}] if uk == "u1" else [])
        monkeypatch.setattr(B.fs_client, "is_executed_workout", lambda w: False)
        monkeypatch.setattr(B, "_entry_van_workout",
                            lambda w: {"completed": True, "activity_type": "Run", "distance": 10})
        monkeypatch.setattr(B.fs_client, "_parallel_per_athlete",
                            lambda todo, fn: [fn(a) for a in todo])

        stats = B.verzamel_week(athletes)
        assert stats["n_atleten"] == 2                 # u1 + u2; u3/u4/u5 vallen buiten de populatie
        assert stats["n_actief"] == 1                  # alleen u1 trainde
        assert stats["stil"] == ["Stil"]

    def test_label_benoemt_de_populatie_en_verklaart_het_verschil(self):
        assert B.POPULATIE_LABEL == "gecoachte atleten actief"
        u = B.POPULATIE_UITLEG
        for stuk in ("actieve coaching", "los", "on hold", "opgezegd",
                     "afgelopen 7 dagen", "volledige FinalSurge-roster"):
            assert stuk in u, f"uitleg mist: {stuk}"

    def test_briefing_endpoint_levert_het_label_mee(self):
        tp = open(os.path.join(_ROOT, "pwa", "teampuls_core.py")).read()
        assert '"populatie_label": B.POPULATIE_LABEL' in tp
        assert '"populatie_uitleg": B.POPULATIE_UITLEG' in tp

    def test_home_noemer_is_bewust_een_andere_populatie(self):
        # Home blijft de volledige roster tonen: de getallen worden NIET gelijkgetrokken.
        hc = open(os.path.join(_ROOT, "pwa", "home_core.py")).read()
        assert "atleten = len(FS.get_athletes())" in hc

    def test_frontend_rendert_label_en_uitleg(self):
        assert "r.populatie_label" in _APP and "r.populatie_uitleg" in _APP
        assert "${s.n_actief ?? \"?\"}/${s.n_atleten ?? \"?\"} ${esc(popLabel)}" in _APP


# ══ T6 — één bron voor het primaire signaal ══════════════════════════════════
def _bel(ernst, km_recent, km_basis, signalen):
    return {"user_key": "u1", "naam": "Test", "ernst": ernst, "signalen": signalen,
            "metrics": {"km_recent": km_recent, "km_basis_week": km_basis}}


class TestPrimairSignaal:
    def test_hoofdreden_is_de_belasting_niet_de_eerste_bronzin(self):
        # De echte auditcase: de eerste bronzin is een notitie-signaal, maar de atleet
        # staat in de lijst om de belasting.
        lm = coach_read.load_metric(_bel("let_op", 40, 46, ["Noemt in notities: gevoelig"]))
        assert lm["primair"] == "Belasting let op · -13% t.o.v. referentie"
        assert lm["kort"] == "belasting let op -13%"
        # de bronzin blijft beschikbaar als ONDERBOUWING
        assert lm["reden"] == "Noemt in notities: gevoelig"
        assert lm["signalen"] == ["Noemt in notities: gevoelig"]

    def test_home_signaal_toont_de_hoofdreden(self):
        s = home_core._belasting_signal(_bel("let_op", 40, 46, ["Noemt in notities: gevoelig"]))
        assert s["reden"] == "Belasting let op · -13% t.o.v. referentie"
        assert s["kort"] == "belasting let op -13%"
        assert s["detail"]["primair"] == s["reden"]
        assert s["detail"]["signalen"] == ["Noemt in notities: gevoelig"]

    def test_hoog_en_positief_percentage(self):
        lm = coach_read.load_metric(_bel("hoog", 64, 40, ["Volume +60% laatste 7 dagen"]))
        assert lm["primair"] == "Belasting hoog · +60% t.o.v. referentie"
        assert lm["kort"] == "belasting hoog +60%"

    def test_zonder_percentage_geen_verzonnen_getal(self):
        lm = coach_read.load_metric({"ernst": "hoog", "signalen": ["Gevoel zakt"], "metrics": {}})
        assert lm["primair"] == "Belasting hoog"
        assert lm["kort"] == "belasting hoog"

    def test_ranking_en_state_ongewijzigd(self):
        """Presentatie raakt de waarheid niet: fingerprint/severity/tier blijven gelijk,
        dus Gezien/Later-state en de rangschikking veranderen niet."""
        s = home_core._belasting_signal(_bel("hoog", 64, 40, ["Volume +60% laatste 7 dagen"]))
        assert s["fingerprint"] == "bhoog" and s["severity"] == 2 and s["tier"] == "actie"
        item = home_core._bouw_item("u1", "Test", "Test", [
            s,
            {"soort": "schema", "tier": "aandacht", "reden": "schema loopt af over 3 dagen",
             "kort": "schema nog 3d", "fingerprint": "s:a", "severity": 1, "detail": {}, "context": []},
        ])
        # tier-rank wint; signalen[0] is de hoofdreden die de UI toont
        assert item["signalen"][0]["soort"] == "belasting"
        assert item["reden"] == "Belasting hoog · +60% t.o.v. referentie"
        assert item["chips"][0]["kort"] == "belasting hoog +60%"
        assert item["signature"] == "belasting:bhoog|schema:s:a"

    def test_ingeklapt_en_uitgeklapt_lezen_dezelfde_keuze(self):
        assert _APP.count("function prioHoofdSignaal(") == 1
        assert _APP.count("function prioPrimairTekst(") == 1
        i = _APP.index("function prioItem(")
        assert "prioPrimairTekst(prioHoofdSignaal(it))" in _APP[i:i + 1600]
        d = _APP.index("function prioDetailHtml(")
        assert "const hoofd = prioHoofdSignaal(it)" in _APP[d:d + 1200]
        assert "prioPrimairTekst(hoofd)" in _APP[d:d + 2400]


# ══ T1 — toast-stack: presentatiecontract ════════════════════════════════════
class TestToastStack:
    def test_een_container_aan_de_veilige_rand(self):
        assert 'id="toaststack"' in _HTML
        # offline + melding staan IN de stack (geen losse fixed elementen meer)
        stack = _HTML.index('id="toaststack"')
        assert stack < _HTML.index('id="offline"') < _HTML.index('id="msg"')
        assert "#toaststack{position:fixed" in _CSS
        assert "env(safe-area-inset-bottom)" in _CSS.split("#toaststack{")[1].split("}")[0]

    def test_meldingen_stapelen_met_tussenruimte(self):
        blok = _CSS.split("#toaststack{")[1].split("}")[0]
        assert "display:flex" in blok and "flex-direction:column" in blok and "gap:10px" in blok
        assert "pointer-events:none" in blok                # container blokkeert geen scroll

    def test_geen_losse_vaste_coordinaten_meer(self):
        for dood in ("#msg{bottom:", "#offline{bottom:", ".gen-banner{", ".prio-toast{position:fixed"):
            assert dood not in _CSS, f"oude losse melding-positie nog aanwezig: {dood}"

    def test_state_melding_dooft_vanzelf_en_blokkeert_niets(self):
        assert "const _GEN_TOAST_MS = 8000" in _APP
        i = _APP.index("function genToast(")
        blok = _APP[i:i + 700]
        assert "setTimeout" in blok and 'classList.remove("on")' in blok
        assert "toastHost().appendChild" in blok
        assert "pointer-events:none" in _CSS.split(".gen-toast{")[1].split("}")[0]

    def test_undo_toast_leeft_in_dezelfde_stack(self):
        assert _APP.count("toastHost().appendChild(t)") == 3   # prio-toast (2×) + gen-toast
        assert "document.body.appendChild(t)" not in _APP


# ══ T2/T3 — routecontract (gedrag staat in de JS-suite) ══════════════════════
class TestRouteContract:
    def test_openworkspace_schrijft_de_route_voor_de_view(self):
        i = _APP.index("function openWorkspace(")
        blok = _APP[i:i + 800]
        # route eerst, dan de view-wissel onder de _routing-guard → geen bare
        # #workspace-entry ertussen (toonView schrijft zelf een bare route).
        assert blok.index("history.pushState") < blok.index("_routing = true")
        assert blok.index("_routing = true") < blok.index('try { toonView("workspace"); }')
        assert "finally { _routing = vorig; }" in blok

    def test_bare_workspace_route_heeft_een_bestemming(self):
        assert "function wsLeegRoute(" in _APP
        assert "wsOpenPending = \"\"; wsLeegRoute();" in _APP
        i = _APP.index("function wsLeegRoute(")
        assert "wsSel = \"\"" in _APP[i:i + 300]          # atleet echt loslaten

    def test_races_scope_zit_in_de_route(self):
        assert 'else if (view === "races") rcZetScope(ident || "alle")' in _APP
        assert 'else if (view === "races") openRaces("alle")' in _APP   # globale nav = ongefilterd


# ══ T7/T8 — P2: bestaande atleet bij intake + leeftijd weekbriefing ══════════
class TestP2Coherentie:
    def test_bestaande_atleet_indicatie_gebruikt_de_bestaande_suggestie(self):
        # Geen nieuwe matching: we labelen alleen de al bestaande, coach-te-bevestigen
        # kandidaat eerlijker. Koppelen blijft een expliciete coach-actie.
        assert "bestaat al als atleet:" in _APP
        assert "bevestig zelf" in _APP
        i = _APP.index("function laadOrphanIntakes(")
        assert "a.suggestie" in _APP[i:i + 1400]

    def test_suggestie_blijft_eenduidig_en_niet_automatisch(self):
        ac = open(os.path.join(_ROOT, "pwa", "atleten_core.py")).read()
        i = ac.index("def _fs_suggestie(")
        blok = ac[i:i + 900]
        assert "if len(treffers) != 1" in blok            # 0 of >1 → geen suggestie
        ic = open(os.path.join(_ROOT, "pwa", "intake_core.py")).read()
        assert "def link_intake(" in ic                    # koppelen blijft expliciet

    def test_briefing_leeftijd_zichtbaar(self):
        assert "function briefGemaaktLabel(" in _APP
        assert "dagen oud" in _APP
        assert "briefGemaaktLabel(r.gemaakt)" in _APP
        # de briefingtekst zelf blijft ongemoeid
        assert "briefHtml(r.tekst" in _APP


# ══ Non-goals: Feedback en de waarheidslagen blijven ongemoeid ═══════════════
class TestNonGoals:
    def test_feedback_generatiepad_onaangeraakt(self):
        import subprocess
        diff = subprocess.run(
            ["git", "diff", "--name-only", "8786210", "--"],
            cwd=_ROOT, capture_output=True, text=True).stdout.split()
        verboden = {"ai_feedback.py", "feedback_atoms.py", "feedback_copy.py",
                    "feedback_facts.py", "feedback_obligations.py", "metric_authority.py",
                    "pwa/feedback_core.py", "pwa/feedback_week.py"}
        raakt = verboden.intersection(diff)
        assert not raakt, f"Feedback buiten scope, toch aangeraakt: {sorted(raakt)}"

    def test_geen_nieuwe_store_of_cache(self):
        hc = open(os.path.join(_ROOT, "pwa", "home_core.py")).read()
        rc = open(os.path.join(_ROOT, "pwa", "races_core.py")).read()
        assert "save_" not in rc                            # races_core blijft lezend (m.u.v. wens)
        assert rc.count("FS.post_comment") == 1             # de bestaande race-wens-write
        assert "_MEM" in hc                                  # bestaande snapshot, geen nieuwe laag
