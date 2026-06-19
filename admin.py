"""Module 8 — Administratie (verborgen, alleen voor Jip).

Klantadministratie bovenop de FinalSurge-koppeling, een KOR-omzettracker
en een dashboard. Handmatige velden (status, pakket, coach, betaalcyclus,
notitie) worden los opgeslagen en nooit door een sync overschreven.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import fs_client
import intake_store

# ── Pakketten: prijs per 4 weken ──
PAKKETTEN = {
    "—": 0,
    "Los Schema": 25,
    "Comfort": 55,
    "Start to Run": 65,
    "Getting Better": 95,
    "Premium": 110,
    "High Performer": 135,
}
COACHES = ["—", "Jip", "Remco"]
STATUSSEN = ["Actief", "On hold", "Opgezegd"]
CYCLI = ["4 weken", "12 weken", "Jaar"]

KOR_GRENS = 20_000
# 4-weken-pakket → 13 periodes per jaar (52 / 4)
PERIODES_PER_JAAR = 13

# Startdata KOR (cumulatief per maand, uit Rompslomp)
REVENUE_SEED = {
    "2026-01": 3258.76,
    "2026-02": 5370.87,
    "2026-03": 8867.12,
    "2026-04": 12010.87,
    "2026-05": 13948.37,
    "2026-06": 16084.62,
}


# ---------------------------------------------------------------------------
# Pure rekenfuncties (zonder Streamlit — testbaar)
# ---------------------------------------------------------------------------

def _maand_einddatum(maand_key: str) -> date:
    """'YYYY-MM' → laatste dag van die maand."""
    jaar, maand = (int(x) for x in maand_key.split("-"))
    if maand == 12:
        return date(jaar, 12, 31)
    return date(jaar, maand + 1, 1) - timedelta(days=1)


def kor_projectie(revenue: dict, grens: float = KOR_GRENS) -> dict:
    """
    Bereken KOR-stand en projectie op basis van cumulatieve maandcijfers.

    Geeft terug: huidig bedrag, resterend, wekelijks tempo (lineaire trend),
    verwachte overschrijdingsdatum, en of de grens al gepasseerd is.
    """
    punten = sorted(revenue.items())  # [(maand_key, bedrag), ...]
    if not punten:
        return {"huidig": 0.0, "resterend": grens, "per_week": None,
                "datum_grens": None, "gepasseerd": False, "laatste_maand": None}

    laatste_maand, huidig = punten[-1]
    huidig = float(huidig)
    resterend = grens - huidig
    gepasseerd = huidig >= grens

    # Lineaire trend over (dag-ordinal, cumulatief)
    per_dag = None
    if len(punten) >= 2:
        xs = [_maand_einddatum(m).toordinal() for m, _ in punten]
        ys = [float(v) for _, v in punten]
        n = len(xs)
        gem_x = sum(xs) / n
        gem_y = sum(ys) / n
        noemer = sum((x - gem_x) ** 2 for x in xs)
        if noemer > 0:
            per_dag = sum((x - gem_x) * (y - gem_y) for x, y in zip(xs, ys)) / noemer

    per_week = per_dag * 7 if per_dag else None

    datum_grens = None
    if not gepasseerd and per_dag and per_dag > 0:
        laatste_dag = _maand_einddatum(laatste_maand)
        dagen_te_gaan = resterend / per_dag
        datum_grens = laatste_dag + timedelta(days=round(dagen_te_gaan))

    return {
        "huidig": huidig,
        "resterend": resterend,
        "per_week": per_week,
        "datum_grens": datum_grens,
        "gepasseerd": gepasseerd,
        "laatste_maand": laatste_maand,
    }


def geschatte_jaaromzet(admin: dict, status_filter: str = "Actief") -> float:
    """Som van pakketprijzen × 13 periodes voor klanten met de gegeven status."""
    totaal = 0.0
    for velden in admin.values():
        if velden.get("status", "Actief") != status_filter:
            continue
        prijs = PAKKETTEN.get(velden.get("pakket", "—"), 0)
        totaal += prijs * PERIODES_PER_JAAR
    return totaal


# ---------------------------------------------------------------------------
# Opslag — seed + merge
# ---------------------------------------------------------------------------

def _revenue() -> dict:
    """Omzetcijfers uit opslag; bij de allereerste keer geseed met REVENUE_SEED."""
    data = intake_store.load_revenue()
    if not data:
        intake_store.save_revenue(REVENUE_SEED)
        return dict(REVENUE_SEED)
    return data


def _admin() -> dict:
    if "_admin_cache" not in st.session_state:
        try:
            st.session_state["_admin_cache"] = intake_store.load_admin_clients()
        except Exception:
            st.session_state["_admin_cache"] = {}
    return st.session_state["_admin_cache"]


def _save_admin(data: dict):
    st.session_state["_admin_cache"] = data
    return intake_store.save_admin_clients(data)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _eur(v) -> str:
    try:
        return "€" + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "€0,00"


def render_admin(athletes_by_group: dict):
    """Hoofdscherm van de administratiemodule."""
    athletes = sorted(
        [a for members in athletes_by_group.values() for a in members],
        key=lambda x: x["name"],
    )
    admin = _admin()
    revenue = _revenue()
    proj = kor_projectie(revenue)

    # Inactiviteit (laatste FinalSurge-activiteit) — on demand, gecachet
    last_act = st.session_state.get("_admin_last_act")

    # ── DASHBOARD ──
    st.markdown("### 📊 Dashboard")

    actief = [a for a in athletes if admin.get(a["user_key"], {}).get("status", "Actief") == "Actief"]
    on_hold = [a for a in athletes if admin.get(a["user_key"], {}).get("status") == "On hold"]
    jaaromzet = geschatte_jaaromzet(admin)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("KOR-ruimte over", _eur(proj["resterend"]),
              "grens gepasseerd!" if proj["gepasseerd"] else None,
              delta_color="inverse")
    c2.metric("Actieve klanten", len(actief))
    c3.metric("Gesch. jaaromzet (actief)", _eur(jaaromzet))
    c4.metric("Op hold", len(on_hold))

    if proj["datum_grens"]:
        _wk = f" · ~{_eur(proj['per_week'])}/week" if proj["per_week"] else ""
        st.caption(f"Bij dit tempo wordt de KOR-grens van {_eur(KOR_GRENS)} verwacht rond "
                   f"**{proj['datum_grens'].strftime('%d-%m-%Y')}**{_wk}.")
    elif proj["gepasseerd"]:
        st.error(f"⚠️ De KOR-grens van {_eur(KOR_GRENS)} is overschreden.")

    # Pakketverdeling van actieve klanten
    verdeling: dict[str, int] = {}
    for a in actief:
        pk = admin.get(a["user_key"], {}).get("pakket", "—")
        verdeling[pk] = verdeling.get(pk, 0) + 1
    if verdeling:
        _vp = "  ·  ".join(f"{k}: {v}" for k, v in sorted(verdeling.items(), key=lambda x: -x[1]))
        st.caption(f"**Actief per pakket:** {_vp}")

    if on_hold:
        st.warning("⏸ **On hold:** " + ", ".join(a["name"] for a in on_hold))

    # Inactiviteitssignaal
    with st.container():
        ccol, bcol = st.columns([3, 1], vertical_alignment="center")
        with bcol:
            if st.button("🔄 Check inactiviteit", use_container_width=True):
                with st.spinner("Laatste activiteit ophalen…"):
                    st.session_state["_admin_last_act"] = fs_client.get_last_activity_dates(60)
                    last_act = st.session_state["_admin_last_act"]
        with ccol:
            if last_act is not None:
                grens_dt = (date.today() - timedelta(days=21)).isoformat()
                stil = []
                for a in athletes:
                    if admin.get(a["user_key"], {}).get("status") == "Opgezegd":
                        continue
                    laatste = last_act.get(a["user_key"])
                    if laatste is None or laatste < grens_dt:
                        stil.append((a["name"], laatste))
                if stil:
                    st.error("🔕 **Mogelijk inactief (>3 weken geen activiteit):** "
                             + ", ".join(f"{n} ({l or 'nooit'})" for n, l in stil))
                else:
                    st.success("Alle actieve klanten trainden de afgelopen 3 weken.")
            else:
                st.caption("Klik om te checken wie >3 weken geen FinalSurge-activiteit had.")

    st.divider()

    # ── KOR-TRACKER ──
    st.markdown("### 💶 KOR-omzettracker")
    pct = min(proj["huidig"] / KOR_GRENS * 100, 100) if KOR_GRENS else 0
    st.progress(pct / 100)
    st.markdown(f"**{_eur(proj['huidig'])}** van {_eur(KOR_GRENS)}  ·  nog **{_eur(proj['resterend'])}** te gaan "
                f"({pct:.0f}%)")

    with st.expander("➕ Nieuw cumulatief omzetbedrag invoeren"):
        st.caption("Kijk in Rompslomp en vul het cumulatieve jaarbedrag tot nu toe in. "
                   "Bestaande maand overschrijven mag.")
        cm1, cm2, cm3 = st.columns([1.2, 1.5, 1])
        with cm1:
            _maand = st.text_input("Maand (YYYY-MM)", value=date.today().strftime("%Y-%m"),
                                   key="adm_rev_maand")
        with cm2:
            _bedrag = st.number_input("Cumulatief bedrag (€)", min_value=0.0, step=100.0,
                                      value=float(proj["huidig"]), key="adm_rev_bedrag")
        with cm3:
            st.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
            if st.button("Opslaan", type="primary", key="adm_rev_save", use_container_width=True):
                revenue[_maand.strip()] = round(float(_bedrag), 2)
                ok, err = intake_store.save_revenue(revenue)
                if ok:
                    st.success(f"Omzet {_maand} opgeslagen.")
                    st.rerun()
                else:
                    st.error(f"Opslaan mislukt: {err}")

        if revenue:
            _df_rev = pd.DataFrame(
                [{"Maand": m, "Cumulatief": v} for m, v in sorted(revenue.items())]
            ).set_index("Maand")
            st.line_chart(_df_rev, height=180)

    st.divider()

    # ── KLANTENLIJST ──
    st.markdown("### 👥 Klantenlijst")
    st.caption("Live uit FinalSurge. Pakket, coach, status, betaalcyclus en notitie stel je hier in; "
               "die blijven bewaard en worden nooit door een sync overschreven.")

    rows = []
    for a in athletes:
        v = admin.get(a["user_key"], {})
        rows.append({
            "user_key": a["user_key"],
            "Naam": a["name"],
            "E-mail": a.get("email", "") or "",
            "Pakket": v.get("pakket", "—"),
            "Coach": v.get("coach", "—"),
            "Status": v.get("status", "Actief"),
            "Betaalcyclus": v.get("cyclus", "4 weken"),
            "Notitie": v.get("notitie", ""),
        })
    df = pd.DataFrame(rows)

    edited = st.data_editor(
        df,
        key="adm_editor",
        use_container_width=True,
        hide_index=True,
        column_config={
            "user_key": None,  # verbergen
            "Naam": st.column_config.TextColumn(disabled=True),
            "E-mail": st.column_config.TextColumn(disabled=True),
            "Pakket": st.column_config.SelectboxColumn(options=list(PAKKETTEN.keys()), required=True),
            "Coach": st.column_config.SelectboxColumn(options=COACHES, required=True),
            "Status": st.column_config.SelectboxColumn(options=STATUSSEN, required=True),
            "Betaalcyclus": st.column_config.SelectboxColumn(options=CYCLI, required=True),
            "Notitie": st.column_config.TextColumn(),
        },
    )

    if st.button("💾 Klantgegevens opslaan", type="primary", key="adm_save_clients"):
        nieuw = dict(admin)
        for _, r in edited.iterrows():
            nieuw[r["user_key"]] = {
                "pakket": r["Pakket"],
                "coach": r["Coach"],
                "status": r["Status"],
                "cyclus": r["Betaalcyclus"],
                "notitie": r["Notitie"] or "",
            }
        ok, err = _save_admin(nieuw)
        if ok:
            st.success("Klantgegevens opgeslagen.")
            st.rerun()
        else:
            st.error(f"Opslaan mislukt: {err}")
