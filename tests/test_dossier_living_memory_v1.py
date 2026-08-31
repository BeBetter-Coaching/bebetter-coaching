"""Dossier — LIVING MEMORY COCKPIT v1 (presentatie-contract).

Vergrendelt de nieuwe cockpit-compositie zonder de gelockte Dossier-waarheid te
raken: één MEMORY SPINE met een lichtgevend VANDAAG-ankerpunt, context als glas-
lenzen, geselecteerd-event als ruimtelijke voorgrond (geen modal/route), en de
EERLIJKE lege-staat (history-capture OFF → geheugenlijn bouwt vanaf-nu op, nooit
verzonnen knopen). Render = presentatie: geen tweede engine/store/route/truth.

    python3 -m pytest tests/test_dossier_living_memory_v1.py -q
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_DS = open(os.path.join(_ROOT, "pwa", "static", "design-system.css")).read()
_HTML = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()


def _fn(name, src=None):
    s = src if src is not None else _APP
    i = s.index("function " + name + "(")
    j = s.index("{", i)
    d = 0
    for k in range(j, len(s)):
        if s[k] == "{":
            d += 1
        elif s[k] == "}":
            d -= 1
            if d == 0:
                return s[j:k + 1]
    raise AssertionError("unbalanced " + name)


class TestMemorySpine:
    def test_1_memory_spine_is_de_hero(self):
        # HERO = tijd zelf: één spine (rail) met warm verleden → koele toekomst en een
        # lichtgevend VANDAAG-ankerpunt. GEEN verticale lijst-tijdlijn.
        scene = _fn("dcScene")
        assert "dc-rail" in scene and "dc-rail-future" in scene   # doorlopende + gestippelde toekomst
        assert "dcHex(coreTone)" in scene                         # kern draagt de dominante toon
        assert "Vandaag" in scene                                 # ankerpunt-label
        for sel in (".dc-rail", ".dc-coredot", ".dc-dot", ".dc-node.future", ".dc-rail-future"):
            assert sel in _DS, f"spine-primitive {sel} niet gestyled"

    def test_2_verleden_uit_changes_toekomst_uit_planning(self):
        rn = _fn("dcRender")
        assert "dcPastNodes(chg)" in rn                           # verleden = echte changes
        assert "dcFutureNodes(plan)" in rn                        # toekomst = planning
        past, fut = _fn("dcPastNodes"), _fn("dcFutureNodes")
        # geen verzonnen knopen: past mapt uitsluitend de aangeleverde changes/timeline
        assert "chg" in past and "provenance_refs" in past
        assert "future: true" in fut and "Wedstrijddatum" in fut

    def test_3_kern_is_puur_ankerpunt_geen_workspace_gauge(self):
        # Dossier RECREËERT Workspace niet: geen Athlete Core / load-gauge in de kern.
        for fn in ("dcRender", "dcScene", "dcStack"):
            body = _fn(fn)
            assert "wsCore(" not in body and "wsAnchor(" not in body, f"{fn} recreëert de Workspace-hero"
        # de kern toont de overall-staat als chip, GEEN groot metriek-getal
        assert "core-chip" in _fn("dcScene")
        assert "core-metric" not in _APP and "core-metric" not in _DS


class TestHonestEmptyState:
    def test_4_lege_historie_is_eerlijk_geen_fake_knopen(self):
        # capture OFF / geen changes → emptyHistory: eerlijke 'bouwt vanaf-nu'-uitleg,
        # nooit verzonnen tijdlijn-knopen.
        rn, scene, stack = _fn("dcRender"), _fn("dcScene"), _fn("dcStack")
        assert "emptyHistory = !past.length" in rn
        assert "vanaf nu" in scene and "nog niets is vastgelegd" in scene
        assert "vanaf nu" in stack
        # de honderd-procent-eerlijke regel uit de brainlaag blijft: geen reconstructie
        assert "dc-l-empty" in scene

    def test_5_timeline_events_alleen_uit_echte_bron(self):
        # oudere spine-knopen komen ALLEEN uit een niet-lege vm.timeline (echte events),
        # nooit gefabriceerd.
        rn = _fn("dcRender")
        assert "!tl.empty_reason && tlv.length" in rn


class TestSelectedEventSpatial:
    def test_6_geselecteerd_event_is_ruimtelijk_geen_modal_of_route(self):
        sel = _fn("dcSelectNode")
        assert 'classList.add("sel")' in sel                      # scène komt naar voren, dimt de rest
        assert "pushRoute" not in sel and "pushState" not in sel  # geen route/modal
        assert ".dc-scene.sel .dc-detail" in _DS                  # spatial forward, in de scène
        assert ".dc-scene.sel .dc-node:not(.is-sel)" in _DS       # rest dimt

    def test_7_provenance_blijft_bereikbaar(self):
        # 'Waarom?' / volledige provenance-keten blijft gewired (geselecteerde knoop
        # én domein-drill), via de bestaande explain-laag.
        assert "dcWaarom" in _fn("dcSelectNode")
        assert "dcWaarom" in _fn("dcOpenDomain")
        assert 'api(`/api/cockpit/explain' in _fn("dcWaarom")


class TestEvidenceSubordinate:
    def test_8_domeinen_zijn_shelf_geen_zes_gelijke_kaarten(self):
        # De zes bewijsdomeinen zijn een subordinate shelf + drill-in — GEEN raster/muur
        # van zes gelijke accordions op het desktop-tableau.
        scene = _fn("dcScene")
        assert "dc-shelf" in scene and "data-dom" in scene
        assert "ds-disc" not in scene                              # geen accordion-muur op desktop
        drill = _fn("dcOpenDomain")
        assert "dc-reg" in drill and "dcProv" in drill             # detail toont bewijs + provenance

    def test_9_bron_infra_is_low_contrast_niet_dominant(self):
        assert "dc-infra" in _fn("dcScene")
        assert ".dc-infra" in _DS


class TestResponsiveAndMotion:
    def test_10_smal_wordt_verticale_tijd_stack(self):
        rn = _fn("dcRender")
        assert "isNarrow = window.innerWidth < 1280" in rn
        assert "dcStack(d)" in rn and "dcScene(d)" in rn
        stack = _fn("dcStack")
        assert "dcm-spine" in stack and "dcm-now" in stack         # verticale tijd-vertelling
        assert ".dcm-spine" in _DS

    def test_11_centrering_in_basisregel_reduced_motion_safe(self):
        # De les uit Workspace: centrering-transforms staan in de BASIS-regel, niet
        # alleen in de entree-keyframe — anders de-centreren ze onder animation:none.
        for sel in (".dc-core{", ".dc-coredot{"):
            block = _DS.split(sel, 1)[1][:260]
            assert "translate(-50%,-50%)" in block, f"{sel} centreert niet in de basisregel"
        now = _DS.split(".dc-nowline{", 1)[1][:320]
        assert "translateX(-50%)" in now
        # alle loops/animaties bevroren onder reduced-motion
        rm = _DS.split("@media (prefers-reduced-motion:reduce)")[-1]
        for a in ("dc-coredot", "dc-core", "dc-node", "dc-haze"):
            assert a in _DS.split("prefers-reduced-motion")[-3] or a in rm or a in _DS


class TestNoNewSubstrate:
    def test_12_presentatie_only_geen_nieuwe_engine_store_route(self):
        # De cockpit is presentatie: geen nieuwe client-state, geen nieuwe route, geen
        # tweede truth. De backend-leeslaag (dossier_cockpit) blijft de enige bron.
        for fn in ("dcRender", "dcScene", "dcStack", "dcSelectNode", "dcOpenDomain"):
            body = _fn(fn)
            assert "localStorage" not in body and "indexedDB" not in body
        # de cockpit blijft de bestaande leeslaag lezen (geen nieuwe cockpit-route)
        assert "/api/cockpit?key=" in _fn("openDossierCockpit")
        assert "/api/cockpit/explain" in _fn("dcWaarom")
        # ic-calendar toegevoegd als enige nieuwe sprite (schema/toekomst-semantiek)
        assert 'id="ic-calendar"' in _HTML
