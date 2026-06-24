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

_GARMIN_LIGHT = {
    "green": ("🟢 GROEN — hersteld, ruimte om te trainen", "success"),
    "amber": ("🟡 ORANJE — let op, pas de intensiteit aan", "warning"),
    "red": ("🔴 ROOD — onderherstel, houd het rustig", "error"),
}


def _render_garmin_panel(user_key: str) -> None:
    """Toon de Garmin-readiness uit de hardloopcoach-app (alleen als die er is).

    Volledig defensief: zonder data of bij wélke fout dan ook wordt er niets
    getoond, zodat het dossier zich exact als voorheen gedraagt. Atleten zonder
    gepubliceerde Garmin-state (alle klanten nu) zien dus niets nieuws.
    """
    try:
        state = (intake_store.load_garmin_state() or {}).get(user_key)
    except Exception:
        return
    if not state:
        return
    try:
        readiness = state.get("readiness") or {}
        sig = readiness.get("signals") or {}
        light = readiness.get("light")

        st.markdown("#### 🏃 Garmin-readiness")
        label, kind = _GARMIN_LIGHT.get(light, (f"Readiness: {light}", "info"))
        getattr(st, kind)(label)

        for reden in (readiness.get("reasons") or [])[:3]:
            st.markdown(f"- {reden}")

        def _f(v, suffix=""):
            return f"{v}{suffix}" if v is not None else "—"

        hrv = sig.get("hrv") or {}
        cols = st.columns(5)
        cols[0].metric("HRV", _f(hrv.get("current")))
        cols[1].metric("Slaap", _f(sig.get("sleep_last_night_h"), " u"))
        cols[2].metric("Rust-HS", _f(sig.get("resting_hr")))
        cols[3].metric("Body Battery", _f(sig.get("body_battery_at_wake")))
        cols[4].metric("ACWR", _f(sig.get("acwr")))

        report_md = (state.get("weekly") or {}).get("report_md")
        if report_md:
            with st.expander("📋 Wekelijks coach-rapport (Garmin)"):
                st.markdown(report_md)

        if state.get("updated_at"):
            st.caption(f"Garmin-data bijgewerkt: {state['updated_at']}")
        st.divider()
    except Exception:
        # Nooit het dossier laten vallen op dit extra paneel.
        return


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


def _workout_score(e: dict) -> float:
    """
    Compliance-score 0–1 voor een geplande training.

    Niet binair: een halve training of een vervangende (kracht)training
    waarbij nauwelijks gepland volume is gedraaid, scoort laag — FinalSurge
    zet 'completed' namelijk al op ja zodra er íéts aan data op de geplande
    workout staat.
    """
    if not e.get("completed"):
        return 0.0
    planned_km = float(e.get("planned_km") or 0)
    planned_min = float(e.get("planned_min") or 0)
    if planned_km:
        return min(float(e.get("actual_km") or 0) / planned_km, 1.0)
    if planned_min:
        return min(float(e.get("actual_min") or 0) / planned_min, 1.0)
    return 1.0  # gepland zonder doelvolume (bijv. losse beschrijving) → gedaan is gedaan


