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
import rompslomp_client

# ── Pakketten: standaard prijs per 4 weken (instelbaar via de module) ──
PAKKET_PRIJZEN_STD = {
    "Los Schema": 25,
    "Comfort": 55,
    "Start to Run": 65,
    "Getting Better": 95,
    "Premium": 110,
    "High Performer": 135,
}
PAKKETTEN = ["—"] + list(PAKKET_PRIJZEN_STD.keys())
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


def pakket_van_groep(group_name: str) -> str:
    """
    Leid het pakket af uit de FinalSurge-(sub)groep. De subgroepen ZIJN de
    pakketten (Los Schema, Start to Run, Getting Better, Comfort, ...).
    Matcht op losse woorden zodat '1. Los trainingsschema' → 'Los Schema'.
    Geeft '—' als geen pakket past.
    """
    g = (group_name or "").strip().lower()
    if not g:
        return "—"
    # Speciale gevallen waar de groepsnaam afwijkt van de pakketnaam
    if "los" in g and "schema" in g:
        return "Los Schema"
    for pakket in PAKKET_PRIJZEN_STD:
        woorden = pakket.lower().split()
        if all(w in g for w in woorden):
            return pakket
    return "—"


def effectieve_prijs(pakket: str, korting_pct: float, prijzen: dict) -> float:
    """Prijs per 4 weken na korting."""
    basis = prijzen.get(pakket, PAKKET_PRIJZEN_STD.get(pakket, 0))
    try:
        k = max(0.0, min(float(korting_pct or 0), 100.0))
    except (ValueError, TypeError):
        k = 0.0
    return basis * (1 - k / 100)


def klant_pakket(athlete: dict, admin: dict) -> str:
    """Pakket van een klant: handmatige override, anders afgeleid uit de groep."""
    v = admin.get(athlete["user_key"], {})
    if v.get("pakket") and v["pakket"] != "—":
        return v["pakket"]
    return pakket_van_groep(athlete.get("group", ""))


def geschatte_jaaromzet(athletes: list, admin: dict, prijzen: dict,
                        status_filter: str = "Actief") -> float:
    """Som van effectieve pakketprijzen × 13 periodes voor klanten met die status."""
    totaal = 0.0
    for a in athletes:
        v = admin.get(a["user_key"], {})
        if v.get("status", "Actief") != status_filter:
            continue
        pakket = klant_pakket(a, admin)
        totaal += effectieve_prijs(pakket, v.get("korting", 0), prijzen) * PERIODES_PER_JAAR
    return totaal


def _prijzen() -> dict:
    """Pakketprijzen uit opslag, aangevuld met standaardwaarden."""
    opgeslagen = {}
    try:
        opgeslagen = intake_store.load_pakket_prijzen()
    except Exception:
        pass
    return {**PAKKET_PRIJZEN_STD, **opgeslagen}


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


def _doe_rompslomp_sync(revenue: dict) -> tuple[dict, str]:
    """
    Haal de cumulatieve omzet van dit jaar uit Rompslomp en schrijf die over
    de maanden van dit jaar heen in de omzetopslag. Eerdere jaren blijven staan.
    Geeft (bijgewerkte_revenue, foutmelding).
    """
    jaar = date.today().year
    with st.spinner("Rompslomp-facturen ophalen…"):
        cumulatief, err = rompslomp_client.get_cumulatieve_omzet(jaar)
        facturen, _ = rompslomp_client.get_invoices(jaar)
    if err:
        st.session_state["_rompslomp_bron"] = f"⚠️ Sync mislukt: {err}"
        return revenue, err
    # Maanden van dit jaar vervangen door de Rompslomp-waarden
    nieuw = {k: v for k, v in revenue.items() if not k.startswith(str(jaar))}
    nieuw.update(cumulatief)
    intake_store.save_revenue(nieuw)
    st.session_state["_rompslomp_facturen"] = facturen
    st.session_state["_rompslomp_sync_dag"] = date.today().isoformat()
    st.session_state["_rompslomp_bron"] = (
        f"Laatst gesynct: {date.today().strftime('%d-%m-%Y')} "
        f"({len(facturen)} facturen dit jaar)."
    )
    return nieuw, ""


def _sync_rompslomp_indien_nodig(revenue: dict, proj: dict, correctie: float):
    """Eén automatische sync per dag bij het openen van de module."""
    if st.session_state.get("_rompslomp_sync_dag") != date.today().isoformat():
        nieuw, err = _doe_rompslomp_sync(revenue)
        if not err:
            return nieuw, kor_projectie(_met_correctie(nieuw, correctie))
    return revenue, proj


def _met_correctie(revenue: dict, correctie: float) -> dict:
    """
    Tel de overige-omzet-correctie op bij de cumulatieve factuuromzet van het
    lopende jaar (parallelle verschuiving: de eindstand klopt, de trend-helling
    blijft gelijk). Zo loopt de KOR-stand gelijk met Rompslomp Winst & Verlies.
    """
    if not correctie:
        return revenue
    jaar = str(date.today().year)
    return {k: (round(v + correctie, 2) if k.startswith(jaar) else v)
            for k, v in revenue.items()}


