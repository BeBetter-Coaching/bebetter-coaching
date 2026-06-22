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
                _excl = _parse_bedrag(inv.get("price_without_vat"))
                _incl = _parse_bedrag(inv.get("price_with_vat"))
                # KOR-vrijgesteld → geen btw, dus het totaalbedrag (incl) IS de
                # omzet en is betrouwbaarder gevuld dan het excl-btw-veld.
                bedrag = _incl if _incl else _excl
                facturen.append({
                    "datum": datum,
                    "nummer": inv.get("invoice_number"),
                    "naam": _contact_naam(inv),
                    "bedrag": bedrag,
                    "bedrag_excl": _excl,
                    "bedrag_incl": _incl,
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


def _paged(url: str, key_candidates: tuple) -> tuple[list, str]:
    """Haal alle pagina's van een lijst-endpoint op. Geeft (items, fout)."""
    cid = _company_id()
    if not cid:
        return [], "Geen bedrijf (company_id) beschikbaar."
    items_all = []
    page = 1
    try:
        while True:
            resp = _session.get(f"{_base()}/companies/{cid}/{url}",
                                headers=_headers(), timeout=_TIMEOUT,
                                params={"page": page, "per_page": 100})
            if resp.status_code in (401, 403):
                return [], f"Geen toegang ({resp.status_code})."
            if resp.status_code == 404:
                return [], "404"
            resp.raise_for_status()
            data = resp.json()
            items = data if isinstance(data, list) else next(
                (data.get(k) for k in key_candidates if data.get(k) is not None), [])
            if not items:
                break
            items_all.extend(items)
            if len(items) < 100:
                break
            page += 1
            if page > 100:
                break
    except Exception as e:
        return [], str(e)
    return items_all, ""


def get_accounts() -> tuple[list[dict], str]:
    """Haal de grootboekrekeningen op."""
    return _paged("accounts", ("data", "accounts"))


def _is_revenue_account(acc: dict) -> bool:
    """True als een grootboekrekening een omzetrekening is."""
    t = (acc.get("type") or "").lower()
    p = (acc.get("path") or acc.get("path_name") or "").lower()
    return t == "revenue" or "revenue" in p or "omzet" in p


def get_omzet_per_maand_grootboek(year: int) -> tuple[dict, str]:
    """
    Omzet per maand uit de GROOTBOEKBOEKINGEN: som van (credit - debet) op
    omzetrekeningen. Dit is exact wat Rompslomp als 'Omzet' in Winst & Verlies
    toont — inclusief losse verkopen en handmatige boekingen, niet alleen
    verkoopfacturen. Geeft ({maand: bedrag}, fout).
    """
    accounts, err = get_accounts()
    if err:
        return {}, err
    revenue_ids = {a.get("id") for a in accounts if _is_revenue_account(a)}

    entries, err = _paged("journal_entries", ("data", "journal_entries"))
    if err:
        return {}, err

    per_maand: dict[str, float] = {}
    for e in entries:
        datum = (e.get("date") or "")[:10]
        if not datum.startswith(str(year)) or len(datum) < 7:
            continue
        maand = datum[:7]
        for line in (e.get("lines") or []):
            acc_id = line.get("account_id")
            acc_path = (line.get("account_path") or "").lower()
            is_rev = acc_id in revenue_ids or "revenue" in acc_path or "omzet" in acc_path
            if not is_rev:
                continue
            credit = _parse_bedrag(line.get("credit_amount"))
            debet = _parse_bedrag(line.get("debit_amount"))
            per_maand[maand] = per_maand.get(maand, 0.0) + (credit - debet)
    return per_maand, ""


def _cumulatief_uit_maanden(per_maand: dict, year: int) -> dict:
    """Bouw een cumulatieve {YYYY-MM: bedrag} t/m de huidige maand."""
    cumulatief: dict[str, float] = {}
    loopsom = 0.0
    for m in range(1, 13):
        key = f"{year}-{m:02d}"
        if key in per_maand:
            loopsom += per_maand[key]
            cumulatief[key] = round(loopsom, 2)
        elif cumulatief:
            cumulatief[key] = round(loopsom, 2)
    vandaag_key = date.today().strftime("%Y-%m")
    return {k: v for k, v in cumulatief.items() if k <= vandaag_key}


def diagnose(year: int | None = None) -> dict:
    """Diagnose-info over de grootboek-omzet: wat geeft de API terug?"""
    if year is None:
        year = date.today().year
    out: dict = {}
    accounts, a_err = get_accounts()
    out["accounts_fout"] = a_err
    out["accounts_aantal"] = len(accounts)
    out["accounts_voorbeeld"] = [
        {"id": a.get("id"), "name": a.get("name"), "type": a.get("type"),
         "path": a.get("path") or a.get("path_name")}
        for a in accounts[:8]
    ]
    rev = [a for a in accounts if _is_revenue_account(a)]
    out["omzetrekeningen"] = [{"id": a.get("id"), "name": a.get("name"),
                               "path": a.get("path") or a.get("path_name")} for a in rev]

    entries, e_err = _paged("journal_entries", ("data", "journal_entries"))
    out["journal_fout"] = e_err
    out["journal_aantal"] = len(entries)
    # Eerste boeking met regels als voorbeeld
    for e in entries:
        if e.get("lines"):
            out["journal_voorbeeld"] = {
                "date": e.get("date"),
                "lines": [{"account_id": l.get("account_id"),
                           "account_path": l.get("account_path"),
                           "debit": l.get("debit_amount"), "credit": l.get("credit_amount")}
                          for l in e["lines"][:4]],
            }
            break

    per_maand, pm_err = get_omzet_per_maand_grootboek(year)
    out["omzet_fout"] = pm_err
    out["omzet_per_maand"] = per_maand
    out["omzet_totaal"] = round(sum(per_maand.values()), 2) if per_maand else 0.0
    return out


def get_cumulatieve_omzet(year: int | None = None) -> tuple[dict, str]:
    """
    Cumulatieve omzet per maand voor het jaar, in het formaat {'YYYY-MM': bedrag}.

    Primair uit de grootboekboekingen (= exact de W&V-omzet). Lukt dat niet
    (bijv. geen toegang tot journal_entries), dan terugvallen op de som van
    de verkoopfacturen.
    """
    if year is None:
        year = date.today().year

    per_maand, err = get_omzet_per_maand_grootboek(year)
    if not err and per_maand:
        return _cumulatief_uit_maanden(per_maand, year), ""

    # Fallback: verkoopfacturen
    facturen, ferr = get_invoices(year)
    if ferr:
        return {}, (err or ferr)
    fmaand: dict[str, float] = {}
    for f in facturen:
        if f.get("status") == "concept":
            continue
        maand = f["datum"][:7]
        if len(maand) == 7:
            fmaand[maand] = fmaand.get(maand, 0.0) + f["bedrag"]
    return _cumulatief_uit_maanden(fmaand, year), ""
