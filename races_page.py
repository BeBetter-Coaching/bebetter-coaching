"""Races-pagina — losgekoppeld uit main.py (stap 2 van het opknippen).

Aankomende races, raceplan-generatie en succeswensen. Aangeroepen vanuit main.py
als races_page.render(COACH_ATHLETE_KEY). Gedrag identiek aan voorheen.
"""
from datetime import date

import streamlit as st

import ai_feedback
import fs_client


def render(coach_athlete_key):
    COACH_ATHLETE_KEY = coach_athlete_key

    # ── Filters ──────────────────────────────────────────────────────────────
    col_f1, col_f2, _ = st.columns([1, 1, 2])
    with col_f1:
        days_ahead = st.selectbox("Kijk vooruit", [7, 14, 21, 30], index=0,
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
        # Een race is afgehandeld als de wens al gepost is in deze sessie OF
        # als er al een coach-comment in FinalSurge staat (wish_given) — dat
        # laatste blijft kloppen na een herstart en over beide coaches heen.
        def _race_done(r):
            return (st.session_state.get(f"race_posted_{r['workout_key']}")
                    or r.get("wish_given"))

        pending_races = [r for r in races if not _race_done(r)]

        c_info_r, c_verberg_r = st.columns([3, 2], vertical_alignment="center")
        with c_info_r:
            st.markdown(f"**{len(pending_races)} race(s)** zonder verstuurde succeswens.")
        with c_verberg_r:
            verberg_race = st.toggle("Verberg afgehandelde", value=True, key="race_verberg")

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
            posted = _race_done(race)
            if verberg_race and posted:
                continue
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
