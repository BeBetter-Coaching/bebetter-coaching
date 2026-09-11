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
import uuid
from collections import OrderedDict
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
        # Staart van de bestaande historie — puur lezen, geen tweede administratie.
        # De lijst is per kaart klein (10/20 strips), dus dit maakt de payload niet zwaar.
        "historie": [h for h in hist[-6:] if isinstance(h, str)],
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


# Kaartgroottes die de app kent (nieuwe kaart, bulkimport en nu ook achteraf aanpassen).
KAART_GROOTTES = (10, 20)


def kaart_grootte(naam: str, totaal, verwacht_totaal=None,
                  verwacht_gebruikt=None) -> tuple[bool, str, dict]:
    """Wijzig ALLEEN de kaartgrootte (`totaal`). `gebruikt`, `historie`, `laatste_batch`
    en de rest van de kaart blijven exact staan, dus ook 'ongedaan maken' van de laatste
    groepsafboeking blijft kloppen (die toetst `gebruikt`, niet `totaal`).

    `verwacht_*` = de stand die de coach zag. Wijkt de server af (tweede tabblad, andere
    coach, Streamlit), dan wordt er niets overschreven."""
    try:
        nieuw = int(totaal)
    except (TypeError, ValueError):
        nieuw = None
    if nieuw not in KAART_GROOTTES:
        return False, "Kies een kaart van 10 of 20 strippen.", {}
    kaarten = intake_store.load_strippenkaarten()
    k = kaarten.get(naam)
    if not k:
        return False, "Onbekende strippenkaart.", {"conflict": "onbekend"}
    huidig, geb = int(k.get("totaal", 10)), int(k.get("gebruikt", 0))
    if (verwacht_totaal is not None and int(verwacht_totaal) != huidig) or \
            (verwacht_gebruikt is not None and int(verwacht_gebruikt) != geb):
        return False, ("De kaart van " + naam + " is inmiddels gewijzigd. Niets aangepast — "
                       "ververs en probeer opnieuw."), {"conflict": "stale"}
    if nieuw == huidig:
        return True, "", {"ongewijzigd": True, "kaart": _view(naam, k)}   # niets te schrijven
    if geb > nieuw:
        # Anders zou 'gebruikt' boven 'totaal' uitkomen en het saldo negatief worden.
        return False, (f"{naam} heeft al {geb} strippen gebruikt; een kaart van {nieuw} "
                       f"kan dat niet dragen."), {"conflict": "te_klein"}
    k["totaal"] = nieuw
    ok, err = intake_store.save_strippenkaarten(kaarten)
    if not ok:
        return False, err or "Opslaan mislukt.", {}
    return True, "", {"kaart": _view(naam, k)}


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


# ── Groepsafboeking: één validatie, één mutatie, één write ───────────────────
# De coach staat met de telefoon in de hand naast de groep. Zes losse POSTs zijn
# daar drie dingen tegelijk: traag (elke write is een GitHub GET+PUT), niet
# atomair (deelnemer 4 kan falen terwijl 1-3 al geboekt zijn) en niet te
# bevestigen (welke stand gold er toen de coach op de knop drukte?).
# Daarom één contract: valideer ALLE deelnemers vóór er iets muteert, muteer in
# geheugen, en schrijf de hele kaartenset in ÉÉN `save_strippenkaarten`. Die
# opslag schrijft het volledige JSON-bestand, dus alles-of-niets komt hier
# gratis — er bestaat geen half geschreven batch.

_MAX_BATCH = 60                       # ruim boven de grootste groep; vangnet tegen onzin


def _rest(k: dict) -> int:
    return max(0, int(k.get("totaal", 10)) - int(k.get("gebruikt", 0)))


# Idempotentie: dezelfde `client_id` twee keer (dubbeltik, retry na een trage
# verbinding) levert het EERSTE resultaat terug in plaats van een tweede write.
# Begrensd op 32 — een ongelimiteerde dict is precies de fout uit de OOM-ronde.
_IDEMPOTENT: "OrderedDict[str, dict]" = OrderedDict()
_IDEMPOTENT_MAX = 32


def _onthoud(client_id: str, res: dict) -> None:
    if not client_id:
        return
    _IDEMPOTENT[client_id] = res
    while len(_IDEMPOTENT) > _IDEMPOTENT_MAX:
        _IDEMPOTENT.popitem(last=False)


