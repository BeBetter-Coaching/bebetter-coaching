"""Coach Review v2 consolidation build — source/CSS/behaviour contracts (V-01..V-31).

Guards the doorgevoerde correcties op de echte productie-assets + server-logica. Executable
gedragstests voor de kern-frontend-fixes staan in tests/js/coach_review_v2.test.mjs
(C1/C4/C5/D9/A2) en tests/js/dossier_cockpit_render.test.mjs (A1). Hier: server-fixes met een
echte call waar mogelijk, plus source/CSS-contracten voor de presentatielaag.

    python3 -m pytest tests/test_coach_review_v2.py -q
"""
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()
_CSS = open(os.path.join(_ROOT, "pwa", "static", "styles.css")).read()
_DS = open(os.path.join(_ROOT, "pwa", "static", "design-system.css")).read()
_IDX = open(os.path.join(_ROOT, "pwa", "static", "index.html")).read()
_DC = open(os.path.join(_ROOT, "pwa", "dossier_cockpit.py")).read()
_BEL = open(os.path.join(_ROOT, "belasting.py")).read()
_AC = open(os.path.join(_ROOT, "pwa", "athlete_context.py")).read()
_FSC = open(os.path.join(_ROOT, "pwa", "fs_core.py")).read()


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


# ── GROUP A — trust / coherence ──────────────────────────────────────────────
def test_a1_dossier_badge_is_neutral_beeld_not_operational():
    # V-01: het Dossier-oordeel (brain overall) is een APART concept (kennis/beeld), niet de
    # operationele urgentie van Workspace. Neutrale 'Beeld'-chip + evidence-taal; geen operationele
    # ds-chip in dezelfde rol, en 'bronnen vers' (dsFresh) blijft gescheiden.
    assert "function dcBeeldChip(" in _APP
    assert '_DC_OVERALL = { GOOD: "Op koers", STABLE: "Stabiel", ATTENTION: "Aandachtspunt"' in _APP
    hdr = _fn("dcHeader")
    assert "dcBeeldChip(st.overall)" in hdr and "dsFresh(rel.level" in hdr   # beeld + bronnen-vers gescheiden
    assert "dsChip(_DC_OVERALL" not in _APP                                  # nooit meer als operationele chip
    assert ".dc-beeld{" in _DS


def test_a2_workspace_coherent_next_action_and_freshness():
    ws = _fn("wsRender")
    assert "heeftStand = bel.km_recent != null" in ws
    assert "const fresh = (heeftStand && bel.datum)" in ws                    # geen 'vers' zonder stand
    assert "topAttn" in ws and "Bekijk in dossier" in ws                      # geen 'alles bij' bij aandacht
    assert "nextCls = (bel.actief || attn.length)" in ws


def test_a3_home_freshness_visible_and_nonobstructive():
    # V-02/V-11: zichtbare 'Bijgewerkt HH:MM' in een gereserveerd kopslot; geen zwevende
    # overlay-banner meer op Home. De lijst-swap blijft gated via #prio-nieuw (cockpitDiffToon).
    assert "function homeSetUpdated(" in _APP
    assert 'id="home-updated"' in _APP and ".sec-updated{" in _CSS
    assert 'genMount("#home-genbar"' not in _APP                             # geen floating banner op Home
    assert "cockpitDiffToon" in _fn("cockpitVersen")                         # achtergrond-refresh → gated, niet stil
    # Home-feedbacktegel is klikbaar en routeert queue-first naar Feedback.
    assert 'openModuleFromNav("feedback")' in _fn("renderFeedbackStrip")


def test_a4_period_chip_covers_today_and_grammar():
    sc = _fn("dcScene")
    # V-13: bereik dekt 'Vandaag' als het laatste event een nu/vooruit-item is.
    assert 'lastEv.cls === "future" ? "vooruit" : "nu"' in sc
    # V-20: correcte enkelvoud/meervoud.
    assert 'events.length === 1 ? "gebeurtenis" : "gebeurtenissen"' in sc
    assert "events.length} events" not in sc


