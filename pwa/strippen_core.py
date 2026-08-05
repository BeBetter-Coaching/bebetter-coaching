"""Gedeelde strippenkaart-logica — bruikbaar door zowel de PWA-API als (later)
de Streamlit-app. Praat met dezelfde opslag via `intake_store`, zodat beide
voorkanten op één bron werken (wijziging in de app zie je in Streamlit en andersom).

Bewust gescheiden van Streamlit: geen `st.`-aanroepen hier, alleen pure functies
en opslag-operaties. Het gedrag (nummer-normalisatie, berichten, bulk-parsing)
is 1-op-1 gelijk aan de huidige Streamlit-module.
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
from datetime import date

# repo-root op het pad zodat we het bestaande intake_store kunnen hergebruiken
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import intake_store  # noqa: E402


# ── Pure helpers (identiek aan de Streamlit-module) ─────────────────────────
def normalize_number(raw: str) -> str:
    """06... -> 316..., 0031... -> 31..., +31 -> 31. Alleen cijfers; leeg = ''."""
    if not raw:
        return ""
    s = "".join(ch for ch in str(raw) if ch.isdigit() or ch == "+")
    if s.startswith("+"):
        digits = s[1:]
    elif s.startswith("00"):
        digits = s[2:]
    elif s.startswith("0"):
        digits = "31" + s[1:]
    else:
        digits = s
    return "".join(ch for ch in digits if ch.isdigit())


def wa_link(telefoon: str, tekst: str) -> str:
    """wa.me-link die WhatsApp opent met nummer + voor-ingevuld bericht."""
    nr = normalize_number(telefoon)
    if not nr:
        return ""
    return f"https://wa.me/{nr}?text={urllib.parse.quote(tekst)}"


def afboek_bericht(voornaam: str, rest: int, totaal: int) -> str:
    """Bericht na afboeken, gelijk aan de Streamlit-teksten."""
    if rest <= 0:
        return (f"Hoi {voornaam}, je hebt zojuist je laatste training van de "
                f"strippenkaart afgetekend, de kaart is nu vol. Wil je een "
                f"nieuwe? Laat maar weten!")
    return (f"Hoi {voornaam}, top getraind! Je hebt zojuist een training "
            f"afgeboekt en hebt nog {rest} van je {totaal} trainingen over. "
            f"Tot de volgende!")


def parse_contacts(text: str) -> list[dict]:
    """Parse geplakte regels 'Naam, nummer' (komma/;/tab of nummer achteraan)."""
    out: list[dict] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[\t;,]", line) if p.strip()]
        if len(parts) >= 2 and normalize_number(parts[-1]):
            naam, tel = " ".join(parts[:-1]), parts[-1]
        else:
            m = re.search(r"([+\d][\d\s\-]{6,})\s*$", line)
            if m and normalize_number(m.group(1)):
                naam, tel = line[:m.start()].strip(" ,;\t"), m.group(1).strip()
            else:
                naam, tel = line, ""
        if naam:
            out.append({"naam": naam, "telefoon": tel})
    return out


def parse_vcard(raw: str) -> list[dict]:
    """Parse een .vcf-contactenbestand naar {naam, telefoon} (eerste TEL per kaart)."""
    out: list[dict] = []
    naam, tel = None, None
    for line in (raw or "").splitlines():
        u = line.strip()
        key = u.split(":", 1)[0].upper()
        if key.startswith("BEGIN") and "VCARD" in u.upper():
            naam, tel = None, None
        elif key.startswith("FN") and ":" in u:
            naam = u.split(":", 1)[1].strip()
        elif key.startswith("TEL") and ":" in u and not tel:
            tel = u.split(":", 1)[1].strip()
        elif key.startswith("END") and "VCARD" in u.upper():
            if naam:
                out.append({"naam": naam, "telefoon": tel or ""})
    return out


def parse_any(text: str) -> list[dict]:
    """Kies automatisch tussen vCard en geplakte regels."""
    if "BEGIN:VCARD" in (text or "").upper():
        return parse_vcard(text)
    return parse_contacts(text)


# ── Opslag-operaties (via intake_store, zelfde bron als Streamlit) ──────────
def _view(naam: str, k: dict) -> dict:
    totaal = int(k.get("totaal", 10))
    gebruikt = int(k.get("gebruikt", 0))
    hist = k.get("historie") or []
    return {
        "naam": naam,
        "totaal": totaal,
        "gebruikt": gebruikt,
        "rest": max(0, totaal - gebruikt),
        "telefoon": k.get("telefoon", ""),
        "laatst": hist[-1] if hist else None,
    }


def cloud_backed() -> bool:
    return intake_store.is_cloud_backed()


def list_kaarten() -> list[dict]:
    kaarten = intake_store.load_strippenkaarten()
    return [_view(n, kaarten[n]) for n in sorted(kaarten.keys())]


def add_kaart(naam: str, aantal: int, telefoon: str = "") -> tuple[bool, str]:
    naam = (naam or "").strip()
    if not naam:
        return False, "Vul een naam in."
    kaarten = intake_store.load_strippenkaarten()
    if naam in kaarten:
        return False, "Er bestaat al een strippenkaart met deze naam."
    kaarten[naam] = {
        "totaal": int(aantal), "gebruikt": 0, "historie": [],
        "aangemaakt": date.today().isoformat(), "telefoon": (telefoon or "").strip(),
    }
    return intake_store.save_strippenkaarten(kaarten)


def afboeken(naam: str) -> tuple[bool, str, dict | None]:
    kaarten = intake_store.load_strippenkaarten()
    k = kaarten.get(naam)
    if not k:
        return False, "Onbekende strippenkaart.", None
    totaal = int(k.get("totaal", 10))
    gebruikt = int(k.get("gebruikt", 0))
    if totaal - gebruikt <= 0:
        return False, "Deze kaart is al vol.", None
    k["gebruikt"] = gebruikt + 1
    k.setdefault("historie", []).append(date.today().isoformat())
    ok, err = intake_store.save_strippenkaarten(kaarten)
    if not ok:
        return False, err, None
    rest = max(0, totaal - k["gebruikt"])
    voornaam = naam.split()[0] if naam else naam
    bericht = afboek_bericht(voornaam, rest, totaal)
    return True, "", {
        "rest": rest, "totaal": totaal, "bericht": bericht,
        "wa_link": wa_link(k.get("telefoon", ""), bericht),
        "telefoon": k.get("telefoon", ""),
    }


def terug(naam: str) -> tuple[bool, str]:
    kaarten = intake_store.load_strippenkaarten()
    k = kaarten.get(naam)
    if not k:
        return False, "Onbekende strippenkaart."
    if int(k.get("gebruikt", 0)) <= 0:
        return False, "Er is niets om terug te draaien."
    k["gebruikt"] = max(0, int(k["gebruikt"]) - 1)
    if k.get("historie"):
        k["historie"].pop()
    return intake_store.save_strippenkaarten(kaarten)


def verwijder(naam: str) -> tuple[bool, str]:
    kaarten = intake_store.load_strippenkaarten()
    if naam in kaarten:
        kaarten.pop(naam)
        return intake_store.save_strippenkaarten(kaarten)
    return True, ""


def import_preview(text: str) -> dict:
    rows = parse_any(text)
    bestaand = intake_store.load_strippenkaarten()
    nieuw = [r for r in rows if r["naam"] not in bestaand]
    bestaat = [r for r in rows if r["naam"] in bestaand]
    zonder_nr = [r["naam"] for r in nieuw if not normalize_number(r["telefoon"])]
    return {"nieuw": nieuw, "bestaat": bestaat, "zonder_nr": zonder_nr}


def import_commit(rows: list[dict], aantal: int) -> tuple[bool, str, dict]:
    kaarten = intake_store.load_strippenkaarten()
    toegevoegd = aangevuld = 0
    for r in rows:
        naam = (r.get("naam") or "").strip()
        tel = (r.get("telefoon") or "").strip()
        if not naam:
            continue
        if naam in kaarten:
            if tel and not kaarten[naam].get("telefoon"):
                kaarten[naam]["telefoon"] = tel
                aangevuld += 1
        else:
            kaarten[naam] = {
                "totaal": int(aantal), "gebruikt": 0, "historie": [],
                "aangemaakt": date.today().isoformat(), "telefoon": tel,
            }
            toegevoegd += 1
    ok, err = intake_store.save_strippenkaarten(kaarten)
    return ok, err, {"toegevoegd": toegevoegd, "aangevuld": aangevuld}
