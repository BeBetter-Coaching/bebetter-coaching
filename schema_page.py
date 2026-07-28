"""Schema-verloop-pagina: einddatums, on-hold, verborgen-trainingen-signaal.
Uit main.py gelicht; body verbatim (4-spatie indent = functie-body).
"""
from datetime import date

import streamlit as st

import fs_client
import intake_store
from fs_client import TokenNotFoundError


def render():
    def go_to(p: str):
        st.session_state["page"] = p
        st.rerun()


    # On-hold opslaan in session state voor snelle lokale updates
    if "schema_on_hold" not in st.session_state:
        st.session_state["schema_on_hold"] = intake_store.load_on_hold()

    on_hold: dict = st.session_state["schema_on_hold"]
    on_hold_keys: set = set(on_hold.keys())

    threshold = st.slider(
        "Toon atleten waarvan schema afloopt binnen … dagen",
        min_value=1, max_value=7, value=3, step=1,
        key="schema_threshold",
    )

    col_load, col_reload = st.columns([2, 1])
    with col_load:
        if "schema_data" not in st.session_state:
            if st.button("📥 Laad schema-overzicht", type="primary", key="schema_load"):
                with st.spinner("Schema-einddatums ophalen voor alle atleten…"):
                    try:
                        st.session_state["schema_data"] = fs_client.get_schema_end_dates(
                            horizon_days=60, on_hold_keys=on_hold_keys
                        )
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
            if days_left < 0:
                return "⚫ Verlopen"
            if days_left <= 7:
                return "🔴 Urgent"
            if days_left <= 14:
                return "🟠 Bijna"
            return "🟢 OK"

        n_verlopen = sum(1 for r in schema_data if r["days_left"] is not None and r["days_left"] < 0)
        n_urgent = sum(1 for r in schema_data if r["days_left"] is not None and 0 <= r["days_left"] <= 7)
        n_bijna  = sum(1 for r in schema_data if r["days_left"] is not None and 7 < r["days_left"] <= 14)
        n_geen   = sum(1 for r in schema_data if r["days_left"] is None)

        c0, c1, c2, c3, c4, c5 = st.columns(6)
        c0.metric("⚫ Verlopen", n_verlopen)
        c1.metric("🔴 Urgent  (≤7d)", n_urgent)
        c2.metric("🟠 Bijna  (8–14d)", n_bijna)
        c3.metric("❌ Geen schema", n_geen)
        c4.metric("Totaal atleten", len(schema_data))
        c5.metric("⏸ Op hold", len(on_hold))

        # ── Verborgen-trainingen signaal (FinalSurge "Hide Workouts from Athlete") ──
        # Atleten waarvan het ZICHTBARE deel binnen een week (bijna) op is én er
        # nog verborgen trainingen achter staan. Eigen venster, los van de
        # schema-slider hierboven (die staat vaak op 3 dagen).
        _HIDE_VENSTER = 7
        verborgen_actie = [
            r for r in schema_data
            if r.get("hidden_count", 0) > 0
            and r.get("visible_days_left") is not None
            and r["visible_days_left"] <= _HIDE_VENSTER
        ]
        if verborgen_actie:
            st.markdown("")
            st.warning(f"👁 **{len(verborgen_actie)} atleten zien (bijna) geen trainingen meer** — "
                       f"hun verborgen-datum is bereikt terwijl er nog trainingen klaarstaan. Zet in "
                       f"FinalSurge bij die atleet 'Hide Workouts from Athlete' vooruit, anders denken "
                       f"ze dat hun schema niet verlengd is.")

            def _vis(r):
                vdl = r["visible_days_left"]
                if vdl < 0:
                    return f"zichtbaar liep **{abs(vdl)} dagen geleden** af"
                if vdl == 0:
                    return "zichtbaar **t/m vandaag**"
                return f"nog **{vdl} dagen** zichtbaar (t/m {r['visible_until']})"

            for r in sorted(verborgen_actie, key=lambda x: x["visible_days_left"]):
                st.markdown(f"- **{r['name']}** ({r['group']}) — {_vis(r)} · "
                            f"{r['hidden_count']} verborgen trainingen klaar")

        st.markdown("---")

        filtered = [r for r in schema_data if r["days_left"] is None or r["days_left"] <= threshold]
        rest     = [r for r in schema_data if r["days_left"] is not None and r["days_left"] > threshold]

        def _render_athlete_row(r, show_build_btn=True):
            c0, c1, c2, c3, c4, c5 = st.columns([2.5, 2, 1, 2, 1.5, 1.5])
            _hide_issue = (
                r.get("hidden_count", 0) > 0
                and r.get("visible_days_left") is not None
                and r["visible_days_left"] <= _HIDE_VENSTER
            )
            c0.write(("👁 " if _hide_issue else "") + r["name"])
            c1.write(r["last_date"] or "—")
            c2.write(str(r["days_left"]) if r["days_left"] is not None else "—")
            c3.write(_status(r["days_left"]))
            with c4:
                if show_build_btn and st.button("🔨 Schema", key=f"quick_build_{r['user_key']}"):
                    st.session_state["builder_client_type"] = "🔄 Bestaande klant"
                    st.session_state["builder_athlete"] = r["name"]
                    st.session_state["builder_naam"] = r["first_name"]
                    st.session_state["builder_step"] = 1
                    for k in ["builder_plan", "builder_csv", "builder_intake",
                              "builder_workouts", "builder_chat_history",
                              "builder_import_done", "schema_bericht"]:
                        st.session_state.pop(k, None)
                    go_to("builder")
            with c5:
                if st.button("⏸ Hold", key=f"hold_{r['user_key']}"):
                    st.session_state[f"hold_form_{r['user_key']}"] = True

            # On-hold formulier inline tonen
            if st.session_state.get(f"hold_form_{r['user_key']}"):
                with st.form(key=f"hold_form_submit_{r['user_key']}"):
                    reden = st.text_input("Reden (bijv. knieblessure, vakantie)", key=f"hold_reden_{r['user_key']}")
                    submitted = st.form_submit_button("Op hold zetten")
                    if submitted:
                        on_hold[r["user_key"]] = {
                            "naam": r["name"],
                            "reden": reden,
                            "since": date.today().isoformat(),
                        }
                        ok, err = intake_store.save_on_hold(on_hold)
                        st.session_state["schema_on_hold"] = on_hold
                        st.session_state.pop(f"hold_form_{r['user_key']}", None)
                        # Verwijder uit schema_data cache
                        st.session_state["schema_data"] = [
                            x for x in st.session_state.get("schema_data", [])
                            if x["user_key"] != r["user_key"]
                        ]
                        if not ok:
                            st.warning(f"Opgeslagen lokaal (GitHub: {err})")
                        st.rerun()

        if filtered:
            st.markdown(f"### Aandacht nodig — afloopt binnen {threshold} dagen of geen schema")

            # Bulk: meerdere atleten in één keer on hold (bijv. einde seizoen)
            with st.expander("⏸ Meerdere atleten tegelijk on hold"):
                _bulk_opts = {r["name"]: r for r in filtered}
                with st.form("bulk_hold_form"):
                    _bulk_sel = st.multiselect("Atleten", list(_bulk_opts.keys()))
                    _bulk_reden = st.text_input("Reden (geldt voor alle geselecteerden)",
                                                placeholder="bijv. winterstop, traint tijdelijk los")
                    if st.form_submit_button("Zet geselecteerde on hold", type="primary"):
                        if not _bulk_sel:
                            st.warning("Selecteer eerst één of meer atleten.")
                        else:
                            for _bn in _bulk_sel:
                                _br = _bulk_opts[_bn]
                                on_hold[_br["user_key"]] = {
                                    "naam": _br["name"],
                                    "reden": _bulk_reden,
                                    "since": date.today().isoformat(),
                                }
                            ok, err = intake_store.save_on_hold(on_hold)
                            st.session_state["schema_on_hold"] = on_hold
                            _sel_keys = {_bulk_opts[n]["user_key"] for n in _bulk_sel}
                            st.session_state["schema_data"] = [
                                x for x in st.session_state.get("schema_data", [])
                                if x["user_key"] not in _sel_keys
                            ]
                            if not ok:
                                st.warning(f"Opgeslagen lokaal (GitHub: {err})")
                            st.rerun()

            groups_shown: dict[str, list] = {}
            for r in filtered:
                groups_shown.setdefault(r["group"], []).append(r)

            for group_name, members in groups_shown.items():
                st.markdown(f"**{group_name}**")
                hdr = st.columns([2.5, 2, 1, 2, 1.5, 1.5])
                hdr[0].markdown("*Atleet*")
                hdr[1].markdown("*Schema tot*")
                hdr[2].markdown("*Dagen*")
                hdr[3].markdown("*Status*")
                hdr[4].markdown("")
                hdr[5].markdown("")
                for r in members:
                    _render_athlete_row(r)
                st.markdown("")
        else:
            st.success(f"✅ Alle atleten hebben een schema dat nog meer dan {threshold} dagen loopt.")

        if rest:
            with st.expander(f"🟢 Voldoende schema — {len(rest)} atleten (meer dan {threshold} dagen)"):
                hdr = st.columns([2.5, 2, 1, 2, 1.5, 1.5])
                hdr[0].markdown("*Atleet*")
                hdr[1].markdown("*Schema tot*")
                hdr[2].markdown("*Dagen*")
                hdr[3].markdown("*Status*")
                hdr[4].markdown("")
                hdr[5].markdown("")
                for r in rest:
                    _render_athlete_row(r)

        # ── Op hold sectie ──
        if on_hold:
            st.markdown("---")
            st.markdown("### ⏸ Op hold")
            st.caption("Deze atleten worden buiten beschouwing gelaten in het schema-overzicht en de dagoverzicht-tegel.")
            for uk, info in list(on_hold.items()):
                c0, c1, c2, c3 = st.columns([3, 2, 3, 1.5])
                c0.write(info.get("naam", uk))
                c1.write(f"Sinds {info.get('since', '—')}")
                c2.write(info.get("reden") or "—")
                with c3:
                    if st.button("↩️ Terugzetten", key=f"unhold_{uk}"):
                        on_hold.pop(uk, None)
                        intake_store.save_on_hold(on_hold)
                        st.session_state["schema_on_hold"] = on_hold
                        # Invalideer cache zodat atleet terugkomt bij volgende laad
                        st.session_state.pop("schema_data", None)
                        st.rerun()
