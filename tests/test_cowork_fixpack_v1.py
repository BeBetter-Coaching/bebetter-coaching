"""Cowork Functional Review Fix Pack v1 — source/CSS contract tests (B2–B12).

Bewaakt de doorgevoerde correcties op de echte productie-assets. Executable logica-tests voor
B4/B7 staan in tests/js/cowork_fixpack.test.mjs; athlete-continuïteit (B1) in
tests/js/athlete_continuity.test.mjs.

    python3 -m pytest tests/test_cowork_fixpack_v1.py -q
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_CSS = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()
_DS = open(os.path.join(_ROOT, "pwa", "static", "design-system.css")).read()


def _fn(name):
    i = _APP.index("function " + name + "(")
    j = _APP.index("{", i)
    d = 0
    for k in range(j, len(_APP)):
        if _APP[k] == "{":
            d += 1
        elif _APP[k] == "}":
            d -= 1
            if d == 0:
                return _APP[i:k + 1]
    raise AssertionError(name)


# ── B1: sidebar carries the shown athlete (fallback op _shownAthleteKey) ──────
def test_b1_openmodulefromnav_falls_back_to_shown_athlete():
    body = _fn("openModuleFromNav")
    assert "activeAthleteKey() || _shownAthleteKey(huidigeView)" in body
    assert "openWorkspace(key)" in body and 'openAthleteModule(view, key)' in body
    assert 'else toonView(view)' in body                       # generieke views laten context los
    sh = _fn("_shownAthleteKey")
    assert "wsSel" in sh and "dcSel" in sh                     # leest de getoonde selectie


# ── B2/B3: Feedback case = één natuurlijke leesflow, opent bovenaan ───────────
def test_b2_case_opens_at_top_no_thread_bottom():
    assert "sc.scrollTop = sc.scrollHeight" not in _fn("fbScrollThreadBottom")  # geen auto-bottom meer
    assert "no-op" in _fn("fbScrollThreadBottom").lower()
    assert 'sc.scrollTo({ top: 0 })' in _fn("fbOpen")          # elke case opent bovenaan


def test_b3_desktop_single_scroller():
    # Geen geneste detail-scroller in een center-scroller op desktop (>1100).
    blk = _DS[_DS.index("@media (min-width:1101px)"):]
    blk = blk[:blk.index("@media (max-width:1100px)")]
    assert ".fb-cockpit .fbf-scroll{max-height:none;overflow:visible}" in blk
    assert ".fb-cockpit .fb-focus-col{position:static;height:auto;overflow:visible}" in blk
    assert ".fb-cockpit .fb-queue-col{position:sticky" in blk  # queue blijft gepind rail


# ── B5: Teampuls 'Dossier →' opent Dossier ───────────────────────────────────
def test_b5_teampuls_dossier_routes_to_dossier():
    blk = _APP[_APP.index("function pulsItem"):_APP.index("function pulsItem") + 2400]
    assert 'openAthleteModule("dossier", it.user_key)' in blk
    assert 'openAthleteModule("atleten", it.user_key)' not in blk
    # stale zoekfilter-reset bij programmatische atleten-open
    assert "dossierPicker.clearQuery()" in _fn("openDossier")


# ── B6: state-banner is non-flow (geen layout shift) ─────────────────────────
def test_b6_banner_non_flow():
    assert ".gen-banner{display:none;position:fixed" in _CSS   # non-flow status-chip
    assert "margin:8px 12px 0" not in _CSS                     # oude in-flow marge weg


# ── B8: 'Dossier' is de canonieke naam; Feedback-kaart → 'Naar feedback' ─────
def test_b8_naming_dossier_not_cockpit():
    nav = _fn("athleteNav")
    assert '{ view: "dossier", label: "Dossier" }' in nav
    assert '{ view: "atleten", label: "Profiel" }' in nav
    assert 'label: "Cockpit"' not in nav
    assert "Dossier laden…" in _APP and "Cockpit laden…" not in _APP
    ws = _fn("wsRender")
    assert ">Naar feedback</button>" in ws
    assert "openModuleFromNav('feedback')" in ws
    assert "Cockpit openen" not in ws


# ── B10: Enter bevestigt de geselecteerde atleet in de picker ────────────────
def test_b10_enter_confirms_in_picker():
    ov = _APP[_APP.index("function openAthletePickerOverlay"):_APP.index("function openAthletePickerOverlay") + 2100]
    assert 'e.key === "Enter"' in ov and "picker.getSelected()" in ov and "opts.onConfirm(a)" in ov
    # gedeelde inline-picker: Enter gebruikt focus óf reeds-geselecteerd
    assert "const k = focusKey || selKey;" in _APP


# ── B11: één desktop-sidebarbreedte (geen Workspace-collapse) ────────────────
def test_b11_no_workspace_sidebar_collapse():
    assert "76px 1fr" not in _DS
    assert 'data-view="workspace"].on) .sidebar .nav-item span' not in _DS
    assert "FOCUS SHELL" not in _DS                            # collapse-blok volledig weg


# ── B12: Workspace Feedback-kaart bezit geen klachtenhistorie ────────────────
def test_b12_workspace_feedback_card_no_complaints():
    ws = _fn("wsRender")
    assert 'id="ws-context"' not in ws                         # klachten-slot verwijderd
    deep = _fn("wsLoadDeep")
    assert 'kind === "complaint"' not in deep                  # geen klacht/tegenstrijdigheid-fill meer
    assert "#ws-context" not in deep
    assert 'id="ws-plan"' in ws                                # doel/planning-slot blijft