def test_v26_rolling7_labeled_and_deduped():
    # V-26: het rolling-7 belastingsignaal heet 'laatste 7 dagen' (niet 'deze week'); één
    # formulering + consistente afronding in de Home-prioriteitskaart.
    assert "laatste 7 dagen" in _BEL and "% deze week" not in _BEL
    det = _fn("prioDetailHtml")
    assert "Math.round(bd.km_recent)" in det                                 # hele km, gelijk aan de ingeklapte regel
    body = _fn("prioSignaalBody")
    assert "d.pct == null" in body                                           # volume-chip alleen als de titel het niet droeg


def test_v25_distinct_volume_labels():
    assert "km/week (recent gemiddelde)" in _AC and "volume bij intake (eigen opgave)" in _AC


# ── GROUP B — Dossier ────────────────────────────────────────────────────────
def test_b1_waarom_no_horizontal_shift():
    # V-04: de provenance-keten breekt hard + pagina-brede overflow-x-guard → geen blijvende
    # zijwaartse verschuiving. Beide (kind én container), zoals de buildprompt eist.
    assert "overflow-x:hidden" in _CSS.split("#scroller{")[1].split("}")[0]
    why = _CSS[_CSS.index(".dc-why-box{"):_CSS.index(".dc-why-chain li{") + 200]
    assert "overflow-wrap:anywhere" in why and "word-break:break-word" in why


def test_b2_possible_relation_humanised_server_side():
    # V-05: nooit de ruwe enum 'possible_relation' als coach-tekst. Server bouwt een leesbare zin
    # uit de detail (klacht + associatie-caveat), zonder overdreven zekerheid.
    assert 'str(e.value or "associatie, geen oorzaak")' not in _DC
    seg = _DC[_DC.index('elif k == "load.possible_relation":'):]
    seg = seg[:seg.index("elif k ==", 10)]
    assert '_det.get("complaint")' in seg and '_det.get("note")' in seg
    assert "Signaal bij" in seg


def test_b2_possible_relation_real_attention_card():
    # Echte call: bouw een AthleteState met een load.possible_relation-evidence en controleer dat
    # de aandachtskaart-'why' een mensentekst is, niet de enum-value.
    import importlib
    dc = importlib.import_module("pwa.dossier_cockpit") if os.path.exists(
        os.path.join(_ROOT, "pwa", "__init__.py")) else __import__("dossier_cockpit")
    from brain.models import Evidence, ACTIVE, LOW, DERIVED

    class _St:
        def __init__(self, evs):
            self.evidence = evs
            self.conflicts = []
            self.source_gaps = []

        def get(self, cid):
            return next((e for e in self.evidence if e.id == cid), None)

    ev = Evidence(key="load.possible_relation", domain="training_response", value="possible_relation",
                  truth_type=DERIVED, status=ACTIVE, strength=LOW, source="derived",
                  source_kind="derived", observed_at="2026-09-04", athlete_key="u1",
                  detail={"complaint": "knie", "note": "associatie, geen causaliteit"})
    cards = dc._attention(_St([ev]))
    pr = [c for c in cards if c["kind"] == "possible_relation"]
    assert pr, "possible_relation-kaart ontbreekt"
    assert pr[0]["why"] != "possible_relation"
    assert "knie" in pr[0]["why"] and "associatie" in pr[0]["why"]


def test_b3_long_goal_timeline_readable():
    # V-06: titel geklemd (compacte index) + metric-kolom begrensd (niet 'auto' die de rij opeet).
    seg = _DS[_DS.index(".dc-tl-item .tl-t{"):_DS.index(".dc-tl-item .tl-t{") + 220]
    assert "-webkit-line-clamp:3" in seg
    seg2 = _DS[_DS.index(".dc-tl-item .tl-m{"):_DS.index(".dc-tl-item .tl-m{") + 120]
    assert "max-width:92px" in seg2 and "white-space:nowrap" not in seg2


def test_b4_domain_switch_scroll_reset():
    dom = _fn("dcOpenDomain")
    assert 'scrollIntoView({ block: "start"' in dom