def _analyse_log(log: list[dict]) -> dict:
    """Bereken compliance, weekvolume en gevoel/RPE-trend uit het log."""
    today = date.today()
    cutoff_8w = today - timedelta(weeks=8)

    scores_8w: list[float] = []
    n_vol = n_deels = n_gemist = 0
    week_km: dict[str, float] = {}
    week_scores: dict[str, list[float]] = {}
    trend_rows = []
    eff_rows = []
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
            score = _workout_score(e)
            scores_8w.append(score)
            week_scores.setdefault(_week_label(d), []).append(score)
            if score >= 0.9:
                n_vol += 1
            elif score > 0:
                n_deels += 1
            else:
                n_gemist += 1

        if e.get("completed"):
            wk = _week_label(d)
            week_km[wk] = week_km.get(wk, 0.0) + float(e.get("actual_km") or 0)

            # Conditie-index: snelheid per hartslag (m/min per bpm × 100).
            # Stijgende lijn = zelfde tempo bij lagere HF = fitter.
            hr = e.get("hr_avg")
            pace_min = fs_client._pace_to_float(e.get("pace"))
            if hr and pace_min != float("inf") and not e.get("is_race"):
                try:
                    # meters per minuut gedeeld door hartslag, ×100
                    # typisch bereik hardlopen: ~70 (rustig) tot ~200 (snel)
                    eff = (1000 / pace_min) / float(hr) * 100
                    if 40 < eff < 300:  # filter sensorruis / wandelingen
                        eff_rows.append({"datum": d, "Conditie-index": round(eff, 1)})
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

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
                vdot = None
                km = e.get("actual_km")
                mins = e.get("actual_min")
                if km and mins and float(km) >= 1.5:
                    try:
                        import schema_builder
                        vdot = round(schema_builder.calculate_vdot(
                            float(km) * 1000, float(mins) * 60
                        ), 1)
                    except Exception:
                        vdot = None
                races.append({
                    "Datum": e["date"],
                    "Race": e.get("name") or "Race",
                    "Afstand": f"{km} km" if km else "—",
                    "Tijd": f"{int(mins)//60}:{int(mins)%60:02d}" if mins else "—",
                    "Pace": e.get("pace") or "—",
                    "VDOT": vdot if vdot else "—",
                })

    # Weekvolume + compliance per week (laatste 8 weken, ook lege weken tonen)
    week_rows = []
    compl_rows = []
    for w_ago in range(7, -1, -1):
        d = today - timedelta(weeks=w_ago)
        wk = _week_label(d)
        week_rows.append({"week": wk, "km": round(week_km.get(wk, 0.0), 1)})
        ws = week_scores.get(wk)
        compl_rows.append({
            "week": wk,
            "Compliance %": round(sum(ws) / len(ws) * 100) if ws else None,
        })
    df_weeks = pd.DataFrame(week_rows).set_index("week")
    df_compl = pd.DataFrame(compl_rows).set_index("week")

    df_trend = None
    if trend_rows:
        df_trend = pd.DataFrame(trend_rows).set_index("datum").sort_index()

    df_eff = None
    if len(eff_rows) >= 3:  # pas tonen als er genoeg punten zijn voor een trend
        df_eff = pd.DataFrame(eff_rows).set_index("datum").sort_index()

    compliance = (
        round(sum(scores_8w) / len(scores_8w) * 100)
        if scores_8w else None
    )

    return {
        "compliance": compliance,
        "n_vol": n_vol,
        "n_deels": n_deels,
        "n_gemist": n_gemist,
        "df_weeks": df_weeks,
        "df_compl": df_compl,
        "df_trend": df_trend,
        "df_eff": df_eff,
        "races": races,
        "km_4w": round(sum(
            r["km"] for r in week_rows[-4:]
        ), 1),
    }


def _periode_stats(entries: list[dict]) -> dict:
    """Aggregaten voor één periode: volume/week, conditie-index, compliance, gevoel/RPE."""
    weken: dict = {}
    effs, felts, rpes, scores = [], [], [], []
    for e in entries:
        try:
            d = date.fromisoformat(e["date"])
        except (ValueError, KeyError):
            continue
        is_planned = bool(e.get("planned_km") or e.get("planned_min") or e.get("description"))
        if is_planned and not e.get("is_race"):
            scores.append(_workout_score(e))
        if not e.get("completed"):
            continue
        if not e.get("is_race"):
            weken.setdefault(_week_label(d), 0.0)
            weken[_week_label(d)] += float(e.get("actual_km") or 0)
            hr = e.get("hr_avg")
            pace_min = fs_client._pace_to_float(e.get("pace"))
            if hr and pace_min != float("inf"):
                try:
                    eff = (1000 / pace_min) / float(hr) * 100
                    if 40 < eff < 300:
                        effs.append(eff)
                except (ValueError, TypeError, ZeroDivisionError):
                    pass
        if e.get("felt"):
            try:
                felts.append(int(float(e["felt"])))
            except (ValueError, TypeError):
                pass
        if e.get("effort"):
            try:
                rpes.append(int(float(e["effort"])))
            except (ValueError, TypeError):
                pass
    return {
        "km_per_week": round(sum(weken.values()) / len(weken), 1) if weken else 0.0,
        "conditie_index": round(sum(effs) / len(effs), 1) if effs else None,
        "compliance": round(sum(scores) / len(scores) * 100) if scores else None,
        "gevoel": round(sum(felts) / len(felts), 1) if felts else None,  # 1=top, 5=slecht
        "rpe": round(sum(rpes) / len(rpes), 1) if rpes else None,
        "n_runs": sum(1 for e in entries if e.get("completed") and not e.get("is_race")),
    }


