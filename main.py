"""BeBetter Coaching — Coach App."""

import streamlit as st
from datetime import date, timedelta
import fs_client
from fs_client import TokenNotFoundError
import ai_feedback
import schema_builder
import base64
import io
import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Intake persistentie — bewaar/herstel intake + plan over herstarts heen
# ---------------------------------------------------------------------------

_PERSIST_FILE = os.path.join(os.path.dirname(__file__), ".builder_state.json")

# ---------------------------------------------------------------------------
# Wachtwoordbeveiliging
# ---------------------------------------------------------------------------

def _check_password() -> bool:
    """Vraag om wachtwoord met 'Onthoud mij' via cookie."""
    try:
        correct = st.secrets.get("APP_PASSWORD", "") or os.environ.get("APP_PASSWORD", "")
    except Exception:
        correct = os.environ.get("APP_PASSWORD", "")

    if not correct:
        return True  # Geen wachtwoord ingesteld → lokaal gebruik

    # Cookie-gebaseerde "onthoud mij"
    try:
        import extra_streamlit_components as stx
        cookie_manager = stx.CookieManager(key="bb_cookie_mgr")
        auth_cookie = cookie_manager.get("bb_auth")
        if auth_cookie == "ok":
            return True
    except Exception:
        cookie_manager = None
        auth_cookie = None

    if st.session_state.get("authenticated"):
        return True

    # Loginscherm
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("assets/logo_zwart.png", width=180)
        st.markdown("## BeBetter Coaching")
        pw = st.text_input("Wachtwoord", type="password", key="login_pw")
        onthoud = st.checkbox("Onthoud mij op dit apparaat", value=True, key="login_remember")
        if st.button("Inloggen →", type="primary", use_container_width=True):
            if pw == correct:
                st.session_state["authenticated"] = True
                if onthoud and cookie_manager:
                    try:
                        from datetime import datetime, timedelta
                        expires = datetime.now() + timedelta(days=365)
                        cookie_manager.set("bb_auth", "ok", expires_at=expires)
                    except Exception:
                        pass
                st.rerun()
            else:
                st.error("Onjuist wachtwoord.")
    return False

