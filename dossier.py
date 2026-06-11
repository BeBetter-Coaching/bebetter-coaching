"""Atleet-dossier — 360° overzicht per atleet.

Eén pagina met alles over een atleet: intake, coach-notities, zones,
schema-status, compliance, volume- en gevoelstrends en racehistorie.
"""

from __future__ import annotations

import html
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import fs_client
import intake_store

_FELT_LABELS = {1: "😄 Geweldig", 2: "🙂 Goed", 3: "😐 Normaal", 4: "😕 Slecht", 5: "😣 Vreselijk"}


# ---------------------------------------------------------------------------
# Coach-notities (GitHub-backed, session-gecachet)
# ---------------------------------------------------------------------------

def _notes() -> dict:
    if "_notes_cache" not in st.session_state:
        try:
            st.session_state["_notes_cache"] = intake_store.load_notes()
        except Exception:
            st.session_state["_notes_cache"] = {}
    return st.session_state["_notes_cache"]


def _save_notes(notes: dict):
    st.session_state["_notes_cache"] = notes
    try:
        intake_store.save_notes(notes)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Trainingsdata-analyse
# ---------------------------------------------------------------------------

def _load_athlete_data(user_key: str) -> dict:
    """Haal log + toekomstig schema + zones op (parallel)."""
    from concurrent.futures import ThreadPoolExecutor

    today = date.today()
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_log = pool.submit(fs_client.get_training_log, user_key, 3, 0)
        fut_future = pool.submit(fs_client.get_workouts_deduped, user_key, today, today + timedelta(days=60))
        fut_zones = pool.submit(fs_client.get_athlete_zones, user_key)
        try:
            log = fut_log.result()
        except Exception:
            log = []
        try:
            future = fut_future.result()
        except Exception:
            future = []
        try:
            zones = fut_zones.result()
        except Exception:
            zones = {"error": "ophalen mislukt"}
    return {"log": log, "future": future, "zones": zones}