def evaluatie_context(log: list[dict], coach_notes: list[dict], naam: str) -> str:
    """Bouw de datacontext voor de AI-evaluatie: toen (1e helft) vs nu (2e helft)."""
    today = date.today()
    mid = (today - timedelta(days=45)).isoformat()
    cutoff = (today - timedelta(days=90)).isoformat()
    eerste = [e for e in log if cutoff <= e.get("date", "") < mid]
    tweede = [e for e in log if e.get("date", "") >= mid]
    s1, s2 = _periode_stats(eerste), _periode_stats(tweede)

    def _reg(label, a, b, hoger_beter=True, suffix=""):
        if a is None and b is None:
            return f"{label}: onvoldoende data"
        av = "—" if a is None else f"{a}{suffix}"
        bv = "—" if b is None else f"{b}{suffix}"
        return f"{label}: toen {av} → nu {bv}"

    regels = [
        _reg("Volume (km/week)", s1["km_per_week"], s2["km_per_week"], suffix=" km"),
        _reg("Conditie-index (tempo per hartslag, hoger=fitter)", s1["conditie_index"], s2["conditie_index"]),
        _reg("Compliance", s1["compliance"], s2["compliance"], suffix="%"),
        _reg("Gevoel (1=top, 5=slecht)", s1["gevoel"], s2["gevoel"]),
        _reg("Inspanning RPE (1-10)", s1["rpe"], s2["rpe"]),
        f"Aantal runs: toen {s1['n_runs']} → nu {s2['n_runs']}",
    ]

    races = [e for e in log if e.get("is_race") and e.get("completed")]
    if races:
        regels.append("Races in deze periode: " + ", ".join(
            f"{e.get('name','race')} ({e.get('date','')[:10]})" for e in races[:5]))

    # Wat de atleet zelf schreef (eigen woorden over hoe het ging)
    atleet_woorden = [
        f"[{e['date'][:10]}] {e['post_notes'][:200]}"
        for e in sorted(log, key=lambda x: x.get("date", ""))
        if e.get("post_notes")
    ]
    woorden_blok = "\n".join(atleet_woorden[-10:]) if atleet_woorden else "(geen notities van de atleet)"

    notes_blok = "\n".join(
        f"[{n.get('datum','')}] {n.get('coach','')}: {n.get('tekst','')[:200]}"
        for n in coach_notes[:10]
    ) if coach_notes else "(geen coach-notities)"

    return f"""Atleet: {naam}
Periode: laatste 3 maanden, vergelijking eerste helft (TOEN) vs tweede helft (NU).

CIJFERS TOEN → NU:
{chr(10).join(regels)}

WAT DE ATLEET ZELF SCHREEF (post-workout notities):
{woorden_blok}

COACH-NOTITIES (incl. automatische signalen):
{notes_blok}"""


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

    _render_garmin_panel(user_key)

    col_intake, col_notes = st.columns([1, 1])

    # ── Intake-samenvatting ──
    with col_intake:
        st.markdown("#### 📝 Intake & doel")
        if intake:
            _velden = [
                ("Doel", intake.get("doel")),
                ("Motivatie", intake.get("motivatie")),
                ("Wedstrijd", intake.get("wedstrijddatum_tekst")),
                ("Referentieprestatie", intake.get("referentie_prestatie")),
                ("PR's", intake.get("prs")),
                ("Loopervaring", intake.get("loopervaring")),
                ("Huidig volume", intake.get("huidig_volume")),
                ("Trainingsdagen", intake.get("trainingsdagen")),
                ("Tijd per training", intake.get("tijd_per_training")),
                ("Slaap/leefritme", intake.get("slaap")),
                ("Herstelcapaciteit", intake.get("herstelcapaciteit")),
                ("Blessurehistorie", intake.get("blessurehistorie")),
                ("Huidige klachten", intake.get("huidige_klachten")),
                ("Vindt leuk", intake.get("leuk")),
                ("Vindt niet leuk", intake.get("niet_leuk")),
                ("Eerdere schema-ervaring", intake.get("eerdere_schemas")),
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

            # Verwijderen met bevestigingsstap
            if not st.session_state.get(f"_del_intake_vraag_{user_key}"):
                if st.button("🗑 Intake verwijderen", key=f"del_intake_{user_key}"):
                    st.session_state[f"_del_intake_vraag_{user_key}"] = True
                    st.rerun()
            else:
                st.warning("Intake definitief verwijderen?")
                c_ja, c_nee = st.columns(2)
                with c_ja:
                    if st.button("Ja, verwijder", type="primary", key=f"del_intake_ja_{user_key}"):
                        _alle = st.session_state.get("intakes")
                        if _alle is None:
                            _alle = intake_store.load_intakes()
                        _alle.pop(user_key, None)
                        ok, err = intake_store.save_intakes(_alle)
                        st.session_state["intakes"] = _alle
                        st.session_state.pop(f"_del_intake_vraag_{user_key}", None)
                        st.session_state.pop("ik_loaded_for", None)
                        if not ok:
                            st.error(f"Verwijderen mislukt: {err}")
                        st.rerun()
                with c_nee:
                    if st.button("Annuleer", key=f"del_intake_nee_{user_key}"):
                        st.session_state.pop(f"_del_intake_vraag_{user_key}", None)
                        st.rerun()
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
            f"{analyse['n_vol']} volledig · {analyse['n_deels']} deels · {analyse['n_gemist']} gemist",
            delta_color="off",
            help="Per geplande training: uitgevoerd volume t.o.v. gepland volume "
                 "(km of tijd). Een halve training telt als 50%, een vervangende "
                 "training zonder gepland volume telt laag mee.",
        )
    else:
        m2.metric("Compliance (8 wkn)", "—", "geen geplande trainingen", delta_color="off")
    m3.metric("Volume laatste 4 wkn", f"{analyse['km_4w']} km")
    m4.metric("Races in log", str(len(analyse["races"])))

    # ── Evaluatie & advies (AI, on demand) ──
    st.markdown("#### 📋 Evaluatie & advies")
    st.caption("Een beknopte coach-evaluatie: vergelijkt de eerste helft van de afgelopen 3 maanden "
               "met nu. Is de atleet vooruitgegaan, wat gaat goed, waar ligt hij het best?")
    _eval_key = f"dossier_eval_{user_key}"
    _eval = st.session_state.get(_eval_key)
    if _eval:
        st.info(_eval)
    ec1, ec2 = st.columns([1, 3])
    with ec1:
        if st.button("✨ Genereer evaluatie" if not _eval else "🔄 Opnieuw",
                     key=f"gen_eval_{user_key}", type="primary" if not _eval else "secondary"):
            import ai_feedback
            with st.spinner("Evaluatie schrijven…"):
                try:
                    _ctx = evaluatie_context(data["log"], _notes().get(user_key, []), naam)
                    st.session_state[_eval_key] = ai_feedback.generate_athlete_evaluation(_ctx, naam)
                except Exception as e:
                    st.error(f"Mislukt: {e}")
            st.rerun()

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

    c_compl, c_eff = st.columns(2)
    with c_compl:
        st.markdown("**Compliance per week (%)**")
        st.bar_chart(analyse["df_compl"], height=220)
    with c_eff:
        st.markdown("**Conditie-index** — tempo per hartslag")
        if analyse["df_eff"] is not None:
            st.line_chart(analyse["df_eff"], height=220)
            st.caption("Stijgende lijn = zelfde tempo bij lagere hartslag = fitter. "
                       "Races niet meegerekend.")
        else:
            st.caption("Te weinig trainingen met hartslag én tempo voor een trend.")

    # ── Races ──
    if analyse["races"]:
        st.markdown("**🏁 Recente races**")
        st.table(pd.DataFrame(analyse["races"]))

        # Zones-advies op basis van de recentste race met VDOT
        _laatste = next(
            (r for r in sorted(analyse["races"], key=lambda x: x["Datum"], reverse=True)
             if r["VDOT"] != "—"),
            None,
        )
        if _laatste:
            with st.expander(f"💡 Zones-advies op basis van {_laatste['Race']} (VDOT {_laatste['VDOT']})"):
                st.caption(
                    "Tempozones volgens Jack Daniels bij deze racevorm. Vergelijk met de "
                    "huidige zones hieronder — wijkt het duidelijk af, dan zijn de zones "
                    "in FinalSurge toe aan een update."
                )
                try:
                    import schema_builder
                    st.code(schema_builder.vdot_to_zones_text(float(_laatste["VDOT"])))
                except Exception:
                    st.caption("Kon geen zones berekenen.")

    # ── Zones ──
    with st.expander("🎯 Huidige zones in FinalSurge"):
        zones = data["zones"]
        if zones.get("zones_text"):
            st.caption(f"Type: {zones.get('zone_type', '?')}")
            st.code(zones["zones_text"])
        else:
            st.caption(f"Geen zones gevonden ({zones.get('error', 'onbekend')}).")

    if st.button("🔄 Data vernieuwen", key=f"reload_{user_key}"):
        del st.session_state[data_key]
        st.rerun()