def _save_builder_state():
    """Schrijf builder_intake, builder_plan, builder_step naar schijf."""
    state = {
        "builder_step":   st.session_state.get("builder_step", 1),
        "builder_intake": st.session_state.get("builder_intake"),
        "builder_plan":   st.session_state.get("builder_plan"),
    }
    # uploaded_images bevatten base64-data — te groot, weglaten
    if state["builder_intake"]:
        intake_copy = dict(state["builder_intake"])
        intake_copy.pop("uploaded_images", None)
        state["builder_intake"] = intake_copy
    try:
        with open(_PERSIST_FILE, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _load_builder_state():
    """Herstel builder-state vanuit schijf als session state leeg is."""
    # Intake al in memory → niets doen, laat stap-navigatie intact
    if "builder_intake" in st.session_state:
        return
    if not os.path.exists(_PERSIST_FILE):
        return
    try:
        with open(_PERSIST_FILE) as f:
            state = json.load(f)
        if state.get("builder_intake"):
            st.session_state["builder_intake"] = state["builder_intake"]
            st.session_state["builder_fields_loaded"] = False  # velden nog laden
        if state.get("builder_plan") is not None:
            st.session_state["builder_plan"] = state["builder_plan"]
        # Als intake aanwezig is maar stap=1, ga direct naar stap 2
        saved_step = state.get("builder_step", 1)
        if state.get("builder_intake") and saved_step == 1:
            saved_step = 2
        st.session_state["builder_step"] = saved_step
    except Exception:
        pass

def _clear_builder_state():
    """Verwijder de persistente state (na handmatig reset)."""
    try:
        os.remove(_PERSIST_FILE)
    except Exception:
        pass

_SKIPPED_FILE = os.path.join(os.path.dirname(__file__), ".feedback_skipped.json")

def _load_skipped() -> dict:
    """Laad overgeslagen workout_keys met timestamp."""
    try:
        if os.path.exists(_SKIPPED_FILE):
            with open(_SKIPPED_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_skipped(skipped: dict):
    """Sla overgeslagen workouts op."""
    try:
        with open(_SKIPPED_FILE, "w") as f:
            json.dump(skipped, f, ensure_ascii=False)
    except Exception:
        pass

st.set_page_config(
    page_title="BeBetter Coaching",
    page_icon="assets/logo_zwart.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Huisstijl CSS
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* ── BeBetter Coaching brand kleuren ──────────────────────────
   Primair blauw : #2876FB
   Cyan accent   : #5EE6EB
   Navy tekst    : #0F2A4B
   Donkerblauw   : #3167C3
   Achtergrond   : #F7F9FC
   Sectie bg     : #F1F6FF
   Rand           : #E6EBF2
   Subtekst      : #4D4D4D
──────────────────────────────────────────────────────────── */

.block-container { padding-top: 1rem !important; }

/* ── Landingspagina cards ── */
.bb-card {
    background: #FFFFFF;
    border: 1.5px solid #E6EBF2;
    border-radius: 14px;
    padding: 1.8rem 1.6rem 1.6rem 1.6rem;
    height: 220px;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    box-shadow: 0 2px 12px rgba(40,118,251,0.06);
    transition: box-shadow 0.2s, border-color 0.2s;
    overflow: hidden;
}
.bb-card:hover {
    box-shadow: 0 6px 24px rgba(40,118,251,0.13);
    border-color: #2876FB;
}
.bb-card-icon { font-size: 1.8rem; line-height: 1; }
.bb-card-title {
    font-size: 1rem;
    font-weight: 800;
    color: #0F2A4B;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin: 0;
}
.bb-card-desc {
    font-size: 0.85rem;
    color: #4D4D4D;
    line-height: 1.55;
    flex-grow: 1;
    margin: 0;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 5;
    -webkit-box-orient: vertical;
}
.bb-card-soon {
    display: inline-block;
    background: #F1F6FF;
    color: #2876FB;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 0.2rem 0.7rem;
    border-radius: 20px;
    border: 1px solid #E6EBF2;
}

/* ── Dividers ── */
.bb-divider {
    border: none;
    border-top: 1.5px solid #E6EBF2;
    margin: 1.5rem 0;
}

/* ── Tagline / subtekst ── */
.bb-tagline {
    color: #4D4D4D;
    font-size: 0.8rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin: 0;
}

/* ── Primaire knoppen ── */
div[data-testid="stButton"] button[kind="primary"] {
    background: linear-gradient(135deg, #2876FB, #3167C3) !important;
    color: #FFFFFF !important;
    border: none !important;
    font-weight: 700 !important;
    letter-spacing: 0.04em !important;
    border-radius: 8px !important;
    box-shadow: 0 2px 8px rgba(40,118,251,0.25) !important;
}
div[data-testid="stButton"] button[kind="primary"]:hover {
    background: linear-gradient(135deg, #3167C3, #2876FB) !important;
    box-shadow: 0 4px 16px rgba(40,118,251,0.35) !important;
}

/* ── Module header balk ── */
.module-header {
    display: flex;
    align-items: center;
    gap: 1rem;
    padding-bottom: 0.75rem;
    border-bottom: 2px solid #E6EBF2;
    margin-bottom: 1.5rem;
}
.module-header-title {
    font-size: 1.4rem;
    font-weight: 800;
    color: #0F2A4B;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #F1F6FF !important;
    border-right: 1.5px solid #E6EBF2 !important;
}

/* ── Gradient accent lijn bovenaan header ── */
.bb-hero-accent {
    height: 4px;
    background: linear-gradient(90deg, #2876FB, #5EE6EB);
    border-radius: 2px;
    margin-bottom: 2rem;
}

/* ── Schema bouwen — stap-indicator ── */
.bb-step-row {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1.5rem;
}
.bb-step-pill {
    flex: 1;
    text-align: center;
    padding: 0.45rem 0.5rem;
    border-radius: 8px;
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    background: #E6EBF2;
    color: #4D4D4D;
    border: 1.5px solid #E6EBF2;
}
.bb-step-pill.active {
    background: #2876FB;
    color: #FFFFFF;
    border-color: #2876FB;
    font-weight: 800;
}
.bb-step-pill.done {
    background: #F1F6FF;
    color: #2876FB;
    border-color: #2876FB;
}

/* ── Intake sectiekaart ── */
.bb-intake-section {
    background: #F7F9FC;
    border: 1.5px solid #E6EBF2;
    border-radius: 12px;
    padding: 1.2rem 1.4rem 1rem 1.4rem;
    margin-bottom: 1rem;
}
.bb-intake-label {
    font-size: 0.78rem;
    font-weight: 700;
    color: #2876FB;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 0.6rem;
}

/* ── Week-groep in CSV preview ── */
.bb-week-header {
    font-size: 0.78rem;
    font-weight: 700;
    color: #4D4D4D;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    background: #F1F6FF;
    border-radius: 6px;
    padding: 0.25rem 0.7rem;
    margin: 0.6rem 0 0.2rem 0;
    border-left: 3px solid #2876FB;
}
.bb-training-row {
    display: flex;
    align-items: center;
    padding: 0.3rem 0;
    border-bottom: 1px solid #F1F6FF;
    gap: 0.5rem;
    font-size: 0.88rem;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Hulpfunctie: logo als base64 voor HTML embedding
# ---------------------------------------------------------------------------

def _logo_b64(path: str) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def is_authenticated() -> bool:
    try:
        fs_client.get_token()
        return True
    except TokenNotFoundError:
        return False


def setup_screen():
    col_logo, col_spacer = st.columns([1, 3])
    with col_logo:
        st.image("assets/logo_zwart.png", width=220)

    st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)
    st.subheader("Verbinding instellen")
    st.markdown("""
    De app heeft je FinalSurge auth-token nodig.

    **Stap 1:** Ga naar [beta.finalsurge.com](https://beta.finalsurge.com) in Chrome

    **Stap 2:** Druk op **F12** → tabblad **"Console"** → typ dit en druk Enter:
    """)
    st.code("copy(localStorage.getItem('auth-token'))", language="javascript")
    st.markdown("**Stap 3:** Plak de token hieronder:")

    token_input = st.text_input("Auth token:", type="password", placeholder="Plak hier je token...")

    if st.button("Opslaan", type="primary", disabled=not token_input):
        if token_input and len(token_input) > 20:
            fs_client.save_token(token_input)
            st.success("Token opgeslagen!")
            st.rerun()
        else:
            st.error("Ongeldige token.")

    if fs_client.is_mac():
        st.caption("Of probeer automatisch ophalen (alleen macOS):")
        if st.button("🔍 Automatisch ophalen uit Chrome"):
            with st.spinner("Ophalen..."):
                token = fs_client.try_get_token_via_applescript()
                if token:
                    fs_client.save_token(token)
                    st.success("Token gevonden!")
                    st.rerun()
                else:
                    st.warning("Mislukt. Gebruik de handmatige methode.")
    else:
        st.caption("**Windows:** open FinalSurge in Chrome → F12 → Application → Local Storage → https://beta.finalsurge.com → kopieer de waarde van **auth-token**")


if not _check_password():
    st.stop()

if not is_authenticated():
    setup_screen()
    st.stop()

# Herstel builder-state na herstart (vóór atleten laden)
_load_builder_state()

# ---------------------------------------------------------------------------
# Atleten laden (altijd nodig, gecached)
# ---------------------------------------------------------------------------

if "athletes_by_group" not in st.session_state:
    try:
        st.session_state["athletes_by_group"] = fs_client.get_athletes_by_group()
    except TokenNotFoundError:
        fs_client.reset_session()
        st.rerun()

athletes_by_group = st.session_state.get("athletes_by_group", {})

# Lookup: user_key → coach_athlete_key (voor CoachAthleteResetCounter)
_all_athletes = [a for members in athletes_by_group.values() for a in members]
COACH_ATHLETE_KEY = {a["user_key"]: a.get("coach_athlete_key", a["user_key"])
                     for a in _all_athletes}


# ---------------------------------------------------------------------------
# Pagina-router
# ---------------------------------------------------------------------------

if "page" not in st.session_state:
    st.session_state["page"] = "home"

page = st.session_state["page"]


def go_to(p: str):
    st.session_state["page"] = p
    st.rerun()


# ---------------------------------------------------------------------------
# MODULE HEADER — terug-knop + logo rechtsboven (alleen buiten home)
# ---------------------------------------------------------------------------

def module_header(title: str, icon: str):
    # Gradient accent lijn bovenaan
    st.markdown('<div class="bb-hero-accent"></div>', unsafe_allow_html=True)
    col_back, col_title, col_logo = st.columns([1, 5, 2])
    with col_back:
        if st.button("← Terug", key="back_btn"):
            go_to("home")
    with col_title:
        st.markdown(f"""
        <div class="module-header">
            <span style="font-size:1.6rem">{icon}</span>
            <p class="module-header-title">{title}</p>
        </div>
        """, unsafe_allow_html=True)
    with col_logo:
        st.image("assets/logo_zwart.png", width=140)
    st.markdown("")


# ===========================================================================
# PAGINA: HOME — Landingspagina
# ===========================================================================

if page == "home":
    # Gradient accent lijn + logo
    logo_b64 = _logo_b64("assets/logo_zwart.png")
    st.markdown(f"""
    <div class="bb-hero-accent"></div>
    <div style="text-align:center; padding: 1rem 0 0.5rem 0;">
        <img src="data:image/png;base64,{logo_b64}"
             style="width: 280px; max-width: 75%; margin-bottom: 0.6rem;" />
        <p class="bb-tagline">Coach dashboard</p>
    </div>
    <hr class="bb-divider">
    """, unsafe_allow_html=True)

    # Welkomsttekst
    st.markdown("""
    <div style="text-align:center; max-width: 620px; margin: 0 auto 2.5rem auto;">
        <p style="color:#4D4D4D; font-size:1.05rem; line-height:1.75;">
            Welkom, Jip. Kies hieronder een module om te starten.
            De app verbindt direct met FinalSurge en gebruikt AI om jou als coach
            sneller en slimmer te laten werken.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Vier kaarten
    col1, col2, col3, col4 = st.columns(4, gap="medium")

    with col1:
        st.markdown("""
        <div class="bb-card">
            <div class="bb-card-icon">📋</div>
            <p class="bb-card-title">Feedback</p>
            <p class="bb-card-desc">Atleten reageren op hun training — jij nog niet. De AI schrijft een concept in jouw stijl. Jij keurt goed en post met één klik.</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Open →", type="primary", key="btn_feedback", use_container_width=True):
            go_to("feedback_groups")

    with col2:
        st.markdown("""
        <div class="bb-card">
            <div class="bb-card-icon">📅</div>
            <p class="bb-card-title">Schema-verloop</p>
            <p class="bb-card-desc">Bekijk in één oogopslag wanneer schema's van je atleten aflopen. Zo weet je precies wie komende week een nieuw plan nodig heeft.</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Open →", type="primary", key="btn_schema", use_container_width=True):
            go_to("schema")

    with col3:
        st.markdown("""
        <div class="bb-card">
            <div class="bb-card-icon">🔨</div>
            <p class="bb-card-title">Schema bouwen</p>
            <p class="bb-card-desc">Genereer een trainingsplan op basis van doel, niveau en datum. Importeer het direct in FinalSurge inclusief workout builder.</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Open →", type="primary", key="btn_builder", use_container_width=True):
            go_to("builder")

    with col4:
        st.markdown("""
        <div class="bb-card">
            <div class="bb-card-icon">🏁</div>
            <p class="bb-card-title">Races</p>
            <p class="bb-card-desc">Aankomende races van je atleten in één overzicht. De AI schrijft een persoonlijke succeswens — jij post met één klik.</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Open →", type="primary", key="btn_races", use_container_width=True):
            go_to("races")

    # Tweede rij kaarten
    st.markdown("<br>", unsafe_allow_html=True)
    col5, col6, col7, col8 = st.columns(4, gap="large")
    with col5:
        st.markdown("""
        <div class="bb-card">
            <div class="bb-card-icon">🔧</div>
            <p class="bb-card-title">Builder bijvullen</p>
            <p class="bb-card-desc">Vul de workout builder automatisch in voor bestaande trainingen die al een beschrijving hebben maar nog geen structuur.</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Open →", type="primary", key="btn_backfill", use_container_width=True):
            go_to("backfill_builder")

    # Debug expander (alleen zichtbaar als je hem openklapt)
    with st.expander("🔧 Debug: coach_athlete_key controle", expanded=False):
        st.caption("Gebruik dit om te controleren of de juiste coach_athlete_key wordt gebruikt voor het resetten van notificaties.")
        if st.button("🔍 Haal ruwe TeamAthleteList op", key="btn_debug_team"):
            with st.spinner("Ophalen..."):
                try:
                    raw = fs_client.get_raw_team_data()
                    top_groups = raw.get("data") or []
                    st.write(f"**Aantal top-level items in data:** {len(top_groups)}")
                    if top_groups:
                        first_top = top_groups[0]
                        st.write(f"**Velden op data[0]:** {list(first_top.keys())}")
                        groups = first_top.get("groups", [])
                        st.write(f"**Aantal groups in data[0]:** {len(groups)}")
                        if groups:
                            athletes_in_first = groups[0].get("athletes", [])
                            st.write(f"**Groep naam:** {groups[0].get('name')}")
                            st.write(f"**Aantal atleten in eerste group:** {len(athletes_in_first)}")
                            if athletes_in_first:
                                first_a = athletes_in_first[0]
                                st.write(f"**Velden op atleet-object:** {list(first_a.keys())}")
                                st.write(f"**user_key:** `{first_a.get('user_key')}`")
                                st.write(f"**key:** `{first_a.get('key')}`")
                                st.write(f"**coach_athlete_key:** `{first_a.get('coach_athlete_key')}`")
                    st.divider()
                    st.write("**Huidige coach_athlete_key mapping:**")
                    for uk, cak in COACH_ATHLETE_KEY.items():
                        same = "⚠️ zelfde als user_key" if uk == cak else "✅ anders"
                        name_label = next((a["name"] for a in _all_athletes if a["user_key"] == uk), uk[:8])
                        st.write(f"- **{name_label}**: user_key=`{uk[:8]}...` → coach_athlete_key=`{cak[:8]}...` {same}")
                except Exception as e:
                    st.error(f"Fout: {e}")

    # Footer
    st.markdown(f"""
    <hr class="bb-divider">
    <div style="text-align:center;">
        <p style="color:#4D4D4D; font-size:0.75rem; letter-spacing:0.1em; text-transform:uppercase;">
            Iedere training telt &nbsp;·&nbsp; Iedere loper telt &nbsp;·&nbsp; {date.today().strftime('%d %B %Y')}
        </p>
        <div style="height:4px; background:linear-gradient(90deg,#2876FB,#5EE6EB);
                    border-radius:2px; max-width:200px; margin:0.8rem auto 0 auto;"></div>
    </div>
    """, unsafe_allow_html=True)


# ===========================================================================
# PAGINA: FEEDBACK — GROEPEN TUSSENMENU
# ===========================================================================

elif page == "feedback_groups":

    module_header("Feedback — Kies groep", "📋")
    st.markdown("### Kies een groep om feedback te bekijken")
    st.markdown("")

    group_names = list(athletes_by_group.keys())
    all_options = ["Alle atleten"] + group_names

    # Verdeel over rijen van 3
    for row_start in range(0, len(all_options), 3):
        row_items = all_options[row_start:row_start + 3]
        cols = st.columns(3, gap="large")
        for col, grp in zip(cols, row_items):
            with col:
                if grp == "Alle atleten":
                    count = sum(len(m) for m in athletes_by_group.values())
                    icon = "👥"
                    desc = f"Alle {count} atleten tegelijk"
                else:
                    count = len(athletes_by_group.get(grp, []))
                    icon = "🏃"
                    desc = f"{count} atleten"

                st.markdown(f"""
                <div class="bb-card">
                    <div class="bb-card-icon">{icon}</div>
                    <p class="bb-card-title">{grp}</p>
                    <p class="bb-card-desc">{desc}</p>
                </div>
                """, unsafe_allow_html=True)
                st.markdown("")
                if st.button(f"Open {grp} →", type="primary",
                             key=f"grp_btn_{grp}", use_container_width=True):
                    if grp == "Alle atleten":
                        st.session_state["feedback_group_filter"] = None
                    else:
                        st.session_state["feedback_group_filter"] = grp
                    # Wis oude workouts zodat ze opnieuw laden
                    st.session_state.pop("workouts", None)
                    st.session_state.pop("last_filter", None)
                    go_to("feedback")
        st.markdown("")


# ===========================================================================
# PAGINA: FEEDBACK
# ===========================================================================

elif page == "feedback":

    module_header("Feedback", "📋")

    # Pas groepsfilter toe vanuit tussenmenu
    _group_filter = st.session_state.pop("feedback_group_filter", None)
    if _group_filter is not None:
        # Selecteer alle atleten van die groep, deselecteer de rest
        for gn, members in athletes_by_group.items():
            for a in members:
                st.session_state[f"chk_{a['user_key']}"] = (gn == _group_filter)

    # Sidebar alleen op feedback pagina
    with st.sidebar:
        st.image("assets/logo_zwart.png", width=160)
        st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)
        st.header("Filters")

        if st.button("← Terug naar groepen", key="btn_back_groups"):
            go_to("feedback_groups")

        days_back = st.slider("Terugkijkperiode (dagen)", 1, 14, 3)

        st.markdown("**Atleten** — laat leeg voor iedereen")
        selected_keys = []

        for group_name, members in athletes_by_group.items():
            group_keys = [a["user_key"] for a in members]
            group_id = group_name.replace(" ", "_").replace(".", "")

            all_checked = all(
                st.session_state.get(f"chk_{k}", False) for k in group_keys
            )

            with st.expander(group_name, expanded=True if all_checked else False):
                btn_label = "✓ Alles deselecteren" if all_checked else "✓ Selecteer hele groep"
                if st.button(btn_label, key=f"btn_{group_id}"):
                    for k in group_keys:
                        st.session_state[f"chk_{k}"] = not all_checked
                    st.rerun()

                st.markdown("---")

                for athlete in sorted(members, key=lambda x: x["name"]):
                    checked = st.checkbox(
                        athlete["name"],
                        key=f"chk_{athlete['user_key']}",
                    )
                    if checked:
                        selected_keys.append(athlete["user_key"])

        athlete_filter = selected_keys if selected_keys else None

        include_planned_no_notes = st.toggle(
            "Geplande trainingen zonder notities",
            value=False,
            help="Voltooide trainingen uit het schema waarop de atleet geen notitie heeft achtergelaten.",
        )
        include_data_only = st.toggle(
            "Ook trainingen zonder notities",
            value=False,
            help="Trainingen die niet gepland waren maar toch zijn gedaan, zonder notities.",
        )

        st.markdown("---")

        if st.button("🔄 Workouts opnieuw laden"):
            if "workouts" in st.session_state:
                del st.session_state["workouts"]
            st.rerun()

        if st.button("🔑 Opnieuw inloggen"):
            fs_client.reset_session()
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        st.markdown("---")
        st.caption(f"Vandaag: {date.today().strftime('%d %B %Y')}")

    # Workouts laden
    filter_state = (days_back, tuple(selected_keys), include_data_only, include_planned_no_notes)
    if st.session_state.get("last_filter") != filter_state:
        if "workouts" in st.session_state:
            del st.session_state["workouts"]
        st.session_state["last_filter"] = filter_state

    if "workouts" not in st.session_state:
        label = "Workouts ophalen"
        if selected_keys:
            all_athletes = [a for members in athletes_by_group.values() for a in members]
            selected_names = [a["name"] for a in all_athletes if a["user_key"] in selected_keys]
            label += f" voor {', '.join(selected_names)}"
        else:
            label += " voor alle atleten"

        with st.spinner(f"{label}..."):
            try:
                workouts = fs_client.get_workouts_needing_feedback(
                    days_back=days_back,
                    athlete_filter=athlete_filter,
                    include_data_only=include_data_only,
                    include_planned_no_notes=include_planned_no_notes,
                )
                st.session_state["workouts"] = workouts
                for w in workouts:
                    wk = w["workout_key"]
                    st.session_state.setdefault(f"feedback_{wk}", None)
                    st.session_state.setdefault(f"posted_{wk}", False)
            except TokenNotFoundError:
                fs_client.reset_session()
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.error("Token verlopen — voer opnieuw je token in.")
                st.rerun()
            except Exception as e:
                st.error(f"Fout bij ophalen workouts: {e}")
                st.stop()

    workouts = st.session_state.get("workouts", [])

    # Filter overgeslagen workouts — tenzij atleet daarna gereageerd heeft
    _skipped = _load_skipped()
    if _skipped:
        filtered = []
        _skipped_updated = False
        for w in workouts:
            wk_key = w.get("workout_key", "")
            if wk_key not in _skipped:
                filtered.append(w)
                continue
            skip_ts = _skipped[wk_key]
            # Check: heeft atleet na het overslaan gereageerd? (nieuwe comment na skip_ts)
            thread = w.get("thread", [])
            new_athlete_msg = any(
                m.get("van") == "atleet" and m.get("timestamp", "") > skip_ts
                for m in thread
            )
            if new_athlete_msg:
                # Atleet heeft gereageerd — verwijder uit skip-lijst en toon weer
                del _skipped[wk_key]
                _skipped_updated = True
                filtered.append(w)
            # else: blijft overgeslagen
        if _skipped_updated:
            _save_skipped(_skipped)
        workouts = filtered

    if not workouts:
        st.success("✅ Geen openstaande workouts gevonden voor de huidige filters.")
        if st.button("Opnieuw laden"):
            del st.session_state["workouts"]
            st.rerun()
    else:
        pending = [i for i, w in enumerate(workouts) if not st.session_state.get(f"posted_{w['workout_key']}")]
        st.markdown(f"**{len(pending)} workout(s)** wachten op jouw reactie.")

        if pending:
            if st.button("⚡ Genereer alle concepten (AI)", type="primary"):
                progress = st.progress(0)
                for idx, i in enumerate(pending):
                    wk = workouts[i]["workout_key"]
                    if st.session_state.get(f"feedback_{wk}") is None:
                        with st.spinner(f"Concept schrijven voor {workouts[i]['athlete_name']}..."):
                            try:
                                _thread = workouts[i].get("thread", [])
                                _last_van = _thread[-1].get("van") if _thread else None
                                _has_coach = any(m.get("van") == "coach" for m in _thread)
                                if _thread and _last_van == "atleet" and _has_coach:
                                    fb = ai_feedback.generate_reply(workouts[i], _thread)
                                else:
                                    fb = ai_feedback.generate_feedback(workouts[i])
                                st.session_state[f"feedback_{wk}"] = fb
                            except Exception as e:
                                st.session_state[f"feedback_{wk}"] = f"[Fout: {e}]"
                    progress.progress((idx + 1) / len(pending))
                st.rerun()

        st.markdown("---")

        def _sec(s):
            if not s:
                return "—"
            s = int(float(s))
            return f"{s//60}:{s%60:02d}"

        for i, workout in enumerate(workouts):
            wk = workout["workout_key"]
            posted = st.session_state.get(f"posted_{wk}", False)
            is_data_only = workout.get("data_only", False)
            is_planned_no_notes = workout.get("planned_no_notes", False)

            with st.container():
                col_h, col_s = st.columns([5, 1])
                with col_h:
                    if posted:
                        icon = "✅"
                    elif is_planned_no_notes:
                        icon = "📅"
                    elif is_data_only:
                        icon = "📊"
                    else:
                        icon = "📋"
                    if is_planned_no_notes:
                        tag = " · *gepland, geen notities*"
                    elif is_data_only:
                        tag = " · *geen notities, alleen data*"
                    else:
                        tag = ""
                    st.subheader(f"{icon} {workout['athlete_name']} — {workout['workout_name']}{tag}")
                    st.caption(f"📅 {workout['workout_date']}")
                with col_s:
                    if posted:
                        st.success("Gepost")

                if posted:
                    st.markdown("---")
                    continue

                col_left, col_right = st.columns(2)

                with col_left:
                    felt = workout.get("felt")
                    effort = workout.get("effort")
                    if felt or effort:
                        felt_str = f"😊 Gevoel: **{felt}**" if felt else ""
                        effort_str = f"💪 Inspanning: **{effort}/10**" if effort else ""
                        st.info("  ·  ".join(filter(None, [felt_str, effort_str])))

                    if workout["post_notes"]:
                        st.markdown("**Post-workout notities:**")
                        st.info(workout["post_notes"])

                    thread = workout.get("thread", [])
                    visible_thread = [m for m in thread if m.get("_display", True)]
                    if visible_thread:
                        st.markdown("**Gesprek:**")
                        for msg in visible_thread:
                            tekst = msg.get("tekst", "")
                            if not tekst.strip():
                                continue
                            van = msg.get("van", "atleet")
                            naam = msg.get("naam", "")
                            if van == "coach":
                                st.success(f"🏋️ **{naam or 'Jip'}:** {tekst}")
                            else:
                                st.info(f"🏃 **{naam or 'Atleet'}:** {tekst}")
                    elif not workout["post_notes"]:
                        st.markdown("**Geen notities van de atleet.**")

                    details = workout.get("details") or {}
                    activities = details.get("Activities") or []
                    if activities:
                        act = activities[0]
                        st.markdown("**Trainingsdata:**")
                        rows = []
                        if act.get("amount"):
                            rows.append(("Afstand", f"{round(act['amount'], 2)} {act.get('amount_type','km')}",
                                         f"{act.get('planned_amount') or '—'} {act.get('amount_type','km')}"))
                        if act.get("duration"):
                            rows.append(("Tijd", _sec(act["duration"]), _sec(act.get("planned_duration"))))
                        if act.get("pace_display"):
                            rows.append(("Pace", f"{act['pace_display']} {act.get('pace_display_type','min/km')}", "—"))
                        if act.get("hr_avg"):
                            rows.append(("Gem. HF", f"{act['hr_avg']} bpm (max {act.get('hr_max','?')} bpm)", "—"))
                        if act.get("power_avg"):
                            rows.append(("Vermogen", f"{act['power_avg']} W", "—"))

                        if rows:
                            cols = st.columns(3)
                            cols[0].markdown("**Meetwaarde**")
                            cols[1].markdown("**Uitgevoerd**")
                            cols[2].markdown("**Gepland**")
                            for label, actual, planned in rows:
                                cols[0].markdown(label)
                                cols[1].markdown(actual)
                                cols[2].markdown(planned)

                with col_right:
                    st.markdown("**Jouw reactie (concept):**")
                    current_fb = st.session_state.get(f"feedback_{wk}")

                    # Bepaal of er al een gesprek loopt (thread met laatste bericht van atleet)
                    thread = workout.get("thread", [])
                    last_msg_van = thread[-1].get("van") if thread else None
                    has_coach_in_thread = any(m.get("van") == "coach" for m in thread)
                    has_athlete_followup = bool(thread) and last_msg_van == "atleet" and has_coach_in_thread

                    if current_fb is None and not st.session_state.get(f"zelf_{wk}"):
                        btn_label = "✨ Reageer op laatste bericht" if has_athlete_followup else "✨ Schrijf concept"
                        col_gen, col_zelf, col_skip_early = st.columns(3)
                        with col_gen:
                            if st.button(btn_label, key=f"gen_{i}", type="primary"):
                                with st.spinner("Concept schrijven..."):
                                    try:
                                        if has_athlete_followup:
                                            fb = ai_feedback.generate_reply(workout, thread)
                                        else:
                                            fb = ai_feedback.generate_feedback(workout)
                                        st.session_state[f"feedback_{wk}"] = fb
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Fout: {e}")
                        with col_zelf:
                            if st.button("✏️ Zelf schrijven", key=f"zelf_btn_{i}"):
                                st.session_state[f"zelf_{wk}"] = True
                                st.rerun()
                        with col_skip_early:
                            if st.button("⏭️ Overslaan", key=f"skip_early_{i}"):
                                _skipped = _load_skipped()
                                _skipped[wk] = date.today().isoformat()
                                _save_skipped(_skipped)
                                st.session_state[f"posted_{wk}"] = True
                                st.rerun()

                    elif st.session_state.get(f"zelf_{wk}"):
                        edited = st.text_area(
                            "Schrijf je eigen feedback:",
                            value="",
                            height=220,
                            key=f"edit_{i}",
                        )
                        col_post_z, col_annul_z = st.columns(2)
                        with col_post_z:
                            if st.button("✅ Posten", key=f"post_zelf_{i}", type="primary"):
                                if edited.strip():
                                    try:
                                        fs_client.post_comment(
                                            workout_key=workout["workout_key"],
                                            user_key=workout["athlete_key"],
                                            comment=edited,
                                            coach_athlete_key=COACH_ATHLETE_KEY.get(workout["athlete_key"]),
                                        )
                                        st.session_state[f"posted_{wk}"] = True
                                        st.session_state.pop(f"zelf_{wk}", None)
                                        _session_log = st.session_state.setdefault("session_feedback_log", [])
                                        _session_log.append({
                                            "athlete_name": workout["athlete_name"],
                                            "workout_name": workout["workout_name"],
                                            "feedback_text": edited,
                                        })
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Fout bij posten: {e}")
                                else:
                                    st.warning("Schrijf eerst een bericht.")
                        with col_annul_z:
                            if st.button("↩️ Terug", key=f"annul_zelf_{i}"):
                                st.session_state.pop(f"zelf_{wk}", None)
                                st.rerun()
                    else:
                        edited = st.text_area(
                            "Pas aan waar nodig:",
                            value=current_fb,
                            height=220,
                            key=f"edit_{i}",
                        )

                        col_post, col_skip, col_regen = st.columns(3)
                        with col_post:
                            if st.button("✅ Posten", key=f"post_{i}", type="primary"):
                                try:
                                    fs_client.post_comment(
                                        workout_key=workout["workout_key"],
                                        user_key=workout["athlete_key"],
                                        comment=edited,
                                        coach_athlete_key=COACH_ATHLETE_KEY.get(workout["athlete_key"]),
                                    )
                                    st.session_state[f"posted_{wk}"] = True
                                    # Sla op voor sessie-samenvatting
                                    _session_log = st.session_state.setdefault("session_feedback_log", [])
                                    _session_log.append({
                                        "athlete_name": workout["athlete_name"],
                                        "workout_name": workout["workout_name"],
                                        "feedback_text": edited,
                                    })
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Fout bij posten: {e}")
                        with col_skip:
                            if st.button("⏭️ Overslaan", key=f"skip_{i}"):
                                _skipped = _load_skipped()
                                _skipped[wk] = date.today().isoformat()
                                _save_skipped(_skipped)
                                st.session_state[f"posted_{wk}"] = True
                                st.rerun()
                        with col_regen:
                            if st.button("🔄 Opnieuw", key=f"regen_{i}"):
                                st.session_state[f"feedback_{wk}"] = None
                                st.rerun()

                st.markdown("---")

        # ── Sessie-samenvatting ───────────────────────────────────────────────
        session_log = st.session_state.get("session_feedback_log", [])
        st.markdown("---")
        st.markdown("### 📋 Sessie-samenvatting")
        if not session_log:
            st.info("Nog geen feedback gepost deze sessie. Zodra je feedback hebt gepost verschijnt hier de samenvatting.")
        if session_log:
            col_coach, col_gen_sum = st.columns([2, 1])
            with col_coach:
                coach_name = st.selectbox(
                    "Wie geeft vandaag feedback?",
                    ["Jip", "Remco"],
                    key="summary_coach",
                )
            with col_gen_sum:
                st.markdown("<div style='margin-top:1.7rem'></div>", unsafe_allow_html=True)
                gen_sum = st.button("✨ Genereer samenvatting", key="btn_gen_summary", type="primary")

            if gen_sum or st.session_state.get("session_summary"):
                if gen_sum:
                    with st.spinner("Samenvatting schrijven..."):
                        try:
                            summary = ai_feedback.generate_session_summary(coach_name, session_log)
                            st.session_state["session_summary"] = summary
                            st.session_state["session_summary_coach"] = coach_name
                        except Exception as e:
                            st.error(f"Fout: {e}")

                summary = st.session_state.get("session_summary", "")
                if summary:
                    st.text_area(
                        "Kopieer voor WhatsApp of e-mail:",
                        value=summary,
                        height=200,
                        key="summary_text",
                    )
                    # Mailto-link voor e-mail
                    import urllib.parse
                    _emails = "jip_vanlent@hotmail.com,Remco-groen@hotmail.com"
                    _subject = urllib.parse.quote(f"Coaching update {date.today().strftime('%d-%m-%Y')} — {st.session_state.get('session_summary_coach','')}")
                    _body = urllib.parse.quote(summary)
                    _mailto = f"mailto:{_emails}?subject={_subject}&body={_body}"
                    st.markdown(
                        f'<a href="{_mailto}" target="_blank"><button style="background:#1a1a2e;color:white;border:none;padding:0.5rem 1.2rem;border-radius:6px;cursor:pointer;font-size:0.9rem">📧 Openen in e-mail</button></a>',
                        unsafe_allow_html=True,
                    )
                    if st.button("🔄 Opnieuw genereren", key="btn_regen_summary"):
                        st.session_state.pop("session_summary", None)
                        st.rerun()


# ===========================================================================
# PAGINA: BUILDER BIJVULLEN
# ===========================================================================

elif page == "backfill_builder":
    module_header("Builder bijvullen", "🔧")

    st.markdown("""
    Scan de geplande trainingen van een atleet op een bepaalde periode.
    Trainingen met een beschrijving maar **zonder workout builder structuur** worden hier getoond.
    Selecteer welke je wil bijvullen en de app doet de rest.
    """)

    # ── Atleet + periode selectie ─────────────────────────────────────────
    all_athletes = sorted(
        [a for members in athletes_by_group.values() for a in members],
        key=lambda x: x["name"],
    )
    athlete_options = {a["name"]: a["user_key"] for a in all_athletes}
    zone_type_options = {a["user_key"]: a for a in all_athletes}

    col_a, col_d1, col_d2 = st.columns([2, 1, 1])
    with col_a:
        selected_name = st.selectbox("Atleet", options=list(athlete_options.keys()), key="bf_athlete")
        bf_athlete_key = athlete_options[selected_name]
    with col_d1:
        bf_start = st.date_input("Van", value=date.today(), key="bf_start")
    with col_d2:
        bf_end = st.date_input("Tot", value=date.today() + timedelta(days=84), key="bf_end")

    zone_type_radio = st.radio(
        "Zone-type voor builder",
        options=["tempo (min/km)", "hartslag (bpm)"],
        horizontal=True,
        key="bf_zone_type",
    )
    bf_zone_type = "pace" if "tempo" in zone_type_radio else "heart_rate"

    # ── Scan knop ─────────────────────────────────────────────────────────
    if st.button("🔍 Scan trainingen", type="primary", key="btn_bf_scan"):
        st.session_state.pop("bf_results", None)
        with st.spinner("Trainingen ophalen…"):
            try:
                w1 = fs_client.get_workouts(bf_athlete_key, bf_start, bf_end, ishistory=False)
                w2 = fs_client.get_workouts(bf_athlete_key, bf_start, bf_end, ishistory=True)
                seen = set()
                workouts_raw = []
                for w in w1 + w2:
                    k = w.get("key")
                    if k and k not in seen:
                        seen.add(k)
                        workouts_raw.append(w)
            except Exception as e:
                st.error(f"Fout bij ophalen trainingen: {e}")
                workouts_raw = []

        with st.expander(f"🔍 Debug: {len(workouts_raw)} workouts opgehaald"):
            for w in workouts_raw[:5]:
                st.json({
                    "key": w.get("key"),
                    "name": w.get("name"),
                    "workout_date": w.get("workout_date"),
                    "has_actual_data": w.get("has_actual_data"),
                    "activity_type_name": w.get("activity_type_name"),
                })

        if workouts_raw:
            results = []
            seen_nd = set()
            for w in sorted(workouts_raw, key=lambda x: (x.get("workout_date") or "")[:10]):
                wk = w.get("key") or ""
                name = (w.get("name") or "").strip()
                workout_date = (w.get("workout_date") or "")[:10]
                if not wk or not name or not workout_date:
                    continue
                if workout_date < bf_start.isoformat():
                    continue
                nd = (workout_date, name)
                if nd in seen_nd:
                    continue
                seen_nd.add(nd)
                results.append({
                    "date": workout_date,
                    "name": name,
                    "description": "",
                    "workout_key": wk,
                    "activity_type": "Run",
                })
            st.session_state["bf_results"] = results
            st.session_state["bf_athlete_key_saved"] = bf_athlete_key
            st.session_state["bf_zone_type_saved"] = bf_zone_type

    # ── Resultaten ────────────────────────────────────────────────────────
    bf_results = st.session_state.get("bf_results")
    if bf_results is not None:
        if not bf_results:
            st.info("Geen geplande trainingen gevonden in deze periode (of alles is al voltooid).")
        else:
            st.markdown(f"**{len(bf_results)} trainingen gevonden zonder builder structuur:**")
            st.markdown("---")

            # Selectie checkboxen
            if "bf_selected" not in st.session_state:
                st.session_state["bf_selected"] = set(range(len(bf_results)))

            col_all, col_none = st.columns([1, 1])
            with col_all:
                if st.button("✅ Alles selecteren", key="bf_sel_all"):
                    st.session_state["bf_selected"] = set(range(len(bf_results)))
                    st.rerun()
            with col_none:
                if st.button("☐ Niets selecteren", key="bf_sel_none"):
                    st.session_state["bf_selected"] = set()
                    st.rerun()

            for idx, w in enumerate(bf_results):
                col_cb, col_date, col_name = st.columns([0.5, 1, 5])
                checked = idx in st.session_state.get("bf_selected", set())
                with col_cb:
                    new_val = st.checkbox("", value=checked, key=f"bf_cb_{idx}", label_visibility="collapsed")
                    if new_val and idx not in st.session_state["bf_selected"]:
                        st.session_state["bf_selected"].add(idx)
                        st.rerun()
                    elif not new_val and idx in st.session_state["bf_selected"]:
                        st.session_state["bf_selected"].discard(idx)
                        st.rerun()
                with col_date:
                    try:
                        dt = date.fromisoformat(w["date"])
                        _dag_nl = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]
                        dag = _dag_nl[dt.weekday()]
                        st.caption(f"{dag} {dt.day}/{dt.month}")
                    except Exception:
                        st.caption(w["date"])
                with col_name:
                    st.markdown(f"**{w['name']}**")

            st.markdown("---")
            selected = st.session_state.get("bf_selected", set())
            n_sel = len(selected)

            if n_sel > 0:
                if st.button(f"🔧 Vul builder voor {n_sel} training(en)", type="primary", key="btn_bf_fill"):
                    to_fill = [bf_results[i] for i in sorted(selected)]
                    bf_key = st.session_state.get("bf_athlete_key_saved", bf_athlete_key)
                    bf_zt = st.session_state.get("bf_zone_type_saved", bf_zone_type)

                    progress2 = st.progress(0)
                    status = st.empty()
                    filled = 0
                    fill_errors = []

                    for idx2, w in enumerate(to_fill):
                        status.markdown(f"Builder genereren: **{w['name']}** ({idx2+1}/{len(to_fill)})")
                        try:
                            # Haal beschrijving op via details (zit niet in WorkoutList)
                            desc = w.get("description", "")
                            if not desc and w["workout_key"]:
                                try:
                                    details = fs_client.get_workout_details(w["workout_key"], bf_key)
                                    desc = (details.get("description") or "").strip()
                                except Exception:
                                    pass
                            if not desc:
                                fill_errors.append(f"{w['date']} {w['name']}: geen beschrijving gevonden")
                                continue
                            steps = schema_builder.generate_builder_steps(
                                workout_name=w["name"],
                                description=desc,
                                zone_type=bf_zt,
                                activity_type=w.get("activity_type", "Run"),
                                op_tijd=False,
                            )
                            if steps and w["workout_key"]:
                                fs_client.save_workout_builder(
                                    user_key=bf_key,
                                    workout_key=w["workout_key"],
                                    target_options=steps,
                                    workout_name=w["name"],
                                )
                                filled += 1
                            else:
                                fill_errors.append(f"{w['date']} {w['name']}: geen stappen gegenereerd")
                        except Exception as fe:
                            fill_errors.append(f"{w['date']} {w['name']}: {fe}")
                        progress2.progress((idx2 + 1) / len(to_fill))

                    progress2.empty()
                    status.empty()

                    if fill_errors:
                        st.warning(f"✅ {filled} gelukt, {len(fill_errors)} mislukt.")
                        with st.expander("Fouten bekijken"):
                            for err in fill_errors:
                                st.code(err)
                    else:
                        st.success(f"🎉 {filled} workout builders succesvol bijgevuld! Controleer in FinalSurge.")
                        st.session_state.pop("bf_results", None)
                        st.session_state.pop("bf_selected", None)
            else:
                st.info("Selecteer minimaal 1 training.")


# ===========================================================================
# ===========================================================================
# PAGINA: RACES & SUCCESWENSEN
# ===========================================================================

elif page == "races":
    module_header("Races & Succeswensen", "🏁")

    # ── Filters ──────────────────────────────────────────────────────────────
    col_f1, col_f2, _ = st.columns([1, 1, 2])
    with col_f1:
        days_ahead = st.selectbox("Kijk vooruit", [7, 14, 21, 30], index=1,
                                  format_func=lambda d: f"{d} dagen", key="races_days")
    with col_f2:
        if st.button("🔄 Vernieuwen", key="races_refresh"):
            for k in list(st.session_state.keys()):
                if k.startswith("race_wish_") or k.startswith("race_posted_"):
                    del st.session_state[k]
            st.session_state.pop("races_data", None)
            st.rerun()

    # ── Data ophalen ──────────────────────────────────────────────────────────
    cache_key = f"races_data_{days_ahead}"
    if cache_key not in st.session_state:
        with st.spinner("Aankomende races ophalen..."):
            try:
                races = fs_client.get_upcoming_races(days_ahead=days_ahead)
                st.session_state[cache_key] = races
            except Exception as e:
                st.error(f"Fout bij ophalen races: {e}")
                st.stop()

    races = st.session_state.get(cache_key, [])

    if not races:
        st.info(f"Geen races gevonden in de komende {days_ahead} dagen.")
    else:
        # Batch-knop
        pending_races = [r for r in races
                         if not st.session_state.get(f"race_posted_{r['workout_key']}")]
        st.markdown(f"**{len(pending_races)} race(s)** gevonden — succeswensen nog te versturen.")

        if pending_races:
            if st.button("⚡ Genereer alle wensen (AI)", type="primary", key="races_batch"):
                progress = st.progress(0)
                for idx, race in enumerate(pending_races):
                    wk = race["workout_key"]
                    if st.session_state.get(f"race_wish_{wk}") is None:
                        with st.spinner(f"Wens schrijven voor {race['athlete_first_name']}..."):
                            try:
                                context = fs_client.get_recent_race_context(
                                    race["athlete_key"], race["workout_name"])
                                wish = ai_feedback.generate_race_wish(
                                    first_name=race["athlete_first_name"],
                                    race_name=race["workout_name"],
                                    race_type=race["race_type"],
                                    race_date=race["workout_date"],
                                    context=context,
                                )
                                st.session_state[f"race_wish_{wk}"] = wish
                            except Exception as e:
                                st.session_state[f"race_wish_{wk}"] = f"[Fout: {e}]"
                    progress.progress((idx + 1) / len(pending_races))
                st.rerun()

        st.markdown("---")

        # Race type kleuren/iconen
        TYPE_ICON = {
            "HYROX": "💪",
            "Marathon": "🏃",
            "Halve marathon": "🏃",
            "10 km": "⚡",
            "5 km": "⚡",
            "Triathlon": "🏊",
            "15 km": "🏃",
            "Veldloop / Cross": "🌿",
            "Race": "🏁",
        }

        for i, race in enumerate(races):
            wk = race["workout_key"]
            posted = st.session_state.get(f"race_posted_{wk}", False)
            icon = TYPE_ICON.get(race["race_type"], "🏁")

            with st.container():
                col_h, col_s = st.columns([5, 1])
                with col_h:
                    status_icon = "✅" if posted else icon
                    st.subheader(f"{status_icon} {race['athlete_name']} — {race['workout_name']}")
                    try:
                        race_dt = date.fromisoformat(race["workout_date"][:10])
                        days_to_race = (race_dt - date.today()).days
                    except ValueError:
                        days_to_race = None

                    if days_to_race is None:
                        days_label = ""
                    elif days_to_race == 0:
                        days_label = "**vandaag**"
                    elif days_to_race == 1:
                        days_label = "**morgen**"
                    elif days_to_race == 2:
                        days_label = "**overmorgen**"
                    else:
                        dag_namen = ["maandag", "dinsdag", "woensdag", "donderdag",
                                     "vrijdag", "zaterdag", "zondag"]
                        dag = dag_namen[race_dt.weekday()]
                        days_label = f"komende **{dag}** (over {days_to_race} dagen)"
                    st.caption(
                        f"📅 {race['workout_date']} ({days_label})  ·  "
                        f"🏷️ {race['race_type']}"
                    )
                with col_s:
                    if posted:
                        st.success("Gepost")

                if posted:
                    st.markdown("---")
                    continue

                col_left, col_right = st.columns(2)

                with col_left:
                    # Eerdere comments tonen als context
                    comments = race.get("comments", [])
                    if comments:
                        st.markdown("**Eerdere opmerkingen over deze race:**")
                        for c in comments:
                            tekst = c.get("comment") or c.get("text") or ""
                            if tekst.strip():
                                naam = c.get("first_name") or "?"
                                st.info(f"💬 **{naam}:** {tekst}")
                    else:
                        st.markdown("*Geen eerdere comments op deze race.*")

                with col_right:
                    # ── Succeswens ──────────────────────────────────────────
                    st.markdown("**Succeswens:**")
                    current_wish = st.session_state.get(f"race_wish_{wk}")

                    if current_wish is None:
                        col_gen_w, col_skip_w = st.columns(2)
                        with col_gen_w:
                            if st.button("✨ Schrijf wens", key=f"gen_race_{i}", type="primary"):
                                with st.spinner("Wens schrijven..."):
                                    try:
                                        context = fs_client.get_recent_race_context(
                                            race["athlete_key"], race["workout_name"])
                                        wish = ai_feedback.generate_race_wish(
                                            first_name=race["athlete_first_name"],
                                            race_name=race["workout_name"],
                                            race_type=race["race_type"],
                                            race_date=race["workout_date"],
                                            context=context,
                                        )
                                        st.session_state[f"race_wish_{wk}"] = wish
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Fout: {e}")
                        with col_skip_w:
                            if st.button("⏭️ Overslaan", key=f"skip_race_{i}"):
                                st.session_state[f"race_posted_{wk}"] = True
                                st.rerun()
                    else:
                        edited_wish = st.text_area(
                            "Pas aan waar nodig:",
                            value=current_wish,
                            height=100,
                            key=f"edit_race_{i}",
                        )
                        col_post_w, col_regen_w = st.columns(2)
                        with col_post_w:
                            if st.button("✅ Posten wens", key=f"post_race_{i}", type="primary"):
                                try:
                                    fs_client.post_comment(
                                        workout_key=wk,
                                        user_key=race["athlete_key"],
                                        comment=edited_wish,
                                        coach_athlete_key=COACH_ATHLETE_KEY.get(race["athlete_key"]),
                                    )
                                    st.session_state[f"race_posted_{wk}"] = True
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Fout bij posten: {e}")
                        with col_regen_w:
                            if st.button("🔄 Opnieuw", key=f"regen_race_{i}"):
                                st.session_state[f"race_wish_{wk}"] = None
                                st.rerun()

                    st.markdown("")

                    # ── Raceplan ─────────────────────────────────────────────
                    st.markdown("**Raceplan:**")
                    current_plan = st.session_state.get(f"race_plan_{wk}")

                    if current_plan is None:
                        if st.button("📋 Genereer raceplan", key=f"gen_plan_{i}"):
                            with st.spinner("Raceplan schrijven..."):
                                try:
                                    context_plan = fs_client.get_recent_race_context(
                                        race["athlete_key"], race["workout_name"])
                                    plan = ai_feedback.generate_race_plan(
                                        first_name=race["athlete_first_name"],
                                        race_name=race["workout_name"],
                                        race_type=race["race_type"],
                                        race_date=race["workout_date"],
                                        athlete_key=race["athlete_key"],
                                        description=race.get("description", ""),
                                        context=context_plan,
                                    )
                                    st.session_state[f"race_plan_{wk}"] = plan
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Fout: {e}")
                    else:
                        edited_plan = st.text_area(
                            "Pas aan waar nodig:",
                            value=current_plan,
                            height=280,
                            key=f"edit_plan_{i}",
                        )
                        col_post_p, col_regen_p = st.columns(2)
                        with col_post_p:
                            if st.button("✅ Posten raceplan", key=f"post_plan_{i}", type="primary"):
                                try:
                                    fs_client.post_comment(
                                        workout_key=wk,
                                        user_key=race["athlete_key"],
                                        comment=edited_plan,
                                        coach_athlete_key=COACH_ATHLETE_KEY.get(race["athlete_key"]),
                                    )
                                    st.session_state[f"race_plan_posted_{wk}"] = True
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Fout bij posten: {e}")
                        with col_regen_p:
                            if st.button("🔄 Opnieuw", key=f"regen_plan_{i}"):
                                st.session_state[f"race_plan_{wk}"] = None
                                st.rerun()

                st.markdown("---")


# ===========================================================================
# PAGINA: SCHEMA-VERLOOP
# ===========================================================================

elif page == "schema":

    module_header("Schema-verloop", "📅")

    threshold = st.slider(
        "Toon atleten waarvan schema afloopt binnen … dagen",
        min_value=1, max_value=14, value=14, step=1,
        key="schema_threshold",
    )

    col_load, col_reload = st.columns([2, 1])
    with col_load:
        if "schema_data" not in st.session_state:
            if st.button("📥 Laad schema-overzicht", type="primary", key="schema_load"):
                with st.spinner("Schema-einddatums ophalen voor alle atleten… (±30 sec)"):
                    try:
                        st.session_state["schema_data"] = fs_client.get_schema_end_dates(horizon_days=60)
                    except TokenNotFoundError:
                        fs_client.reset_session()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fout: {e}")
                st.rerun()
            st.info("Klik op 'Laad schema-overzicht' om te beginnen.")

    if "schema_data" not in st.session_state:
        pass
    else:
        with col_reload:
            if st.button("🔄 Vernieuwen", key="schema_reload"):
                del st.session_state["schema_data"]
                st.rerun()

        schema_data = st.session_state.get("schema_data", [])

        def _status(days_left):
            if days_left is None:
                return "❌ Geen schema"
            if days_left <= 7:
                return "🔴 Urgent"
            if days_left <= 14:
                return "🟠 Bijna"
            return "🟢 OK"

        n_urgent = sum(1 for r in schema_data if r["days_left"] is not None and r["days_left"] <= 7)
        n_bijna  = sum(1 for r in schema_data if r["days_left"] is not None and 7 < r["days_left"] <= 14)
        n_geen   = sum(1 for r in schema_data if r["days_left"] is None)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("❌ Geen schema", n_geen)
        c2.metric("🔴 Urgent  (≤7d)", n_urgent)
        c3.metric("🟠 Bijna  (8–14d)", n_bijna)
        c4.metric("Totaal atleten", len(schema_data))

        st.markdown("---")

        filtered = [r for r in schema_data if r["days_left"] is None or r["days_left"] <= threshold]
        rest     = [r for r in schema_data if r["days_left"] is not None and r["days_left"] > threshold]

        if filtered:
            st.markdown(f"### Aandacht nodig — afloopt binnen {threshold} dagen of geen schema")

            groups_shown: dict[str, list] = {}
            for r in filtered:
                groups_shown.setdefault(r["group"], []).append(r)

            for group_name, members in groups_shown.items():
                st.markdown(f"**{group_name}**")
                hdr = st.columns([3, 2, 1, 2, 2])
                hdr[0].markdown("*Atleet*")
                hdr[1].markdown("*Schema tot*")
                hdr[2].markdown("*Dagen*")
                hdr[3].markdown("*Status*")
                hdr[4].markdown("")
                for r in members:
                    c0, c1, c2, c3, c4 = st.columns([3, 2, 1, 2, 2])
                    c0.write(r["name"])
                    c1.write(r["last_date"] or "—")
                    c2.write(str(r["days_left"]) if r["days_left"] is not None else "—")
                    c3.write(_status(r["days_left"]))
                    with c4:
                        if st.button("🔨 Bouw schema", key=f"quick_build_{r['user_key']}"):
                            # Pre-fill builder met atleetgegevens
                            st.session_state["builder_client_type"] = "🔄 Bestaande klant"
                            st.session_state["builder_athlete"] = r["name"]
                            st.session_state["builder_naam"] = r["first_name"]
                            st.session_state["builder_step"] = 1
                            for k in ["builder_plan", "builder_csv", "builder_intake",
                                      "builder_workouts", "builder_chat_history"]:
                                st.session_state.pop(k, None)
                            go_to("builder")
                st.markdown("")
        else:
            st.success(f"✅ Alle atleten hebben een schema dat nog meer dan {threshold} dagen loopt.")

        if rest:
            with st.expander(f"🟢 Voldoende schema — {len(rest)} atleten (meer dan {threshold} dagen)"):
                hdr = st.columns([3, 2, 1])
                hdr[0].markdown("*Atleet*")
                hdr[1].markdown("*Schema tot*")
                hdr[2].markdown("*Dagen*")
                for r in rest:
                    c0, c1, c2 = st.columns([3, 2, 1])
                    c0.write(r["name"])
                    c1.write(r["last_date"] or "—")
                    c2.write(str(r["days_left"]))


# ===========================================================================
# PAGINA: SCHEMA BOUWEN
# ===========================================================================

elif page == "builder":

    module_header("Schema bouwen", "🔨")

    # Toon herstel-melding als state hersteld is vanuit schijf
    if st.session_state.get("builder_intake") and st.session_state.get("builder_step", 1) > 1:
        intake_naam = st.session_state["builder_intake"].get("naam", "")
        c_msg, c_reset = st.columns([5, 1])
        c_msg.info(f"↩️ Sessie hersteld voor **{intake_naam}** — je kunt verder waar je gebleven was.")
        with c_reset:
            if st.button("🗑️ Nieuw", key="btn_reset_intake"):
                for k in ["builder_intake", "builder_plan", "builder_csv",
                          "builder_workouts", "builder_workouts_import",
                          "builder_chat_history", "builder_step", "builder_excluded",
                          "builder_referentie", "builder_tijd_per_training",
                          "builder_langste_afstand", "builder_kwaliteitservaring",
                          "builder_herstelcapaciteit", "builder_werkdruk",
                          "builder_ondergrond", "builder_race_prioriteit",
                          "builder_tussenraces", "builder_coach_notitie",
                          "builder_wat_werkte", "builder_wat_niet_werkte"]:
                    st.session_state.pop(k, None)
                _clear_builder_state()
                st.rerun()

    # ── Stap-indicator ──────────────────────────────────────────────────────
    if "builder_step" not in st.session_state:
        st.session_state["builder_step"] = 1

    step = st.session_state["builder_step"]

    def _set_step(s):
        if s == 1:
            # Reset de sync-vlag zodat velden opnieuw geladen worden vanuit builder_intake
            st.session_state["builder_fields_loaded"] = False
        st.session_state["builder_step"] = s
        st.rerun()

    step_labels = ["1 · Intake", "2 · Plan", "3 · CSV", "4 · Import"]
    pills_html = '<div class="bb-step-row">'
    for i, label in enumerate(step_labels, 1):
        cls = "active" if step == i else ("done" if step > i else "")
        suffix = " ✓" if step > i else ""
        pills_html += f'<div class="bb-step-pill {cls}">{label}{suffix}</div>'
    pills_html += '</div>'
    st.markdown(pills_html, unsafe_allow_html=True)
    st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)

    # ── Atleet selectie (altijd beschikbaar bovenaan) ───────────────────────
    all_athletes = sorted(
        [a for members in athletes_by_group.values() for a in members],
        key=lambda x: x["name"],
    )
    athlete_options = {a["name"]: a["user_key"] for a in all_athletes}

    # ===========================================================================
    # STAP 1 — INTAKE
    # ===========================================================================

    if step == 1:
        st.markdown("<div class='bb-intake-label'>Stap 1 — Intake</div>", unsafe_allow_html=True)

        # Vul widget-keys vanuit builder_intake — eenmalig bij binnenkomst op stap 1.
        # Daarna niet meer overschrijven zodat gebruikerswijzigingen (zoals checkbox) bewaard blijven.
        _existing = st.session_state.get("builder_intake") or {}
        if _existing and not st.session_state.get("builder_fields_loaded", False):
            st.session_state["builder_naam"]              = _existing.get("naam", "")
            st.session_state["builder_doel"]              = _existing.get("doel", "")
            st.session_state["builder_volume"]            = _existing.get("huidig_volume", "")
            st.session_state["builder_dagen"]             = _existing.get("trainingsdagen", "")
            st.session_state["builder_referentie"]        = _existing.get("referentie_prestatie", "")
            st.session_state["builder_tijd_per_training"] = _existing.get("tijd_per_training", "")
            st.session_state["builder_langste_afstand"]   = _existing.get("langste_afstand", "")
            st.session_state["builder_blessure"]          = _existing.get("blessurehistorie", "")
            st.session_state["builder_andere_sporten"]    = _existing.get("andere_sporten", "")
            st.session_state["builder_coach_notitie"]     = _existing.get("coach_notitie", "")
            st.session_state["builder_wat_werkte"]        = _existing.get("wat_werkte", "")
            st.session_state["builder_wat_niet_werkte"]   = _existing.get("wat_niet_werkte", "")
            st.session_state["builder_tussenraces"]       = _existing.get("tussenraces", "")
            st.session_state["builder_werkdruk"]          = _existing.get("werkdruk", "")
            st.session_state["builder_op_tijd"]           = _existing.get("op_tijd", False)
            _zt = _existing.get("zone_type", "tempo")
            st.session_state["builder_zone_type"]         = "hartslag (bpm)" if _zt == "hartslag" else "tempo (min/km)"
            _sed = _existing.get("schema_einddatum", "")
            st.session_state["builder_schema_einddatum"]  = date.fromisoformat(_sed) if _sed else None
            st.session_state["builder_fields_loaded"]     = True  # niet opnieuw laden

        client_type = st.radio(
            "Type klant",
            options=["🆕 Nieuwe klant", "🔄 Bestaande klant"],
            horizontal=True,
            key="builder_client_type",
        )
        is_new = "Nieuwe" in client_type
        st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)

        # ── KOLOM LINKS: Doel & Planning | RECHTS: Training & Niveau ─────────
        col_l, col_r = st.columns(2, gap="large")

        with col_l:
            st.markdown("<div class='bb-intake-label'>Doel & planning</div>", unsafe_allow_html=True)
            selected_athlete_name = st.selectbox(
                "Atleet *", options=list(athlete_options.keys()), key="builder_athlete",
            )
            athlete_key_selected = athlete_options[selected_athlete_name]
            if "builder_naam" not in st.session_state:
                st.session_state["builder_naam"] = selected_athlete_name.split()[0] if selected_athlete_name else ""
            naam = st.text_input("Naam in coaching-tekst *", key="builder_naam", placeholder="bijv. Lisa")
            doel = st.text_area(
                "Doelstelling *", key="builder_doel", height=70,
                placeholder="bijv. 10km in sub 55min, of: HYROX afmaken in Amsterdam",
            )
            startdatum = st.date_input(
                "Startdatum schema *",
                value=date.today() + timedelta(days=(7 - date.today().weekday())),
                key="builder_startdatum",
            )
            c_datum1, c_datum2 = st.columns(2)
            with c_datum1:
                schema_einddatum = st.date_input(
                    "Schema eindigt op",
                    value=None,
                    key="builder_schema_einddatum",
                    min_value=date.today(),
                    help="Laat leeg als het schema doorloopt tot aan de hoofdrace.",
                )
            with c_datum2:
                wedstrijddatum = st.date_input(
                    "Datum hoofddoel",
                    value=None,
                    key="builder_wedstrijddatum",
                    min_value=date.today(),
                    help="De uiteindelijke wedstrijddatum. Mag verder weg liggen dan het schema.",
                )
            schema_target = schema_einddatum or wedstrijddatum
            if schema_target and startdatum:
                weken_berekend = max(1, (schema_target - startdatum).days // 7)
                if weken_berekend > 20:
                    st.warning(f"⚠️ {weken_berekend} weken is erg lang — overweeg dit schema in 2 blokken te splitsen.")
                else:
                    st.caption(f"📅 {weken_berekend} weken schema")
                if wedstrijddatum and schema_einddatum and wedstrijddatum > schema_einddatum:
                    st.caption(f"🎯 Hoofddoel: {wedstrijddatum.day} {wedstrijddatum.strftime('%B %Y')} ({(wedstrijddatum - schema_einddatum).days // 7} weken na dit schema)")
            race_prioriteit = st.radio(
                "Race prioriteit",
                options=["A-race (volledig pieken)", "B-race (lichte taper)", "C-race (geen taper)"],
                horizontal=True, key="builder_race_prioriteit",
            )
            tussenraces = st.text_input(
                "Tussenraces", key="builder_tussenraces",
                placeholder="bijv. 15 jun 10km, 20 jul 5km",
            )

        with col_r:
            st.markdown("<div class='bb-intake-label'>Training & niveau</div>", unsafe_allow_html=True)
            referentie_prestatie = st.text_input(
                "Recente referentieprestatie *", key="builder_referentie",
                placeholder="bijv. 5km in 22:30 (vorige maand)",
            )
            huidig_volume = st.text_input(
                "Huidig wekelijks volume *", key="builder_volume",
                placeholder="bijv. 25-30 km/week",
            )
            trainingsdagen = st.text_input(
                "Trainingsdagen *", key="builder_dagen",
                placeholder="bijv. ma / wo / vr / zo",
            )
            tijd_per_training = st.text_input(
                "Tijd per training *", key="builder_tijd_per_training",
                placeholder="bijv. ma: 45min, wo: 60min, zo: 90min",
            )
            langste_afstand = st.text_input(
                "Langste afstand recent", key="builder_langste_afstand",
                placeholder="bijv. 14km (3 weken geleden)",
            )
            kwaliteitservaring = st.radio(
                "Ervaring intervals/tempo",
                options=["Weinig/geen", "Enige ervaring", "Regelmatig"],
                horizontal=True, key="builder_kwaliteitservaring",
            )
            op_tijd = st.checkbox(
                "Schema op tijd (minuten) i.p.v. kilometers",
                key="builder_op_tijd",
                help="Trainingen worden beschreven in minuten (bijv. '45 min Z2') en geïmporteerd als tijdsduur.",
            )
            if is_new:
                c_lft, c_hor = st.columns(2)
                with c_lft:
                    leeftijd = st.text_input("Leeftijd", key="builder_leeftijd", placeholder="bijv. 34")
                with c_hor:
                    horloge = st.text_input("Horloge / GPS", key="builder_horloge", placeholder="bijv. Garmin 255")
            else:
                leeftijd = horloge = ""

        # ── ATLEETPROFIEL (compact, onder de twee kolommen) ─────────────────
        st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)
        st.markdown("<div class='bb-intake-label'>Atleetprofiel</div>", unsafe_allow_html=True)
        cp1, cp2, cp3 = st.columns(3)
        with cp1:
            herstelcapaciteit = st.radio(
                "Herstelcapaciteit", options=["Langzaam", "Normaal", "Snel"],
                horizontal=True, index=1, key="builder_herstelcapaciteit",
            )
        with cp2:
            werkdruk = st.radio(
                "Werkdruk buiten sport", options=["Laag", "Normaal", "Hoog"],
                horizontal=True, index=1, key="builder_werkdruk",
            )
        with cp3:
            loopondergrond = st.multiselect(
                "Loopondergrond",
                options=["Weg", "Trail", "Baan", "Loopband"],
                default=["Weg"], key="builder_ondergrond",
            )

        ca, cb = st.columns(2)
        with ca:
            blessurehistorie = st.text_input(
                "Blessurehistorie", key="builder_blessure",
                placeholder="bijv. linkerknie (2023), schouder (recent)",
            )
        with cb:
            andere_sporten = st.text_input(
                "Andere sporten / verplichtingen", key="builder_andere",
                placeholder="bijv. HYROX 2x/week, zwemmen wo",
            )

        coach_notitie = st.text_area(
            "⭐ Coach notitie — jouw kennis over deze atleet",
            key="builder_coach_notitie", height=80,
            placeholder="bijv. neiging te snel op te bouwen, mentaal sterk, sloeg vorig schema half af door kniepijn bij hoge km",
        )

        if not is_new:
            cw1, cw2 = st.columns(2)
            with cw1:
                wat_werkte = st.text_input(
                    "Wat werkte goed", key="builder_wat_werkte",
                    placeholder="bijv. vaste weekstructuur, progressieve lange duurlopen",
                )
            with cw2:
                wat_niet_werkte = st.text_input(
                    "Wat werkte niet", key="builder_wat_niet_werkte",
                    placeholder="bijv. te veel intervals te snel",
                )
        else:
            wat_werkte = wat_niet_werkte = ""

        # ── ZONES ───────────────────────────────────────────────────────────
        if is_new:
            # Nieuwe klant: VDOT-calculator + handmatig invoer
            st.markdown("<div class='bb-intake-label'>Zones — VDOT-berekening</div>", unsafe_allow_html=True)
            st.caption("Vul een recent wedstrijd- of testresultaat in om zones automatisch te berekenen. Sla over als je de zones handmatig wilt invullen.")

            with st.expander("🔢 Bereken zones via VDOT (Jack Daniels)", expanded=True):
                vc1, vc2, vc3 = st.columns([2, 2, 1])
                with vc1:
                    vdot_afstand = st.selectbox(
                        "Afstand",
                        options=["5 km", "10 km", "Halve marathon (21,1 km)", "Marathon (42,2 km)", "Andere afstand"],
                        key="vdot_afstand",
                    )
                    if vdot_afstand == "Andere afstand":
                        vdot_km = st.number_input("Afstand in km", min_value=0.1, value=5.0, step=0.1, key="vdot_km_custom")
                    else:
                        afstand_map = {"5 km": 5.0, "10 km": 10.0, "Halve marathon (21,1 km)": 21.0975, "Marathon (42,2 km)": 42.195}
                        vdot_km = afstand_map[vdot_afstand]
                with vc2:
                    vdot_tijd = st.text_input(
                        "Tijd (uu:mm:ss of mm:ss)",
                        key="vdot_tijd",
                        placeholder="bijv. 22:30 of 1:45:00",
                    )
                with vc3:
                    st.markdown("<div style='margin-top:1.7rem'></div>", unsafe_allow_html=True)
                    calc_btn = st.button("Bereken →", key="btn_vdot_calc", type="primary")

                if calc_btn and vdot_tijd:
                    try:
                        # Tijd parsen
                        parts = vdot_tijd.strip().split(":")
                        if len(parts) == 2:
                            t_sec = int(parts[0]) * 60 + int(parts[1])
                        elif len(parts) == 3:
                            t_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                        else:
                            raise ValueError("Ongeldig tijdformaat")
                        vdot_val = schema_builder.calculate_vdot(vdot_km * 1000, t_sec)
                        zones_calc = schema_builder.vdot_to_zones_text(vdot_val)
                        st.session_state["vdot_result"] = vdot_val
                        st.session_state["vdot_zones_calc"] = zones_calc
                    except Exception as e:
                        st.error(f"Berekeningsfout: {e}")

                if st.session_state.get("vdot_result"):
                    vdot_val = st.session_state["vdot_result"]
                    zones_calc = st.session_state["vdot_zones_calc"]
                    st.success(f"**VDOT: {vdot_val:.1f}**")
                    st.code(zones_calc)
                    if st.button("✅ Gebruik deze zones", key="btn_use_vdot_zones"):
                        st.session_state["builder_zones_prefill"] = zones_calc
                        st.session_state["builder_zone_type_prefill"] = "tempo (min/km)"
                        st.rerun()

            zone_type = st.radio(
                "Zones op basis van",
                options=["tempo (min/km)", "hartslag (bpm)"],
                horizontal=True,
                key="builder_zone_type",
                index=0 if st.session_state.get("builder_zone_type_prefill", "tempo") == "tempo (min/km)" else 1,
            )
            zones_placeholder = (
                "bijv. Z1: >6:30, Z2: 6:00-6:30, Z3: 5:30-6:00, Z4: 5:00-5:30, Z5: <5:00"
                if "tempo" in zone_type else
                "bijv. Z1: <130 bpm, Z2: 130-145 bpm, Z3: 145-158 bpm, Z4: 158-168 bpm, Z5: >168 bpm"
            )
            zones_prefill = st.session_state.pop("builder_zones_prefill", "") or ""
            zones = st.text_area(
                "Zones *",
                value=zones_prefill,
                key="builder_zones",
                placeholder=zones_placeholder,
                height=110,
            )

        else:
            # Bestaande klant: automatisch ophalen uit FinalSurge
            st.markdown("<div class='bb-intake-label'>Zones — FinalSurge</div>", unsafe_allow_html=True)

            zones_fetch_key = f"fetched_zones_{athlete_key_selected}"
            if zones_fetch_key not in st.session_state:
                with st.spinner("Zones ophalen uit FinalSurge…"):
                    fetched = fs_client.get_athlete_zones(athlete_key_selected)
                    st.session_state[zones_fetch_key] = fetched

            fetched = st.session_state.get(zones_fetch_key, {})

            if fetched and fetched.get("zones_text"):
                zone_type_fetched = fetched.get("zone_type", "tempo")
                zone_type_label_fetched = "hartslag (bpm)" if zone_type_fetched == "hartslag" else "tempo (min/km)"
                st.success(f"✅ Zones opgehaald ({zone_type_label_fetched})")
                zones = fetched["zones_text"]
                # Zorg dat session state overeenkomt met opgehaalde zones
                if st.session_state.get("builder_zones", "") != zones:
                    st.session_state["builder_zones"] = zones
                st.code(zones)
                # Keuze hartslag / tempo — ook als FinalSurge al één type heeft
                zone_type = st.radio(
                    "Sturing schema op",
                    options=["tempo (min/km)", "hartslag (bpm)"],
                    horizontal=True,
                    key="builder_zone_type",
                    index=1 if zone_type_fetched == "hartslag" else 0,
                )
                st.caption("Zones worden automatisch meegenomen. Je kunt ze hieronder nog aanpassen.")
                zones_override = st.text_area(
                    "Zones aanpassen (optioneel)",
                    key="builder_zones",
                    height=110,
                )
                zones = zones_override or zones
            else:
                st.warning("Geen zones gevonden in FinalSurge voor deze atleet. Vul ze handmatig in.")
                with st.expander("🔍 Debug API-respons"):
                    st.json(fetched)
                zone_type = st.radio(
                    "Zones op basis van",
                    options=["tempo (min/km)", "hartslag (bpm)"],
                    horizontal=True,
                    key="builder_zone_type",
                )
                zones = st.text_area(
                    "Zones *",
                    key="builder_zones",
                    placeholder="bijv. Z1: >6:30, Z2: 6:00-6:30, …",
                    height=110,
                )
                col_refetch, _ = st.columns([1, 3])
                with col_refetch:
                    if st.button("🔄 Opnieuw proberen", key="btn_refetch_zones"):
                        st.session_state.pop(zones_fetch_key, None)
                        st.rerun()

        # ── Trainingslog (alleen bestaande klant) ───────────────────────────
        auto_log_text = ""
        if not is_new:
            st.markdown("<div class='bb-intake-label'>Trainingslog — afgelopen 4 maanden</div>", unsafe_allow_html=True)
            log_fetch_key = f"training_log_{athlete_key_selected}"
            if log_fetch_key not in st.session_state:
                with st.spinner("Trainingslog ophalen uit FinalSurge… (even geduld)"):
                    log_workouts = fs_client.get_training_log(athlete_key_selected, months=4)
                    st.session_state[log_fetch_key] = log_workouts

            log_workouts = st.session_state.get(log_fetch_key, [])

            # Auto pre-fill langste afstand voor bestaande klanten
            if log_workouts and not is_new:
                completed_workouts = [w for w in log_workouts if w.get("completed")]
                if completed_workouts:
                    max_km_workout = max(completed_workouts, key=lambda w: w.get("actual_km") or 0)
                    max_km = max_km_workout.get("actual_km")
                    if max_km and "builder_langste_afstand" not in st.session_state:
                        st.session_state["builder_langste_afstand"] = f"{max_km} km ({max_km_workout.get('date', '')})"

            if log_workouts:
                total_w = len(log_workouts)
                done_w = sum(1 for w in log_workouts if w["completed"])
                st.success(f"✅ {total_w} trainingen opgehaald — {done_w} voltooid")
                auto_log_text = schema_builder.format_training_log(log_workouts)
                with st.expander("📋 Trainingslog bekijken"):
                    st.text(auto_log_text[:3000] + ("…" if len(auto_log_text) > 3000 else ""))
                col_relog, _ = st.columns([1, 3])
                with col_relog:
                    if st.button("🔄 Opnieuw laden", key="btn_reload_log"):
                        st.session_state.pop(log_fetch_key, None)
                        st.rerun()
            else:
                st.info("Geen trainingen gevonden voor de afgelopen 4 maanden.")

        # ── Bestandsupload ──────────────────────────────────────────────────
        st.markdown("<div class='bb-intake-label'>Documenten *(optioneel)*</div>", unsafe_allow_html=True)
        st.caption("Extra bestanden zoals printscreens of aanvullende info. De AI houdt hier rekening mee.")
        uploaded_files = st.file_uploader(
            "Sleep bestanden hierheen of klik om te uploaden",
            type=["pdf", "docx", "xlsx", "xls", "csv", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="builder_uploads",
        )
        if uploaded_files:
            st.success(f"{len(uploaded_files)} bestand(en) geladen: {', '.join(f.name for f in uploaded_files)}")

        # ── Validatie & doorgaan ────────────────────────────────────────────
        required = [naam, doel, trainingsdagen, huidig_volume, zones, referentie_prestatie, tijd_per_training]
        all_filled = all(str(r).strip() for r in required)

        if not all_filled:
            st.warning("Vul alle verplichte velden (*) in om door te gaan.")

        if st.button("Genereer plan →", type="primary", disabled=not all_filled, key="btn_gen_plan"):
            schema_target = schema_einddatum or wedstrijddatum
            weken_val = str(max(1, (schema_target - startdatum).days // 7)) if schema_target else ""

            # Haal kalender-labels op
            labels_tekst = ""
            try:
                _end_date = startdatum + timedelta(days=int(weken_val) * 7 + 7) if weken_val else startdatum + timedelta(days=90)
                labels = fs_client.get_calendar_labels(athlete_key_selected, startdatum, _end_date)
                if labels:
                    label_regels = [
                        f"  - {l['start_date']}{' t/m ' + l['end_date'] if l['end_date'] != l['start_date'] else ''}: {l['name']}"
                        for l in labels
                    ]
                    labels_tekst = "KALENDER-LABELS (coach-reminders uit FinalSurge):\n" + "\n".join(label_regels)
            except Exception:
                pass

            # Verwerk geüploade bestanden
            uploaded_summary_parts = []
            uploaded_images = []
            for f in (uploaded_files or []):
                f.seek(0)
                item = schema_builder.extract_file_content(f)
                if item["type"] == "text":
                    uploaded_summary_parts.append(item["content"][:3000])
                elif item["type"] == "image":
                    uploaded_images.append(item)
                    uploaded_summary_parts.append(f"[Afbeelding: {item['label']} — zie vision-context]")

            # Voeg automatisch opgehaalde trainingslog toe (bestaande klant)
            if auto_log_text:
                uploaded_summary_parts.insert(0, auto_log_text[:9000])

            # Extra context voor nieuwe klant
            extra_context_parts = []
            if is_new:
                if leeftijd:
                    extra_context_parts.append(f"Leeftijd: {leeftijd} jaar")
                if horloge:
                    extra_context_parts.append(f"Horloge/GPS: {horloge}")
                if st.session_state.get("vdot_result"):
                    extra_context_parts.append(f"VDOT (berekend): {st.session_state['vdot_result']:.1f}")

            st.session_state["builder_intake"] = {
                "naam": naam,
                "athlete_key": athlete_key_selected,
                "athlete_name": selected_athlete_name,
                "client_type": "nieuw" if is_new else "bestaand",
                "doel": doel,
                "schema_einddatum": str(schema_einddatum) if schema_einddatum else "",
                "wedstrijddatum": str(wedstrijddatum) if wedstrijddatum else "",
                "weken": weken_val,
                "startdatum": str(startdatum),
                "trainingsdagen": trainingsdagen,
                "huidig_volume": huidig_volume,
                "zone_type": "tempo" if "tempo" in zone_type else "hartslag",
                "zones": zones,
                "andere_sporten": andere_sporten,
                "blessurehistorie": blessurehistorie,
                "extra": "\n".join(extra_context_parts),
                "uploaded_summary": "\n\n".join(filter(None, [labels_tekst] + uploaded_summary_parts)),
                "uploaded_images": uploaded_images,
                "referentie_prestatie": referentie_prestatie,
                "tijd_per_training": tijd_per_training,
                "langste_afstand": langste_afstand,
                "kwaliteitservaring": kwaliteitservaring,
                "herstelcapaciteit": herstelcapaciteit,
                "werkdruk": werkdruk,
                "loopondergrond": ", ".join(loopondergrond) if loopondergrond else "",
                "race_prioriteit": race_prioriteit,
                "tussenraces": tussenraces,
                "coach_notitie": coach_notitie,
                "wat_werkte": wat_werkte,
                "wat_niet_werkte": wat_niet_werkte,
                "op_tijd": op_tijd,
            }
            st.session_state["builder_plan"] = None
            st.session_state["builder_csv"] = None
            st.session_state["builder_step"] = 2
            st.session_state.pop("vdot_result", None)
            st.session_state.pop("vdot_zones_calc", None)
            _save_builder_state()
            st.rerun()

    # ===========================================================================
    # STAP 2 — PLAN GENEREREN & BEOORDELEN
    # ===========================================================================

    elif step == 2:
        intake = st.session_state.get("builder_intake", {})
        naam = intake.get("naam", "")

        st.markdown(f"<div class='bb-intake-label'>Stap 2 — Plan voor {naam}</div>", unsafe_allow_html=True)

        # Auto-genereren als we hier net zijn aangekomen
        if st.session_state.get("builder_plan") is None:
            with st.spinner("Plan genereren… (±15-30 seconden, automatische retry bij serverfouten)"):
                try:
                    plan = schema_builder.generate_plan(intake)
                    st.session_state["builder_plan"] = plan
                    st.session_state["builder_chat_history"] = []
                    _save_builder_state()
                    st.rerun()
                except Exception as e:
                    st.error(f"Fout bij genereren: {e}")
                    # Laat builder_plan op None staan zodat de retry-knop werkt

        # Toon retry/terug-knoppen als genereren mislukt is
        if st.session_state.get("builder_plan") is None:
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                if st.button("🔄 Opnieuw proberen", key="btn_retry_plan"):
                    st.rerun()
            with col_r2:
                if st.button("← Terug naar intake", key="btn_retry_back"):
                    _set_step(1)
            st.stop()

        if "builder_chat_history" not in st.session_state:
            st.session_state["builder_chat_history"] = []

        plan = st.session_state.get("builder_plan", "")

        col_plan, col_chat = st.columns([3, 2], gap="large")

        with col_plan:
            plan_edited = st.text_area(
                "Plan (pas aan waar nodig voor je verdergaat naar de CSV):",
                value=plan,
                height=520,
            )
            st.session_state["builder_plan"] = plan_edited

            col_back, col_regen, col_next = st.columns([1, 2, 2])
            with col_back:
                if st.button("← Intake", key="btn_plan_back"):
                    _set_step(1)
            with col_regen:
                if st.button("🔄 Opnieuw genereren", key="btn_regen"):
                    st.session_state["builder_plan"] = None
                    st.session_state["builder_chat_history"] = []
                    st.rerun()
            with col_next:
                if st.button("Genereer CSV →", type="primary", key="btn_to_csv",
                             disabled=not bool(st.session_state.get("builder_plan", "").strip())):
                    st.session_state["builder_csv"] = None
                    _set_step(3)

        with col_chat:
            st.markdown("**Sparren met AI**")
            st.caption("Stel vragen of vraag aanpassingen — de AI past het plan direct aan.")

            chat_history = st.session_state["builder_chat_history"]

            # Toon gespreksgeschiedenis
            chat_container = st.container(height=380)
            with chat_container:
                if not chat_history:
                    st.markdown(
                        "<div style='color:#4D4D4D;font-size:0.85rem;padding:0.5rem 0;'>"
                        "Nog geen gesprek. Stel een vraag hieronder.</div>",
                        unsafe_allow_html=True,
                    )
                for msg in chat_history:
                    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
                        # Strip plan markers from displayed text
                        display_text = msg["content"]
                        if "===PLAN UPDATE===" in display_text:
                            before = display_text.split("===PLAN UPDATE===")[0].strip()
                            display_text = before + "\n\n*[Plan bijgewerkt — zie links]*" if before else "*[Plan bijgewerkt — zie links]*"
                        st.markdown(display_text)

            # Chat input
            user_input = st.chat_input("Stel een vraag of vraag een aanpassing…", key="builder_chat_input")
            if user_input:
                chat_history.append({"role": "user", "content": user_input})
                st.session_state["builder_chat_history"] = chat_history

                with st.spinner("AI denkt na…"):
                    try:
                        ai_response = schema_builder.chat_about_plan(
                            plan=st.session_state["builder_plan"],
                            intake=intake,
                            history=chat_history,
                        )
                    except Exception as e:
                        ai_response = f"[Fout: {e}]"

                # Detect plan update
                if "===PLAN UPDATE===" in ai_response and "===EINDE PLAN===" in ai_response:
                    new_plan = ai_response.split("===PLAN UPDATE===")[1].split("===EINDE PLAN===")[0].strip()
                    if new_plan.strip():
                        st.session_state["builder_plan"] = new_plan
                        _save_builder_state()
                        st.session_state["_pending_plan_update"] = True
                elif "===PLAN UPDATE===" in ai_response and "===EINDE PLAN===" not in ai_response:
                    # Plan update gestart maar niet afgesloten — respons was te lang
                    partial = ai_response.split("===PLAN UPDATE===")[1].strip()
                    if partial:
                        st.session_state["builder_plan"] = partial
                        _save_builder_state()
                    st.session_state["_pending_plan_update"] = "truncated"

                chat_history.append({"role": "assistant", "content": ai_response})
                st.session_state["builder_chat_history"] = chat_history
                st.rerun()

            update_state = st.session_state.get("_pending_plan_update")
            if update_state == "truncated":
                st.warning("⚠️ Plan deels bijgewerkt — de respons was te lang en is afgeknipt. Vraag de AI om te verdergaan of de resterende weken toe te voegen.")
                if st.button("Wis melding", key="btn_dismiss_update"):
                    st.session_state.pop("_pending_plan_update", None)
                    st.rerun()
            elif update_state:
                st.success("✅ Plan bijgewerkt. Zie het plan links.")
                if st.button("Wis melding", key="btn_dismiss_update"):
                    st.session_state.pop("_pending_plan_update", None)
                    st.rerun()

            if chat_history:
                if st.button("🗑️ Gesprek wissen", key="btn_clear_chat"):
                    st.session_state["builder_chat_history"] = []
                    st.session_state.pop("_pending_plan_update", None)
                    st.rerun()

    # ===========================================================================
    # STAP 3 — CSV GENEREREN & DOWNLOADEN
    # ===========================================================================

    elif step == 3:
        intake = st.session_state.get("builder_intake", {})
        plan = st.session_state.get("builder_plan", "")
        naam = intake.get("naam", "")

        st.markdown(f"<div class='bb-intake-label'>Stap 3 — CSV voor {naam}</div>", unsafe_allow_html=True)

        # Auto-genereren als we hier net zijn aangekomen
        if st.session_state.get("builder_csv") is None:
            with st.spinner("CSV genereren voor het volledige schema… (±15-30 seconden)"):
                try:
                    csv_tekst = schema_builder.generate_csv(plan, intake)
                    st.session_state["builder_csv"] = csv_tekst
                    # Direct parsen
                    st.session_state["builder_workouts"] = schema_builder.parse_csv_text(csv_tekst)
                except Exception as e:
                    st.error(f"Fout bij CSV genereren: {e}")
                    st.stop()
            st.rerun()

        csv_tekst = st.session_state.get("builder_csv", "")
        workouts = st.session_state.get("builder_workouts", [])

        # Type icons
        _type_icon = {"Run": "🏃", "Bike": "🚴", "Swim": "🏊", "CrossTraining": "💪", "Rest": "😴", "Strength": "🏋️"}
        _dag_nl = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]

        # Selectie-state initialiseren
        if "builder_excluded" not in st.session_state:
            st.session_state["builder_excluded"] = set()

        # Toon preview tabel
        if workouts:
            n_excluded = len(st.session_state["builder_excluded"])
            n_included = len(workouts) - n_excluded
            c_info, c_sel_all, c_sel_none = st.columns([3, 1, 1])
            c_info.markdown(f"**{n_included} van {len(workouts)} trainingen geselecteerd** voor import.")
            with c_sel_all:
                if st.button("✅ Alles", key="btn_sel_all"):
                    st.session_state["builder_excluded"] = set()
                    st.rerun()
            with c_sel_none:
                if st.button("☐ Geen", key="btn_sel_none"):
                    st.session_state["builder_excluded"] = {i for i in range(len(workouts))}
                    st.rerun()

            # Groepeer per week — relatief t.o.v. startdatum (niet ISO-week)
            from collections import defaultdict as _dd
            from datetime import datetime as _dt
            _startdatum_str = intake.get("startdatum", "")
            try:
                _start_dt = _dt.strptime(_startdatum_str, "%Y-%m-%d")
                # Normaliseer naar maandag van de startweek
                _start_monday = _start_dt - timedelta(days=_start_dt.weekday())
            except Exception:
                _start_monday = None

            by_week = _dd(list)
            for idx, w in enumerate(workouts):
                try:
                    dt = _dt.strptime(w["date"], "%Y-%m-%d")
                    if _start_monday:
                        week_num = ((dt - _start_monday).days // 7) + 1
                        wk = f"week_{week_num:03d}"
                    else:
                        wk = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
                except Exception:
                    wk = "onbekend"
                by_week[wk].append((idx, w))

            for wk, week_items in sorted(by_week.items()):
                week_km = sum((w.get("planned_km") or 0) for _, w in week_items)
                km_str = f" · {week_km:.0f} km" if week_km else ""
                # Weeknummer afleiden voor weergave
                if wk.startswith("week_"):
                    disp_num = int(wk.split("_")[1])
                    # Datum­range van deze week berekenen voor weergave
                    if _start_monday:
                        _mon = _start_monday + timedelta(weeks=disp_num - 1)
                        _sun = _mon + timedelta(days=6)
                        _dag_kort = ["ma", "di", "wo", "do", "vr", "za", "zo"]
                        date_range = f" · {_mon.day}/{_mon.month} – {_sun.day}/{_sun.month}"
                    else:
                        date_range = ""
                    week_label = f"Week {disp_num}{date_range}{km_str}"
                else:
                    week_label = f"Week {wk[-2:]}{km_str}"
                st.markdown(f"<div class='bb-week-header'>{week_label}</div>", unsafe_allow_html=True)
                for idx, w in week_items:
                    included = idx not in st.session_state["builder_excluded"]
                    col_cb, col_dag, col_icon, col_name, col_km = st.columns([0.5, 0.8, 0.5, 5, 1.2])
                    with col_cb:
                        checked = st.checkbox("", value=included, key=f"cb_w_{idx}", label_visibility="collapsed")
                        if checked and idx in st.session_state["builder_excluded"]:
                            st.session_state["builder_excluded"].discard(idx)
                            st.rerun()
                        elif not checked and idx not in st.session_state["builder_excluded"]:
                            st.session_state["builder_excluded"].add(idx)
                            st.rerun()
                    try:
                        dt = _dt.strptime(w["date"], "%Y-%m-%d")
                        dag = _dag_nl[dt.weekday()]
                        datum = f"{dt.day}/{dt.month}"
                    except Exception:
                        dag, datum = "", w["date"]
                    col_dag.markdown(f"<span style='color:#4D4D4D;font-size:0.82rem'>{dag} {datum}</span>", unsafe_allow_html=True)
                    col_icon.markdown(_type_icon.get(w.get("activity_type", "Run"), "🏃"))
                    style = "color:#4D4D4D;" if included else "color:#aaa;text-decoration:line-through;"
                    col_name.markdown(f"<span style='{style}'>{w['name']}</span>", unsafe_allow_html=True)
                    km = round(w["planned_km"], 1) if w.get("planned_km") else ""
                    col_km.markdown(f"<span style='color:#4D4D4D;font-size:0.82rem'>{km} km</span>" if km else "", unsafe_allow_html=True)
        else:
            st.warning("Geen trainingen herkend in de CSV. Controleer de ruwe CSV hieronder.")

        # Ruwe CSV bekijken / bewerken
        with st.expander("Ruwe CSV bekijken / bewerken"):
            csv_edited = st.text_area(
                "CSV:",
                value=csv_tekst,
                height=300,
                key="builder_csv_edit",
            )
            if csv_edited != csv_tekst:
                if st.button("CSV opnieuw parsen", key="btn_reparse"):
                    st.session_state["builder_csv"] = csv_edited
                    st.session_state["builder_workouts"] = schema_builder.parse_csv_text(csv_edited)
                    st.rerun()

        # Download knop
        csv_bytes = csv_tekst.encode("utf-8")
        st.download_button(
            label="⬇️ Download CSV",
            data=csv_bytes,
            file_name=f"schema_{naam.lower().replace(' ','_')}_{date.today()}.csv",
            mime="text/csv",
            key="btn_download_csv",
        )

        col_back2, col_regen2, col_next2 = st.columns([1, 2, 2])
        with col_back2:
            if st.button("← Plan", key="btn_csv_back"):
                _set_step(2)
        with col_regen2:
            if st.button("🔄 Opnieuw genereren", key="btn_regen_csv"):
                st.session_state["builder_csv"] = None
                st.rerun()
        with col_next2:
            n_sel = len(workouts) - len(st.session_state.get("builder_excluded", set()))
            if workouts and n_sel > 0:
                if st.button(f"Importeer {n_sel} trainingen →", type="primary", key="btn_to_import"):
                    # Sla alleen geselecteerde workouts op voor import
                    excluded = st.session_state.get("builder_excluded", set())
                    st.session_state["builder_workouts_import"] = [w for i, w in enumerate(workouts) if i not in excluded]
                    _set_step(4)
            elif workouts:
                st.warning("Selecteer minimaal 1 training.")

    # ===========================================================================
    # STAP 4 — IMPORT IN FINALSURGE
    # ===========================================================================

    elif step == 4:
        intake = st.session_state.get("builder_intake", {})
        # Gebruik de gefilterde lijst (zonder uitgesloten trainingen)
        workouts = st.session_state.get("builder_workouts_import") or st.session_state.get("builder_workouts", [])
        naam = intake.get("naam", "")
        athlete_key = intake.get("athlete_key", "")
        athlete_name = intake.get("athlete_name", "")

        st.markdown("<div class='bb-intake-label'>Stap 4 — Import in FinalSurge</div>", unsafe_allow_html=True)

        st.markdown(f"""
        Je staat op het punt **{len(workouts)} trainingen** te importeren voor:

        **Atleet:** {athlete_name}
        **Schema:** {workouts[0]["date"] if workouts else "?"} t/m {workouts[-1]["date"] if workouts else "?"}
        """)

        st.warning(
            "⚠️ Dit plaatst alle trainingen direct in FinalSurge. "
            "Bestaande trainingen op dezelfde datums worden NIET overschreven — "
            "er worden nieuwe trainingen bijgevoegd. Controleer of de kalender leeg is."
        )

        fill_builder = st.toggle(
            "🔧 Vul ook de Workout Builder (zones/intervallen)",
            value=True,
            help="Laat AI automatisch de zone-stappen invullen op basis van de beschrijving. "
                 "Duurt iets langer maar geeft een mooier resultaat in FinalSurge.",
        )

        # Normaliseer zone_type: intake slaat "hartslag" of "tempo" op (NL), builder gebruikt "heart_rate" of "pace"
        _zt = intake.get("zone_type", "pace")
        zone_type = "heart_rate" if _zt in ("hartslag", "heart_rate") else "pace"

        # Debug: test met 1 workout
        with st.expander("🔍 Debug: test met 1 workout (toont ruwe API-respons)"):
            if workouts and st.button("Test eerste workout", key="btn_test_one"):
                w = workouts[0]
                try:
                    result = fs_client.save_workout(
                        user_key=athlete_key,
                        workout_date=w["date"],
                        name="[TEST] " + w["name"],
                        description=w.get("description", ""),
                        activity_type=w.get("activity_type", "Run"),
                        planned_distance_km=w.get("planned_km"),
                        planned_duration_min=w.get("planned_min"),
                    )
                    st.success("HTTP 200 ontvangen")
                    st.json(result)
                except Exception as e:
                    st.error(f"Fout: {e}")

        col_back3, col_import = st.columns([1, 2])
        with col_back3:
            if st.button("← CSV", key="btn_import_back"):
                _set_step(3)

        with col_import:
            label = f"✅ Importeer {len(workouts)} trainingen"
            if fill_builder:
                label += " + Workout Builder"
            if st.button(label, type="primary", key="btn_do_import"):
                progress_bar = st.progress(0)
                status_text = st.empty()

                errors = []
                ok_count = [0]

                def _cb(i, total, w_name):
                    progress_bar.progress((i + 1) / total)
                    extra = " + builder" if fill_builder else ""
                    status_text.markdown(f"Importeren{extra}: **{w_name}** ({i+1}/{total})")

                with st.spinner("Bezig met importeren…"):
                    try:
                        ok, errors, builder_errors = schema_builder.import_to_finalsurge(
                            athlete_key=athlete_key,
                            workouts=workouts,
                            zone_type=zone_type,
                            progress_callback=_cb,
                            fill_builder=fill_builder,
                            op_tijd=intake.get("op_tijd", False),
                        )
                        ok_count[0] = ok
                    except Exception as e:
                        st.error(f"Importfout: {e}")
                        st.stop()

                progress_bar.empty()
                status_text.empty()

                if errors:
                    st.warning(f"**{ok_count[0]} van {len(workouts)} trainingen geïmporteerd.** "
                               f"Mislukt: {len(errors)}")
                    with st.expander("Workout-fouten bekijken"):
                        for err in errors:
                            st.code(err)
                else:
                    st.success(
                        f"🎉 **{ok_count[0]} trainingen succesvol geïmporteerd!** "
                        f"Open FinalSurge om het schema van {athlete_name} te controleren."
                    )

                if fill_builder and builder_errors:
                    st.warning(f"⚠️ Workout Builder: {len(builder_errors)} van {ok_count[0]} niet gelukt.")
                    with st.expander("Builder-fouten bekijken (debug)"):
                        for err in builder_errors:
                            st.code(err)
                elif fill_builder and not builder_errors and ok_count[0] > 0:
                    st.info("🔧 Workout Builder succesvol ingevuld voor alle trainingen.")

                if not errors:
                    st.balloons()

                    # Reset voor nieuw schema
                    st.markdown("---")
                    if st.button("📋 Nieuw schema bouwen", type="primary"):
                        for k in ["builder_step", "builder_intake", "builder_plan",
                                  "builder_csv", "builder_workouts"]:
                            st.session_state.pop(k, None)
                        _set_step(1)
