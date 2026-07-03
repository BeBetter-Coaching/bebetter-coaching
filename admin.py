"""Module 8 — Administratie (verborgen, alleen voor Jip).

Klantadministratie bovenop de FinalSurge-koppeling, een KOR-omzettracker
en een dashboard. Handmatige velden (status, pakket, coach, betaalcyclus,
notitie) worden los opgeslagen en nooit door een sync overschreven.
"""

from __future__ import annotations

import re
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
# Per 1 augustus 2026 verlaat BeBetter de KOR en wordt btw gerekend.
# Tot die datum: KOR-bewaking + rek-monitor; daarna: btw-modus.
KOR_TOT = date(2026, 8, 1)
BTW_PCT = 21
# 4-weken-pakket → 13 periodes per jaar (52 / 4)
PERIODES_PER_JAAR = 13

# Standaard omschakel-to-do's (KOR → btw). Volgorde = logische werkvolgorde.
BTW_TODO_STANDAARD = [
    "Afmelden KOR bij de Belastingdienst (vóór 1 augustus) — juiste melding checken met je boekhouder",
    "Btw-tarief per dienst bevestigen met je boekhouder (21%, evt. uitzonderingen voor sport)",
    "Btw-nummer controleren en op het factuursjabloon zetten",
    "Rompslomp: btw aanzetten en alle producten op het juiste btw-tarief",
    "Nieuwe pakketprijzen (+21%) instellen voor nieuwe klanten vanaf 1 augustus",
    "Bestaande klanten: bevestigen dat hun prijs gelijk blijft (btw absorbeer jij)",
    "Apart btw-potje (spaarrekening) openen en automatisch vullen",
    "Bonnetjes en inkoopfacturen bewaren: voorbelasting terugvragen kan vanaf 1 augustus",
    "IB-reservepercentage afstemmen met je boekhouder",
    "Eerste btw-aangifte (Q3 2026, aangifte in oktober) inplannen",
]

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


def klant_is_gratis(athlete: dict, admin: dict) -> bool:
    """True als de klant als vriendendienst (gratis) is gemarkeerd."""
    return bool(admin.get(athlete["user_key"], {}).get("gratis"))


def klant_prijs(athlete: dict, admin: dict, prijzen: dict) -> float:
    """Effectieve 4-wekenprijs van een klant.
    0 bij vriendendienst (gratis); eigen prijs als die is ingevuld (afwijkende/oude
    prijs); anders de standaard pakketprijs."""
    if klant_is_gratis(athlete, admin):
        return 0.0
    v = admin.get(athlete["user_key"], {})
    override = v.get("prijs_override")
    if override:
        try:
            return float(override)
        except (ValueError, TypeError):
            pass
    return effectieve_prijs(klant_pakket(athlete, admin), 0, prijzen)


def geschatte_jaaromzet(athletes: list, admin: dict, prijzen: dict,
                        status_filter: str = "Actief") -> float:
    """Som van effectieve pakketprijzen × 13 periodes voor klanten met die status.
    Vriendendiensten (gratis) tellen mee als klant maar leveren €0 omzet."""
    totaal = 0.0
    for a in athletes:
        v = admin.get(a["user_key"], {})
        if v.get("status", "Actief") != status_filter:
            continue
        totaal += klant_prijs(a, admin, prijzen) * PERIODES_PER_JAAR
    return totaal


NL_MAANDEN = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]
VOLLE_MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli",
                 "augustus", "september", "oktober", "november", "december"]


def jaar_maandomzet(revenue_cum: dict, jaar: int) -> dict:
    """Cumulatief per maand → omzet PER maand (niet-cumulatief) voor dat jaar. {maand_int: bedrag}."""
    cum: dict[int, float] = {}
    for k, v in revenue_cum.items():
        if k.startswith(f"{jaar}-"):
            try:
                cum[int(k.split("-")[1])] = float(v)
            except (ValueError, IndexError):
                continue
    if not cum:
        return {}
    maand_omzet: dict[int, float] = {}
    prev = 0.0
    for m in range(1, max(cum) + 1):
        if m in cum:
            maand_omzet[m] = round(cum[m] - prev, 2)
            prev = cum[m]
    return maand_omzet


def prognose_maanden(maand_omzet: dict) -> dict:
    """Vul de resterende maanden van het jaar met een prognose o.b.v. het gemiddelde van de laatste 3 maanden."""
    if not maand_omzet:
        return {}
    laatste = max(maand_omzet)
    vals = [maand_omzet[m] for m in sorted(maand_omzet)]
    basis = vals[-3:] if len(vals) >= 3 else vals
    gem = sum(basis) / len(basis)
    return {m: round(gem, 2) for m in range(laatste + 1, 13)}


def omzet_per_pakket(athletes: list, admin: dict, prijzen: dict) -> dict:
    """Geschatte jaaromzet per pakkettype voor actieve klanten. {pakket: bedrag}."""
    per: dict[str, float] = {}
    for a in athletes:
        v = admin.get(a["user_key"], {})
        if v.get("status", "Actief") != "Actief":
            continue
        pk = klant_pakket(a, admin)
        if pk == "—":
            continue
        bedrag = klant_prijs(a, admin, prijzen) * PERIODES_PER_JAAR
        if bedrag <= 0:  # vriendendienst (gratis) telt niet mee in de omzetverdeling
            continue
        per[pk] = per.get(pk, 0.0) + bedrag
    return per


# Omzetcategorieën voor de donut + vaste kleuren (BeBetter dark palet)
CATEGORIE_VOLGORDE = ["Coaching", "Clinics", "Lactaatmetingen", "Strippenkaarten", "Overig"]
CATEGORIE_KLEUR = {
    "Coaching": "#5EE6EB",        # cyan
    "Clinics": "#2876FB",         # blauw
    "Lactaatmetingen": "#FAC775", # amber
    "Strippenkaarten": "#22C55E", # groen
    "Overig": "#8FA8CE",          # grijsblauw
}
# Clinics/bedrijfstrainingen: op betaler-naam óf op omschrijving
_CLINIC_NAMEN = ("gemeente", "optimum")
_CLINIC_WOORDEN = ("clinic", "bedrijfstraining", "bedrijfs training", "workshop")
# Coaching: voluit-pakketnamen + losse trefwoorden + afkortingen (als heel woord)
_COACHING_WOORDEN = [p.lower() for p in PAKKET_PRIJZEN_STD] + [
    "coaching", "begeleiding", "schema", "hardloopschema"]