def _week_label(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _analyse_log(log: list[dict]) -> dict:
    """Bereken compliance, weekvolume en gevoel/RPE-trend uit het log."""
    today = date.today()
    cutoff_8w = today - timedelta(weeks=8)

    planned_8w = 0
    completed_of_planned_8w = 0
    week_km: dict[str, float] = {}
    trend_rows = []
    races = []

    for e in log:
        try:
            d = date.fromisoformat(e["date"])
        except (ValueError, KeyError):
            continue
        if d > today:
            continue

        is_planned = bool(e.get("planned_km") or e.get("planned_min") or e.get("description"))
        if d >= cutoff_8w and is_planned and not e.get("is_race"):
            planned_8w += 1
            if e.get("completed"):
                completed_of_planned_8w += 1

        if e.get("completed"):
            wk = _week_label(d)
            week_km[wk] = week_km.get(wk, 0.0) + float(e.get("actual_km") or 0)

            felt = e.get("felt")
            effort = e.get("effort")
            if felt or effort:
                row = {"datum": d}
                if felt:
                    try:
                        # Inverteren zodat hoger = beter in de grafiek
                        row["Gevoel (5 = top)"] = 6 - int(float(felt))
                    except (ValueError, TypeError):
                        pass
                if effort:
                    try:
                        row["Inspanning (RPE)"] = int(float(effort))
                    except (ValueError, TypeError):
                        pass
                trend_rows.append(row)

            if e.get("is_race"):
                races.append({
                    "Datum": e["date"],
                    "Race": e.get("name") or "Race",
                    "Afstand": f"{e['actual_km']} km" if e.get("actual_km") else "—",
                    "Pace": e.get("pace") or "—",
                })

    # Weekvolume als dataframe (laatste 8 weken, ook lege weken tonen)
    week_rows = []
    for w_ago in range(7, -1, -1):
        d = today - timedelta(weeks=w_ago)
        wk = _week_label(d)
        week_rows.append({"week": wk, "km": round(week_km.get(wk, 0.0), 1)})
    df_weeks = pd.DataFrame(week_rows).set_index("week")

    df_trend = None
    if trend_rows:
        df_trend = pd.DataFrame(trend_rows).set_index("datum").sort_index()

    compliance = (
        round(completed_of_planned_8w / planned_8w * 100)
        if planned_8w else None
    )

    return {
        "compliance": compliance,
        "planned_8w": planned_8w,
        "completed_8w": completed_of_planned_8w,
        "df_weeks": df_weeks,
        "df_trend": df_trend,
        "races": races,
        "km_4w": round(sum(
            r["km"] for r in week_rows[-4:]
        ), 1),
    }


def _schema_end(future: list[dict]) -> tuple[str | None, int | None]:
    """Laatste geplande structured workout — zelfde definitie als schema-verloop."""
    dates = [
        w["workout_date"][:10]
        for w in future
        if w.get("workout_date") and w.get("has_structured_workout") and not w.get("is_race")
    ]
    if len(dates) < 4:  # zelfde drempel als fs_client._MIN_SCHEMA_WORKOUTS
        return None, None
    last = max(dates)
    return last, (date.fromisoformat(last) - date.today()).days


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_dossier(athlete: dict, intake: dict | None, on_hold_info: dict | None):
    user_key = athlete["user_key"]
    naam = athlete.get("name") or "Atleet"

    # ── Statusregel ──
    status_parts = [f"Groep: **{athlete.get('group', '—')}**"]
    if on_hold_info:
        reden = on_hold_info.get("reden") or "geen reden opgegeven"
        status_parts.append(f"⏸ **Op hold** sinds {on_hold_info.get('since', '?')} ({reden})")
    st.markdown("  ·  ".join(status_parts))
    if on_hold_info:
        st.warning("Deze atleet staat op hold en telt niet mee in dagstatus en schema-verloop.")

    col_intake, col_notes = st.columns([1, 1])

    # ── Intake-samenvatting ──
    with col_intake:
        st.markdown("#### 📝 Intake & doel")
        if intake:
            _velden = [
                ("Doel", intake.get("doel")),
                ("Referentieprestatie", intake.get("referentie_prestatie")),
                ("Huidig volume", intake.get("huidig_volume")),
                ("Trainingsdagen", intake.get("trainingsdagen")),
                ("Tijd per training", intake.get("tijd_per_training")),
                ("Herstelcapaciteit", intake.get("herstelcapaciteit")),
                ("Blessurehistorie", intake.get("blessurehistorie")),
                ("Wat werkte", intake.get("wat_werkte")),
                ("Wat niet werkte", intake.get("wat_niet_werkte")),
                ("Coach-notitie (intake)", intake.get("coach_notitie")),
            ]
            gevuld = [(k, v) for k, v in _velden if v]
            if gevuld:
                for k, v in gevuld:
                    st.markdown(f"**{k}:** {v}")
            else:
                st.caption("Intake aanwezig maar zonder ingevulde velden.")
        else:
            st.caption("Geen intake opgeslagen voor deze atleet. Vul er één in via de Intake-module.")

    # ── Coach-notities ──
    with col_notes:
        st.markdown("#### 🗒️ Coach-notities")
        st.caption("Gedeeld tussen Jip & Remco — voor alles wat niet in FinalSurge staat.")
        notes = _notes()
        athlete_notes = notes.get(user_key, [])

        with st.form(f"note_form_{user_key}", clear_on_submit=True):
            c_txt, c_coach = st.columns([3, 1])
            with c_txt:
                note_txt = st.text_input("Nieuwe notitie", placeholder="bijv. liever geen zware blokken na nachtdienst")
            with c_coach:
                note_coach = st.selectbox("Coach", ["Jip", "Remco"], label_visibility="visible")
            if st.form_submit_button("➕ Toevoegen", use_container_width=True):
                if note_txt.strip():
                    athlete_notes.insert(0, {
                        "datum": date.today().isoformat(),
                        "coach": note_coach,
                        "tekst": note_txt.strip(),
                    })
                    notes[user_key] = athlete_notes
                    _save_notes(notes)
                    st.rerun()

        if athlete_notes:
            for n_idx, note in enumerate(athlete_notes):
                c_note, c_del = st.columns([6, 1])
                with c_note:
                    st.markdown(
                        f"<div style='background:#0E2547; border:1px solid #1E3A66; border-radius:10px; "
                        f"padding:0.6rem 0.9rem; margin-bottom:0.4rem;'>"
                        f"<span style='color:#5EE6EB; font-size:0.7rem; font-weight:700;'>"
                        f"{html.escape(note.get('coach', '?'))} · {html.escape(note.get('datum', ''))}</span><br>"
                        f"<span style='color:#EAF2FF; font-size:0.88rem;'>{html.escape(note.get('tekst', ''))}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with c_del:
                    if st.button("🗑", key=f"del_note_{user_key}_{n_idx}", help="Notitie verwijderen"):
                        athlete_notes.pop(n_idx)
                        notes[user_key] = athlete_notes
                        _save_notes(notes)
                        st.rerun()
        else:
            st.caption("Nog geen notities.")

    st.markdown("---")

    # ── Trainingsdata (on demand, gecachet per sessie) ──
    st.markdown("#### 📈 Trainingsdata & trends")
    data_key = f"dossier_data_{user_key}"

    if data_key not in st.session_state:
        if st.button("📥 Laad trainingsdata (laatste 3 maanden)", type="primary", key=f"load_{user_key}"):
            with st.spinner("Trainingslog, schema en zones ophalen…"):
                st.session_state[data_key] = _load_athlete_data(user_key)
            st.rerun()
        return

    data = st.session_state[data_key]
    analyse = _analyse_log(data["log"])
    last_date, days_left = _schema_end(data["future"])

    # ── Kerngetallen ──
    m1, m2, m3, m4 = st.columns(4)
    if days_left is not None:
        m1.metric("Schema loopt tot", last_date, f"{days_left} dagen", delta_color="off")
    else:
        m1.metric("Schema loopt tot", "—", "geen actief schema", delta_color="off")
    if analyse["compliance"] is not None:
        m2.metric(
            "Compliance (8 wkn)",
            f"{analyse['compliance']}%",
            f"{analyse['completed_8w']}/{analyse['planned_8w']} trainingen",
            delta_color="off",
        )
    else:
        m2.metric("Compliance (8 wkn)", "—", "geen geplande trainingen", delta_color="off")
    m3.metric("Volume laatste 4 wkn", f"{analyse['km_4w']} km")
    m4.metric("Races in log", str(len(analyse["races"])))

    # ── Grafieken ──
    c_vol, c_trend = st.columns(2)
    with c_vol:
        st.markdown("**Weekvolume (km)**")
        st.bar_chart(analyse["df_weeks"], height=220)
    with c_trend:
        st.markdown("**Gevoel & inspanning per training**")
        if analyse["df_trend"] is not None:
            st.line_chart(analyse["df_trend"], height=220)
        else:
            st.caption("Nog geen gevoel/RPE-scores in deze periode.")

    # ── Races ──
    if analyse["races"]:
        st.markdown("**🏁 Recente races**")
        st.table(pd.DataFrame(analyse["races"]))

    # ── Zones ──
    with st.expander("🎯 Zones in FinalSurge"):
        zones = data["zones"]
        if zones.get("zones_text"):
            st.caption(f"Type: {zones.get('zone_type', '?')}")
            st.code(zones["zones_text"])
        else:
            st.caption(f"Geen zones gevonden ({zones.get('error', 'onbekend')}).")

    if st.button("🔄 Data vernieuwen", key=f"reload_{user_key}"):
        del st.session_state[data_key]
        st.rerun()
