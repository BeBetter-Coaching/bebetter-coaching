"""BeBetter Coaching — Coach App."""
# Deploy-marker: strippenkaart-module (schone herbouw forceren).

from __future__ import annotations

import streamlit as st
from datetime import date, timedelta
import fs_client
from fs_client import TokenNotFoundError
import ai_feedback
import schema_builder
import intake_store
import dossier
import admin
import builder_page
import documenten_page
import intake_page
import puls_page
import races_page
import schema_page
import belasting
import briefing
import rompslomp_client
import base64
import html as _html_mod
import io
import pandas as pd
import json
import os
from pathlib import Path


def _esc(s) -> str:
    """HTML-escape voor strings die in unsafe_allow_html-blokken belanden."""
    return _html_mod.escape(str(s or ""))


def _wa_number(raw: str) -> str:
    """Normaliseer een telefoonnummer naar internationaal formaat zonder '+' (voor wa.me).

    Nederlands standaard: 06... -> 316..., 0031... -> 31..., +31 -> 31. Levert
    alleen cijfers; lege of onbruikbare invoer geeft ''."""
    if not raw:
        return ""
    s = "".join(ch for ch in str(raw) if ch.isdigit() or ch == "+")
    if s.startswith("+"):
        digits = s[1:]
    elif s.startswith("00"):
        digits = s[2:]
    elif s.startswith("0"):
        digits = "31" + s[1:]  # nationaal NL-nummer -> landcode 31
    else:
        digits = s
    return "".join(ch for ch in digits if ch.isdigit())


def _wa_link(telefoon: str, tekst: str) -> str:
    """Bouw een wa.me-link die WhatsApp opent met nummer + voor-ingevuld bericht."""
    import urllib.parse
    nr = _wa_number(telefoon)
    if not nr:
        return ""
    return f"https://wa.me/{nr}?text={urllib.parse.quote(tekst)}"


def _parse_contacts(text: str) -> list[tuple[str, str]]:
    """Parse geplakte regels 'Naam, nummer' (komma/puntkomma/tab of nummer achteraan)."""
    import re
    out: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[\t;,]", line) if p.strip()]
        if len(parts) >= 2 and _wa_number(parts[-1]):
            naam, tel = " ".join(parts[:-1]), parts[-1]
        else:
            m = re.search(r"([+\d][\d\s\-]{6,})\s*$", line)
            if m and _wa_number(m.group(1)):
                naam, tel = line[:m.start()].strip(" ,;\t"), m.group(1).strip()
            else:
                naam, tel = line, ""
        if naam:
            out.append((naam, tel))
    return out


def _parse_vcard(raw: str) -> list[tuple[str, str]]:
    """Parse een .vcf-contactenbestand naar (naam, telefoon)-paren (eerste TEL per kaart)."""
    out: list[tuple[str, str]] = []
    naam, tel = None, None
    for line in (raw or "").splitlines():
        u = line.strip()
        key = u.split(":", 1)[0].upper()
        if key.startswith("BEGIN") and "VCARD" in u.upper():
            naam, tel = None, None
        elif key.startswith("FN") and ":" in u:
            naam = u.split(":", 1)[1].strip()
        elif key.startswith("TEL") and ":" in u and not tel:
            tel = u.split(":", 1)[1].strip()
        elif key.startswith("END") and "VCARD" in u.upper():
            if naam:
                out.append((naam, tel or ""))
    return out

# ---------------------------------------------------------------------------
# Persistentie — GitHub-backed via intake_store, werkt op alle apparaten.
# Session-gecachet zodat er niet bij elke rerun een GitHub-call gebeurt.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Wachtwoordbeveiliging
# ---------------------------------------------------------------------------

def _check_password() -> bool:
    """Vraag om wachtwoord; 'onthoud mij' = willekeurig token in de URL (bookmarkbaar).

    Het token is random (NIET afgeleid van het wachtwoord — de code van deze app
    is publiek) en alleen de SHA256-hash staat in de opslag. Intrekken kan via
    de adminmodule ("Log alle apparaten uit"); alle oude bookmarks zijn dan
    direct ongeldig.
    """
    import hashlib
    import hmac
    try:
        correct = st.secrets.get("APP_PASSWORD", "") or os.environ.get("APP_PASSWORD", "")
    except Exception:
        correct = os.environ.get("APP_PASSWORD", "")

    if not correct:
        return True

    if st.session_state.get("authenticated"):
        return True

    # Check URL-token (remember me = bookmark met ?k=... in URL).
    # Eén opslag-lookup per browsersessie; daarna draait alles op session_state.
    _qp = st.query_params.get("k", "")
    if _qp:
        _hash = hashlib.sha256(_qp.encode()).hexdigest()
        try:
            _geldig = intake_store.load_auth_tokens()
        except Exception:
            _geldig = {}
        if _hash in _geldig:
            st.session_state["authenticated"] = True
            return True

    # Loginscherm — col-verdeling ruim zodat het op mobiel past
    col1, col2, col3 = st.columns([0.3, 2.4, 0.3])
    with col2:
        try:
            _logo_login = _logo_b64("assets/logo_wit.png")
            st.markdown(f"""
            <div style="text-align:center; padding: 3rem 0 1.6rem 0;">
                <img src="data:image/png;base64,{_logo_login}" style="width:210px; max-width:70%;" />
                <p style="color:#8FA8CE; font-size:0.74rem; font-weight:700; letter-spacing:0.2em;
                          text-transform:uppercase; margin-top:0.9rem;">Coach Dashboard</p>
                <div style="height:3px; background:linear-gradient(90deg,#2876FB,#5EE6EB);
                            border-radius:2px; max-width:120px; margin:1.1rem auto 0 auto;"></div>
            </div>
            """, unsafe_allow_html=True)
        except Exception:
            st.markdown("## BeBetter Coaching")
        with st.form("bb_login", enter_to_submit=True):
            pw = st.text_input("Wachtwoord", type="password")
            onthoud = st.checkbox("Onthoud mij op dit apparaat", value=True)
            submitted = st.form_submit_button("Inloggen →", type="primary", use_container_width=True)
        if submitted:
            import time
            # Brute-force rem: oplopende vertraging na elke foute poging.
            # Kost legitieme gebruikers niets — alleen het foute-wachtwoord pad.
            _fails = st.session_state.get("_login_fails", 0)
            if hmac.compare_digest(pw.encode(), correct.encode()):
                st.session_state["authenticated"] = True
                st.session_state["_login_fails"] = 0
                if onthoud:
                    # Random token; alleen de hash wordt opgeslagen. Lukt het
                    # opslaan niet (opslag onbereikbaar), dan blijf je gewoon
                    # deze sessie ingelogd, alleen zonder bookmark-token.
                    import secrets as _pysecrets
                    from datetime import datetime as _dt
                    _nieuw = _pysecrets.token_urlsafe(24)
                    try:
                        _tokens = intake_store.load_auth_tokens()
                        _tokens[hashlib.sha256(_nieuw.encode()).hexdigest()] = {
                            "created": _dt.now().isoformat(timespec="seconds"),
                        }
                        # Maximaal 20 tokens bewaren (oudste eerst weg)
                        if len(_tokens) > 20:
                            _oudste = sorted(_tokens, key=lambda h: _tokens[h].get("created", ""))
                            for _h in _oudste[:len(_tokens) - 20]:
                                _tokens.pop(_h, None)
                        _ok, _ = intake_store.save_auth_tokens(_tokens)
                    except Exception:
                        _ok = False
                    if _ok:
                        st.query_params["k"] = _nieuw
                st.rerun()
            else:
                st.session_state["_login_fails"] = _fails + 1
                time.sleep(min(2 ** _fails, 30))  # 1s, 2s, 4s … max 30s
                st.error("Onjuist wachtwoord.")
    return False


def _load_skipped() -> dict:
    """Overgeslagen workout_keys met timestamp — gedeeld tussen beide coaches."""
    if "_skipped_cache" not in st.session_state:
        try:
            st.session_state["_skipped_cache"] = intake_store.load_skipped()
        except Exception:
            st.session_state["_skipped_cache"] = {}
    return st.session_state["_skipped_cache"]

def _save_skipped(skipped: dict):
    """Sla overgeslagen workouts op (cache + GitHub write-through)."""
    st.session_state["_skipped_cache"] = skipped
    try:
        intake_store.save_skipped(skipped)
    except Exception:
        pass

def _athlete_latest_ts(workout: dict) -> str:
    """Laatste tijdstempel van een atleet-bericht in de thread (of '')."""
    return max(
        (m.get("timestamp") or "" for m in workout.get("thread", [])
         if m.get("van") == "atleet"),
        default="",
    )

def _skip_snapshot(workout: dict) -> dict:
    """Momentopname van de atleet-input op het moment van overslaan."""
    return {
        "date": date.today().isoformat(),
        "athlete_ts": _athlete_latest_ts(workout),
        "notes": bool(workout.get("post_notes")),
        "felt": bool(workout.get("felt")),
        "effort": bool(workout.get("effort")),
    }

def _filter_skipped(workouts: list) -> list:
    """
    Filter overgeslagen workouts eruit — tenzij de atleet ná het overslaan
    NIEUWE input heeft gegeven (reactie, notitie, gevoel of RPE), dan komt de
    workout terug. We vergelijken tegen een momentopname van bij het overslaan,
    dus FinalSurge-tijdstempels onderling: geen datum- of tijdzone-gedoe.
    Gedeeld door de feedbackpagina én de dagstatus-telling.
    """
    _skipped = _load_skipped()
    if not _skipped:
        return workouts
    filtered = []
    _updated = False
    for w in workouts:
        wk_key = w.get("workout_key", "")
        snap = _skipped.get(wk_key)
        if snap is None:
            filtered.append(w)
            continue

        cur_ts = _athlete_latest_ts(w)
        if isinstance(snap, dict):
            nieuwe_input = (
                (cur_ts and cur_ts > (snap.get("athlete_ts") or ""))
                or (bool(w.get("post_notes")) and not snap.get("notes"))
                or (bool(w.get("felt")) and not snap.get("felt"))
                or (bool(w.get("effort")) and not snap.get("effort"))
            )
        else:
            # Oud formaat (kale datum-string): val terug op datum-vergelijking
            nieuwe_input = cur_ts[:10] > str(snap)[:10]

        if nieuwe_input:
            del _skipped[wk_key]
            _updated = True
            filtered.append(w)
    if _updated:
        _save_skipped(_skipped)
    return filtered

def _day_stats_mark_done(posted: bool):
    """Houd de dagstatus-tegels live bij na posten/overslaan van feedback."""
    _ds = st.session_state.get("day_stats")
    if _ds:
        _ds["feedback_pending"] = max(0, _ds.get("feedback_pending", 0) - 1)
        if posted:
            _ds["posted_today"] = _ds.get("posted_today", 0) + 1

def _auto_dossier_note(workout: dict):
    """
    Zet automatisch een 🤖-notitie in het dossier als het atleet-bericht
    een uitschieter is (blessure, dip, doorbraak). Best-effort: een fout
    mag het posten nooit blokkeren. Max één notitie per workout.
    """
    try:
        samenvatting = ai_feedback.check_dossier_signal(workout)
        if not samenvatting:
            return
        notes = dossier._notes()
        athlete_notes = notes.get(workout["athlete_key"], [])
        wk = workout["workout_key"]
        if any(n.get("bron") == wk for n in athlete_notes):
            return  # al genoteerd voor deze workout
        athlete_notes.insert(0, {
            "datum": date.today().isoformat(),
            "coach": "🤖 Auto",
            "tekst": f"{samenvatting} (uit: {workout.get('workout_name', 'training')}, "
                     f"{workout.get('workout_date', '')})",
            "bron": wk,
        })
        notes[workout["athlete_key"]] = athlete_notes
        dossier._save_notes(notes)
    except Exception:
        pass


def _coach_profiel(athlete_key: str) -> str:
    """Coach-geheugen van een atleet (sessie-gecachet, 1 opslag-load per sessie)."""
    if "_profielen_cache" not in st.session_state:
        try:
            st.session_state["_profielen_cache"] = intake_store.load_profielen()
        except Exception:
            st.session_state["_profielen_cache"] = {}
    return (st.session_state["_profielen_cache"].get(athlete_key) or {}).get("profiel", "")