_COACHING_AFK = {"str", "gb", "hp"}  # Start to Run, Getting Better, High Performer


def factuur_categorie(naam: str, omschrijving: str, bedrag: float = 0) -> str:
    """Deel een factuur in op categorie o.b.v. betaler-naam en omschrijving (factuurregel)."""
    n = (naam or "").lower()
    o = (omschrijving or "").lower()
    if any(w in n for w in _CLINIC_NAMEN) or any(w in o for w in _CLINIC_WOORDEN):
        return "Clinics"
    if "lactaat" in o:
        return "Lactaatmetingen"
    if "strip" in o or "ritten" in o:
        return "Strippenkaarten"
    tokens = set(re.findall(r"[a-zà-ÿ]+", o))
    if any(w in o for w in _COACHING_WOORDEN) or (tokens & _COACHING_AFK):
        return "Coaching"
    return "Overig"


def omzet_per_categorie(facturen: list) -> dict:
    """Werkelijk gefactureerde omzet per categorie (excl. btw na de omschakeling)."""
    per: dict[str, float] = {}
    for f in facturen or []:
        if f.get("status") == "concept":
            continue
        cat = factuur_categorie(f.get("naam", ""), f.get("omschrijving", ""), f.get("bedrag", 0))
        per[cat] = per.get(cat, 0.0) + rompslomp_client.factuur_omzet(f)
    return {k: v for k, v in per.items() if v}


