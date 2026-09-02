"""Dossier — LIVING MEMORY COCKPIT v1 (presentatie-contract, North-Star 3-zone).

Vergrendelt de 3-zone geheugencockpit zonder de gelockte Dossier-waarheid te raken:
LINKS = TIJDLIJN (wat gebeurde), MIDDEN = GESELECTEERDE HERINNERING (waarom het
ertoe doet — de hero, default-staat), RECHTS = GERELATEERDE DRADEN (welke context
hangt eraan — connectoren). Alléén echte view-model-velden; history-capture OFF →
eerlijke lege-staat (geen verzonnen historie/metrics/causaliteit/coachnotities).
Render = presentatie: geen tweede engine/store/route/truth.

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


class TestThreeZone:
    def test_1_twee_zones_tijdlijn_hero(self):
        # UX/IA v1 (Target D): 2-zone — tijdlijn (links) · geselecteerde herinnering (midden).
        # Het gededupliceerde 'Gerelateerde draden'-paneel (zelfde events als de tijdlijn) is weg;
        # navigeren gebeurt via de klikbare tijdlijn.
        scene = _fn("dcScene")
        assert "dc-grid-2" in scene
        for zone in ("dc-tl", "dc-center", "dc-mem"):
            assert zone in scene, f"zone {zone} ontbreekt"
        assert "Tijdlijn" in scene
        assert "Gerelateerde draden" not in scene and "dc-rt-pane" not in scene
        for sel in (".dc-grid.dc-grid-2", ".dc-tl-item", ".dc-mem"):
            assert sel in _DS, f"2-zone-primitive {sel} niet gestyled"

    def test_2_events_uit_echte_velden_klacht_gededupliceerd(self):
        # Tijdlijn-events uit echte velden: verleden = changes[] (klachten gedateerd via
        # attention, NIET dubbel), nu = attention/load, toekomst = planning.
        b = _fn("dcBuildEvents")
        assert "chg" in b and "attn" in b and "plan" in b and "lo" in b
        assert 'filter(c => !/klacht/i.test(c.title))' in b     # geen dubbele klacht-change
        assert 'c.kind !== "complaint"' in b                    # klacht niet óók als nu-signaal
        assert "dcFutureNodes(plan)" in b                       # toekomst = planning

    def test_3_geen_workspace_hero_center_is_beslissingspaneel(self):
        # Dossier RECREËERT Workspace niet: geen Athlete Core / load-gauge / spine-kern.
        for fn in ("dcRender", "dcScene", "dcMemPanel", "dcBuildEvents"):
            body = _fn(fn)
            assert "wsCore(" not in body and "wsAnchor(" not in body, f"{fn} recreëert de Workspace-hero"
        assert "core-metric" not in _APP and "dc-coredot" not in _DS and "dc-rail" not in _DS
        # de midden-hero is een beslissings-geheugenpaneel met echte secties
        mem = _fn("dcMemPanel")
        for sec in ("Wat veranderde", "Waarom relevant", "Bronnen"):
            assert sec in mem, f"hero mist sectie {sec}"

    def test_4_selected_event_is_default_hero(self):
        # De geselecteerde herinnering is de DEFAULT staat (geen leeg scherm tot klik).
        b = _fn("dcBuildEvents")
        assert "e.sel = e.id === selId" in b                    # er is altijd een geselecteerde
        assert "now[0] || all[0]" in b                          # default = dominant nu-event
        scene = _fn("dcScene")
        assert "events.find(e => e.sel) || events[0]" in scene  # hero rendert de selectie
        assert "dcMemPanel(sel)" in scene

    def test_5_eerlijke_lege_staat_geen_fake_historie(self):
        rn, scene, stack = _fn("dcRender"), _fn("dcScene"), _fn("dcStack")
        assert "emptyHistory = !past.length" in rn
        assert "vanaf nu" in scene and "nog niets is vastgelegd" in scene
        assert "vanaf nu" in stack
        assert "dc-empty-note" in scene
        # oudere tijdlijn-knopen alleen uit een niet-lege echte timeline
        assert "!tl.empty_reason && tlv.length" in rn

    def test_6_herselecteren_is_in_scene_geen_route_of_modal(self):
        sel = _fn("dcSelectEvent")
        assert "dcMemPanel(ev)" in sel                          # midden ververst (in-scene)
        assert "dcRelCard" not in sel                           # 2-zone: geen rechter-draden meer
        assert "pushRoute" not in sel and "pushState" not in sel and "location.hash" not in sel
        assert ".dc-tl-item.sel" in _DS                         # tijdlijn-highlight

    def test_7_relationele_context_via_connectoren(self):
        # De draden hangen zichtbaar aan de geselecteerde herinnering via connectoren
        # (na layout gemeten; alléén de echte events, geen decoratie).
        dc = _fn("dcDrawConnectors")
        assert "getBoundingClientRect" in dc and ".dc-rt-card" in dc and ".dc-mem" in dc
        assert "dcHex(tone)" in dc                              # semantische kleur per event
        assert "dcDrawConnectors(wrap)" in _fn("dcRender")      # getekend na render

    def test_8_provenance_blijft_bereikbaar(self):
        assert "dc-why" in _fn("dcMemPanel")
        assert "dc-why" in _fn("dcOpenDomain")
        assert "/api/cockpit/explain" in _fn("dcWaarom")

    def test_9_domeinen_subordinate_strip_geen_zes_kaarten(self):
        # Bewijsdomeinen = compacte strip + drill naar de midden-hero (geen 6 gelijke
        # dashboard-kaarten/accordions op het desktop-tableau).
        scene = _fn("dcScene")
        assert "dc-domstrip" in scene and "data-dom" in scene
        assert "ds-disc" not in scene                           # geen accordion-muur op desktop
        drill = _fn("dcOpenDomain")
        assert "dc-reg" in drill and "dcProv" in drill and "#dc-center" in drill  # drill vult de hero

    def test_10_control_shell_en_actiebalk_zijn_echt(self):
        scene = _fn("dcScene")
        assert "Periode" in scene and "Bronnen" in scene        # echte, afgeleide control-pillen
        assert "openAthleteModule('schema'" in scene and "openWorkspace(" in scene  # echte routes
        # geen verzonnen write/period-controls
        assert "Notitie toevoegen" not in scene and "Notitie bewerken" not in scene

    def test_11_smal_wordt_verticale_tijd_stack(self):
        rn = _fn("dcRender")
        assert "isNarrow = window.innerWidth < 1280" in rn
        assert "dcStack(d)" in rn and "dcScene(d)" in rn
        stack = _fn("dcStack")
        assert "dcm-spine" in stack and "dcm-now" in stack
        assert ".dcm-spine" in _DS

    def test_12_motion_is_reduced_motion_safe(self):
        # Alle zone-animaties bevroren onder reduced-motion; connectoren animeren geen
        # transform (alleen stroke-dashoffset transition).
        rm = _DS.split("@media (prefers-reduced-motion:reduce)")[-1]
        for a in ("dc-grid", "dc-actionbar", "dc-domstrip"):
            assert a in _DS.split("prefers-reduced-motion")[-2] or a in rm
        assert "transition:stroke-dashoffset" in _DS

    def test_13_presentatie_only_geen_nieuwe_engine_store_route(self):
        for fn in ("dcRender", "dcScene", "dcBuildEvents", "dcSelectEvent", "dcOpenDomain"):
            body = _fn(fn)
            assert "localStorage" not in body and "indexedDB" not in body
        assert "/api/cockpit?key=" in _fn("openDossierCockpit")
        assert "/api/cockpit/explain" in _fn("dcWaarom")
        assert 'id="ic-calendar"' in _HTML
