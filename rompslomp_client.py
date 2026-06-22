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
    """Haal de grootboekrekeningen op (zonder paginatie — endpoint weigert die)."""
    cid = _company_id()
    if not cid:
        return [], "Geen bedrijf (company_id) beschikbaar."
    try:
        resp = _session.get(f"{_base()}/companies/{cid}/accounts",
                            headers=_headers(), timeout=_TIMEOUT)
        if resp.status_code in (401, 403):
            return [], f"Geen toegang ({resp.status_code})."
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else (data.get("data") or data.get("accounts") or [])
        return items, ""
    except Exception as e:
        return [], str(e)


def _path_is_revenue(path: str) -> bool:
    """Herken een omzet-grootboekpad (Rompslomp gebruikt dot-paden)."""
    p = (path or "").lower()
    if any(k in p for k in ("kosten", "cost", "expense")):
        return False
    return any(k in p for k in ("revenue", "omzet", "opbrengst", "turnover", "sales"))


def _is_revenue_account(acc: dict) -> bool:
    """True als een grootboekrekening een omzetrekening is."""
    t = (acc.get("type") or "").lower()
    return t == "revenue" or _path_is_revenue(acc.get("path") or acc.get("path_name") or "")


def get_journal_revenue_per_maand(year: int) -> tuple[dict, str]:
    """
    Omzet per maand uit de HANDMATIGE journaalboekingen (losse verkopen e.d.
    die niet als verkoopfactuur zijn geboekt). Som van (credit - debet) op
    omzetrekeningen. Best effort; bij fout een lege dict + foutmelding.
    """
    accounts, _ = get_accounts()
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
            is_rev = line.get("account_id") in revenue_ids or _path_is_revenue(line.get("account_path"))
            if not is_rev:
                continue
            credit = _parse_bedrag(line.get("credit_amount"))
            debet = _parse_bedrag(line.get("debit_amount"))
            per_maand[maand] = per_maand.get(maand, 0.0) + (credit - debet)
    return per_maand, ""


def _invoice_revenue_per_maand(year: int) -> tuple[dict, str]:
    """Omzet per maand uit verkoopfacturen (geen concepten)."""
    facturen, err = get_invoices(year)
    if err:
        return {}, err
    per_maand: dict[str, float] = {}
    for f in facturen:
        if f.get("status") == "concept":
            continue
        maand = f["datum"][:7]
        if len(maand) == 7:
            per_maand[maand] = per_maand.get(maand, 0.0) + f["bedrag"]
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
    # ALLE boekingen tonen (zijn er weinig) zodat we de omzetregel kunnen vinden
    out["journal_boekingen"] = [
        {"date": e.get("date"),
         "lines": [{"path": l.get("account_path"),
                    "debit": l.get("debit_amount"), "credit": l.get("credit_amount"),
                    "is_omzet": _path_is_revenue(l.get("account_path"))}
                   for l in (e.get("lines") or [])]}
        for e in entries[:20]
    ]

    inv_pm, _ = _invoice_revenue_per_maand(year)
    jr_pm, jr_err = get_journal_revenue_per_maand(year)
    out["facturen_omzet"] = round(sum(inv_pm.values()), 2)
    out["journal_omzet"] = round(sum(jr_pm.values()), 2)
    out["journal_omzet_fout"] = jr_err
    out["totaal_omzet"] = round(sum(inv_pm.values()) + sum(jr_pm.values()), 2)

    # Factuur-diagnose: welke velden heeft een factuur, en welke facturen
    # tellen op €0 (bedrag in onverwacht veld) of hebben geen datum?
    raw_inv, _ = _paged("sales_invoices", ("data", "sales_invoices"))
    out["factuur_velden"] = sorted(raw_inv[0].keys()) if raw_inv else []
    inv_year = [i for i in raw_inv if (i.get("date") or "")[:10].startswith(str(year))]
    out["facturen_2026_aantal"] = len(inv_year)
    verdacht = []
    for i in inv_year:
        excl = _parse_bedrag(i.get("price_without_vat"))
        incl = _parse_bedrag(i.get("price_with_vat"))
        bedrag = incl if incl else excl
        if bedrag <= 0:
            verdacht.append({k: i.get(k) for k in i.keys()
                             if "price" in k or "amount" in k or "total" in k
                             or k in ("invoice_number", "date", "status")})
    out["facturen_op_nul"] = verdacht
    # Facturen met status != published/imported (worden mogelijk wel meegeteld in W&V)
    out["factuur_statussen"] = sorted({(i.get("status") or "?") for i in inv_year})
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

    # Totale omzet = verkoopfacturen + handmatige omzetboekingen (losse verkopen).
    # Beide bronnen zijn gescheiden in Rompslomp (facturen staan NIET in
    # journal_entries), dus optellen geeft exact de W&V-omzet zonder dubbeltelling.
    inv_pm, inv_err = _invoice_revenue_per_maand(year)
    if inv_err:
        return {}, inv_err
    jr_pm, _ = get_journal_revenue_per_maand(year)  # best effort

    per_maand: dict[str, float] = dict(inv_pm)
    for maand, bedrag in jr_pm.items():
        per_maand[maand] = per_maand.get(maand, 0.0) + bedrag
    return _cumulatief_uit_maanden(per_maand, year), ""