def btw_stand(facturen: list, vandaag: date | None = None) -> dict:
    """
    Btw-overzicht sinds de omschakeling: totaal af te dragen, omzet excl.,
    en de stand van het lopende aangiftekwartaal.
    """
    vandaag = vandaag or date.today()
    btw_totaal = 0.0
    omzet_excl = 0.0
    kw_start_maand = ((vandaag.month - 1) // 3) * 3 + 1
    kw_start = date(vandaag.year, kw_start_maand, 1).isoformat()
    kwartaal_nr = (vandaag.month - 1) // 3 + 1
    btw_kwartaal = 0.0

    for f in facturen or []:
        if f.get("status") == "concept":
            continue
        b = rompslomp_client.factuur_btw(f)
        if b <= 0:
            continue
        btw_totaal += b
        omzet_excl += rompslomp_client.factuur_omzet(f)
        if (f.get("datum") or "") >= kw_start:
            btw_kwartaal += b

    # Aangifte: in de maand ná het kwartaaleinde
    aangifte_maand = VOLLE_MAANDEN[(kwartaal_nr * 3) % 12]
    return {
        "btw_totaal": round(btw_totaal, 2),
        "omzet_excl": round(omzet_excl, 2),
        "kwartaal": f"Q{kwartaal_nr}",
        "btw_kwartaal": round(btw_kwartaal, 2),
        "aangifte_label": f"aangifte in {aangifte_maand}",
    }


def potjes_advies(omzet_netto_ytd: float, kosten_ytd: float, ib_pct: float,
                  buffer_pct: float, btw_pot: float) -> dict:
    """
    Indicatieve verdeling van wat er tot nu toe verdiend is:
    IB-pot en buffer als percentage van de winst; wat overblijft is in
    beginsel privé te onttrekken. Geen belastingadvies — rekenhulp.
    """
    kosten_ytd = round(float(kosten_ytd or 0), 2)
    winst = max(omzet_netto_ytd - kosten_ytd, 0.0)
    ib_pot = round(winst * ib_pct / 100, 2)
    buffer = round(winst * buffer_pct / 100, 2)
    prive = round(winst - ib_pot - buffer, 2)
    return {
        "kosten_ytd": kosten_ytd,
        "winst": round(winst, 2),
        "ib_pot": ib_pot,
        "buffer": buffer,
        "btw_pot": round(btw_pot, 2),
        "prive": prive,
    }


def facturen_per_categorie(facturen: list) -> dict:
    """Groepeer facturen per categorie (voor de uitklapbare details)."""
    groepen: dict[str, list] = {}
    for f in facturen or []:
        if f.get("status") == "concept":
            continue
        cat = factuur_categorie(f.get("naam", ""), f.get("omschrijving", ""), f.get("bedrag", 0))
        groepen.setdefault(cat, []).append(f)
    return groepen


def _naam_tokens(s: str) -> set:
    """Naam → set van losse woorden (lowercase, leestekens weg) voor matching."""
    return set(re.sub(r"[^a-zà-ÿ ]", " ", (s or "").lower()).split())


# Tussenvoegsels tellen niet mee bij het matchen van de achternaam.
_TUSSENVOEGSELS = {"van", "de", "den", "der", "ten", "te", "het", "op", "aan",
                   "in", "du", "la", "le", "von", "of"}


def _achternaam_kern(last_name: str) -> set:
    """Kernwoorden van de achternaam, zonder tussenvoegsels (bijv. 'De Rijder' -> {rijder})."""
    toks = _naam_tokens(last_name)
    kern = {t for t in toks if t not in _TUSSENVOEGSELS}
    return kern or toks


def match_contact_fs(contact: dict, athletes: list) -> str:
    """Koppel een Rompslomp-contact aan een FinalSurge-klant (e-mail óf achternaam-kern).
    Geeft de FinalSurge-naam terug, of '' als er geen match is."""
    email = (contact.get("email", "") or "").strip().lower()
    if email:
        for a in athletes:
            if (a.get("email", "") or "").strip().lower() == email:
                return a["name"]
    ctoks = _naam_tokens(contact.get("naam", ""))
    for a in athletes:
        kern = _achternaam_kern(a.get("last_name", ""))
        if kern and kern.issubset(ctoks):
            return a["name"]
    return ""


def niet_gefactureerde_klanten(athletes: list, admin: dict, facturen: list) -> list:
    """
    Actieve, niet-gratis klanten zonder gematchte factuur dit jaar.
    Match = de kern van de achternaam (zonder tussenvoegsels) staat op een factuur,
    óf het e-mailadres van de betaler komt overeen (vangt 'partner/ouder betaalt').
    Klanten met 'Vooruitbetaald t/m' in de toekomst vallen buiten het signaal.
    Naam-matching is niet 100% sluitend, dus een hint.
    """
    losse = [f for f in (facturen or []) if f.get("status") != "concept"]
    factuur_tokens = [_naam_tokens(f.get("naam", "")) for f in losse]
    factuur_emails = {(f.get("email") or "").strip().lower() for f in losse if f.get("email")}
    vandaag = date.today().isoformat()
    result = []
    for a in athletes:
        v = admin.get(a["user_key"], {})
        if v.get("status", "Actief") != "Actief" or v.get("gratis"):
            continue
        if v.get("vooruitbetaald_tot") and vandaag <= str(v["vooruitbetaald_tot"]):
            continue
        email = (a.get("email", "") or "").strip().lower()
        if email and email in factuur_emails:
            continue
        kern = _achternaam_kern(a.get("last_name", ""))
        if not kern:
            continue  # geen achternaam om op te matchen → niet flaggen
        if any(kern.issubset(ft) for ft in factuur_tokens):
            continue
        result.append(a)
    return result


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
    # Werkelijke kosten dit jaar (uit de journaalboekingen) — voor de potjes
    _kosten, _kerr = rompslomp_client.get_kosten_ytd(jaar)
    st.session_state["_rompslomp_kosten_ytd"] = None if _kerr else _kosten
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


def _eur0(v) -> str:
    """Hele euro's, met punt als duizendtalscheiding: '€ 14.860'."""
    try:
        return "€ " + f"{float(v):,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return "€ 0"


DASH_CSS = """
<style>
/* BeBetter dark design system — navy #081830 / surface #0E2547 / cyan #5EE6EB */
.bb-card{background:linear-gradient(135deg,#0B1F3A 0%,#0E2547 60%,#10294E 100%);
  border:1px solid #1E3A66;border-radius:16px;padding:18px 20px;height:100%;
  box-shadow:0 14px 32px rgba(2,10,26,0.45);transition:transform .2s ease,border-color .2s ease}
.bb-card:hover{transform:translateY(-3px);border-color:rgba(94,230,235,0.45)}
.bb-card-label{font-size:.74rem;color:#8FA8CE;margin-bottom:10px;display:flex;justify-content:space-between;
  letter-spacing:.04em;text-transform:uppercase;font-weight:700}
.bb-card-value{font-size:1.85rem;font-weight:800;color:#FFFFFF;line-height:1.1;letter-spacing:-.01em}
.bb-card-delta{font-size:.78rem;margin-top:8px;font-weight:600}
.bb-card-delta.up{color:#5EE6EB}
.bb-card-delta.down{color:#FF8A8A}
.bb-card-sub{font-size:.78rem;color:#5B7396;margin-top:8px}
.bb-section-title{font-weight:700;color:#5EE6EB;font-size:.74rem;margin:2px 0 10px;
  letter-spacing:.20em;text-transform:uppercase}
.kor-pct{font-family:'Archivo Black','Inter',sans-serif;font-size:2.6rem;font-weight:800;color:#5EE6EB;line-height:1}
.kor-pct-sub{font-size:.8rem;color:#8FA8CE;margin-top:5px}
.kor-bar{position:relative;height:26px;border-radius:13px;background:#10294E;border:1px solid #1E3A66;overflow:hidden}
.kor-fill{position:absolute;left:0;top:0;bottom:0;border-radius:13px;
  background:linear-gradient(90deg,#22C55E 0%,#86C440 55%,#FAC775 100%)}
.kor-marker{position:absolute;top:-3px;bottom:-3px;width:0;border-left:2px dashed #EAF2FF}
.kor-leg{display:flex;gap:18px;margin-top:12px;font-size:.78rem;color:#8FA8CE;flex-wrap:wrap}
.kor-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
.sig{display:flex;gap:12px;align-items:flex-start;background:#0E2547;border:1px solid #1E3A66;
  border-radius:12px;padding:13px 15px;margin-bottom:10px}
.sig-ico{font-size:1.05rem;line-height:1.3}
.sig-t{font-weight:700;color:#EAF2FF;font-size:.9rem}
.sig-d{color:#8FA8CE;font-size:.8rem;margin-top:2px}
</style>
"""


def _card(label: str, value: str, extra_html: str = "") -> str:
    return (f"<div class='bb-card'><div class='bb-card-label'><span>{label}</span>"
            f"<span style='color:#cbd0d8'>&#9432;</span></div>"
            f"<div class='bb-card-value'>{value}</div>{extra_html}</div>")


def _sig(ico: str, titel: str, detail: str) -> str:
    return (f"<div class='sig'><div class='sig-ico'>{ico}</div>"
            f"<div><div class='sig-t'>{titel}</div><div class='sig-d'>{detail}</div></div></div>")


def _visueel_dashboard(athletes, actief, on_hold, admin, prijzen, proj,
                       revenue_cum, facturen, last_act):
    """Rendert het visuele administratie-dashboard (KPI's, KOR-gauge, grafieken, signalen)."""
    try:
        import plotly.graph_objects as go
    except Exception:
        go = None

    st.markdown(DASH_CSS, unsafe_allow_html=True)
    jaar = date.today().year
    CYAN = "#5EE6EB"
    AMBER = "#FAC775"

    maand_omzet = jaar_maandomzet(revenue_cum, jaar)
    sorted_m = sorted(maand_omzet)
    omzet_ytd = proj["huidig"]
    omzet_maand = maand_omzet.get(sorted_m[-1], 0.0) if sorted_m else 0.0
    ruimte = max(proj["resterend"], 0)
    pct_kor = (omzet_ytd / KOR_GRENS * 100) if KOR_GRENS else 0

    # Delta omzet deze maand vs vorige maand
    maand_delta = ""
    if len(sorted_m) >= 2 and maand_omzet[sorted_m[-2]]:
        pct = (maand_omzet[sorted_m[-1]] - maand_omzet[sorted_m[-2]]) / maand_omzet[sorted_m[-2]] * 100
        kl, tk = ("up", "+") if pct >= 0 else ("down", "")
        maand_delta = f"<div class='bb-card-delta {kl}'>{tk}{pct:.1f}% t.o.v. vorige maand</div>"

    # ── KPI-tegels ──
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_card("Omzet YTD", _eur0(omzet_ytd)), unsafe_allow_html=True)
    k2.markdown(_card("Omzet deze maand", _eur0(omzet_maand), maand_delta), unsafe_allow_html=True)
    gratis_n = sum(1 for a in actief if klant_is_gratis(a, admin))
    _k3_sub = (f"{gratis_n} vriendendienst · " if gratis_n else "") + f"{len(on_hold)} on hold"
    k3.markdown(_card("Actieve klanten", str(len(actief)),
                      f"<div class='bb-card-sub'>{_k3_sub}</div>"), unsafe_allow_html=True)
    btw_modus = date.today() >= KOR_TOT
    btw = btw_stand(facturen) if btw_modus else None
    if btw_modus:
        k4.markdown(_card("Btw-pot (af te dragen)", _eur0(btw["btw_totaal"]),
                          f"<div class='bb-card-sub'>{btw['kwartaal']}: {_eur0(btw['btw_kwartaal'])} · "
                          f"{btw['aangifte_label']}</div>"), unsafe_allow_html=True)
    else:
        k4.markdown(_card("Ruimte tot KOR-grens", _eur0(ruimte),
                          f"<div class='bb-card-sub'>van {_eur0(KOR_GRENS)} · KOR t/m 31 juli</div>"),
                    unsafe_allow_html=True)

    st.write("")

    if not btw_modus:
        # ── KOR-status gauge + rek-monitor (t/m 31 juli) ──
        st.markdown("<div class='bb-section-title'>KOR-status · t/m 31 juli</div>",
                    unsafe_allow_html=True)
        gc1, gc2 = st.columns([1, 3.2])
        with gc1:
            st.markdown(f"<div class='kor-pct'>{pct_kor:.1f}%</div>"
                        f"<div class='kor-pct-sub'>benut van de KOR-grens</div>", unsafe_allow_html=True)
            _dagen_rek = (KOR_TOT - date.today()).days
            st.markdown(f"<div class='kor-pct-sub'>Nog <b>{_dagen_rek} dagen</b> tot de btw-start "
                        f"(1 augustus)</div>", unsafe_allow_html=True)
        with gc2:
            fillpct = min(pct_kor, 100)
            st.markdown(
                "<div style='display:flex;justify-content:space-between;font-size:.8rem;color:#8FA8CE;margin-bottom:6px'>"
                f"<span>{_eur0(omzet_ytd)} gebruikt</span><span>{_eur0(KOR_GRENS)} KOR-grens</span></div>"
                f"<div class='kor-bar'><div class='kor-fill' style='width:{fillpct}%'></div>"
                f"<div class='kor-marker' style='left:{fillpct}%'></div></div>"
                "<div class='kor-leg'>"
                "<span><span class='kor-dot' style='background:#16a34a'></span>Veilig (&lt; 80%)</span>"
                "<span><span class='kor-dot' style='background:#f59e0b'></span>Let op (80% - 100%)</span>"
                "<span><span class='kor-dot' style='background:#d92d20'></span>Grens overschreden (&gt; 100%)</span>"
                "</div>", unsafe_allow_html=True)
            # Rek-monitor: de grens mag vóór 1 aug NIET geraakt worden
            if ruimte > 0:
                st.markdown(
                    f"<div class='kor-pct-sub' style='margin-top:8px'>🎯 <b>Rek-monitor:</b> nog maximaal "
                    f"<b>{_eur0(ruimte)}</b> factureren t/m 31 juli. Alles daarboven doorschuiven naar "
                    f"augustus (wordt dan btw-omzet). Raak je de grens eerder, dan stopt de KOR op dat "
                    f"moment, niet op 1 augustus.</div>", unsafe_allow_html=True)
            else:
                st.error("De KOR-grens is geraakt — de KOR is daarmee al vervallen. "
                         "Overleg met je boekhouder over de gevolgen voor de grensoverschrijdende factuur.")
    else:
        # ── Btw-overzicht (vanaf 1 augustus) ──
        st.markdown("<div class='bb-section-title'>Btw · sinds 1 augustus</div>",
                    unsafe_allow_html=True)
        bc1, bc2, bc3 = st.columns(3)
        bc1.markdown(_card("Omzet excl. btw (sinds 1 aug)", _eur0(btw["omzet_excl"])),
                     unsafe_allow_html=True)
        bc2.markdown(_card(f"Af te dragen {btw['kwartaal']}", _eur0(btw["btw_kwartaal"]),
                           f"<div class='bb-card-sub'>{btw['aangifte_label']}</div>"),
                     unsafe_allow_html=True)
        bc3.markdown(_card("Btw totaal (sinds 1 aug)", _eur0(btw["btw_totaal"]),
                           "<div class='bb-card-sub'>zet dit bedrag apart</div>"),
                     unsafe_allow_html=True)
        st.caption("Berekend uit je Rompslomp-facturen (incl. minus excl. per factuur). "
                   "De KOR-periode t/m 31 juli telt hier niet in mee.")

    st.write("")

    # ── Potjes: waar moet je omzet heen ──
    st.markdown("<div class='bb-section-title'>Potjes · indicatief</div>", unsafe_allow_html=True)
    try:
        inst = {**{"ib_pct": 45, "buffer_pct": 10, "kosten_pm": 250},
                **(intake_store.load_btw_instellingen() or {})}
    except Exception:
        inst = {"ib_pct": 45, "buffer_pct": 10, "kosten_pm": 250}
    # Werkelijke kosten uit Rompslomp (bij de dagelijkse sync opgehaald);
    # alleen als die er niet zijn valt de schatting per maand in.
    _kosten_echt = st.session_state.get("_rompslomp_kosten_ytd")
    if _kosten_echt is not None:
        _kosten_ytd = float(_kosten_echt)
        _kosten_bron = f"werkelijke kosten uit Rompslomp ({_eur0(_kosten_ytd)})"
    else:
        _kosten_ytd = inst["kosten_pm"] * date.today().month
        _kosten_bron = f"geschatte kosten ({_eur0(_kosten_ytd)} = {_eur0(inst['kosten_pm'])}/mnd)"
    potjes = potjes_advies(omzet_ytd, _kosten_ytd, inst["ib_pct"],
                           inst["buffer_pct"], (btw or {}).get("btw_totaal", 0.0))
    p1, p2, p3, p4 = st.columns(4)
    p1.markdown(_card("IB-pot (inkomstenbelasting)", _eur0(potjes["ib_pot"]),
                      f"<div class='bb-card-sub'>{inst['ib_pct']:.0f}% van {_eur0(potjes['winst'])} winst · "
                      f"naast loondienst</div>"),
                unsafe_allow_html=True)
    p2.markdown(_card("Btw-pot", _eur0(potjes["btw_pot"]),
                      "<div class='bb-card-sub'>af te dragen, niet jouw geld</div>"),
                unsafe_allow_html=True)
    p3.markdown(_card("Buffer", _eur0(potjes["buffer"]),
                      f"<div class='bb-card-sub'>{inst['buffer_pct']:.0f}% van de winst</div>"),
                unsafe_allow_html=True)
    p4.markdown(_card("Privé te onttrekken", _eur0(potjes["prive"]),
                      "<div class='bb-card-sub'>winst minus IB-pot en buffer</div>"),
                unsafe_allow_html=True)
    st.caption(f"Rekenhulp, geen belastingadvies: winst = netto-omzet YTD ({_eur0(omzet_ytd)}) minus "
               f"{_kosten_bron}. De IB-reserve staat op {inst['ib_pct']:.0f}% omdat de winst bovenop "
               "een fulltime loondienst-inkomen komt en dus grotendeels in de hoogste schijf valt "
               "(de MKB-winstvrijstelling dempt dat iets). Stem het exacte percentage af met je boekhouder.")
    st.write("")

    # ── Omzetverloop + donut ──
    mc1, mc2 = st.columns([1.7, 1])
    with mc1:
        st.markdown(f"<div class='bb-section-title'>Omzetverloop {jaar}</div>", unsafe_allow_html=True)
        if go and maand_omzet:
            prog = prognose_maanden(maand_omzet)
            laatste = max(maand_omzet)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=[NL_MAANDEN[m - 1] for m in sorted_m], y=[maand_omzet[m] for m in sorted_m],
                name="Realisatie", mode="lines+markers",
                line=dict(color=CYAN, width=3), marker=dict(size=7, color=CYAN)))
            if prog:
                fig.add_trace(go.Scatter(
                    x=[NL_MAANDEN[laatste - 1]] + [NL_MAANDEN[m - 1] for m in sorted(prog)],
                    y=[maand_omzet[laatste]] + [prog[m] for m in sorted(prog)],
                    name="Prognose", mode="lines+markers",
                    line=dict(color=AMBER, width=2, dash="dot"), marker=dict(size=6, color=AMBER)))
            fig.update_layout(
                height=300, margin=dict(l=0, r=0, t=10, b=0),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                            font=dict(color="#8FA8CE")),
                yaxis=dict(tickprefix="€ ", gridcolor="#1E3A66", zeroline=False, color="#8FA8CE"),
                xaxis=dict(showgrid=False, categoryorder="array", categoryarray=NL_MAANDEN,
                           color="#8FA8CE"),
                font=dict(color="#8FA8CE"))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            st.caption(f"Realisatie {NL_MAANDEN[sorted_m[0] - 1].lower()}–{NL_MAANDEN[laatste - 1].lower()}: "
                       f"**{_eur0(omzet_ytd)}** (YTD)")
        else:
            st.caption("Nog geen maandcijfers beschikbaar." if maand_omzet else
                       "Plotly niet beschikbaar — voeg 'plotly' toe aan requirements.txt.")
    with mc2:
        st.markdown("<div class='bb-section-title'>Omzet per categorie</div>", unsafe_allow_html=True)
        per = omzet_per_categorie(facturen)
        if go and per:
            labels = ([c for c in CATEGORIE_VOLGORDE if c in per]
                      + [c for c in per if c not in CATEGORIE_VOLGORDE])
            values = [per[c] for c in labels]
            colors = [CATEGORIE_KLEUR.get(c, "#1E3A66") for c in labels]
            fig2 = go.Figure(go.Pie(
                labels=labels, values=values, hole=.62, sort=False, direction="clockwise",
                marker=dict(colors=colors, line=dict(color="#081830", width=2)),
                textinfo="percent", textfont=dict(color="#081830", size=12)))
            fig2.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                               plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                               legend=dict(orientation="v", x=1, y=.5, font=dict(color="#C9D8F0")),
                               font=dict(color="#8FA8CE"))
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
            st.caption(f"Werkelijk gefactureerd in {jaar}: **{_eur0(sum(values))}** — uit Rompslomp, "
                       "ingedeeld op betaler en factuuromschrijving.")
        elif per:
            for k in sorted(per, key=lambda x: -per[x]):
                st.caption(f"{k}: {_eur0(per[k])}")
        else:
            st.caption("Nog geen facturen geladen — sync hieronder met Rompslomp.")

    # ── Categorie-details: één compacte kijker i.p.v. losse uitklapmenu's ──
    cat_groepen = facturen_per_categorie(facturen)
    if cat_groepen:
        _volgorde = ([c for c in CATEGORIE_VOLGORDE if c in cat_groepen]
                     + [c for c in cat_groepen if c not in CATEGORIE_VOLGORDE])
        with st.expander("🔍 Facturen per categorie bekijken"):
            _labels = {}
            for cat in _volgorde:
                som = sum(rompslomp_client.factuur_omzet(f) for f in cat_groepen[cat])
                _labels[f"{cat} — {_eur0(som)} · {len(cat_groepen[cat])} facturen"] = cat
            _keuze = st.selectbox("Categorie", list(_labels), label_visibility="collapsed",
                                  key="adm_cat_kijker")
            items = sorted(cat_groepen[_labels[_keuze]],
                           key=lambda f: f.get("datum", ""), reverse=True)
            st.dataframe(
                pd.DataFrame([{
                    "Datum": f.get("datum", ""),
                    "Klant": f.get("naam", ""),
                    "Omschrijving": f.get("omschrijving", ""),
                    "Bedrag": f.get("bedrag", 0),
                    "Status": "Betaald" if f.get("betaald") else "Open",
                } for f in items]),
                hide_index=True, use_container_width=True,
                column_config={"Bedrag": st.column_config.NumberColumn(format="€ %.2f")})

    st.write("")

    # ── Laatste facturen + signalen ──
    fc1, fc2 = st.columns([1.7, 1])
    with fc1:
        st.markdown("<div class='bb-section-title'>Laatste facturen</div>", unsafe_allow_html=True)
        rijen = sorted([f for f in (facturen or []) if f.get("status") != "concept"],
                       key=lambda f: f.get("datum", ""), reverse=True)[:6]
        if rijen:
            df = pd.DataFrame([{"Datum": f.get("datum", ""), "Klant": f.get("naam", ""),
                                "Bedrag": f.get("bedrag", 0),
                                "Status": "Betaald" if f.get("betaald") else "Open"} for f in rijen])
            st.dataframe(df, hide_index=True, use_container_width=True,
                         column_config={"Bedrag": st.column_config.NumberColumn(format="€ %.2f")})
        else:
            st.caption("Nog geen facturen geladen — sync hieronder met Rompslomp.")
    with fc2:
        st.markdown("<div class='bb-section-title'>Signalen</div>", unsafe_allow_html=True)
        sig_html = ""
        if btw_modus:
            sig_html += _sig("&#129534;", f"Btw {btw['kwartaal']}: {_eur0(btw['btw_kwartaal'])} af te dragen",
                             f"{btw['aangifte_label'].capitalize()}. Zorg dat de btw-pot gevuld is.")
        elif pct_kor >= 100:
            sig_html += _sig("&#128680;", "KOR-grens overschreden",
                             f"{pct_kor:.1f}% benut. Let op de fiscale gevolgen.")
        elif pct_kor >= 70:
            sig_html += _sig("&#9888;&#65039;", f"KOR-grens nadert: {pct_kor:.1f}% benut",
                             f"Nog {_eur0(ruimte)} factureerbaar t/m 31 juli; schuif de rest naar augustus.")
        else:
            sig_html += _sig("&#9989;", f"Ruim binnen KOR: {pct_kor:.1f}% benut",
                             f"Nog {_eur0(ruimte)} ruimte tot de grens.")
        open_f = [f for f in (facturen or [])
                  if f.get("open_bedrag", 0) > 0 and f.get("status") != "concept"]
        if open_f:
            som = sum(f.get("open_bedrag", 0) for f in open_f)
            _deels = sum(1 for f in open_f if f.get("open_bedrag", 0) < (f.get("bedrag") or 0))
            sig_html += _sig("&#128196;", f"{len(open_f)} openstaande facturen ({_eur0(som)} te ontvangen)",
                             ("Inclusief betalingsregelingen: alleen het restant telt. "
                              if _deels else "") + "Verstuur waar nodig een herinnering.")
        niet_gef = niet_gefactureerde_klanten(athletes, admin, facturen) if facturen else []
        if niet_gef:
            sig_html += _sig("&#129534;", f"{len(niet_gef)} klanten nog niet gefactureerd in {jaar}",
                             "Werk ze af op het tabblad Facturatie.")
        st.markdown(sig_html, unsafe_allow_html=True)

        if last_act is not None:
            grens_dt = (date.today() - timedelta(days=21)).isoformat()
            stil = [a["name"] for a in actief if (last_act.get(a["user_key"]) or "") < grens_dt]
            if stil:
                st.markdown(_sig("&#128101;", f"{len(stil)} klanten zonder recente activiteit",
                                 ", ".join(stil[:6]) + ("…" if len(stil) > 6 else "")), unsafe_allow_html=True)
            else:
                st.markdown(_sig("&#128077;", "Alle actieve klanten trainden recent",
                                 "Geen inactiviteit in de laatste 3 weken."), unsafe_allow_html=True)
        else:
            if st.button("🔄 Check inactieve klanten", use_container_width=True, key="dash_inact"):
                with st.spinner("Laatste activiteit ophalen…"):
                    st.session_state["_admin_last_act"] = fs_client.get_last_activity_dates(60)
                st.rerun()


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

    # Rompslomp-sync eerst, zodat het dashboard verse omzet + facturen toont.
    if rompslomp_client.is_configured():
        revenue, proj = _sync_rompslomp_indien_nodig(revenue, proj, correctie)

    actief = [a for a in athletes if admin.get(a["user_key"], {}).get("status", "Actief") == "Actief"]
    on_hold = [a for a in athletes if admin.get(a["user_key"], {}).get("status") == "On hold"]
    facturen = st.session_state.get("_rompslomp_facturen") or []

    # ── VISUEEL DASHBOARD ──
    # ── Omschakel-to-do (KOR → btw per 1 aug) ──
    if "_btw_todo" not in st.session_state:
        try:
            _opgeslagen = intake_store.load_btw_todo()
        except Exception:
            _opgeslagen = {}
        if not _opgeslagen.get("items"):
            _opgeslagen = {"items": [
                {"id": f"std{i}", "tekst": t, "done": False, "custom": False}
                for i, t in enumerate(BTW_TODO_STANDAARD)]}
        st.session_state["_btw_todo"] = _opgeslagen
    _todo = st.session_state["_btw_todo"]
    _items = _todo.get("items", [])
    _n_done = sum(1 for i in _items if i.get("done"))
    _alles_klaar = _items and _n_done == len(_items)

    def _save_todo():
        st.session_state["_btw_todo"] = _todo
        try:
            intake_store.save_btw_todo(_todo)
        except Exception:
            pass

    with st.expander(
        f"{'✅' if _alles_klaar else '🔀'} Omschakeling KOR → btw (per 1 aug) · "
        f"{_n_done}/{len(_items)} gedaan",
        expanded=not _alles_klaar and date.today() >= KOR_TOT - timedelta(days=45),
    ):
        st.caption("Jouw checklist voor de overstap. Vinkjes worden gedeeld opgeslagen, "
                   "dus jij en Remco zien dezelfde stand. Eigen punten toevoegen kan onderaan.")
        for _it in _items:
            c_chk, c_del = st.columns([8, 1], vertical_alignment="center")
            with c_chk:
                _nieuw = st.checkbox(_it["tekst"], value=bool(_it.get("done")),
                                     key=f"btwtodo_{_it['id']}")
                if _nieuw != bool(_it.get("done")):
                    _it["done"] = _nieuw
                    _save_todo()
                    st.rerun()
            with c_del:
                if _it.get("custom") and st.button("🗑", key=f"btwtodo_del_{_it['id']}",
                                                   help="Eigen punt verwijderen"):
                    _todo["items"] = [x for x in _items if x["id"] != _it["id"]]
                    _save_todo()
                    st.rerun()
        with st.form("btw_todo_add", clear_on_submit=True):
            c_in, c_btn = st.columns([4, 1], vertical_alignment="bottom")
            with c_in:
                _nieuw_punt = st.text_input("Eigen punt toevoegen",
                                            placeholder="bijv. prijsbrief naar klanten sturen")
            with c_btn:
                if st.form_submit_button("➕", use_container_width=True) and _nieuw_punt.strip():
                    from uuid import uuid4
                    _todo.setdefault("items", []).append(
                        {"id": f"c{uuid4().hex[:8]}", "tekst": _nieuw_punt.strip(),
                         "done": False, "custom": True})
                    _save_todo()
                    st.rerun()

    st.markdown("### 📊 Administratie")
    _bron = st.session_state.get("_rompslomp_bron", "")
    st.caption(f"Financiële cockpit · data uit Rompslomp en FinalSurge. {_bron}")

    tab_dash, tab_fact, tab_klant, tab_beheer = st.tabs(
        ["📊 Dashboard", "🧾 Facturatie", "👥 Klanten", "⚙️ Beheer"])

    # ══ TAB 1 — DASHBOARD (alleen kijken, geen knoppen nodig) ══
    with tab_dash:
        _visueel_dashboard(athletes, actief, on_hold, admin, prijzen, proj,
                           _met_correctie(revenue, correctie), facturen, last_act)

    # ══ TAB 2 — FACTURATIE (alles waar je iets mee moet) ══
    with tab_fact:
        if rompslomp_client.is_configured():
            fc_sync1, fc_sync2 = st.columns([3, 1], vertical_alignment="center")
            with fc_sync1:
                st.caption("Facturen en omzet komen automatisch uit Rompslomp "
                           "(één sync per dag bij het openen van de module).")
            with fc_sync2:
                if st.button("🔄 Sync nu", key="adm_rompslomp_sync", use_container_width=True):
                    _doe_rompslomp_sync(revenue)
                    st.rerun()

            _niet_gef = niet_gefactureerde_klanten(athletes, admin, facturen) if facturen else []
            if _niet_gef:
                st.markdown(f"**🧾 Nog niet gefactureerd dit jaar ({len(_niet_gef)})**")
                st.caption("Actieve, niet-gratis klanten zonder gematchte factuur. Geregeld? "
                           "Vul 'Vooruitbetaald t/m' in of pas de status aan op het tabblad Klanten.")
                st.dataframe(pd.DataFrame([{
                    "Naam": a["name"],
                    "E-mail": a.get("email", "") or "",
                    "Pakket": klant_pakket(a, admin),
                    "Prijs/4wk": round(klant_prijs(a, admin, prijzen), 2),
                } for a in _niet_gef]), hide_index=True, use_container_width=True,
                    column_config={"Prijs/4wk": st.column_config.NumberColumn(format="€ %.2f")})
            elif facturen:
                st.caption("✅ Alle actieve klanten hebben dit jaar een factuur.")

            _open_f = [f for f in (facturen or [])
                       if f.get("open_bedrag", 0) > 0 and f.get("status") != "concept"]
            if _open_f:
                st.markdown(f"**📄 Openstaand ({len(_open_f)} · "
                            f"{_eur0(sum(f.get('open_bedrag', 0) for f in _open_f))} te ontvangen)**")
                st.caption("Bij een betalingsregeling telt alleen het nog openstaande restant.")
                st.dataframe(pd.DataFrame([{
                    "Datum": f["datum"], "Nr": f.get("nummer", ""), "Klant": f["naam"],
                    "Factuurbedrag": f["bedrag"],
                    "Nog open": f.get("open_bedrag", 0),
                    "Status": ("Deels betaald" if f.get("open_bedrag", 0) < (f.get("bedrag") or 0)
                               else "Open"),
                } for f in sorted(_open_f, key=lambda x: x["datum"])]),
                    hide_index=True, use_container_width=True,
                    column_config={
                        "Factuurbedrag": st.column_config.NumberColumn(format="€ %.2f"),
                        "Nog open": st.column_config.NumberColumn(format="€ %.2f"),
                    })

            with st.expander(f"📋 Alle facturen dit jaar ({len(facturen or [])})"):
                if facturen:
                    st.dataframe(pd.DataFrame([{
                        "Datum": f["datum"], "Nr": f.get("nummer", ""), "Klant": f["naam"],
                        "Omschrijving": f.get("omschrijving", ""), "Bedrag": f["bedrag"],
                        "Betaald": "✅" if f.get("betaald") else "openstaand",
                    } for f in sorted(facturen, key=lambda x: x["datum"], reverse=True)
                        if f.get("status") != "concept"]),
                        hide_index=True, use_container_width=True,
                        column_config={"Bedrag": st.column_config.NumberColumn(format="€ %.2f")})
                else:
                    st.caption("Nog geen facturen geladen — klik op Sync nu.")
        else:
            st.caption("💡 Nog niet gekoppeld met Rompslomp. Zet ROMPSLOMP_API_TOKEN in de "
                       "Streamlit-secrets voor automatische omzet, of voer op het tabblad "
                       "Beheer handmatig een omzetbedrag in.")

    # ══ TAB 3 — KLANTEN ══
    with tab_klant:
        st.caption("Live uit FinalSurge; het pakket volgt de FinalSurge-groep (overschrijven kan). "
                   "'Gratis' = vriendendienst, 'Eigen prijs/4wk' = afwijkende (oude) prijs, "
                   "'Vooruitbetaald t/m' = ineens vooruitbetaald. Wordt nooit door een sync overschreven.")

        with st.expander("⚙️ Pakketprijzen (per 4 weken)"):
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

        rows = []
        for a in athletes:
            v = admin.get(a["user_key"], {})
            pakket = klant_pakket(a, admin)
            gratis = bool(v.get("gratis"))
            eigen = float(v.get("prijs_override") or 0)
            vb_val = None
            if v.get("vooruitbetaald_tot"):
                try:
                    vb_val = datetime.fromisoformat(str(v["vooruitbetaald_tot"])).date()
                except ValueError:
                    vb_val = None
            rows.append({
                "user_key": a["user_key"],
                "Naam": a["name"],
                "E-mail": a.get("email", "") or "",
                "Pakket": pakket,
                "Gratis": gratis,
                "Eigen prijs/4wk": eigen,
                "Prijs/4wk": round(klant_prijs(a, admin, prijzen), 2),
                "Coach": v.get("coach", "—"),
                "Status": v.get("status", "Actief"),
                "Betaalcyclus": v.get("cyclus", "4 weken"),
                "Vooruitbetaald t/m": vb_val,
                "Notitie": v.get("notitie", ""),
            })
        df = pd.DataFrame(rows)
        df["Vooruitbetaald t/m"] = pd.to_datetime(df["Vooruitbetaald t/m"], errors="coerce")

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
                "Gratis": st.column_config.CheckboxColumn(
                           help="Vriendendienst: telt mee als actieve klant, maar levert €0 omzet "
                                "en wordt niet in Rompslomp verwacht."),
                "Eigen prijs/4wk": st.column_config.NumberColumn(min_value=0, step=5, format="€%.2f",
                           help="Laat op €0 voor de standaard pakketprijs. Vul het werkelijke bedrag in "
                                "bij een afwijkende prijs, bijv. de oude prijs van vóór de verhoging."),
                "Prijs/4wk": st.column_config.NumberColumn(disabled=True, format="€%.2f",
                           help="Effectieve prijs (berekend): eigen prijs indien ingevuld, anders de "
                                "pakketprijs. €0,00 bij een vriendendienst."),
                "Coach": st.column_config.SelectboxColumn(options=COACHES, required=True),
                "Status": st.column_config.SelectboxColumn(options=STATUSSEN, required=True),
                "Betaalcyclus": st.column_config.SelectboxColumn(options=CYCLI, required=True),
                "Vooruitbetaald t/m": st.column_config.DateColumn(format="DD-MM-YYYY",
                           help="Vul een datum in als de klant vooruit/ineens betaald heeft. Tot die "
                                "datum valt hij buiten het 'nog niet gefactureerd'-signaal."),
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
                _vb = r["Vooruitbetaald t/m"]
                _vb_iso = _vb.date().isoformat() if pd.notna(_vb) else None
                nieuw[r["user_key"]] = {
                    "pakket": _pakket_val,
                    "prijs_override": float(r["Eigen prijs/4wk"]) or None,
                    "gratis": bool(r["Gratis"]),
                    "coach": r["Coach"],
                    "status": r["Status"],
                    "cyclus": r["Betaalcyclus"],
                    "vooruitbetaald_tot": _vb_iso,
                    "notitie": r["Notitie"] or "",
                }
            ok, err = _save_admin(nieuw)
            if ok:
                st.success("Klantgegevens opgeslagen.")
                st.rerun()
            else:
                st.error(f"Opslaan mislukt: {err}")

    # ══ TAB 4 — BEHEER (instellingen en zelden-nodig) ══
    with tab_beheer:
        st.markdown("**⚙️ Potjes-instellingen**")
        st.caption("Bepalen de verdeling op het dashboard. Stem de percentages af met je boekhouder.")
        pi1, pi2, pi3 = st.columns(3)
        try:
            _inst = {**{"ib_pct": 45, "buffer_pct": 10, "kosten_pm": 250},
                     **(intake_store.load_btw_instellingen() or {})}
        except Exception:
            _inst = {"ib_pct": 45, "buffer_pct": 10, "kosten_pm": 250}
        with pi1:
            _ib_in = st.number_input("IB-reserve (% van winst)", min_value=0.0, max_value=60.0,
                                     step=1.0, value=float(_inst["ib_pct"]), key="adm_ib_pct",
                                     help="De winst komt bovenop je fulltime loondienst-inkomen en valt "
                                          "daardoor grotendeels in de hoogste IB-schijf (~49,5%); de "
                                          "MKB-winstvrijstelling dempt dat iets. 45% is een veilige "
                                          "vuistregel — exact percentage via je boekhouder.")
        with pi2:
            _buf_in = st.number_input("Buffer (% van winst)", min_value=0.0, max_value=50.0,
                                      step=1.0, value=float(_inst["buffer_pct"]), key="adm_buf_pct")
        with pi3:
            _kos_in = st.number_input("Kosten per maand (€, alleen fallback)", min_value=0.0, step=25.0,
                                      value=float(_inst["kosten_pm"]), key="adm_kosten_pm",
                                      help="De potjes gebruiken je werkelijke kosten uit Rompslomp. "
                                           "Deze schatting geldt alleen als die even niet opgehaald "
                                           "kunnen worden.")
        if st.button("💾 Potjes opslaan", key="adm_potjes_save"):
            ok, err = intake_store.save_btw_instellingen(
                {"ib_pct": _ib_in, "buffer_pct": _buf_in, "kosten_pm": _kos_in})
            if ok:
                st.success("Opgeslagen.")
                st.rerun()
            else:
                st.error(f"Opslaan mislukt: {err}")

        st.divider()

        if rompslomp_client.is_configured():
            _jaar = str(date.today().year)
            _api_omzet = max((v for k, v in revenue.items() if k.startswith(_jaar)), default=0.0)

            with st.expander("🎯 Bijstellen op je Winst & Verlies (zelden nodig)"):
                st.caption("Alles loopt automatisch via je facturen en boekingen. Klopt de stand een "
                           "keer niet met je Rompslomp Winst & Verlies — bijvoorbeeld door een bedrag "
                           "dat je direct op omzet boekte zonder factuur — vul dan hier je W&V-omzet "
                           "in. De app onthoudt het verschil.")
                _ijk_in = st.number_input("Omzet volgens je Rompslomp W&V (€)", min_value=0.0, step=10.0,
                                          value=float(_api_omzet + correctie), key="adm_kor_ijk")
                ijc1, ijc2 = st.columns([1, 2])
                with ijc1:
                    if st.button("Bijstellen", type="primary", key="adm_kor_ijk_save"):
                        intake_store.save_kor_correctie(round(_ijk_in - _api_omzet, 2))
                        st.rerun()
                with ijc2:
                    if correctie:
                        st.caption(f"Huidige bijstelling: **{_eur(correctie)}** bovenop de "
                                   f"automatische **{_eur(_api_omzet)}**.")

            with st.expander("👥 Rompslomp-contacten (koppelingscontrole)"):
                st.caption("Iedereen die ooit een factuur kreeg in Rompslomp, met of er een "
                           "FinalSurge-klant aan gekoppeld is. Zonder koppeling = clinics, losse "
                           "kopers of oud-klanten.")
                if st.button("Haal Rompslomp-contacten op", key="adm_contacten"):
                    _ct, _cterr = rompslomp_client.get_contacts()
                    st.session_state["_rompslomp_contacten"] = _ct
                    st.session_state["_rompslomp_contacten_err"] = _cterr
                if st.session_state.get("_rompslomp_contacten_err"):
                    st.error(st.session_state["_rompslomp_contacten_err"])
                _ct = st.session_state.get("_rompslomp_contacten")
                if _ct:
                    _gekoppeld = sum(1 for c in _ct if match_contact_fs(c, athletes))
                    st.caption(f"**{len(_ct)} contacten** · {_gekoppeld} gekoppeld aan FinalSurge · "
                               f"{len(_ct) - _gekoppeld} zonder koppeling.")
                    st.dataframe(pd.DataFrame([{
                        "Naam": c["naam"],
                        "E-mail": c["email"],
                        "Nr": c["nummer"],
                        "FinalSurge-klant": match_contact_fs(c, athletes) or "—",
                    } for c in sorted(_ct, key=lambda x: x["naam"])]),
                        use_container_width=True, hide_index=True)
        else:
            with st.expander("➕ Omzetbedrag handmatig invoeren"):
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
                        intake_store.save_revenue(revenue)
                        st.rerun()