def render_admin(athletes_by_group: dict):
    """Hoofdscherm van de administratiemodule."""
    athletes = sorted(
        [a for members in athletes_by_group.values() for a in members],
        key=lambda x: x["name"],
    )
    admin = _admin()
    revenue = _revenue()
    prijzen = _prijzen()
    try:
        correctie = intake_store.load_kor_correctie()
    except Exception:
        correctie = 0.0
    proj = kor_projectie(_met_correctie(revenue, correctie))

    # Inactiviteit (laatste FinalSurge-activiteit) — on demand, gecachet
    last_act = st.session_state.get("_admin_last_act")

    # ── DASHBOARD ──
    st.markdown("### 📊 Dashboard")

    actief = [a for a in athletes if admin.get(a["user_key"], {}).get("status", "Actief") == "Actief"]
    on_hold = [a for a in athletes if admin.get(a["user_key"], {}).get("status") == "On hold"]
    jaaromzet = geschatte_jaaromzet(athletes, admin, prijzen)

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

    # Pakketverdeling van actieve klanten (pakket afgeleid uit de groep)
    verdeling: dict[str, int] = {}
    for a in actief:
        pk = klant_pakket(a, admin)
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

    # Rompslomp-sync: automatisch één keer per dag bij openen, plus handmatig.
    if rompslomp_client.is_configured():
        revenue, proj = _sync_rompslomp_indien_nodig(revenue, proj, correctie)

    pct = min(proj["huidig"] / KOR_GRENS * 100, 100) if KOR_GRENS else 0
    st.progress(pct / 100)
    st.markdown(f"**{_eur(proj['huidig'])}** van {_eur(KOR_GRENS)}  ·  nog **{_eur(proj['resterend'])}** te gaan "
                f"({pct:.0f}%)")

    if rompslomp_client.is_configured():
        _bron = st.session_state.get("_rompslomp_bron", "")
        rc1, rc2 = st.columns([3, 1], vertical_alignment="center")
        with rc1:
            st.caption(f"🔗 Gekoppeld met Rompslomp. {_bron}")
        with rc2:
            if st.button("🔄 Sync nu", key="adm_rompslomp_sync", use_container_width=True):
                _doe_rompslomp_sync(revenue)
                st.rerun()

        st.caption("De omzet komt rechtstreeks uit je grootboek (Winst & Verlies), dus inclusief "
                   "losse verkopen, clinics, strippenkaarten en handmatige boekingen.")

        with st.expander("🔧 Diagnose grootboek (waarom klopt de omzet wel/niet?)"):
            if st.button("Analyseer grootboek", key="adm_diag_grootboek"):
                with st.spinner("Grootboek ophalen…"):
                    st.session_state["_rompslomp_diag"] = rompslomp_client.diagnose()
            _diag = st.session_state.get("_rompslomp_diag")
            if _diag:
                st.write(f"**Facturen-omzet:** {_eur(_diag.get('facturen_omzet', 0))}  ·  "
                         f"**handmatige omzetboekingen:** {_eur(_diag.get('journal_omzet', 0))}  ·  "
                         f"**totaal:** {_eur(_diag.get('totaal_omzet', 0))}")
                st.write(f"**Grootboekrekeningen:** {_diag['accounts_aantal']} "
                         f"(fout: {_diag['accounts_fout'] or 'geen'})")
                st.write(f"**Herkend als omzetrekening:** {len(_diag['omzetrekeningen'])}")
                if _diag["omzetrekeningen"]:
                    st.json(_diag["omzetrekeningen"])
                st.write(f"**Journaalboekingen:** {_diag['journal_aantal']} "
                         f"(fout: {_diag['journal_fout'] or 'geen'})")
                with st.container():
                    st.write("**Alle boekingen:**")
                    st.json(_diag.get("journal_boekingen", []))
                st.markdown("---")
                st.write(f"**Facturen 2026:** {_diag.get('facturen_2026_aantal', 0)} · "
                         f"statussen: {_diag.get('factuur_statussen', [])}")
                st.write("**Beschikbare factuurvelden:**")
                st.json(_diag.get("factuur_velden", []))
                st.write(f"**Facturen die op €0 worden geteld** "
                         f"({len(_diag.get('facturen_op_nul', []))}) — hier zit de gemiste omzet:")
                st.json(_diag.get("facturen_op_nul", []))
        # Vangnet: alleen tonen als er ondanks de grootboek-sync nog een
        # handmatige correctie is ingesteld (normaal niet nodig).
        if correctie:
            with st.expander(f"➕ Handmatige correctie: {_eur(correctie)} (normaal niet nodig)"):
                st.caption("De omzet komt nu uit het grootboek en hoort vanzelf te kloppen met je "
                           "Winst & Verlies. Zet dit op 0 als de stand klopt.")
                _corr_in = st.number_input("Handmatige correctie (€)", min_value=0.0, step=10.0,
                                           value=float(correctie), key="adm_kor_corr")
                if st.button("Opslaan", key="adm_kor_corr_save"):
                    intake_store.save_kor_correctie(_corr_in)
                    st.rerun()
        with st.expander("🧾 Facturen dit jaar (Rompslomp)"):
            _facturen = st.session_state.get("_rompslomp_facturen")
            if _facturen is None:
                st.caption("Klik op 'Sync nu' om de facturen op te halen.")
            elif not _facturen:
                st.caption("Geen facturen gevonden voor dit jaar.")
            else:
                # Reconciliatie: tel mee zoals de KOR-tracker (geen concepten)
                _gepubliceerd = [f for f in _facturen if f.get("status") != "concept"]
                _tot = sum(f["bedrag"] for f in _gepubliceerd)
                st.caption(f"**{len(_gepubliceerd)} facturen** (excl. concepten) · "
                           f"totaal **{_eur(_tot)}**. Vergelijk dit met 'Omzet' in je "
                           f"Rompslomp Winst & Verlies; die horen gelijk te zijn.")
                _df_f = pd.DataFrame([
                    {"Datum": f["datum"], "Nr": f["nummer"], "Klant": f["naam"],
                     "Bedrag": f["bedrag"], "Status": f.get("status", ""),
                     "Betaald": "✅" if f["betaald"] else "openstaand"}
                    for f in _facturen
                ])
                st.dataframe(_df_f, use_container_width=True, hide_index=True,
                             column_config={"Bedrag": st.column_config.NumberColumn(format="€%.2f")})
    else:
        st.caption("💡 Rompslomp-koppeling staat klaar maar is nog niet geconfigureerd. "
                   "Zet ROMPSLOMP_API_TOKEN in de Streamlit-secrets om automatisch te syncen "
                   "(het bedrijf-id wordt automatisch opgehaald). Tot dan kun je hieronder handmatig invoeren.")

    with st.expander("➕ Nieuw cumulatief omzetbedrag handmatig invoeren"):
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

    # ── PAKKETPRIJZEN ──
    with st.expander("⚙️ Pakketprijzen (per 4 weken)"):
        st.caption("Pas de prijs per pakket aan. Geldt voor de omzetschatting van alle klanten.")
        _pcols = st.columns(len(PAKKET_PRIJZEN_STD))
        _nieuw_prijzen = {}
        for _i, _pk in enumerate(PAKKET_PRIJZEN_STD):
            with _pcols[_i]:
                _nieuw_prijzen[_pk] = st.number_input(
                    _pk, min_value=0, step=5, value=int(prijzen.get(_pk, 0)),
                    key=f"prijs_{_pk}",
                )
        if st.button("💾 Prijzen opslaan", key="adm_save_prijzen"):
            ok, err = intake_store.save_pakket_prijzen(_nieuw_prijzen)
            if ok:
                st.success("Pakketprijzen opgeslagen.")
                st.rerun()
            else:
                st.error(f"Opslaan mislukt: {err}")

    st.divider()

    # ── KLANTENLIJST ──
    st.markdown("### 👥 Klantenlijst")
    st.caption("Live uit FinalSurge. Het pakket wordt automatisch afgeleid uit de FinalSurge-groep; "
               "je kunt het overschrijven. Coach, status, betaalcyclus, korting en notitie stel je hier in. "
               "Alles wordt bewaard en nooit door een sync overschreven.")

    rows = []
    for a in athletes:
        v = admin.get(a["user_key"], {})
        pakket = klant_pakket(a, admin)
        korting = float(v.get("korting", 0) or 0)
        rows.append({
            "user_key": a["user_key"],
            "Naam": a["name"],
            "E-mail": a.get("email", "") or "",
            "Pakket": pakket,
            "Korting %": korting,
            "Prijs/4wk": round(effectieve_prijs(pakket, korting, prijzen), 2),
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
            "Pakket": st.column_config.SelectboxColumn(options=PAKKETTEN, required=True,
                       help="Automatisch uit de groep; overschrijven kan."),
            "Korting %": st.column_config.NumberColumn(min_value=0, max_value=100, step=5,
                       help="Korting op de pakketprijs, in procenten."),
            "Prijs/4wk": st.column_config.NumberColumn(disabled=True, format="€%.2f",
                       help="Effectieve prijs na korting (berekend)."),
            "Coach": st.column_config.SelectboxColumn(options=COACHES, required=True),
            "Status": st.column_config.SelectboxColumn(options=STATUSSEN, required=True),
            "Betaalcyclus": st.column_config.SelectboxColumn(options=CYCLI, required=True),
            "Notitie": st.column_config.TextColumn(),
        },
    )

    if st.button("💾 Klantgegevens opslaan", type="primary", key="adm_save_clients"):
        nieuw = dict(admin)
        for _, r in edited.iterrows():
            # Pakket alleen opslaan als override wanneer het afwijkt van de
            # groep-afleiding; anders leeg laten zodat het de groep blijft volgen.
            _afgeleid = pakket_van_groep(
                next((a.get("group", "") for a in athletes if a["user_key"] == r["user_key"]), "")
            )
            _pakket_val = r["Pakket"] if r["Pakket"] != _afgeleid else ""
            nieuw[r["user_key"]] = {
                "pakket": _pakket_val,
                "korting": float(r["Korting %"] or 0),
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