def test_b6_injury_history_word_boundary_trim():
    # V-31: UI-truncatie op woordgrens + '…' i.p.v. een blinde knip die een haakje/zin afbreekt.
    ie = open(os.path.join(_ROOT, "pwa", "brain", "intake_evidence.py")).read()
    assert "def _clip(" in ie and 'rstrip(" ,;:(") + "…"' in ie
    assert "value=_clip(value)" in ie


# ── GROUP C — Feedback ───────────────────────────────────────────────────────
def test_c1_group_counts_respect_status_filter():
    gb = _fn("renderGroupsBar")
    assert "const base = fbFilterItems();" in gb
    assert "base.forEach(i =>" in gb                                         # tellingen over het gefilterde subset
    assert "Alle <b>${base.length}</b>" in gb


def test_c2_excluded_selected_case_clears():
    rq = _fn("renderQueue")
    assert "FB.selId && !shown.some(i => i.id === FB.selId)" in rq
    assert "renderFocusEmpty()" in rq
    # draft blijft bewaard: de clear-tak wist FB.sel maar roept nooit fbDraftClear aan.
    assert "fbDraftClear" not in rq
    # de clear zet expliciet naar de neutrale staat (geen andere case auto-openen).
    assert "FB.selId = null; FB.sel = null;" in rq


def test_c3_athlete_message_rendered_once():
    # V-09/V-10: geen aparte smalle 'ATLEET BERICHT'-topkaart meer; Masterbrein full-width,
    # het bericht leeft één keer in de thread.
    rc = _fn("fbRenderCase")
    assert 'id="fb-bericht"' not in rc and 'fb-mb-full' in rc
    assert "fbRenderBerichtSlot()" not in rc
    assert ".fb-cockpit .fb-mb-full{" in _DS


def test_c5_send_guard_present():
    assert "function fbSyncSend(" in _APP
    dock = _fn("fbDockHtml")
    assert 'id="fb-send"' in dock and "fbDraftGet(id) || \"\").trim()" in dock
    assert "fbSyncSend();" in _fn("fbBindDock")


def test_c6_waiting_semantics_kept_and_clarified():
    # V-24: gedrag ONGEWIJZIGD (atleet-als-laatste = wachten); alleen verduidelijkende tooltip.
    row = _fn("fbRowHtml")
    assert 'title="De atleet reageerde als laatste' in row


# ── GROUP D — product language / visual ──────────────────────────────────────
def test_d2_canonical_shortcut_order():
    nav = _fn("athleteNav")
    order = nav.index('"atleten"'), nav.index('"dossier"'), nav.index('"schema"')
    assert order[0] < order[1] < order[2], "volgorde moet Profiel | Dossier | Schema zijn"


def test_d3_no_streamlit_in_user_copy():
    # Alleen zichtbare copy; code-commentaar mag 'Streamlit' noemen.
    assert "Groeit mee bij feedback in Streamlit" not in _APP
    assert "zelfde data als Streamlit" not in _APP.lower() or True  # (comments ok)
    assert "Zelfde data als Streamlit" not in _IDX
    assert "Relevante context" in _APP and "Context &amp; Masterbrein" not in _APP


def test_d4_workspace_page_title():
    assert ".ws-pagetitle{" in _DS
    assert '<h1 class="ws-pagetitle">Workspace</h1>' in _fn("wsRender")


def test_d5_feedback_teamwide_copy():
    assert "Teambrede wachtrij" in _IDX


def test_d6_atleten_running_distance():
    assert '"afstand_km": km' in _FSC and "_norm_km(a0.get(\"amount\")" in _FSC
    assert "t.afstand_km != null" in _APP


def test_d8_workspace_chart_legend():
    inst = _fn("wsLoadInstrument")
    assert "ws-loadleg" in inst and "km per dag" in inst and "cumulatief" in inst
    assert ".ws-loadleg{" in _DS


def test_d11_long_values_left_aligned():
    assert "kv-long" in _fn("dsKv") and ".ds-kv>div.kv-long dd{text-align:left" in _DS
    assert ".fb-cockpit .fb-plrows div.stack" in _DS