def _leer_profiel(workout: dict, coach_tekst: str):
    """
    Werk het coach-geheugen van de atleet bij met deze geposte interactie.
    Draait op een achtergrond-thread zodat het posten nooit trager wordt;
    best-effort: een fout mag het posten nooit blokkeren.
    """
    athlete_key = workout.get("athlete_key")
    if not athlete_key or not (coach_tekst or "").strip():
        return
    athlete_tekst = "\n".join(
        t for t in [workout.get("post_notes", "")] + (workout.get("athlete_comments") or [])
        if t and t.strip()
    )
    workout_naam = workout.get("workout_name", "")

    def _werk():
        try:
            profielen = intake_store.load_profielen()
            huidig = profielen.get(athlete_key) or {}
            nieuw = ai_feedback.update_athlete_profiel(
                huidig.get("profiel", ""), athlete_tekst, coach_tekst, workout_naam)
            if nieuw and nieuw != huidig.get("profiel", ""):
                profielen[athlete_key] = {
                    "profiel": nieuw,
                    "bijgewerkt": date.today().isoformat(),
                    "n": huidig.get("n", 0) + 1,
                }
                intake_store.save_profielen(profielen)
        except Exception:
            pass

    import threading
    threading.Thread(target=_werk, daemon=True).start()


def _laps_chart(details: dict):
    """
    Compacte pace/HF-grafiek per km uit de lapdata van een workout.
    Pure weergave van al opgehaalde data — geen extra API- of AI-kosten.
    Geeft None terug als er te weinig bruikbare laps zijn.
    """
    acts = (details or {}).get("Activities") or []
    raw_laps = (acts[0].get("Laps") or []) if acts else []
    rows = []
    for i, lap in enumerate(raw_laps[:30], start=1):
        if not isinstance(lap, dict):
            continue
        pace_f = fs_client._pace_to_float(lap.get("pace_display"))
        if pace_f == float("inf") or pace_f <= 0 or pace_f > 15:
            continue
        rows.append({
            "km": i,
            "Pace": round(pace_f, 3),
            "pace_label": str(lap.get("pace_display") or ""),
            "HF": lap.get("hr_avg"),
        })
    if len(rows) < 2:
        return None

    import altair as alt
    import pandas as pd

    df = pd.DataFrame(rows)
    # Vega-expressie: 5.75 → "5:45" op de pace-as
    _pace_fmt = ("floor(datum.value) + ':' + "
                 "(min(59, round((datum.value % 1) * 60)) < 10 ? '0' : '') + "
                 "min(59, round((datum.value % 1) * 60))")
    base = alt.Chart(df).encode(
        x=alt.X("km:O", title=None, axis=alt.Axis(labelAngle=0)),
    )
    pace_line = base.mark_line(
        color="#5EE6EB", strokeWidth=2.5,
        point=alt.OverlayMarkDef(color="#5EE6EB", size=30),
    ).encode(
        y=alt.Y("Pace:Q",
                scale=alt.Scale(zero=False, reverse=True),  # omhoog = sneller
                axis=alt.Axis(title="pace", labelExpr=_pace_fmt, grid=False)),
        tooltip=[
            alt.Tooltip("km:O", title="km"),
            alt.Tooltip("pace_label:N", title="pace"),
            alt.Tooltip("HF:Q", title="HF"),
        ],
    )
    layers = [pace_line]
    if df["HF"].notna().any():
        hr_line = base.mark_line(
            color="#FAC775", strokeWidth=1.8, strokeDash=[5, 3],
            point=alt.OverlayMarkDef(color="#FAC775", size=24),
        ).encode(
            y=alt.Y("HF:Q", scale=alt.Scale(zero=False),
                    axis=alt.Axis(title="HF (bpm)", grid=False)),
            tooltip=[
                alt.Tooltip("km:O", title="km"),
                alt.Tooltip("pace_label:N", title="pace"),
                alt.Tooltip("HF:Q", title="HF"),
            ],
        )
        layers.append(hr_line)
    return (
        alt.layer(*layers)
        .resolve_scale(y="independent")
        .properties(height=170)
        .configure_view(strokeWidth=0)
    )

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
/* ════════════════════════════════════════════════════════════
   BeBetter Coaching — Kinetic Dark Design System
   Page bg     : #081830   Surface       : #0E2547
   Surface-2   : #10294E   Rand          : #1E3A66
   Navy        : #0B1F3A   Primair blauw : #2876FB
   Cyan accent : #5EE6EB   Tekst         : #EAF2FF
   Subtekst    : #8FA8CE   Gedimd        : #5B7396
   ════════════════════════════════════════════════════════════ */

@import url('https://fonts.googleapis.com/css2?family=Archivo+Black&family=Inter:wght@400;500;600;700;800;900&display=swap');

html, body, [data-testid="stAppViewContainer"], .stMarkdown, button, input, textarea, select {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}
.bb-disp { font-family: 'Archivo Black', 'Inter', sans-serif !important; }

/* ── App achtergrond: diep navy met gloed ── */
[data-testid="stAppViewContainer"] {
    background:
        radial-gradient(1100px 520px at 88% -8%, rgba(94,230,235,0.07), transparent 60%),
        radial-gradient(900px 460px at -8% 4%, rgba(40,118,251,0.10), transparent 55%),
        #081830;
}

/* ── Streamlit chrome verbergen ── */
#MainMenu, footer, [data-testid="stDecoration"] { display: none !important; }
header[data-testid="stHeader"] { background: transparent !important; }

.block-container { padding-top: 1.2rem !important; max-width: 1260px; }

