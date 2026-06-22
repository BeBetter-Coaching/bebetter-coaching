"""Rompslomp API-client — facturen ophalen voor de KOR-omzettracker.

Activeert zich alleen als ROMPSLOMP_API_TOKEN én ROMPSLOMP_COMPANY_ID in de
Streamlit-secrets (of omgevingsvariabelen) staan. Anders is is_configured()
False en valt de admin-module terug op handmatige omzetinvoer.

Auth: persoonlijke API-token als 'Authorization: Bearer <token>'.
Endpoints (officiële Swagger): /api/v1/companies/{company_id}/sales_invoices
"""

from __future__ import annotations

import os
from datetime import date

import requests

# Officiële API-host (zie developer.rompslomp.nl)
_BASE_DEFAULT = "https://api.rompslomp.nl/api/v1"
_TIMEOUT = (5, 30)

# Gevonden company_id wordt gecachet zodat we /companies niet elke call herhalen
_company_id_cache: str | None = None

# Omzetbasis voor KOR: turnover is excl. btw. Voor een KOR-deelnemer zonder
# btw zijn beide velden gelijk; we nemen de excl-btw-waarde als omzet.
_OMZET_VELD = "price_without_vat"

_session = requests.Session()


def _secret(naam: str) -> str:
    try:
        import streamlit as st
        val = st.secrets.get(naam, "")
        if val:
            return str(val).strip()
    except Exception:
        pass
    return os.environ.get(naam, "").strip()


def _token() -> str:
    return _secret("ROMPSLOMP_API_TOKEN")


def _company_id_secret() -> str:
    return _secret("ROMPSLOMP_COMPANY_ID")


def _base() -> str:
    return _secret("ROMPSLOMP_API_BASE") or _BASE_DEFAULT


def is_configured() -> bool:
    """True zodra er een API-token is; company_id wordt automatisch opgehaald."""
    return bool(_token())


def get_companies() -> tuple[list[dict], str]:
    """Haal de bedrijven van de token-eigenaar op. Geeft (lijst, foutmelding)."""
    if not _token():
        return [], "Geen API-token ingesteld."
    try:
        resp = _session.get(f"{_base()}/companies", headers=_headers(), timeout=_TIMEOUT)
        if resp.status_code in (401, 403):
            return [], f"Geen toegang ({resp.status_code}). Is de API-token geldig?"
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else (data.get("data") or data.get("companies") or [])
        return items, ""
    except Exception as e:
        return [], str(e)


def _company_id() -> str:
    """
    Bepaal het company_id: handmatig ingesteld secret heeft voorrang, anders
    automatisch het eerste bedrijf van de token-eigenaar (gecachet).
    """
    global _company_id_cache
    handmatig = _company_id_secret()
    if handmatig:
        return handmatig
    if _company_id_cache:
        return _company_id_cache
    companies, _ = get_companies()
    if companies:
        cid = str(companies[0].get("id") or companies[0].get("company_id") or "")
        if cid:
            _company_id_cache = cid
            return cid
    return ""


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/json",
    }


def _parse_bedrag(val) -> float:
    """Parse een bedrag dat als string ('1234.56' of '1234,56') of getal komt."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(" ", "").replace(" ", "")
    # '1.234,56' (NL) → '1234.56'  |  '1234.56' blijft
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _contact_naam(inv: dict) -> str:
    """Haal de klantnaam uit een factuur (cached_contact kan dict of string zijn)."""
    cc = inv.get("cached_contact")
    if isinstance(cc, dict):
        return (cc.get("name") or cc.get("contact_person_name")
                or cc.get("company_name") or "").strip()
    if isinstance(cc, str):
        return cc.strip()
    return ""


def get_invoices(year: int | None = None) -> tuple[list[dict], str]:
    """
    Haal verkoopfacturen op (alle pagina's). Optioneel gefilterd op kalenderjaar.
    Geeft (lijst, foutmelding). Bij fout: ([], reden).

    Elke factuur: {datum, nummer, naam, bedrag (excl btw), bedrag_incl,
    betaald (bool), status}.
    """
    if not is_configured():
        return [], "Rompslomp niet geconfigureerd (API-token ontbreekt)."

    cid = _company_id()
    if not cid:
        return [], ("Kon geen bedrijf (company_id) ophalen via de API. "
                    "Is de API-token geldig en geactiveerd?")

    url = f"{_base()}/companies/{cid}/sales_invoices"
    facturen = []
    page = 1
    try:
        while True:
            resp = _session.get(url, headers=_headers(), timeout=_TIMEOUT,
                                params={"page": page, "per_page": 100})
            if resp.status_code in (401, 403):
                return [], f"Geen toegang ({resp.status_code}). Is de API-token geldig en geactiveerd?"
            if resp.status_code == 404:
                return [], (f"Bedrijf niet gevonden (404). Klopt ROMPSLOMP_COMPANY_ID? "
                            f"Nu ingesteld op '{_company_id()}'. Probeer de naam-slug uit je "
                            f"Rompslomp-URL, bijv. 'bebetter-coaching'.")
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else (data.get("data") or data.get("sales_invoices") or [])
            if not items:
                break
            for inv in items:
                datum = (inv.get("date") or "")[:10]
                if year and not datum.startswith(str(year)):
                    continue
                facturen.append({
                    "datum": datum,
                    "nummer": inv.get("invoice_number"),
                    "naam": _contact_naam(inv),
                    "bedrag": _parse_bedrag(inv.get(_OMZET_VELD)),
                    "bedrag_incl": _parse_bedrag(inv.get("price_with_vat")),
                    "betaald": inv.get("payment_status") == "paid",
                    "status": inv.get("status"),
                })
            if len(items) < 100:
                break
            page += 1
            if page > 50:  # veiligheidsrem
                break
    except Exception as e:
        return [], str(e)

    facturen.sort(key=lambda f: f["datum"])
    return facturen, ""


def get_cumulatieve_omzet(year: int | None = None) -> tuple[dict, str]:
    """
    Bereken cumulatieve omzet per maand voor het jaar, in hetzelfde formaat
    als de handmatige omzetopslag: {'YYYY-MM': cumulatief_bedrag}.
    Alleen gepubliceerde/geïmporteerde facturen tellen mee (geen concepten).
    """
    if year is None:
        year = date.today().year
    facturen, err = get_invoices(year)
    if err:
        return {}, err

    per_maand: dict[str, float] = {}
    for f in facturen:
        if f.get("status") == "concept":
            continue
        maand = f["datum"][:7]
        if len(maand) != 7:
            continue
        per_maand[maand] = per_maand.get(maand, 0.0) + f["bedrag"]

    # Cumulatief opbouwen over alle maanden t/m de laatste met omzet
    cumulatief: dict[str, float] = {}
    loopsom = 0.0
    for m in range(1, 13):
        key = f"{year}-{m:02d}"
        if key in per_maand:
            loopsom += per_maand[key]
            cumulatief[key] = round(loopsom, 2)
        elif cumulatief:  # alleen doorlopen na de eerste maand met omzet
            cumulatief[key] = round(loopsom, 2)
    # Toekomstige maanden zonder omzet weglaten
    vandaag_key = date.today().strftime("%Y-%m")
    cumulatief = {k: v for k, v in cumulatief.items() if k <= vandaag_key}
    return cumulatief, ""