def afboeken_batch(namen: list, verwacht: dict | None = None,
                   client_id: str = "") -> tuple[bool, str, dict]:
    """Boek bij ELKE genoemde deelnemer precies één strip af — of bij niemand.

    `verwacht` = {naam: gebruikt} zoals de CLIENT het zag. Wijkt de server af,
    dan keek de coach naar een verouderde stand (tweede tabblad, andere coach,
    Streamlit) en weigeren we de hele batch: liever een eerlijke melding dan een
    stilzwijgend andere uitkomst dan de bevestiging beloofde.
    """
    # Volgorde behouden, dubbelen eruit: twee keer dezelfde naam is één strip.
    gezien, uniek = set(), []
    for n in (namen or []):
        n = (n or "").strip()
        if n and n not in gezien:
            gezien.add(n)
            uniek.append(n)
    if not uniek:
        return False, "Geen deelnemers geselecteerd.", {}
    if len(uniek) > _MAX_BATCH:
        return False, f"Te veel deelnemers in één keer (max {_MAX_BATCH}).", {}

    cid = (client_id or "").strip()[:64]
    if cid and cid in _IDEMPOTENT:
        # Zelfde tik, tweede request: geef exact hetzelfde antwoord, schrijf niets.
        return True, "", dict(_IDEMPOTENT[cid], herhaald=True)

    kaarten = intake_store.load_strippenkaarten()

    # ── 1. Volledige validatie VÓÓR elke mutatie ────────────────────────────
    onbekend = [n for n in uniek if n not in kaarten]
    if onbekend:
        return False, "Onbekende strippenkaart: " + ", ".join(onbekend), {
            "conflict": "onbekend", "namen": onbekend}
    leeg = [n for n in uniek if _rest(kaarten[n]) <= 0]
    if leeg:
        # Zonder deze grens telt `gebruikt` gewoon door en gaat het saldo stil naar -1.
        return False, "Geen strippen meer over bij: " + ", ".join(leeg), {
            "conflict": "leeg", "namen": leeg}
    if verwacht:
        stale = [n for n in uniek
                 if str(verwacht.get(n, "")) != "" and
                 int(verwacht[n]) != int(kaarten[n].get("gebruikt", 0))]
        if stale:
            return False, ("De stand is inmiddels gewijzigd bij: " + ", ".join(stale)
                           + ". Niets afgeboekt — ververs en probeer opnieuw."), {
                "conflict": "stale", "namen": stale}

    # ── 2. Muteren in geheugen ──────────────────────────────────────────────
    bid = uuid.uuid4().hex[:12]
    vandaag = date.today().isoformat()
    deelnemers = []
    for n in uniek:
        k = kaarten[n]
        totaal = int(k.get("totaal", 10))
        geb = int(k.get("gebruikt", 0)) + 1
        k["gebruikt"] = geb
        k.setdefault("historie", []).append(vandaag)
        # Het transactiespoor voor 'ongedaan maken'. `gebruikt_na` is de bewijslast:
        # is de kaart daarna nog een keer geraakt (app, Streamlit, offline-queue),
        # dan klopt dit getal niet meer en weigert `batch_terug` de hele undo.
        k["laatste_batch"] = {"id": bid, "gebruikt_na": geb, "datum": vandaag}
        rest = max(0, totaal - geb)
        voornaam = n.split()[0] if n else n
        bericht = afboek_bericht(voornaam, rest, totaal)
        deelnemers.append({
            "naam": n, "rest": rest, "totaal": totaal, "gebruikt": geb,
            "bericht": bericht, "wa_link": wa_link(k.get("telefoon", ""), bericht),
            "telefoon": k.get("telefoon", ""),
        })

    # ── 3. Eén write ────────────────────────────────────────────────────────
    ok, err = intake_store.save_strippenkaarten(kaarten)
    if not ok:
        # Niets opgeslagen = niets gebeurd: de mutatie zat alleen in dit dict.
        return False, err or "Opslaan mislukt.", {}

    res = {"batch_id": bid, "aantal": len(deelnemers), "deelnemers": deelnemers,
           "datum": vandaag}
    _onthoud(cid, res)
    return True, "", res


def batch_terug(batch_id: str) -> tuple[bool, str, dict]:
    """Draai precies één groepsafboeking terug — of niets.

    Terugdraaien mag alleen als de kaarten sindsdien onaangeroerd zijn: het
    merkje `laatste_batch` moet nog van DEZE batch zijn én `gebruikt` moet nog
    exact de stand van die batch hebben. Na afloop is het merkje weg, dus een
    tweede undo van dezelfde batch vindt niets meer en doet niets.
    """
    bid = (batch_id or "").strip()
    if not bid:
        return False, "Geen afboeking om terug te draaien.", {}
    kaarten = intake_store.load_strippenkaarten()
    doel = [n for n, k in kaarten.items()
            if ((k or {}).get("laatste_batch") or {}).get("id") == bid]
    if not doel:
        return False, "Deze afboeking is al teruggedraaid.", {"conflict": "weg"}

    afwijkend = [n for n in doel
                 if int(kaarten[n].get("gebruikt", 0))
                 != int((kaarten[n]["laatste_batch"] or {}).get("gebruikt_na", -1))]
    if afwijkend:
        return False, ("Er is daarna al iets gewijzigd bij: " + ", ".join(afwijkend)
                       + ". Niets teruggedraaid."), {"conflict": "gewijzigd", "namen": afwijkend}

    for n in sorted(doel):
        k = kaarten[n]
        k["gebruikt"] = max(0, int(k.get("gebruikt", 0)) - 1)
        if k.get("historie"):
            k["historie"].pop()
        k.pop("laatste_batch", None)          # merkje weg → tweede undo doet niets
    ok, err = intake_store.save_strippenkaarten(kaarten)
    if not ok:
        return False, err or "Opslaan mislukt.", {}
    return True, "", {
        "aantal": len(doel),
        "kaarten": [_view(n, kaarten[n]) for n in sorted(doel)],
    }