/* ── Typografie ── */
h1, h2, h3 { color: #EAF2FF !important; font-weight: 800 !important; letter-spacing: -0.015em !important; }
[data-testid="stCaptionContainer"], .stCaption { color: #8FA8CE !important; }
[data-testid="stMarkdownContainer"] { color: #C9D8F0; }

/* ── Animaties ── */
@keyframes bbFadeUp {
    from { opacity: 0; transform: translateY(16px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes bbShimmer {
    0%   { background-position: -200% 0; }
    100% { background-position: 200% 0; }
}
@keyframes bbPulseGlow {
    0%, 100% { opacity: 0.45; }
    50%      { opacity: 1; }
}
@keyframes bbMarquee {
    from { transform: translateX(0); }
    to   { transform: translateX(-50%); }
}
@keyframes bbPopIn {
    0%   { opacity: 0; transform: scale(0.6); }
    70%  { transform: scale(1.08); }
    100% { opacity: 1; transform: scale(1); }
}

/* ══ HERO (home) ══ */
.bb-hero {
    position: relative;
    background: linear-gradient(130deg, #0B1F3A 0%, #0E2547 55%, #10294E 100%);
    border: 1px solid #1E3A66;
    border-radius: 22px;
    padding: 2.6rem 2.8rem 2.4rem 2.8rem;
    margin-bottom: 0;
    overflow: hidden;
    box-shadow: 0 24px 60px rgba(2,10,26,0.55);
    animation: bbFadeUp 0.5s ease both;
}
.bb-hero::before {
    content: "";
    position: absolute;
    top: -140px; right: -90px;
    width: 460px; height: 460px;
    background: radial-gradient(circle, rgba(94,230,235,0.14), transparent 65%);
    pointer-events: none;
    animation: bbPulseGlow 6s ease-in-out infinite;
}
.bb-hero::after {
    content: "";
    position: absolute;
    bottom: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, #2876FB 25%, #5EE6EB 50%, #2876FB 75%);
    background-size: 200% 100%;
    animation: bbShimmer 5s linear infinite;
}
.bb-hero-content { position: relative; z-index: 2; }
.bb-hero-kicker {
    color: #5EE6EB;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.30em;
    text-transform: uppercase;
    margin: 0 0 1rem 0;
}
.bb-hero-title {
    font-family: 'Archivo Black', sans-serif;
    color: #FFFFFF;
    font-size: 3.1rem;
    line-height: 0.98;
    letter-spacing: -0.01em;
    margin: 0;
    text-transform: uppercase;
}
.bb-hero-title-outline {
    font-family: 'Archivo Black', sans-serif;
    font-size: 3.1rem;
    line-height: 0.98;
    letter-spacing: -0.01em;
    margin: 0 0 0.3rem 0;
    text-transform: uppercase;
    color: transparent;
    -webkit-text-stroke: 1.6px #5EE6EB;
}
.bb-hero-sub {
    color: #8FA8CE;
    font-size: 0.95rem;
    font-weight: 500;
    margin: 0.9rem 0 0 0;
    max-width: 460px;
}
.bb-hero-watermark {
    position: absolute;
    right: 200px; top: 14px;
    font-family: 'Archivo Black', sans-serif;
    font-size: 9rem;
    line-height: 1;
    color: #10294E;
    user-select: none;
    pointer-events: none;
    z-index: 1;
}
.bb-hero-photo {
    position: absolute;
    right: 2.2rem; top: 50%;
    transform: translateY(-50%) rotate(3deg);
    width: 168px;
    border-radius: 14px;
    border: 1px solid #2C4A7E;
    box-shadow: 0 18px 40px rgba(2,10,26,0.6), -6px 6px 0 rgba(94,230,235,0.18);
    z-index: 2;
    transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.bb-hero-photo:hover { transform: translateY(-50%) rotate(0deg) scale(1.04); }

.bb-kpi-row { display: flex; gap: 0.9rem; margin-top: 1.5rem; flex-wrap: wrap; }
.bb-kpi {
    background: rgba(8,24,48,0.55);
    border: 1px solid #1E3A66;
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border-radius: 14px;
    padding: 0.85rem 1.5rem;
    min-width: 120px;
    transition: transform 0.2s ease, background 0.2s ease, border-color 0.2s ease;
}
.bb-kpi:hover {
    transform: translateY(-3px) scale(1.03);
    background: rgba(40,118,251,0.18);
    border-color: rgba(94,230,235,0.50);
}
.bb-kpi-value {
    font-family: 'Archivo Black', sans-serif;
    color: #FFFFFF; font-size: 1.55rem; margin: 0; line-height: 1.2;
    animation: bbPopIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 0.25s both;
}
.bb-kpi-label {
    color: #5B7396;
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin: 0;
}

/* ══ MARQUEE ══ */
.bb-marquee {
    overflow: hidden;
    border-top: 1px solid #16335E;
    border-bottom: 1px solid #16335E;
    background: #0B1F3A;
    border-radius: 0 0 14px 14px;
    margin: 0 0 1.8rem 0;
    padding: 0.55rem 0;
    animation: bbFadeUp 0.5s ease 0.1s both;
}
.bb-marquee-inner {
    display: flex;
    white-space: nowrap;
    animation: bbMarquee 22s linear infinite;
    will-change: transform;
    font-family: 'Archivo Black', sans-serif;
    font-size: 0.78rem;
    letter-spacing: 0.14em;
    color: #5EE6EB;
    text-transform: uppercase;
}
.bb-marquee:hover .bb-marquee-inner { animation-play-state: paused; }

/* ── Sectie-label ── */
.bb-section-label {
    font-size: 0.72rem;
    font-weight: 800;
    color: #5B7396;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    margin: 0.4rem 0 0.9rem 0;
}

/* ══ MODULE CARDS ══ */
.bb-card {
    position: relative;
    background: #0E2547;
    border: 1px solid #1E3A66;
    border-radius: 16px;
    padding: 1.6rem 1.5rem 1.4rem 1.5rem;
    min-height: 210px;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
    box-shadow: 0 8px 24px rgba(2,10,26,0.35);
    transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.22s ease, border-color 0.22s ease;
    overflow: hidden;
    animation: bbFadeUp 0.5s ease both;
}
[data-testid="stColumn"]:nth-of-type(1) .bb-card { animation-delay: 0.05s; }
[data-testid="stColumn"]:nth-of-type(2) .bb-card { animation-delay: 0.12s; }
[data-testid="stColumn"]:nth-of-type(3) .bb-card { animation-delay: 0.19s; }
[data-testid="stColumn"]:nth-of-type(4) .bb-card { animation-delay: 0.26s; }
.bb-card::before {
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, #2876FB 25%, #5EE6EB 50%, #2876FB 75%);
    background-size: 200% 100%;
    opacity: 0;
    transition: opacity 0.2s ease;
}
.bb-card:hover {
    transform: translateY(-6px);
    box-shadow: 0 6px 16px rgba(94,230,235,0.08), 0 26px 52px rgba(2,10,26,0.55);
    border-color: #5EE6EB;
}
.bb-card:hover::before { opacity: 1; animation: bbShimmer 2.5s linear infinite; }
.bb-card-icon {
    width: 48px; height: 48px;
    display: flex; align-items: center; justify-content: center;
    background: linear-gradient(135deg, #10294E 0%, #122E5C 100%);
    border: 1px solid #2C4A7E;
    border-radius: 13px;
    font-size: 1.4rem;
    line-height: 1;
    transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.25s ease, border-color 0.25s ease;
}
.bb-card:hover .bb-card-icon {
    transform: scale(1.12) rotate(-6deg);
    border-color: #5EE6EB;
    box-shadow: 0 6px 18px rgba(94,230,235,0.25);
}
.bb-card-title {
    font-family: 'Archivo Black', sans-serif;
    font-size: 0.95rem;
    color: #FFFFFF;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    margin: 0;
}
.bb-card-desc {
    font-size: 0.84rem;
    color: #8FA8CE;
    line-height: 1.6;
    flex-grow: 1;
    margin: 0;
}

/* ══ MODULE STARTLIJST ══ */
.bb-mrow {
    display: flex;
    align-items: center;
    gap: 1.4rem;
    background: #0E2547;
    border: 1px solid #1E3A66;
    border-radius: 14px;
    padding: 1.05rem 1.5rem;
    transition: transform 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), border-color 0.22s ease, box-shadow 0.22s ease;
    animation: bbFadeUp 0.45s ease both;
    overflow: hidden;
    position: relative;
}
.bb-mrow::before {
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 3px;
    background: linear-gradient(180deg, #2876FB, #5EE6EB);
    opacity: 0;
    transition: opacity 0.2s ease;
}
.bb-mrow:hover {
    transform: translateX(8px);
    border-color: #5EE6EB;
    box-shadow: -8px 0 24px rgba(94,230,235,0.10), 0 14px 34px rgba(2,10,26,0.5);
}
.bb-mrow:hover::before { opacity: 1; }
.bb-mrow-num {
    font-family: 'Archivo Black', sans-serif;
    font-size: 2.1rem;
    line-height: 1;
    color: transparent;
    -webkit-text-stroke: 1.3px #2C4A7E;
    flex-shrink: 0;
    width: 64px;
    transition: -webkit-text-stroke-color 0.2s ease;
}
.bb-mrow:hover .bb-mrow-num { -webkit-text-stroke-color: #5EE6EB; }
.bb-mrow-icon {
    font-size: 1.45rem;
    flex-shrink: 0;
    transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.bb-mrow:hover .bb-mrow-icon { transform: scale(1.25) rotate(-8deg); }
.bb-mrow-body { flex-grow: 1; min-width: 0; }
.bb-mrow-title {
    font-family: 'Archivo Black', sans-serif;
    font-size: 0.95rem;
    color: #FFFFFF;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin: 0 0 0.15rem 0;
}
.bb-mrow-desc {
    font-size: 0.82rem;
    color: #8FA8CE;
    line-height: 1.5;
    margin: 0;
}
.bb-mrow-tag {
    flex-shrink: 0;
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: #5EE6EB;
    background: rgba(94,230,235,0.08);
    border: 1px solid rgba(94,230,235,0.25);
    border-radius: 999px;
    padding: 0.28rem 0.85rem;
    white-space: nowrap;
}
.bb-mrow.featured {
    border-color: #2876FB;
    background: linear-gradient(100deg, #0E2547 55%, rgba(40,118,251,0.16) 100%);
}
.bb-mrow.featured .bb-mrow-num { -webkit-text-stroke-color: #2876FB; }
.bb-mrow-feat {
    font-family: 'Inter', sans-serif;
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #FFFFFF;
    background: linear-gradient(135deg, #2876FB, #1E56B8);
    border-radius: 999px;
    padding: 0.22rem 0.7rem;
    margin-left: 0.7rem;
    vertical-align: 2px;
    white-space: nowrap;
}

/* ══ DAGOVERZICHT ══ */
.bb-day-panel {
    background: #0E2547;
    border: 1px solid #1E3A66;
    border-radius: 16px;
    padding: 1.4rem 1.6rem 1.3rem 1.6rem;
    box-shadow: 0 8px 24px rgba(2,10,26,0.35);
    margin-bottom: 1.6rem;
    animation: bbFadeUp 0.5s ease 0.08s both;
}
.bb-stat-row { display: flex; gap: 0.9rem; flex-wrap: wrap; margin-top: 0.4rem; }
.bb-stat {
    flex: 1;
    min-width: 150px;
    background: #10294E;
    border: 1px solid #1E3A66;
    border-radius: 13px;
    padding: 0.95rem 1.2rem;
    transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}
.bb-stat:hover {
    transform: translateY(-3px);
    border-color: #2C4A7E;
    box-shadow: 0 10px 24px rgba(2,10,26,0.45);
}
.bb-stat.done { background: rgba(29,158,117,0.10); border-color: rgba(93,202,165,0.35); }
.bb-stat.done .bb-stat-value { color: #5DCAA5; }
.bb-stat.attention { background: rgba(239,159,39,0.08); border-color: rgba(250,199,117,0.35); }
.bb-stat.attention .bb-stat-value { color: #FAC775; }
.bb-stat-value {
    font-family: 'Archivo Black', sans-serif;
    font-size: 1.5rem; color: #FFFFFF; margin: 0; line-height: 1.2;
    animation: bbPopIn 0.6s cubic-bezier(0.34, 1.56, 0.64, 1) 0.3s both;
}
.bb-stat-label {
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #5B7396;
    margin: 0.1rem 0 0 0;
}
.bb-progress-track {
    height: 9px;
    background: #081830;
    border: 1px solid #16335E;
    border-radius: 6px;
    overflow: hidden;
    margin-top: 1rem;
}
.bb-progress-fill {
    height: 100%;
    background: linear-gradient(90deg, #2876FB 25%, #5EE6EB 50%, #2876FB 75%);
    background-size: 200% 100%;
    border-radius: 6px;
    transition: width 0.6s cubic-bezier(0.22, 1, 0.36, 1);
    animation: bbShimmer 3s linear infinite;
}
.bb-card-soon {
    display: inline-block;
    background: rgba(40,118,251,0.15);
    color: #5EE6EB;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    padding: 0.2rem 0.7rem;
    border-radius: 20px;
    border: 1px solid #2C4A7E;
}

/* ── Dividers ── */
.bb-divider { border: none; border-top: 1px solid #1E3A66; margin: 1.6rem 0; }

/* ── Tagline ── */
.bb-tagline {
    color: #5B7396;
    font-size: 0.78rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin: 0;
}

/* ══ KNOPPEN ══ */
div[data-testid="stButton"] button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    transition: all 0.15s ease !important;
}
div[data-testid="stButton"] button[kind="secondary"] {
    background: #0E2547 !important;
    border: 1.5px solid #1E3A66 !important;
    color: #EAF2FF !important;
    box-shadow: 0 1px 2px rgba(2,10,26,0.4) !important;
}
div[data-testid="stButton"] button[kind="secondary"]:hover {
    border-color: #5EE6EB !important;
    color: #5EE6EB !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 14px rgba(94,230,235,0.15) !important;
}
div[data-testid="stButton"] button[kind="primary"] {
    background: linear-gradient(135deg, #2876FB, #1E56B8) !important;
    color: #FFFFFF !important;
    border: none !important;
    font-weight: 700 !important;
    letter-spacing: 0.03em !important;
    box-shadow: 0 4px 16px rgba(40,118,251,0.35) !important;
}
div[data-testid="stButton"] button[kind="primary"]:hover {
    background: linear-gradient(135deg, #3D85FF, #2876FB) !important;
    box-shadow: 0 6px 22px rgba(94,230,235,0.30) !important;
    transform: translateY(-1px);
}

/* ══ INVOERVELDEN ══ */
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input {
    background: #0E2547 !important;
    color: #EAF2FF !important;
    border-radius: 10px !important;
}
[data-testid="stTextInput"] > div > div,
[data-testid="stTextArea"] > div > div,
[data-testid="stNumberInput"] > div > div,
[data-testid="stDateInput"] > div > div {
    background: #0E2547 !important;
    border-radius: 10px !important;
    border-color: #1E3A66 !important;
}
div[data-baseweb="select"] > div {
    background: #0E2547 !important;
    border-radius: 10px !important;
    border-color: #1E3A66 !important;
}

/* ══ EXPANDERS ══ */
[data-testid="stExpander"] {
    background: #0E2547;
    border: 1px solid #1E3A66 !important;
    border-radius: 12px !important;
    box-shadow: 0 1px 6px rgba(2,10,26,0.35);
    overflow: hidden;
}
[data-testid="stExpander"] summary { font-weight: 600; color: #EAF2FF !important; }

/* ══ ALERTS ══ */
[data-testid="stAlert"] {
    border-radius: 12px !important;
    border: none !important;
    box-shadow: 0 1px 6px rgba(2,10,26,0.3);
}

/* ══ PROGRESS BAR ══ */
[data-testid="stProgress"] > div > div > div {
    background: linear-gradient(90deg, #2876FB, #5EE6EB) !important;
    border-radius: 6px;
}

/* ── Module header balk ── */
.module-header {
    display: flex;
    align-items: center;
    gap: 0.9rem;
    padding-bottom: 0.7rem;
    margin-bottom: 1.2rem;
}
.module-header-icon {
    width: 44px; height: 44px;
    display: flex; align-items: center; justify-content: center;
    background: linear-gradient(135deg, #10294E 0%, #122E5C 100%);
    border: 1px solid #2C4A7E;
    border-radius: 12px;
    font-size: 1.25rem;
    line-height: 1;
    flex-shrink: 0;
}
.module-header-title {
    font-family: 'Archivo Black', sans-serif;
    font-size: 1.3rem;
    color: #FFFFFF;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0B1F3A !important;
    border-right: 1px solid #1E3A66 !important;
}

/* ── Gradient accent lijn ── */
.bb-hero-accent {
    height: 4px;
    background: linear-gradient(90deg, #2876FB 25%, #5EE6EB 50%, #2876FB 75%);
    background-size: 200% 100%;
    border-radius: 2px;
    margin-bottom: 1.6rem;
    animation: bbShimmer 5s linear infinite;
}

/* ── Schema bouwen — stap-indicator ── */
.bb-step-row { display: flex; gap: 0.6rem; margin-bottom: 1.6rem; }
.bb-step-pill {
    flex: 1;
    text-align: center;
    padding: 0.55rem 0.5rem;
    border-radius: 10px;
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    background: #0E2547;
    color: #5B7396;
    border: 1.5px solid #1E3A66;
    box-shadow: 0 1px 2px rgba(2,10,26,0.3);
    transition: all 0.15s ease;
}
.bb-step-pill.active {
    background: linear-gradient(135deg, #2876FB, #1E56B8);
    color: #FFFFFF;
    border-color: transparent;
    font-weight: 800;
    box-shadow: 0 4px 16px rgba(40,118,251,0.35);
}
.bb-step-pill.done {
    background: rgba(40,118,251,0.14);
    color: #5EE6EB;
    border-color: #2C4A7E;
}

/* ── Intake sectiekaart ── */
.bb-intake-section {
    background: #0E2547;
    border: 1px solid #1E3A66;
    border-radius: 14px;
    padding: 1.2rem 1.4rem 1rem 1.4rem;
    margin-bottom: 1rem;
    box-shadow: 0 1px 6px rgba(2,10,26,0.3);
}
.bb-intake-label {
    font-size: 0.74rem;
    font-weight: 800;
    color: #5EE6EB;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin-bottom: 0.6rem;
}

/* ── Week-groep in CSV preview ── */
.bb-week-header {
    font-size: 0.76rem;
    font-weight: 700;
    color: #EAF2FF;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    background: linear-gradient(90deg, #10294E, #0E2547);
    border-radius: 8px;
    padding: 0.35rem 0.8rem;
    margin: 0.7rem 0 0.25rem 0;
    border-left: 3px solid #5EE6EB;
}
.bb-training-row {
    display: flex;
    align-items: center;
    padding: 0.3rem 0;
    border-bottom: 1px solid #122E5C;
    gap: 0.5rem;
    font-size: 0.88rem;
}

/* ══ DAGSTATUS-TEGELS (klikbare knoppen) ══ */
.st-key-bb_day_tiles [data-testid="stButton"] button[kind="secondary"] {
    background: #10294E !important;
    border: 1.5px solid #1E3A66 !important;
    border-radius: 13px !important;
    padding: 0.85rem 1.1rem !important;
    min-height: 96px;
    text-align: left !important;
    justify-content: flex-start !important;
    box-shadow: none !important;
    transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease !important;
}
.st-key-bb_day_tiles [data-testid="stButton"] button[kind="secondary"]:hover {
    transform: translateY(-3px);
    border-color: #5EE6EB !important;
    box-shadow: 0 10px 24px rgba(2,10,26,0.45) !important;
}
.st-key-bb_day_tiles [data-testid="stButton"] button p {
    color: #5B7396 !important;
    font-size: 0.66rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    line-height: 1.5;
    margin: 0;
    text-align: left;
}
.st-key-bb_day_tiles [data-testid="stButton"] button p strong {
    display: block;
    font-family: 'Archivo Black', sans-serif !important;
    font-size: 1.5rem !important;
    font-weight: 400 !important;
    color: #FFFFFF;
    letter-spacing: 0;
    line-height: 1.25;
    margin-bottom: 0.15rem;
}

/* ══ RESPONSIVE ══ */
@media (max-width: 900px) {
    .block-container { padding-left: 1rem !important; padding-right: 1rem !important; }
    .bb-hero { padding: 1.8rem 1.5rem 1.6rem 1.5rem; }
    .bb-hero-title { font-size: 2.2rem; }
    .bb-hero-title-outline { font-size: 2.2rem; }
    .bb-hero-watermark { display: none !important; }
    .bb-kpi { padding: 0.65rem 1rem; min-width: 90px; }
    .bb-kpi-value { font-size: 1.25rem; }
    .bb-mrow { padding: 0.85rem 1rem; gap: 0.9rem; }
    .bb-mrow-num { font-size: 1.7rem; width: 48px; }
}

@media (max-width: 640px) {
    .block-container {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
        padding-top: 0.5rem !important;
    }
    .bb-hero {
        padding: 1.2rem 1rem 1.1rem 1rem;
        border-radius: 14px;
    }
    .bb-hero-photo { display: none !important; }
    .bb-hero-title { font-size: 1.65rem; }
    .bb-hero-title-outline { font-size: 1.65rem; }
    .bb-hero-kicker { font-size: 0.60rem; letter-spacing: 0.16em; }
    .bb-hero-sub { font-size: 0.82rem; }
    .bb-kpi-row { gap: 0.4rem; margin-top: 1rem; }
    .bb-kpi { padding: 0.5rem 0.7rem; min-width: 70px; border-radius: 10px; }
    .bb-kpi-value { font-size: 1.05rem; }
    .bb-kpi-label { font-size: 0.56rem; letter-spacing: 0.1em; }
    .bb-marquee-inner { font-size: 0.65rem; letter-spacing: 0.1em; }
    .bb-mrow { padding: 0.7rem 0.8rem; gap: 0.5rem; border-radius: 10px; }
    .bb-mrow-num { display: none !important; }
    .bb-mrow-desc { display: none !important; }
    .bb-mrow-tag { display: none !important; }
    .bb-mrow-feat { font-size: 0.52rem; padding: 0.18rem 0.5rem; }
    .bb-mrow-icon { font-size: 1.1rem; }
    .bb-mrow-title { font-size: 0.82rem; letter-spacing: 0.04em; }
    .bb-stat { min-width: 110px; padding: 0.75rem 0.9rem; }
    .bb-stat-value { font-size: 1.2rem; }
    .st-key-bb_day_tiles [data-testid="stButton"] button[kind="secondary"] {
        min-height: 60px;
        padding: 0.55rem 0.8rem !important;
    }
    .st-key-bb_day_tiles [data-testid="stButton"] button p strong { font-size: 1.15rem !important; }
    .bb-day-panel { padding: 0.9rem 0.85rem; border-radius: 12px; }
    .bb-section-label { font-size: 0.64rem; }
    .module-header-title { font-size: 1.1rem; }
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Hulpfunctie: logo als base64 voor HTML embedding
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _logo_b64(path: str) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode()


@st.cache_data(show_spinner=False)
def _team_photo_b64() -> str | None:
    """Teamfoto voor de hero — verkleind en gecachet. None als er geen foto is."""
    for naam in ("team.jpg", "team.jpeg", "team.png"):
        p = Path("assets") / naam
        if p.exists():
            try:
                from PIL import Image
                img = Image.open(p)
                img = img.convert("RGB")
                if img.width > 1600:
                    img = img.resize((1600, int(img.height * 1600 / img.width)))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=80)
                return base64.b64encode(buf.getvalue()).decode()
            except Exception:
                return None
    return None


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
        st.image("assets/logo_wit.png", width=220)

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


# ── Publieke self-service intake (vóór de login) ──
# Klant opent ?intake=<token>; zonder geldige token gebeurt er niets en valt
# de app gewoon terug op de normale coach-login.
_intake_q = st.query_params.get("intake", "")
if _intake_q:
    import intake_form
    if intake_form.token_geldig(_intake_q):
        intake_form.render_publieke_intake(st.query_params.get("resume", ""))
        st.stop()

if not _check_password():
    st.stop()

if not is_authenticated():
    setup_screen()
    st.stop()

# Herstel builder-state na herstart (vóór atleten laden)
builder_page._load_builder_state()

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

# Geldige pagina's — voor het veilig herstellen uit de URL.
_VALID_PAGES = {
    "home", "admin", "puls", "feedback_groups", "feedback", "backfill_builder",
    "intake", "races", "schema", "atleten", "dossier", "builder", "strippenkaart",
    "documenten",
}

# Herstel de pagina uit de URL (?page=...). Bij sessieverlies (mobiel dat de
# verbinding herstelt, tabblad dat sliep) gaat session_state verloren en zou de
# app terugvallen naar 'home'. De URL-parameter overleeft dat wél — net als de
# login-token (?k=) — dus daaruit herstellen we de laatst actieve pagina.
if "page" not in st.session_state:
    _qp_page = st.query_params.get("page", "")
    st.session_state["page"] = _qp_page if _qp_page in _VALID_PAGES else "home"

# Verborgen ingang admin (alleen Jip): ?admin=1 in de URL → adminroute.
# Remco ziet hier niets van; er staat geen knop in het hoofdmenu.
if st.query_params.get("admin") == "1":
    st.session_state["page"] = "admin"
    st.query_params.pop("admin", None)

page = st.session_state["page"]

# Houd de URL in sync met de actieve pagina, zodat een reconnect (zie boven)
# op de juiste plek terugkomt. 'home' laten we schoon (geen ?page in de URL).
try:
    if page == "home":
        st.query_params.pop("page", None)
    elif st.query_params.get("page") != page:
        st.query_params["page"] = page
except Exception:
    pass


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
            <span class="module-header-icon">{icon}</span>
            <p class="module-header-title">{title}</p>
        </div>
        """, unsafe_allow_html=True)
    with col_logo:
        st.image("assets/logo_wit.png", width=130)
    st.markdown("")


# ===========================================================================
# PAGINA: HOME — Landingspagina
# ===========================================================================

if page == "home":
    # ── Hero banner met teamfoto + KPI's ──
    logo_wit_b64 = _logo_b64("assets/logo_wit.png")
    n_athletes = sum(len(m) for m in athletes_by_group.values())
    n_groups = len(athletes_by_group)

    # Modules — één bron van waarheid (ook voor de KPI in de hero, geen hardcoded getal).
    _MOD = {
        "feedback": ("📋", "Feedback", "Atleten reageren op hun training — de AI schrijft een concept in jouw stijl. Jij keurt goed en post met één klik.", "Dagelijks", "btn_feedback", "feedback_groups", "primary", True),
        "schema": ("📅", "Schema-verloop", "De bewaking: wiens schema loopt af? Daarna begint de cyclus opnieuw bij schema bouwen.", "Wekelijks", "btn_schema", "schema", "secondary", False),
        "puls": ("🩺", "Teampuls", "Belasting-signalen (wie loopt uit de pas) en de weekbriefing — het team-overzicht, met onderbouwing per atleet.", "Signalen", "btn_puls", "puls", "secondary", False),
        "races": ("🏁", "Races", "Het hoogtepunt — aankomende races in één overzicht, met raceplan en persoonlijke succeswens.", "Racedag", "btn_races", "races", "secondary", False),
        "admin": ("🗃️", "Administratie", "Financiële cockpit: KOR-bewaking, omzet per categorie, facturen en klantadministratie. Afgeschermd met pincode.", "Beheer", "btn_admin", "admin", "secondary", False),
        "intake": ("📝", "Intake", "Hier begint alles — leg doel, niveau en achtergrond van een nieuwe atleet vast. Wordt automatisch ingeladen bij het bouwen.", "Nieuwe atleet", "btn_intake", "intake", "secondary", False),
        "builder": ("🔨", "Schema bouwen", "Genereer een trainingsplan op doel, niveau en datum. Direct importeren in FinalSurge, inclusief workout builder.", "Planning", "btn_builder", "builder", "secondary", False),
        "atleten": ("👤", "Atleet-dossiers", "Alles per atleet op één plek: intake, notities, compliance, trends, races en zones.", "Overzicht", "btn_atleten", "atleten", "secondary", False),
        "documenten": ("📄", "Documenten", "Genereer een strak, persoonlijk document (handleiding, wedstrijd, voeding, kracht) voor een atleet. De AI schrijft de persoonlijke stukjes in de huisstijl.", "Per atleet", "btn_documenten", "documenten", "secondary", False),
        "backfill": ("🔧", "Builder bijvullen & zones", "Vul de workout builder voor bestaande trainingen, of zet een heel schema om tussen tempo en hartslag.", "Onderhoud", "btn_backfill", "backfill_builder", "secondary", False),
        "strippenkaart": ("🎟️", "Strippenkaart", "Losse-trainingen-klanten: tel per training een strip af en zie wie er nog hoeveel over heeft, met een kant-en-klaar appje.", "Per training", "btn_strip", "strippenkaart", "secondary", False),
    }
    n_modules = len(_MOD)
    _maanden = ["januari", "februari", "maart", "april", "mei", "juni",
                "juli", "augustus", "september", "oktober", "november", "december"]
    _dagen = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
    _vandaag = date.today()
    datum_str = f"{_dagen[_vandaag.weekday()]} {_vandaag.day} {_maanden[_vandaag.month - 1]} {_vandaag.year}"

    from datetime import datetime as _dt
    _uur = _dt.now().hour
    groet = "Goedemorgen" if _uur < 12 else ("Goedemiddag" if _uur < 18 else "Goedenavond")

    # Teamfoto als ingelijst accent rechts in de hero
    _team_b64 = _team_photo_b64()
    foto_html = (
        f'<img class="bb-hero-photo" src="data:image/jpeg;base64,{_team_b64}" />'
        if _team_b64 else ""
    )

    st.markdown(f"""
    <div class="bb-hero">
      <div class="bb-hero-watermark">{n_athletes}</div>
      {foto_html}
      <div class="bb-hero-content">
        <img src="data:image/png;base64,{logo_wit_b64}" style="height:44px; margin-bottom:1.2rem;" />
        <p class="bb-hero-kicker">{groet} · Coach Dashboard · {datum_str}</p>
        <p class="bb-hero-title">Zij lopen.</p>
        <p class="bb-hero-title-outline">Jij stuurt.</p>
        <p class="bb-hero-sub">Direct verbonden met FinalSurge — AI-ondersteund coachen voor elke atleet.</p>
        <div class="bb-kpi-row">
            <div class="bb-kpi">
                <p class="bb-kpi-value">{n_athletes}</p>
                <p class="bb-kpi-label">Atleten</p>
            </div>
            <div class="bb-kpi">
                <p class="bb-kpi-value">{n_groups}</p>
                <p class="bb-kpi-label">Groepen</p>
            </div>
            <div class="bb-kpi">
                <p class="bb-kpi-value">{n_modules}</p>
                <p class="bb-kpi-label">Modules</p>
            </div>
        </div>
      </div>
    </div>
    <div class="bb-marquee">
      <div class="bb-marquee-inner">
        <span style="padding-right:48px">PR's worden hier gemaakt&nbsp;&nbsp;✦&nbsp;&nbsp;Elke atleet gezien&nbsp;&nbsp;✦&nbsp;&nbsp;Feedback met impact&nbsp;&nbsp;✦&nbsp;&nbsp;Data + gevoel&nbsp;&nbsp;✦&nbsp;&nbsp;Schema op maat&nbsp;&nbsp;✦&nbsp;&nbsp;</span>
        <span style="padding-right:48px">PR's worden hier gemaakt&nbsp;&nbsp;✦&nbsp;&nbsp;Elke atleet gezien&nbsp;&nbsp;✦&nbsp;&nbsp;Feedback met impact&nbsp;&nbsp;✦&nbsp;&nbsp;Data + gevoel&nbsp;&nbsp;✦&nbsp;&nbsp;Schema op maat&nbsp;&nbsp;✦&nbsp;&nbsp;</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Dagoverzicht — voortgangsmonitor ──
    st.markdown('<p class="bb-section-label">Dagoverzicht</p>', unsafe_allow_html=True)

    def _fetch_day_stats():
        from concurrent.futures import ThreadPoolExecutor as _TPE
        if "schema_on_hold" not in st.session_state:
            st.session_state["schema_on_hold"] = intake_store.load_on_hold()
        _oh_keys = set(st.session_state["schema_on_hold"].keys())
        with _TPE(max_workers=4) as _pool:
            # "Los schema"-groep krijgt geen feedback → niet meetellen
            _fb_fut = _pool.submit(
                fs_client.get_workouts_needing_feedback,
                7, None, False, True,  # 7 dagen terug; include_planned_no_notes=True:
                {"los schema"}, True,  # uitgevoerde geplande trainingen altijd meetellen
            )
            _races_fut = _pool.submit(fs_client.get_upcoming_races, 7)
            _alerts_fut = _pool.submit(
                fs_client.get_compliance_alerts,
                7, _oh_keys, {"los schema"},
            )
            _schema_fut = _pool.submit(
                fs_client.get_schema_end_dates, 60, _oh_keys,
            )
            _fb, _fb_stats = _fb_fut.result()
            _fb = _filter_skipped(_fb)  # zelfde filter als de feedbackpagina
            _races = _races_fut.result()
            try:
                _alerts = _alerts_fut.result()
            except Exception:
                _alerts = []
            try:
                _schema_rows = _schema_fut.result()
            except Exception:
                _schema_rows = None
        # Schema-overzicht meteen klaarzetten voor de schema-pagina
        if _schema_rows is not None:
            st.session_state["schema_data"] = _schema_rows
        # Actie nodig = geen actief schema (None), verlopen (<0) of ≤7 dagen.
        # Bewuste uitzonderingen horen op on hold — die zijn al uitgefilterd.
        _schema_urgent = sum(
            1 for r in (_schema_rows or [])
            if r["days_left"] is None or r["days_left"] <= 7
        )
        from datetime import datetime as _dtn
        st.session_state["day_stats"] = {
            "feedback_pending": len(_fb),
            "posted_today": _fb_stats.get("posted_today", 0),
            # Alleen races tellen waarvoor nog GEEN wens (coach-comment) is gegeven
            "races_coming": sum(1 for r in _races if not r.get("wish_given")),
            # Namenlijst voor de weekbriefing
            "races_list": [f"{r['athlete_name']} ({r.get('workout_name', 'race')}, "
                           f"{(r.get('workout_date') or '')[:10]})" for r in _races],
            "compliance_alerts": _alerts,
            "schema_urgent": _schema_urgent,
            "loaded_at": date.today().isoformat(),
            "loaded_ts": _dtn.now().strftime("%H:%M"),
        }

    # Auto-laden bij eerste bezoek deze sessie of bij een nieuwe dag
    # (één poging — bij een fout blijft de Ververs-knop als handmatige weg)
    _ds_oud = st.session_state.get("day_stats")
    if _ds_oud is not None and _ds_oud.get("loaded_at") != date.today().isoformat():
        st.session_state["day_stats"] = None
        st.session_state.pop("_day_stats_attempted", None)
    if (
        st.session_state.get("day_stats") is None
        and not st.session_state.get("_day_stats_attempted")
    ):
        st.session_state["_day_stats_attempted"] = True
        with st.spinner("Dagstatus ophalen…"):
            try:
                _fetch_day_stats()
            except Exception:
                pass

    # Belasting-stand: homepage LEEST alleen de opgeslagen dagstand (1 goedkope
    # opslag-load per sessie). De berekening zelf draait pas bij het openen van
    # de Teampuls-pagina — de homepage mag daar geen laadtijd voor betalen.
    if "belasting_data" not in st.session_state:
        st.session_state["belasting_data"] = belasting.laad_stand()

    day_stats = st.session_state.get("day_stats")
    # Gepost vandaag: FinalSurge-telling (alle coaches/apparaten, bij laatste
    # ververs) of de eigen sessie-teller als die hoger is (posts ná de ververs)
    _api_posted = (day_stats or {}).get("posted_today", 0)
    n_posted_today = max(_api_posted, len(st.session_state.get("session_feedback_log", [])))

    col_day, col_refresh = st.columns([5, 1])
    with col_refresh:
        if st.button("🔄 Ververs", key="btn_day_refresh", use_container_width=True):
            with st.spinner("Dagstatus ophalen…"):
                try:
                    _fetch_day_stats()
                    st.rerun()
                except Exception as e:
                    st.error(f"Fout: {e}")

    with col_day:
        if day_stats:
            fb_pending = day_stats.get("feedback_pending", 0)
            races_coming = day_stats.get("races_coming", 0)
            total_tasks = fb_pending + n_posted_today
            pct = int(n_posted_today / total_tasks * 100) if total_tasks else 100
            fb_cls = "done" if fb_pending == 0 else "attention"
            race_cls = "done" if races_coming == 0 else ""

            # Schema-tegel: urgent = afloopt binnen 7 dagen of al verlopen
            _schema_urgent = day_stats.get("schema_urgent", 0)
            schema_val = str(_schema_urgent)
            schema_cls = "done" if _schema_urgent == 0 else "attention"

            # Afgehandelde afhakers (gedeeld tussen coaches) — 7 dagen gedempt,
            # daarna komt de atleet vanzelf terug als het patroon aanhoudt
            if "_alerts_handled" not in st.session_state:
                try:
                    st.session_state["_alerts_handled"] = intake_store.load_alerts_handled()
                except Exception:
                    st.session_state["_alerts_handled"] = {}
            _handled = st.session_state["_alerts_handled"]
            _vandaag_iso = date.today().isoformat()
            _handled_cutoff = (date.today() - timedelta(days=7)).isoformat()

            def _afhaker_gedempt(a):
                rec = _handled.get(a["user_key"])
                if not rec:
                    return False
                # Severity-aware (gelijk aan Home): erger geworden → weer tonen.
                # Backward-compat: oud record zonder n_low → geen escalatie-check.
                if "n_low" in rec and a.get("n_low", 0) > rec.get("n_low", 0):
                    return False
                tot = rec.get("tot")
                if tot:                                  # nieuw record: echt dempvenster (3/7/14)
                    return _vandaag_iso < tot
                return rec.get("datum", "") >= _handled_cutoff   # oud record: datum + 7 dagen

            _alerts = [a for a in day_stats.get("compliance_alerts", []) if not _afhaker_gedempt(a)]
            _alert_cls = "done" if not _alerts else "attention"

            # Tegels zijn klikbare knoppen — kleur per status via dynamische CSS
            _TILE_COLORS = {"done": "#5DCAA5", "attention": "#FAC775", "": "#FFFFFF"}
            # Belasting-tegel: leest alleen de opgeslagen stand (geen berekening)
            _bel_stand = st.session_state.get("belasting_data") or {}
            _bel_zicht = belasting.zichtbare_resultaten(_bel_stand)
            _bel_hoog = sum(1 for r in _bel_zicht if r.get("ernst") == "hoog")
            _bel_vers = _bel_stand.get("datum") == date.today().isoformat()
            _puls_cls = "attention" if _bel_zicht else ("done" if _bel_vers else "")

            _tile_states = {
                "tile_fb": fb_cls,
                "tile_posted": "done",
                "tile_alerts": _alert_cls,
                "tile_schema": schema_cls,
                "tile_races": race_cls,
                "tile_puls": _puls_cls,
            }
            _tile_css = "\n".join(
                f".st-key-{_k} [data-testid='stButton'] button[kind='secondary'] p strong "
                f"{{ color: {_TILE_COLORS.get(_v, '#FFFFFF')} !important; }}"
                + (
                    f"\n.st-key-{_k} [data-testid='stButton'] button[kind='secondary'] "
                    f"{{ border-color: {_TILE_COLORS[_v]}66 !important; }}"
                    if _v else ""
                )
                for _k, _v in _tile_states.items()
            )
            st.markdown(f"<style>{_tile_css}</style>", unsafe_allow_html=True)

            def _open_feedback_alle():
                # Wis een eventueel achtergebleven groeps-/atleetfilter zodat de
                # module exact de volledige lijst toont die deze tegel telt
                for _k in list(st.session_state.keys()):
                    if _k.startswith("chk_"):
                        st.session_state[_k] = False
                st.session_state.pop("feedback_group_filter", None)
                st.session_state.pop("workouts", None)
                st.session_state.pop("last_filter", None)
                go_to("feedback")

            with st.container(key="bb_day_tiles"):
                t1, t2, t3, t4, t5, t6 = st.columns(6)
                with t1:
                    if st.button(f"**{fb_pending}**  \nWachten op feedback",
                                 key="tile_fb", use_container_width=True):
                        _open_feedback_alle()
                with t2:
                    if st.button(f"**{n_posted_today}**  \nVandaag gepost",
                                 key="tile_posted", use_container_width=True):
                        _open_feedback_alle()
                with t3:
                    if st.button(f"**{len(_alerts)}**  \nAfhakers deze week",
                                 key="tile_alerts", use_container_width=True):
                        st.session_state["_alerts_open"] = True
                        st.rerun()
                with t4:
                    if st.button(f"**{schema_val}**  \nSchema-actie nodig",
                                 key="tile_schema", use_container_width=True,
                                 help="Geen actief schema, verlopen, of loopt binnen 7 dagen af — "
                                      "verlengen of on hold zetten"):
                        go_to("schema")
                with t5:
                    if st.button(f"**{races_coming}**  \nRaces komende 7 dgn",
                                 key="tile_races", use_container_width=True):
                        go_to("races")
                with t6:
                    _puls_val = str(len(_bel_zicht)) if _bel_vers or _bel_zicht else "—"
                    if st.button(f"**{_puls_val}**  \nBelasting-signalen",
                                 key="tile_puls", use_container_width=True,
                                 help="Wie loopt uit de pas qua volume, gevoel of klachten. "
                                      "Klik voor de Teampuls met onderbouwing per atleet."):
                        go_to("puls")

            st.markdown(f"""
            <div class="bb-day-panel" style="padding:0.9rem 1.6rem 1rem 1.6rem; margin-top:0.3rem;">
                <div class="bb-progress-track" style="margin-top:0;">
                    <div class="bb-progress-fill" style="width:{pct}%"></div>
                </div>
                <p style="font-size:0.72rem; color:#8FA8CE; margin:0.45rem 0 0 0;">
                    Dagvoortgang feedback: <b>{pct}%</b> &nbsp;·&nbsp; status van {day_stats.get('loaded_at','')} {day_stats.get('loaded_ts','')} — ververs voor de actuele stand
                </p>
            </div>
            """, unsafe_allow_html=True)

            if _alerts:
                _alerts_open = st.session_state.pop("_alerts_open", False)
                with st.expander(
                    f"⚠️ {len(_alerts)} atleten met gemiste of halve trainingen (laatste 7 dagen)",
                    expanded=_alerts_open,
                ):
                    st.caption("≥2 geplande trainingen gemist of voor minder dan de helft uitgevoerd. "
                               "Trainingen van vandaag tellen niet mee. "
                               "**Afgehandeld** verbergt de atleet 7 dagen uit deze lijst — voor beide coaches.")
                    for _al in _alerts:
                        c_al, c_done_al, c_btn_al = st.columns([3.4, 1.1, 1.1], vertical_alignment="center")
                        with c_al:
                            st.markdown(
                                f"**{_al['name']}** ({_al['group']}) — "
                                f"{_al['n_low']} van {_al['n_planned']} geplande trainingen gemist/half"
                            )
                        with c_done_al:
                            if st.button("✓ Afgehandeld", key=f"al_done_{_al['user_key']}",
                                         use_container_width=True,
                                         help="Bijv. contact gehad of bewust rustig aan — 7 dagen niet meer tonen"):
                                _handled[_al["user_key"]] = {
                                    "datum": date.today().isoformat(),
                                    "naam": _al["name"],
                                }
                                # Oude vermeldingen (>30 dagen) opruimen
                                _prune = (date.today() - timedelta(days=30)).isoformat()
                                for _hk in list(_handled.keys()):
                                    if (_handled[_hk] or {}).get("datum", "") < _prune:
                                        del _handled[_hk]
                                st.session_state["_alerts_handled"] = _handled
                                try:
                                    intake_store.save_alerts_handled(_handled)
                                except Exception:
                                    pass
                                st.rerun()
                        with c_btn_al:
                            if st.button("Dossier →", key=f"al_dos_{_al['user_key']}", use_container_width=True):
                                st.session_state["dossier_user_key"] = _al["user_key"]
                                go_to("dossier")
        else:
            st.markdown("""
            <div class="bb-day-panel">
                <p style="color:#8FA8CE; font-size:0.9rem; margin:0;">
                    Dagstatus kon niet automatisch geladen worden — klik op <b>🔄 Ververs</b> om het
                    opnieuw te proberen.
                </p>
            </div>
            """, unsafe_allow_html=True)

    # ── Atleet-zoekbalk: typ een naam → direct naar het dossier ──
    _zoek_opts = {a["name"]: a["user_key"] for a in _all_athletes}
    _ZOEK_PLACEHOLDER = "🔍 Zoek een atleet en spring naar het dossier…"

    def _ga_naar_dossier():
        _naam = st.session_state.get("home_atleet_zoek")
        if _naam in _zoek_opts:
            st.session_state["dossier_user_key"] = _zoek_opts[_naam]
            st.session_state["home_atleet_zoek"] = _ZOEK_PLACEHOLDER  # reset de zoekbalk
            st.session_state["page"] = "dossier"

    st.selectbox("Zoek atleet", options=[_ZOEK_PLACEHOLDER] + sorted(_zoek_opts),
                 key="home_atleet_zoek", label_visibility="collapsed",
                 on_change=_ga_naar_dossier)

    # Gegroepeerd op ritme: coaching-werk vooraan (dagelijks → wekelijks → per
    # atleet), beheer & onderhoud achteraan. Schema-verloop en schema bouwen staan
    # bewust naast elkaar (schema loopt af → bouw het volgende).
    _groepen = [
        ("Dagelijks", ["feedback"]),
        ("Wekelijks", ["schema", "builder", "puls", "races"]),
        ("Per atleet", ["intake", "atleten", "documenten"]),
        ("Beheer & onderhoud", ["admin", "strippenkaart", "backfill"]),
    ]

    def _render_module_rij(_key, _i):
        _icon, _titel, _desc, _tag, _btn_key, _page, _btn_type, _featured = _MOD[_key]
        c_row, c_btn = st.columns([8.6, 1.4], vertical_alignment="center")
        with c_row:
            _feat_cls = " featured" if _featured else ""
            _feat_badge = '<span class="bb-mrow-feat">★ Meest gebruikt</span>' if _featured else ""
            st.markdown(f"""
            <div class="bb-mrow{_feat_cls}" style="animation-delay:{0.05 + _i * 0.05:.2f}s">
                <span class="bb-mrow-icon">{_icon}</span>
                <div class="bb-mrow-body">
                    <p class="bb-mrow-title">{_titel}{_feat_badge}</p>
                    <p class="bb-mrow-desc">{_desc}</p>
                </div>
                <span class="bb-mrow-tag">{_tag}</span>
            </div>
            """, unsafe_allow_html=True)
        with c_btn:
            if st.button("Open →", type=_btn_type, key=_btn_key, use_container_width=True):
                go_to(_page)

    _rij_i = 0
    for _grp_titel, _grp_keys in _groepen:
        st.markdown(f'<p class="bb-section-label">{_grp_titel}</p>', unsafe_allow_html=True)
        for _mk in _grp_keys:
            _render_module_rij(_mk, _rij_i)
            _rij_i += 1

    # Footer
    st.markdown("""
    <hr class="bb-divider">
    <div style="text-align:center; padding-bottom: 1rem;">
        <p style="color:#8FA8CE; font-size:0.72rem; font-weight:600; letter-spacing:0.16em; text-transform:uppercase; margin-bottom:0.8rem;">
            Iedere training telt &nbsp;·&nbsp; Iedere loper telt
        </p>
        <div style="height:3px; background:linear-gradient(90deg,#2876FB,#5EE6EB);
                    border-radius:2px; max-width:160px; margin:0 auto;"></div>
    </div>
    """, unsafe_allow_html=True)

    # Verborgen admin-ingang: het BeBetter-logo onderaan is een afbeelding
    # die alleen ná drie tikken de pincode-gate opent. Ziet eruit als pure
    # branding; één nieuwsgierige klik doet niets.
    _sp1, _brand_col, _sp2 = st.columns([5, 2, 5])
    with _brand_col:
        st.markdown(f"""
        <style>
        div.st-key-bb_brand_stamp button {{
            background: url('data:image/png;base64,{logo_wit_b64}') center/contain no-repeat !important;
            border: none !important; box-shadow: none !important;
            height: 30px; width: 100%; color: transparent !important;
            opacity: 0.35; transition: opacity 0.25s ease;
        }}
        div.st-key-bb_brand_stamp button:hover {{ opacity: 0.7; }}
        div.st-key-bb_brand_stamp button p {{ color: transparent !important; }}
        </style>
        """, unsafe_allow_html=True)
        if st.button("BeBetter", key="bb_brand_stamp", help=""):
            _tik = st.session_state.get("_brand_tik", 0) + 1
            st.session_state["_brand_tik"] = _tik
            if _tik >= 3:
                st.session_state["_brand_tik"] = 0
                go_to("admin")
            else:
                st.rerun()


# ===========================================================================
# PAGINA: STRIPPENKAART (module 10) — losse trainingen aftellen per klant
# ===========================================================================

elif page == "strippenkaart":
    module_header("Strippenkaart", "🎟️")

    if "strippenkaarten" not in st.session_state:
        st.session_state["strippenkaarten"] = intake_store.load_strippenkaarten()
    _kaarten = st.session_state["strippenkaarten"]

    if not intake_store.is_cloud_backed():
        st.caption("⚠️ Geen GitHub-opslag actief — wijzigingen staan alleen lokaal op dit apparaat.")

    # ── Nieuwe strippenkaart toevoegen ──
    with st.expander("➕ Nieuwe strippenkaart", expanded=not _kaarten):
        c1, c2 = st.columns([3, 2])
        with c1:
            _nieuw_naam = st.text_input("Naam", key="strip_nieuw_naam", placeholder="bijv. Lisa Jansen")
        with c2:
            _nieuw_tel = st.text_input("Telefoon (voor WhatsApp)", key="strip_nieuw_tel",
                                       placeholder="bijv. 06 12 34 56 78")
        c3, c4 = st.columns([3, 1.4])
        with c3:
            _nieuw_aantal = st.radio("Aantal trainingen", [10, 20], horizontal=True, key="strip_nieuw_aantal")
        with c4:
            st.markdown("<div style='margin-top:1.7rem'></div>", unsafe_allow_html=True)
            if st.button("Toevoegen", type="primary", key="btn_strip_add"):
                _n = (_nieuw_naam or "").strip()
                if not _n:
                    st.warning("Vul een naam in.")
                elif _n in _kaarten:
                    st.warning("Er bestaat al een strippenkaart met deze naam.")
                else:
                    _kaarten[_n] = {
                        "totaal": int(_nieuw_aantal),
                        "gebruikt": 0,
                        "historie": [],
                        "aangemaakt": date.today().isoformat(),
                        "telefoon": (_nieuw_tel or "").strip(),
                    }
                    _ok, _err = intake_store.save_strippenkaarten(_kaarten)
                    if _ok:
                        st.session_state["strippenkaarten"] = _kaarten
                        st.rerun()
                    else:
                        st.error(f"Opslaan mislukt: {_err}")

    # ── Meerdere tegelijk toevoegen (uit je contacten) ──
    with st.expander("⬆️ Meerdere tegelijk toevoegen (uit je contacten)"):
        st.caption("Plak hieronder je klanten als 'Naam, nummer' per regel, of upload een "
                   ".vcf-contactenbestand uit je telefoon. Je ziet eerst een controle-overzicht "
                   "voordat er iets wordt toegevoegd, zodat je niet per ongeluk al je contacten importeert.")
        _bulk_aantal = st.radio("Aantal trainingen voor nieuwe kaarten", [10, 20],
                                horizontal=True, key="strip_bulk_aantal")
        _bulk_txt = st.text_area("Plak namen en nummers", key="strip_bulk_txt",
                                 placeholder="Lisa Jansen, 06 12 34 56 78\nPiet de Vries, 0612345679")
        _bulk_vcf = st.file_uploader("of upload contacten (.vcf)", type=["vcf"], key="strip_bulk_vcf")

        if st.button("🔍 Controleer", key="strip_bulk_check"):
            _rows = _parse_contacts(_bulk_txt)
            if _bulk_vcf is not None:
                try:
                    _rows += _parse_vcard(_bulk_vcf.getvalue().decode("utf-8", "ignore"))
                except Exception as _e:
                    st.error(f"Kon het .vcf-bestand niet lezen: {_e}")
            st.session_state["strip_bulk_preview"] = _rows

        _preview = st.session_state.get("strip_bulk_preview")
        if _preview is not None:
            _nieuw = [(n, t) for n, t in _preview if n not in _kaarten]
            _bestaat = [(n, t) for n, t in _preview if n in _kaarten]
            _zonder_nr = [n for n, t in _nieuw if not _wa_number(t)]
            if not _preview:
                st.warning("Niks gevonden om te importeren. Controleer de invoer.")
            else:
                st.write(f"**{len(_nieuw)}** nieuwe kaarten, **{len(_bestaat)}** namen bestaan al.")
                if _zonder_nr:
                    st.caption(f"⚠️ {len(_zonder_nr)} zonder bruikbaar nummer (kaart wordt wel aangemaakt, "
                               f"nummer kun je later invullen): {', '.join(_zonder_nr[:8])}"
                               + ("…" if len(_zonder_nr) > 8 else ""))
                import pandas as _pd
                st.dataframe(_pd.DataFrame(_nieuw or _preview, columns=["Naam", "Telefoon"]),
                             hide_index=True, use_container_width=True)
                a1, a2 = st.columns(2)
                with a1:
                    if st.button(f"✓ {len(_nieuw)} toevoegen", type="primary", key="strip_bulk_do",
                                 disabled=not _nieuw):
                        for _n, _t in _nieuw:
                            _kaarten[_n] = {
                                "totaal": int(_bulk_aantal), "gebruikt": 0, "historie": [],
                                "aangemaakt": date.today().isoformat(), "telefoon": (_t or "").strip(),
                            }
                        # bestaande kaarten zonder nummer alsnog aanvullen
                        _aangevuld = 0
                        for _n, _t in _bestaat:
                            if _t and not _kaarten[_n].get("telefoon"):
                                _kaarten[_n]["telefoon"] = _t.strip()
                                _aangevuld += 1
                        _ok, _err = intake_store.save_strippenkaarten(_kaarten)
                        if _ok:
                            st.session_state["strippenkaarten"] = _kaarten
                            st.session_state.pop("strip_bulk_preview", None)
                            st.success(f"{len(_nieuw)} toegevoegd"
                                       + (f", {_aangevuld} nummer aangevuld" if _aangevuld else "") + ".")
                            st.rerun()
                        else:
                            st.error(f"Opslaan mislukt: {_err}")
                with a2:
                    if st.button("Annuleer", key="strip_bulk_cancel"):
                        st.session_state.pop("strip_bulk_preview", None)
                        st.rerun()

    if not _kaarten:
        st.info("Nog geen strippenkaarten. Voeg hierboven de eerste toe.")
    else:
        for _naam in sorted(_kaarten.keys()):
            _k = _kaarten[_naam]
            _tot = int(_k.get("totaal", 10))
            _gebr = int(_k.get("gebruikt", 0))
            _rest = max(0, _tot - _gebr)
            with st.container(border=True):
                cc1, cc2 = st.columns([3, 2], vertical_alignment="center")
                with cc1:
                    st.markdown(f"**{_naam}**")
                    st.progress((_gebr / _tot) if _tot else 0.0, text=f"{_rest} van {_tot} over")
                    if _k.get("historie"):
                        st.caption("Laatst afgeboekt: " + _k["historie"][-1])
                with cc2:
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("✓ Strip afboeken", key=f"strip_af_{_naam}",
                                     type="primary", disabled=_rest <= 0):
                            _k["gebruikt"] = _gebr + 1
                            _k.setdefault("historie", []).append(date.today().isoformat())
                            _ok, _err = intake_store.save_strippenkaarten(_kaarten)
                            if _ok:
                                st.session_state["strippenkaarten"] = _kaarten
                                st.session_state["strip_laatste_bericht"] = (
                                    _naam, max(0, _tot - _k["gebruikt"]), _tot,
                                )
                                st.rerun()
                            else:
                                st.error(f"Opslaan mislukt: {_err}")
                    with b2:
                        if st.button("↩ Terug", key=f"strip_terug_{_naam}", disabled=_gebr <= 0):
                            _k["gebruikt"] = max(0, _gebr - 1)
                            if _k.get("historie"):
                                _k["historie"].pop()
                            _ok, _err = intake_store.save_strippenkaarten(_kaarten)
                            if _ok:
                                st.session_state["strippenkaarten"] = _kaarten
                                st.rerun()

                # Bericht na afboeken — één tik: opent WhatsApp met nummer + tekst ingevuld
                _lb = st.session_state.get("strip_laatste_bericht")
                if _lb and _lb[0] == _naam:
                    _bn, _br, _bt = _lb
                    _voornaam = _bn.split()[0] if _bn else _bn
                    if _br <= 0:
                        _msg = (f"Hoi {_voornaam}, je hebt zojuist je laatste training van de "
                                f"strippenkaart afgetekend, de kaart is nu vol. Wil je een "
                                f"nieuwe? Laat maar weten!")
                    else:
                        _msg = (f"Hoi {_voornaam}, top getraind! Je hebt zojuist een training "
                                f"afgeboekt en hebt nog {_br} van je {_bt} trainingen over. "
                                f"Tot de volgende!")
                    _wa = _wa_link(_k.get("telefoon", ""), _msg)
                    if _wa:
                        st.link_button("📲 Stuur via WhatsApp", _wa, type="primary")
                        st.caption("Opent WhatsApp met het nummer en bericht al ingevuld, jij tikt op verzenden.")
                    else:
                        st.caption("📩 Bericht voor de atleet — kopieer voor WhatsApp "
                                   "(voeg een telefoonnummer toe voor de verzendknop):")
                        st.code(_msg, language=None)

                with st.expander("Telefoon / verwijderen"):
                    _tel_key = f"strip_tel_{_naam}"
                    _nieuw_tel = st.text_input("Telefoon (voor WhatsApp)", value=_k.get("telefoon", ""),
                                               key=_tel_key, placeholder="bijv. 06 12 34 56 78")
                    if st.button("Telefoon opslaan", key=f"strip_tel_save_{_naam}"):
                        _k["telefoon"] = (_nieuw_tel or "").strip()
                        _ok, _err = intake_store.save_strippenkaarten(_kaarten)
                        if _ok:
                            st.session_state["strippenkaarten"] = _kaarten
                            st.rerun()
                        else:
                            st.error(f"Opslaan mislukt: {_err}")
                    if st.button(f"🗑️ Strippenkaart van {_naam} verwijderen", key=f"strip_del_{_naam}"):
                        _kaarten.pop(_naam, None)
                        _ok, _err = intake_store.save_strippenkaarten(_kaarten)
                        if _ok:
                            st.session_state["strippenkaarten"] = _kaarten
                            st.session_state.pop("strip_laatste_bericht", None)
                            st.rerun()
                        else:
                            st.error(f"Verwijderen mislukt: {_err}")


# ===========================================================================
# PAGINA: ADMINISTRATIE (module 8, verborgen — alleen Jip)
# ===========================================================================

elif page == "admin":
    module_header("Administratie", "🗃️")

    # Pincode-gate — los van het app-wachtwoord, alleen voor Jip
    try:
        _admin_pin = st.secrets.get("ADMIN_PIN", "") or os.environ.get("ADMIN_PIN", "")
    except Exception:
        _admin_pin = os.environ.get("ADMIN_PIN", "")
    _admin_pin = (_admin_pin or "").strip()
    if not _admin_pin:
        # Bewust GEEN standaardpincode: de code van deze app staat in een
        # publieke repo, dus een fallback-pin zou publiek bekend zijn.
        st.error("De adminmodule is vergrendeld: er is geen ADMIN_PIN ingesteld. "
                 "Voeg de secret ADMIN_PIN toe in Streamlit Cloud → Settings → Secrets.")
        st.stop()

    if not st.session_state.get("_admin_unlocked"):
        st.markdown("Deze module is afgeschermd.")
        with st.form("admin_pin_form"):
            _pin_in = st.text_input("Pincode", type="password")
            if st.form_submit_button("Ontgrendelen", type="primary"):
                import hmac as _hmac
                if _hmac.compare_digest(_pin_in.strip(), _admin_pin):
                    st.session_state["_admin_unlocked"] = True
                    st.rerun()
                else:
                    import time as _t
                    _t.sleep(1)
                    st.error("Onjuiste pincode.")
        st.stop()

    with st.expander("🔐 Beveiliging — ingelogde apparaten"):
        st.caption("Maakt alle 'onthoud mij'-bookmarks in één keer ongeldig. Iedereen "
                   "(ook jijzelf en Remco) moet daarna één keer opnieuw inloggen met het "
                   "wachtwoord en krijgt dan een verse bookmark-link.")
        try:
            _n_tokens = len(intake_store.load_auth_tokens())
            st.caption(f"Actieve onthoud-tokens: **{_n_tokens}**")
        except Exception:
            pass
        if st.button("Log alle apparaten uit", key="adm_revoke_tokens"):
            _ok, _err = intake_store.save_auth_tokens({})
            if _ok:
                st.query_params.pop("k", None)
                st.success("Alle onthoud-tokens ingetrokken.")
            else:
                st.error(f"Intrekken mislukt: {_err}")

    # Ontwikkelaar-debug: verplaatst vanaf de homepage naar achter de admin-pincode.
    with st.expander("🔧 Debug: coach_athlete_key controle", expanded=False):
        st.caption("Controleer of de juiste coach_athlete_key wordt gebruikt voor het resetten van notificaties.")
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

    admin.render_admin(athletes_by_group)


# ===========================================================================
# PAGINA: FEEDBACK — GROEPEN TUSSENMENU
# ===========================================================================
# PAGINA: TEAMPULS (module 9) — belasting-signalen + weekbriefing
# ===========================================================================

elif page == "puls":
    module_header("Teampuls", "🩺")
    puls_page.render(_all_athletes)


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
                    <p class="bb-card-title">{_esc(grp)}</p>
                    <p class="bb-card-desc">{_esc(desc)}</p>
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
        st.image("assets/logo_wit.png", width=160)
        st.markdown("<hr class='bb-divider'>", unsafe_allow_html=True)
        st.header("Filters")

        if st.button("← Terug naar groepen", key="btn_back_groups"):
            go_to("feedback_groups")

        days_back = st.slider("Terugkijkperiode (dagen)", 1, 21, 7,
                              help="Hoe ver terug workouts worden opgehaald. Ruimer = ook iets oudere "
                                   "trainingen waar de atleet later nog op reageerde.")

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
            value=True,
            help="Afspraak: een uitgevoerde geplande training wordt altijd getoond, "
                 "ook als de atleet er geen notitie bij schreef. Uitzetten verbergt ze.",
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
        with st.expander("🔍 Waarom mist iemand?"):
            st.caption("Kies een atleet en zie per training waarom die wel of niet in de "
                       "feedbacklijst komt.")
            _diag_all = sorted(
                [a for members in athletes_by_group.values() for a in members],
                key=lambda x: x["name"],
            )
            _diag_naam = st.selectbox("Atleet", [a["name"] for a in _diag_all], key="diag_athlete")
            _diag_dagen = st.slider("Kijk terug (dagen)", 3, 21, 10, key="diag_days")
            if st.button("Analyseer", key="diag_run"):
                _diag_key = next(a["user_key"] for a in _diag_all if a["name"] == _diag_naam)
                with st.spinner("Analyseren…"):
                    try:
                        st.session_state["diag_result"] = fs_client.diagnose_athlete_feedback(
                            _diag_key, days_back=_diag_dagen)
                    except Exception as e:
                        st.session_state["diag_result"] = [{"fout": str(e)}]
            _diag_res = st.session_state.get("diag_result")
            if _diag_res is not None:
                if not _diag_res:
                    st.info("Geen trainingen in deze periode.")
                else:
                    for _r in _diag_res:
                        if "fout" in _r:
                            st.error(_r["fout"])
                            continue
                        st.markdown(f"**{_r['datum']} · {_r['naam']}** — {_r['beslissing']}")
                        st.caption(
                            f"{_r['activiteiten']} · gepland: {'ja' if _r.get('gepland') else 'nee'} · "
                            f"voltooid: {'ja' if _r['voltooid'] else 'nee'} · "
                            f"gevoel: {_r['gevoel'] or '—'} · RPE: {_r['rpe'] or '—'} · "
                            f"notitie: {'ja' if _r['post_notes'] else 'nee'} · comments: {_r['comments']}"
                        )
                        st.caption(f"↳ {_r['reden']}")
                        st.markdown("")

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
                    # Los schema krijgt geen feedback — alleen tonen als een
                    # atleet expliciet in de zijbalk is aangevinkt
                    exclude_groups=None if athlete_filter else {"los schema"},
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

    # Filter overgeslagen workouts — zelfde filter als de dagstatus-tegel
    workouts = _filter_skipped(workouts)

    # Synchroniseer de homepage-tegel met de live module-telling, maar alleen
    # als de filters exact overeenkomen met waarmee de tegel zelf telt:
    # geen atleetfilter, days_back=7, data-only uit, geplande-zonder-notitie aan.
    if (
        athlete_filter is None
        and not include_data_only
        and include_planned_no_notes
        and days_back == 7
    ):
        _live_open = sum(
            1 for w in workouts
            if not st.session_state.get(f"posted_{w['workout_key']}")
        )
        _ds = st.session_state.get("day_stats")
        if _ds is not None:
            _ds["feedback_pending"] = _live_open

    if not workouts:
        st.success("✅ Geen openstaande workouts gevonden voor de huidige filters.")
        if st.button("Opnieuw laden"):
            del st.session_state["workouts"]
            st.rerun()
    else:
        pending = [i for i, w in enumerate(workouts) if not st.session_state.get(f"posted_{w['workout_key']}")]
        _n_done = len(workouts) - len(pending)

        c_info, c_verberg = st.columns([3, 2], vertical_alignment="center")
        with c_info:
            st.markdown(f"**{len(pending)} open** · {_n_done} afgehandeld deze sessie")
        with c_verberg:
            verberg_gedaan = st.toggle(
                "Verberg afgehandelde", value=True, key="fb_verberg_gedaan",
                help="Geposte en overgeslagen kaarten verdwijnen — de volgende atleet staat direct bovenaan",
            )
        if workouts:
            st.progress(_n_done / len(workouts))

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
                                workouts[i]["coach_profiel"] = _coach_profiel(workouts[i]["athlete_key"])
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

        @st.fragment
        def _feedback_card(i: int, workout: dict):
            """Eén feedback-kaart — herrendert geïsoleerd, niet de hele pagina."""
            wk = workout["workout_key"]
            posted = st.session_state.get(f"posted_{wk}", False)
            is_data_only = workout.get("data_only", False)
            is_planned_no_notes = workout.get("planned_no_notes", False)

            with st.container():
                col_h, col_dos, col_s = st.columns([4.4, 0.8, 0.8])
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
                with col_dos:
                    if st.button("👤 Dossier", key=f"dos_fb_{i}",
                                 help="Open het atleet-dossier (intake, notities, trends)"):
                        st.session_state["dossier_user_key"] = workout["athlete_key"]
                        go_to("dossier")
                with col_s:
                    if posted:
                        st.success("Gepost")

                if posted:
                    st.markdown("---")
                    return

                col_left, col_right = st.columns(2)

                with col_left:
                    felt = workout.get("felt")
                    effort = workout.get("effort")
                    if felt or effort:
                        _FELT_ICONS = {"1": "😄 Geweldig", "2": "🙂 Goed", "3": "😐 Normaal", "4": "😕 Slecht", "5": "😣 Vreselijk"}
                        felt_key = str(felt).split(".")[0] if felt else ""
                        felt_label = _FELT_ICONS.get(felt_key, str(felt)) if felt else ""
                        felt_str = f"Gevoel: **{felt_label}**" if felt else ""
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

                    # Verloop per km — pace (cyaan, omhoog = sneller) + HF (amber)
                    _chart = _laps_chart(details)
                    if _chart is not None:
                        st.markdown("**Verloop per km:**")
                        st.altair_chart(_chart, use_container_width=True)

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
                                        workout["coach_profiel"] = _coach_profiel(workout["athlete_key"])
                                        if has_athlete_followup:
                                            fb = ai_feedback.generate_reply(workout, thread)
                                        else:
                                            fb = ai_feedback.generate_feedback(workout)
                                        st.session_state[f"feedback_{wk}"] = fb
                                        st.rerun(scope="fragment")
                                    except Exception as e:
                                        st.error(f"Fout: {e}")
                        with col_zelf:
                            if st.button("✏️ Zelf schrijven", key=f"zelf_btn_{i}"):
                                st.session_state[f"zelf_{wk}"] = True
                                st.rerun(scope="fragment")
                        with col_skip_early:
                            if st.button("⏭️ Overslaan", key=f"skip_early_{i}"):
                                _skipped = _load_skipped()
                                _skipped[wk] = _skip_snapshot(workout)
                                _save_skipped(_skipped)
                                st.session_state[f"posted_{wk}"] = True
                                _day_stats_mark_done(posted=False)
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
                                        _day_stats_mark_done(posted=True)
                                        _auto_dossier_note(workout)
                                        _leer_profiel(workout, edited)
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
                                st.rerun(scope="fragment")
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
                                    _day_stats_mark_done(posted=True)
                                    _auto_dossier_note(workout)
                                    _leer_profiel(workout, edited)
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
                                _skipped[wk] = _skip_snapshot(workout)
                                _save_skipped(_skipped)
                                st.session_state[f"posted_{wk}"] = True
                                _day_stats_mark_done(posted=False)
                                st.rerun()
                        with col_regen:
                            if st.button("🔄 Opnieuw", key=f"regen_{i}"):
                                st.session_state[f"feedback_{wk}"] = None
                                st.rerun(scope="fragment")

                st.markdown("---")

        for i, workout in enumerate(workouts):
            if verberg_gedaan and st.session_state.get(f"posted_{workout['workout_key']}"):
                continue
            _feedback_card(i, workout)

        if verberg_gedaan and _n_done and not pending:
            st.success("🎉 Alles afgehandeld — sterke ronde!")

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

    # ── Zones omzetten (tempo ↔ hartslag) van reeds geplande trainingen ──
    with st.container(border=True):
        st.markdown("**🔄 Zones omzetten (tempo ↔ hartslag)** — zet reeds geplande trainingen om "
                    "naar het andere doeltype. Zelfde trainingen, zelfde zone-nummers; alleen "
                    "tempo↔hartslag. Handig als een atleet na een lactaatmeting op hartslag wil.")
        _naar_lbl = st.radio("Omzetten naar", ["hartslag", "tempo"], horizontal=True,
                             key="bf_convert_naar")
        _naar = "hr" if _naar_lbl == "hartslag" else "tempo"
        st.caption(f"Alle nog niet uitgevoerde trainingen van **{_esc(selected_name)}** tussen "
                   f"**{bf_start.strftime('%d-%m-%Y')}** en **{bf_end.strftime('%d-%m-%Y')}** → "
                   f"**{_naar_lbl}**. Wandel-herstel (vaste pace) blijft ongewijzigd. "
                   f"Zorg dat de {_naar_lbl}-zones van de atleet in FinalSurge kloppen "
                   f"(bv. bijgewerkt na de meting).")
        if st.button(f"🔄 Zet trainingen om naar {_naar_lbl}", key="btn_bf_convert"):
            _prog = st.progress(0.0)
            _status = st.empty()

            def _bf_cb(i, n, label):
                _prog.progress((i + 1) / max(n, 1))
                _status.caption(f"Bezig: {label} ({i + 1}/{n})")

            _rap = None
            with st.spinner("Trainingen omzetten…"):
                try:
                    _rap = fs_client.convert_schema_zones(bf_athlete_key, bf_start, bf_end,
                                                          _naar, _bf_cb)
                except Exception as e:
                    st.error(f"Omzetten mislukt: {e}")
            _prog.empty()
            _status.empty()
            if _rap:
                st.success(f"✅ {len(_rap['omgezet'])} van {_rap['n_todo']} trainingen omgezet naar "
                           f"{_naar_lbl}.")
                if _rap["omgezet"]:
                    st.markdown("**Omgezet:**  \n" + "  \n".join(f"· {x}" for x in _rap["omgezet"]))
                if _rap["overgeslagen"]:
                    with st.expander(f"Overgeslagen ({len(_rap['overgeslagen'])})"):
                        st.markdown("  \n".join(f"· {x}" for x in _rap["overgeslagen"]))
                if _rap["fouten"]:
                    st.error("Fouten:  \n" + "  \n".join(f"· {x}" for x in _rap["fouten"]))

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
# PAGINA: INTAKE
# ===========================================================================

elif page == "intake":
    module_header("Intake", "📝")
    intake_page.render(athletes_by_group)


# ===========================================================================
# ===========================================================================
# PAGINA: RACES & SUCCESWENSEN
# ===========================================================================

elif page == "races":
    module_header("Races & Succeswensen", "🏁")
    races_page.render(COACH_ATHLETE_KEY)


# ===========================================================================
# PAGINA: SCHEMA-VERLOOP
# ===========================================================================

elif page == "schema":
    module_header("Schema-verloop", "📅")
    schema_page.render()


# ===========================================================================
# PAGINA: DOCUMENTEN — genereer strakke, persoonlijke atleet-documenten
# ===========================================================================

elif page == "documenten":
    module_header("Documenten", "📄")
    documenten_page.render(_all_athletes)


# ===========================================================================
# PAGINA: ATLETEN — overzicht voor dossiers
# ===========================================================================

elif page == "atleten":

    module_header("Atleet-dossiers", "👤")

    st.caption("Klik op een atleet voor het volledige dossier: intake, notities, trends, races en zones. "
               "📝 = intake aanwezig · 🗒️ = coach-notities (aantal) · ⏸ = op hold")

    if st.session_state.get("intakes") is None:
        st.session_state["intakes"] = intake_store.load_intakes()
    _intakes_all = st.session_state["intakes"]
    if "schema_on_hold" not in st.session_state:
        st.session_state["schema_on_hold"] = intake_store.load_on_hold()
    _oh = st.session_state["schema_on_hold"]
    # Notities één keer per sessie laden (gedeelde cache met het dossier)
    _notes_all = dossier._notes()

    # ── Recent bekeken dossiers ──
    _recents = st.session_state.get("recent_dossiers", [])
    if _recents:
        _rec_atleten = [a for k in _recents for a in _all_athletes if a["user_key"] == k]
        if _rec_atleten:
            st.markdown('<p class="bb-section-label">🕘 Recent bekeken</p>', unsafe_allow_html=True)
            cols_r = st.columns(min(len(_rec_atleten), 5))
            for r_i, a in enumerate(_rec_atleten[:5]):
                with cols_r[r_i]:
                    if st.button(a["name"], key=f"rec_{a['user_key']}", use_container_width=True):
                        st.session_state["dossier_user_key"] = a["user_key"]
                        go_to("dossier")

    _czoek, _cfilter = st.columns([3, 1], vertical_alignment="center")
    with _czoek:
        _zoek = st.text_input("🔍 Zoek atleet", key="atleten_zoek",
                              placeholder="Typ een naam…", label_visibility="collapsed").strip().lower()
    with _cfilter:
        _alleen_notities = st.toggle("🗒️ Alleen met notities", key="atleten_alleen_notities")

    # ── Nieuwe klanten: intake gedaan, nog niet in FinalSurge ──
    _wachtend = {k: v for k, v in _intakes_all.items() if k.startswith("nieuw:")}
    if _wachtend:
        st.markdown('<p class="bb-section-label">🆕 Nieuwe klanten — wachten op FinalSurge-account</p>',
                    unsafe_allow_html=True)
        cols_n = st.columns(3)
        for n_i, (_nk, _nv) in enumerate(sorted(_wachtend.items())):
            with cols_n[n_i % 3]:
                if st.button(f"{_nv.get('athlete_name', _nk[6:])}  📝",
                             key=f"nieuw_{_nk}", use_container_width=True,
                             help="Intake openen — koppelen kan daar zodra het FinalSurge-account bestaat"):
                    st.session_state["ik_mode"] = "🆕 Nieuwe klant"
                    st.session_state["ik_nieuw_sel"] = _nv.get("athlete_name", _nk[6:])
                    st.session_state.pop("ik_loaded_for", None)
                    go_to("intake")

    for group_name, members in athletes_by_group.items():
        if _zoek:
            members = [a for a in members if _zoek in a["name"].lower()]
        if _alleen_notities:
            members = [a for a in members if _notes_all.get(a["user_key"])]
        if not members:
            continue
        st.markdown(f'<p class="bb-section-label">{_esc(group_name)} — {len(members)}</p>',
                    unsafe_allow_html=True)
        cols = st.columns(3)
        for a_i, a in enumerate(sorted(members, key=lambda x: x["name"])):
            badges = []
            if a["user_key"] in _intakes_all:
                badges.append("📝")
            _n_notes = len(_notes_all.get(a["user_key"], []))
            if _n_notes:
                badges.append(f"🗒️{_n_notes}")
            if a["user_key"] in _oh:
                badges.append("⏸")
            label = a["name"] + (("  " + " ".join(badges)) if badges else "")
            with cols[a_i % 3]:
                if st.button(label, key=f"dos_{a['user_key']}", use_container_width=True):
                    st.session_state["dossier_user_key"] = a["user_key"]
                    go_to("dossier")


# ===========================================================================
# PAGINA: DOSSIER — alles over één atleet
# ===========================================================================

elif page == "dossier":

    _dkey = st.session_state.get("dossier_user_key")
    _datleet = next((a for a in _all_athletes if a["user_key"] == _dkey), None)

    if not _datleet:
        module_header("Atleet-dossier", "👤")
        st.warning("Geen atleet geselecteerd.")
        if st.button("→ Naar atletenoverzicht", key="to_atleten"):
            go_to("atleten")
    else:
        module_header(_datleet["name"], "👤")
        if st.button("← Alle atleten", key="back_atleten"):
            go_to("atleten")

        # Bijhouden voor "Recent bekeken" op de atleten-pagina
        _rec = st.session_state.setdefault("recent_dossiers", [])
        if _dkey in _rec:
            _rec.remove(_dkey)
        _rec.insert(0, _dkey)
        del _rec[5:]

        if st.session_state.get("intakes") is None:
            st.session_state["intakes"] = intake_store.load_intakes()
        # Leeskant-unificatie: toon de nieuwste intake uit beide bakjes, zodat een
        # atleet die alleen via een gebouwd schema bekend is niet 'Geen intake' toont.
        if "laatste_intakes" not in st.session_state:
            st.session_state["laatste_intakes"] = intake_store.load_laatste_intakes()
        if "schema_on_hold" not in st.session_state:
            st.session_state["schema_on_hold"] = intake_store.load_on_hold()

        dossier.render_dossier(
            _datleet,
            intake_store.nieuwste_intake(
                st.session_state["intakes"].get(_dkey),
                st.session_state["laatste_intakes"].get(_dkey),
            ),
            st.session_state["schema_on_hold"].get(_dkey),
        )


# ===========================================================================
# PAGINA: SCHEMA BOUWEN
# ===========================================================================

elif page == "builder":

    module_header("Schema bouwen", "🔨")

    builder_page.render(athletes_by_group)
