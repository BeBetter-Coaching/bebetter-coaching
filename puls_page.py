"""Teampuls-pagina: belasting-signalen + weekbriefing.
Uit main.py gelicht; body verbatim (4-spatie indent = functie-body).
"""
import html as _html_mod
from datetime import date

import streamlit as st

import admin
import belasting
import briefing
import intake_store
import rompslomp_client


def _esc(s) -> str:
    return _html_mod.escape(str(s or ""))


def render(all_athletes):
    _all_athletes = all_athletes

    def go_to(p: str):
        st.session_state["page"] = p
        st.rerun()


    # ── Belasting-signalen ──
    # Berekening draait hier (niet op de homepage): 1x per dag automatisch,
    # daarna alleen via de knop. De stand wordt gedeeld opgeslagen.
    _bel_data = st.session_state.get("belasting_data") or belasting.laad_stand()
    _vandaag_iso = date.today().isoformat()
    if _bel_data.get("datum") != _vandaag_iso:
        with st.spinner("Belasting-signalen berekenen (alle atleten)…"):
            try:
                _bel_data = belasting.dagelijkse_check(_all_athletes)
            except Exception as _be:
                st.warning(f"Berekenen mislukt ({_be}) — laatst bekende stand wordt getoond.")
        st.session_state["belasting_data"] = _bel_data

    _bel = belasting.zichtbare_resultaten(_bel_data)
    _n_hoog = sum(1 for r in _bel if r.get("ernst") == "hoog")

    ph_kop, ph_knop = st.columns([4, 1], vertical_alignment="center")
    with ph_kop:
        st.markdown(f"#### Belasting-signalen · {_bel_data.get('datum', '—')}")
        st.caption("Signalen uit volume, gevoel, RPE en notities. Geen diagnose, wel een seintje "
                   "om mee te kijken. **Gezien** dempt 7 dagen (voor beide coaches); bij "
                   "escalatie komt de atleet eerder terug. Klap de onderbouwing open om te "
                   "controleren welke trainingen zijn geteld.")
    with ph_knop:
        if st.button("🔄 Herbereken", key="puls_recalc", use_container_width=True):
            with st.spinner("Belasting-signalen berekenen…"):
                try:
                    st.session_state["belasting_data"] = belasting.dagelijkse_check(
                        _all_athletes, forceer=True)
                except Exception as _be:
                    st.error(f"Berekenen mislukt: {_be}")
            st.rerun()

    if not _bel:
        st.success("Geen belasting-signalen — iedereen binnen de marge.")
    for _r in _bel:
        _ico = "🔴" if _r["ernst"] == "hoog" else "⚠️"
        c_bel, c_seen, c_dos = st.columns([3.4, 1.1, 1.1], vertical_alignment="center")
        with c_bel:
            st.markdown(f"{_ico} **{_esc(_r['naam'])}** ({_esc(_r.get('group', ''))})  \n"
                        + "  \n".join(f"· {_esc(s)}" for s in _r["signalen"]))
            if _r.get("duiding"):
                st.caption(f"💬 {_r['duiding']}")
            _mx = _r.get("metrics") or {}
            _runs = _mx.get("runs_recent") or []
            if _runs or _mx:
                with st.expander("🔍 Onderbouwing (welke trainingen zijn geteld)"):
                    if _runs:
                        st.markdown("**Geteld in de recente week:**  \n" + "  \n".join(
                            f"· {r['datum']}: {r['km']} km"
                            + (f" ({_esc(r['naam'])})" if r.get('naam') else "")
                            for r in _runs))
                    st.caption(
                        f"Recente week: {_mx.get('km_recent', '?')} km · basis: "
                        f"{_mx.get('km_basis_week', '?')} km/wk (gem. van de 4 weken ervoor) · "
                        f"gevoel {_mx.get('gevoel_recent', '—')} vs {_mx.get('gevoel_basis', '—')} · "
                        f"RPE {_mx.get('rpe_recent', '—')} vs {_mx.get('rpe_basis', '—')}. "
                        "Klopt een geteld aantal km niet met FinalSurge? Meld het — dan zit er "
                        "een dubbeltelling in die we gericht kunnen fixen.")
        with c_seen:
            if st.button("✓ Gezien", key=f"puls_seen_{_r['user_key']}", use_container_width=True,
                         help="7 dagen niet meer tonen (voor beide coaches); "
                              "bij verergering komt de atleet eerder terug"):
                st.session_state["belasting_data"] = belasting.markeer_gezien(
                    _bel_data, _r["user_key"], _r["ernst"])
                st.rerun()
        with c_dos:
            if st.button("Dossier →", key=f"puls_dos_{_r['user_key']}", use_container_width=True):
                st.session_state["dossier_user_key"] = _r["user_key"]
                go_to("dossier")

    st.markdown("---")

    # ── Weekbriefing ──
    if "weekbriefing" not in st.session_state:
        try:
            st.session_state["weekbriefing"] = intake_store.load_weekbriefing()
        except Exception:
            st.session_state["weekbriefing"] = {}
    _wb = st.session_state["weekbriefing"]
    _wk_nu = briefing.week_label()

    def _maak_weekbriefing(force: bool = False) -> dict:
        _bel_res = (st.session_state.get("belasting_data") or {}).get("resultaten", [])
        _schema_rows = st.session_state.get("schema_data") or []
        _schema_namen = [r["name"] for r in _schema_rows
                         if r.get("days_left") is None or r["days_left"] <= 7]
        _races_lijst = (st.session_state.get("day_stats") or {}).get("races_list", [])
        _fact = []
        try:
            if rompslomp_client.is_configured():
                _facturen, _fe = rompslomp_client.get_invoices(date.today().year)
                if not _fe:
                    _fact = [a["name"] for a in admin.niet_gefactureerde_klanten(
                        _all_athletes, intake_store.load_admin_clients(), _facturen)]
        except Exception:
            pass  # facturatie is bonus in de briefing
        return briefing.weekbriefing(_all_athletes, _bel_res, _schema_namen,
                                     _races_lijst, _fact, forceer=force)

    st.markdown(f"#### 📰 Weekbriefing · week {_wk_nu.split('-W')[1]}")
    if _wb.get("week") != _wk_nu:
        with st.spinner("Weekbriefing samenstellen…"):
            try:
                _wb = _maak_weekbriefing()
                st.session_state["weekbriefing"] = _wb
            except Exception as _wbe:
                st.warning(f"Briefing maken mislukt: {_wbe}")

    if _wb.get("tekst"):
        _ws = _wb.get("stats", {})
        st.caption(f"Gemaakt op {_wb.get('gemaakt', '')} · gedeeld met beide coaches · "
                   f"{_ws.get('n_trainingen', '?')} trainingen · ±{_ws.get('km_totaal', '?')} km · "
                   f"{_ws.get('n_actief', '?')}/{_ws.get('n_atleten', '?')} atleten actief")
        st.markdown(_wb["tekst"])
        if st.button("🔄 Vernieuw briefing", key="wb_refresh",
                     help="Verzamelt de weekdata opnieuw en schrijft een verse briefing"):
            with st.spinner("Weekbriefing samenstellen…"):
                try:
                    st.session_state["weekbriefing"] = _maak_weekbriefing(force=True)
                except Exception as _wbe:
                    st.error(f"Briefing vernieuwen mislukt: {_wbe}")
            st.rerun()

