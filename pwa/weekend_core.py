"""Trainingsweekend Vakantiehuis de Kraanvogels — inschrijving + beheer (v1, 14 sep 2026).

Eén afgebakende module, los van de coachingdata:
- Een weekenddeelnemer is GEEN coachingatleet: niets hier schrijft naar intakes,
  de intake-inbox, strippenkaarten of FinalSurge.
- Prijs, aanbetaling, betaaltermijn en voorwaarden zijn pas bekend als beheer ze
  invult. De code verzint geen bedragen of afspraken; zolang een van de vier
  ontbreekt kan de inschrijving niet open.
- Elke inhoudelijke wijziging van die vier geeft een nieuwe `voorwaarden_versie`.
  Een inschrijving bewaart wat de deelnemer op dat moment accepteerde (bedragen,
  betaaltermijn, versie, hash van de voorwaardentekst, tijdstip) en blijft zo staan,
  ook als beheer de voorwaarden later wijzigt.
- Openbare responses zijn een whitelist: evenementinfo, open/dicht en, alleen als
  de inschrijving open is (of beheer test), de deelnemerskosten. Nooit deelnemers.
"""

from __future__ import annotations

import copy
import hashlib
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timezone

import intake_store

# Deelnemersinformatie die vaststaat. Alles wat nog niet vaststaat, staat hier NIET.
EVENEMENT = {
    "naam": "Trainingsweekend",
    "locatie": "Vakantiehuis de Kraanvogels",
    "aankomst": {"datum": "2027-01-29", "tekst": "Vrijdag 29 januari 2027", "tijd": "vanaf 15.30 uur"},
    "vertrek": {"datum": "2027-02-01", "tekst": "Maandag 1 februari 2027", "tijd": "om 10.00 uur"},
    "praktisch": ["Neem je eigen handdoeken mee.", "Keukenlinnen is aanwezig."],
}

GESLOTEN_TEKST = "Inschrijving opent binnenkort — definitieve informatie volgt"

INSCHRIJFSTATUS = {"ingeschreven": "Ingeschreven", "bevestigd": "Bevestigd", "geannuleerd": "Geannuleerd"}
BETAALSTATUS = {"open": "Nog niet betaald", "aanbetaling": "Aanbetaling ontvangen",
                "betaald": "Volledig betaald", "terugbetaald": "Terugbetaald"}
_STATUSVELDEN = {"inschrijfstatus": INSCHRIJFSTATUS, "betaalstatus": BETAALSTATUS}

_KOSTENVELDEN = ("deelnemersprijs_cent", "aanbetaling_cent", "betaaltermijn", "voorwaarden")
_KOSTEN_LABELS = {"deelnemersprijs_cent": "deelnemersprijs", "aanbetaling_cent": "aanbetaling",
                  "betaaltermijn": "betaaltermijn", "voorwaarden": "voorwaarden"}
_MAX_CENT = 1_000_000            # € 10.000 — sanity-grens tegen typefouten, geen prijsafspraak
_MAX_TERMIJN = 1000
_MAX_VOORWAARDEN = 20000

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_TELEFOON_TEKENS = re.compile(r"^[+0-9 ()\-.]+$")

_LOCK = threading.RLock()        # load → wijzig → save is één stap binnen dit proces
_PUBLIEK_TTL = 30.0              # openbare pagina leest niet bij elke view de store
_MEM: dict = {"t": 0.0, "staat": None}


class WeekendFout(Exception):
    def __init__(self, err: str, status: int = 400, **extra):
        super().__init__(err)
        self.err, self.status, self.extra = err, status, extra


# ── Opslag ──────────────────────────────────────────────────────────────────
def _load() -> dict:
    return intake_store.load_weekend()


def _save(data: dict) -> tuple[bool, str]:
    return intake_store.save_weekend(data)


def reset_cache() -> None:
    _MEM.update(t=0.0, staat=None)


def _klok() -> datetime:
    return datetime.now(timezone.utc)


def _nu() -> str:
    return _klok().isoformat(timespec="seconds")


# Vangrail tegen massaal automatisch inschrijven (geen capaciteitsafspraak). Afgeleid uit de
# OPGESLAGEN inschrijvingen, dus een herstart zet hem niet op nul. Testinschrijvingen tellen niet.
INSCHRIJF_LIMIETEN = ((20, 10 * 60), (100, 24 * 3600))    # (max. inschrijvingen, venster in seconden)


def drukte_wachttijd(staat: dict) -> int:
    """Seconden tot er weer openbaar ingeschreven kan worden (0 = nu)."""
    nu = _klok()
    tijden = []
    for r in staat["inschrijvingen"].values():
        if r.get("test") or not r.get("ingeschreven_op"):
            continue
        try:
            tijden.append((nu - datetime.fromisoformat(r["ingeschreven_op"])).total_seconds())
        except ValueError:
            continue
    wacht = 0.0
    for maximum, venster in INSCHRIJF_LIMIETEN:
        leeftijden = sorted(a for a in tijden if 0 <= a < venster)       # jongste eerst
        if len(leeftijden) >= maximum:
            wacht = max(wacht, venster - leeftijden[maximum - 1])       # tot er weer één uit het venster valt
    return int(wacht) + 1 if wacht > 0 else 0


def _normaliseer(raw: dict) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    inst = {"inschrijving_open": False, "deelnemersprijs_cent": None, "aanbetaling_cent": None,
            "betaaltermijn": "", "voorwaarden": "", "voorwaarden_versie": 0,
            "vastgesteld_op": "", "vastgesteld_door": "", "open_gewijzigd_op": "", "open_gewijzigd_door": ""}
    inst.update(raw.get("instellingen") or {})
    return {"instellingen": inst,
            "versies": dict(raw.get("versies") or {}),
            "inschrijvingen": dict(raw.get("inschrijvingen") or {})}


def _lees_vers() -> dict:
    """Verse, strikte read. Faalt de read, dan faalt de actie — nooit schrijven op een lege read."""
    try:
        staat = _normaliseer(_load())
    except Exception as e:
        raise WeekendFout("De inschrijvingen konden niet worden gelezen. Probeer het zo nog eens.", 503) from e
    _MEM.update(t=time.monotonic(), staat=copy.deepcopy(staat))
    return staat


def _schrijf(staat: dict) -> None:
    ok, err = _save(staat)
    if not ok:
        reset_cache()
        raise WeekendFout("Opslaan lukte niet. Probeer het zo nog eens.", 503, detail=str(err)[:200])
    _MEM.update(t=time.monotonic(), staat=copy.deepcopy(staat))


def _lees_gecachet() -> dict:
    if _MEM["staat"] is not None and time.monotonic() - _MEM["t"] < _PUBLIEK_TTL:
        return copy.deepcopy(_MEM["staat"])
    return _lees_vers()


# ── Kosten & voorwaarden ────────────────────────────────────────────────────
def ontbrekende_kosten(inst: dict) -> list[str]:
    """Welke deelnemersafspraken nog niet zijn ingevuld (labels, in vaste volgorde)."""
    mist = []
    for veld in _KOSTENVELDEN:
        v = inst.get(veld)
        if v is None or (isinstance(v, str) and not v.strip()):
            mist.append(_KOSTEN_LABELS[veld])
    return mist


def _voorwaarden_hash(tekst: str) -> str:
    return hashlib.sha256((tekst or "").encode("utf-8")).hexdigest()


def _publieke_kosten(inst: dict) -> dict:
    # Whitelist: precies wat een deelnemer mag zien. Voeg hier NOOIT interne velden toe.
    return {"deelnemersprijs_cent": inst.get("deelnemersprijs_cent"),
            "aanbetaling_cent": inst.get("aanbetaling_cent"),
            "betaaltermijn": inst.get("betaaltermijn") or "",
            "voorwaarden": inst.get("voorwaarden") or "",
            "voorwaarden_versie": int(inst.get("voorwaarden_versie") or 0)}


def is_open(inst: dict) -> bool:
    return bool(inst.get("inschrijving_open")) and not ontbrekende_kosten(inst)


def publieke_info(testmodus: bool = False) -> dict:
    """De openbare weekendpagina. `testmodus` alleen doorgeven voor een beheersessie."""
    inst = _lees_gecachet()["instellingen"]
    open_ = is_open(inst)
    out = {"evenement": EVENEMENT, "open": open_, "testmodus": bool(testmodus),
           "formulier": open_ or bool(testmodus), "melding": "" if open_ else GESLOTEN_TEKST}
    if open_ or testmodus:
        out["kosten"] = _publieke_kosten(inst)
        out["kosten_ontbreken"] = ontbrekende_kosten(inst)
    return out


def _cent(v, label: str):
    if v is None or v == "":
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise WeekendFout(f"De {label} moet een bedrag in centen zijn.")
    if v < 0 or v > _MAX_CENT:
        raise WeekendFout(f"De {label} valt buiten het toegestane bereik.")
    return v


def _tekst(v, label: str, maxlen: int) -> str:
    s = str(v or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    s = "".join(c for c in s if c in "\n\t" or unicodedata.category(c)[0] != "C")
    if len(s) > maxlen:
        raise WeekendFout(f"De {label} is te lang (max. {maxlen} tekens).")
    return s


def instellingen_opslaan(body: dict, door: str) -> dict:
    """Sla deelnemersprijs, aanbetaling, betaaltermijn en voorwaarden op.

    `verwacht_versie` = de versie die beheer zag: wijzigde iemand anders ondertussen iets,
    dan weigeren we i.p.v. stil te overschrijven. Alleen een echte wijziging geeft een
    nieuwe versie; die versie wordt integraal bewaard in `versies`."""
    nieuw = {"deelnemersprijs_cent": _cent(body.get("deelnemersprijs_cent"), "deelnemersprijs"),
             "aanbetaling_cent": _cent(body.get("aanbetaling_cent"), "aanbetaling"),
             "betaaltermijn": _tekst(body.get("betaaltermijn"), "betaaltermijn", _MAX_TERMIJN),
             "voorwaarden": _tekst(body.get("voorwaarden"), "voorwaarden", _MAX_VOORWAARDEN)}
    if (nieuw["deelnemersprijs_cent"] is not None and nieuw["aanbetaling_cent"] is not None
            and nieuw["aanbetaling_cent"] > nieuw["deelnemersprijs_cent"]):
        raise WeekendFout("De aanbetaling kan niet hoger zijn dan de deelnemersprijs.")
    with _LOCK:
        staat = _lees_vers()
        inst = staat["instellingen"]
        huidig = int(inst.get("voorwaarden_versie") or 0)
        if body.get("verwacht_versie") != huidig:
            raise WeekendFout("De kosten en voorwaarden zijn intussen door iemand anders gewijzigd. "
                              "Herlaad en controleer ze opnieuw.", 409)
        if all(inst.get(k) == nieuw[k] for k in _KOSTENVELDEN):
            return beheer_overzicht(staat)
        kandidaat = {**inst, **nieuw}
        if inst.get("inschrijving_open") and ontbrekende_kosten(kandidaat):
            raise WeekendFout("De inschrijving is open; alle kosten en voorwaarden moeten ingevuld blijven. "
                              "Sluit eerst de inschrijving.", 409)
        versie = huidig + 1
        op = _nu()
        inst.update(nieuw, voorwaarden_versie=versie, vastgesteld_op=op, vastgesteld_door=door)
        staat["versies"][str(versie)] = {**nieuw, "vastgesteld_op": op, "vastgesteld_door": door,
                                         "voorwaarden_sha256": _voorwaarden_hash(nieuw["voorwaarden"])}
        _schrijf(staat)
        return beheer_overzicht(staat)


def inschrijving_open_zetten(open_: bool, door: str) -> dict:
    with _LOCK:
        staat = _lees_vers()
        inst = staat["instellingen"]
        if open_:
            mist = ontbrekende_kosten(inst)
            if mist:
                raise WeekendFout("De inschrijving kan pas open als dit is ingevuld: " + ", ".join(mist) + ".",
                                  409, ontbreekt=mist)
        if bool(inst.get("inschrijving_open")) != bool(open_):
            inst.update(inschrijving_open=bool(open_), open_gewijzigd_op=_nu(), open_gewijzigd_door=door)
            _schrijf(staat)
        return beheer_overzicht(staat)


# ── Inschrijven ─────────────────────────────────────────────────────────────
def _schoon(v, maxlen: int) -> str:
    s = unicodedata.normalize("NFC", str(v or ""))
    s = "".join(c for c in s if unicodedata.category(c)[0] != "C")
    return " ".join(s.split())[:maxlen + 1]


def valideer_deelnemer(raw: dict) -> dict:
    naam = _schoon(raw.get("naam"), 120)
    email = _schoon(raw.get("email"), 254).lower()
    telefoon = _schoon(raw.get("telefoon"), 30)
    if len(naam) < 2 or len(naam) > 120:
        raise WeekendFout("Vul je naam in.")
    if len(email) > 254 or not _EMAIL.match(email):
        raise WeekendFout("Vul een geldig e-mailadres in.")
    cijfers = sum(c.isdigit() for c in telefoon)
    if len(telefoon) > 30 or not _TELEFOON_TEKENS.match(telefoon or "x") or not 8 <= cijfers <= 15:
        raise WeekendFout("Vul een geldig telefoonnummer in.")
    if raw.get("bevestig_deelname") is not True:
        raise WeekendFout("Bevestig dat je je definitief inschrijft.")
    if raw.get("akkoord_voorwaarden") is not True:
        raise WeekendFout("Ga akkoord met de kosten en voorwaarden om je in te schrijven.")
    return {"naam": naam, "email": email, "telefoon": telefoon}


def inschrijven(raw: dict, *, test: bool = False, door: str = "") -> dict:
    """Definitieve inschrijving. `test=True` mag alleen voor een beheersessie (API checkt dat).

    Openbaar kan alleen als de inschrijving open is. De deelnemer bevestigt de versie
    die hij zag; is die intussen gewijzigd, dan weigeren we (hij moet opnieuw kijken)."""
    if str(raw.get("website") or "").strip():          # honeypot: bots vullen dit, mensen zien het niet
        return {"ok": True}
    deelnemer = valideer_deelnemer(raw)
    with _LOCK:
        staat = _lees_vers()
        inst = staat["instellingen"]
        if not test and not is_open(inst):
            raise WeekendFout(GESLOTEN_TEKST, 403)
        if not test:
            wacht = drukte_wachttijd(staat)
            if wacht:
                minuten = -(-wacht // 60)
                tijd = f"{-(-minuten // 60)} uur" if minuten >= 120 else ("1 minuut" if minuten == 1 else f"{minuten} minuten")
                raise WeekendFout(f"Er komen nu erg veel inschrijvingen binnen. Probeer het over {tijd} opnieuw.", 429)
        versie = int(inst.get("voorwaarden_versie") or 0)
        if raw.get("voorwaarden_versie") != versie:
            raise WeekendFout("De kosten of voorwaarden zijn net gewijzigd. Bekijk ze opnieuw en "
                              "bevestig je inschrijving nog eens.", 409)
        op = _nu()
        dubbel = any(r.get("email") == deelnemer["email"] and r.get("inschrijfstatus") != "geannuleerd"
                     and bool(r.get("test")) == bool(test) for r in staat["inschrijvingen"].values())
        iid = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        staat["inschrijvingen"][iid] = {
            **deelnemer,
            "id": iid,
            "ingeschreven_op": op,
            "test": bool(test),
            "test_door": door if test else "",
            "mogelijk_dubbel": dubbel,
            "inschrijfstatus": "ingeschreven",
            "betaalstatus": "open",
            "bevestiging_deelname": True,
            "akkoord": {
                "deelnemersprijs_cent": inst.get("deelnemersprijs_cent"),
                "aanbetaling_cent": inst.get("aanbetaling_cent"),
                "betaaltermijn": inst.get("betaaltermijn") or "",
                "voorwaarden_versie": versie,
                "voorwaarden_sha256": _voorwaarden_hash(inst.get("voorwaarden") or ""),
                "geaccepteerd_op": op,
            },
            "historie": [],
        }
        _schrijf(staat)
        a = staat["inschrijvingen"][iid]["akkoord"]
        return {"ok": True, "ingeschreven_op": op, "test": bool(test),
                "akkoord": {k: a[k] for k in ("deelnemersprijs_cent", "aanbetaling_cent",
                                              "betaaltermijn", "voorwaarden_versie")}}


# ── Beheer ──────────────────────────────────────────────────────────────────
def beheer_overzicht(staat: dict | None = None) -> dict:
    staat = staat if staat is not None else _lees_vers()
    inst = staat["instellingen"]
    rijen = sorted(staat["inschrijvingen"].values(), key=lambda r: r.get("ingeschreven_op", ""), reverse=True)
    echt = [r for r in rijen if not r.get("test")]
    tel = lambda veld, labels: {k: sum(1 for r in echt if r.get(veld) == k) for k in labels}  # noqa: E731
    return {
        "evenement": EVENEMENT,
        "instellingen": copy.deepcopy(inst),
        "open": is_open(inst),
        "ontbreekt": ontbrekende_kosten(inst),
        "versies": [{"versie": int(k), **{f: v.get(f) for f in ("vastgesteld_op", "vastgesteld_door")}}
                    for k, v in sorted(staat["versies"].items(), key=lambda kv: int(kv[0]))],
        "inschrijvingen": copy.deepcopy(rijen),
        "tellingen": {"totaal": len(echt), "test": len(rijen) - len(echt),
                      "inschrijfstatus": tel("inschrijfstatus", INSCHRIJFSTATUS),
                      "betaalstatus": tel("betaalstatus", BETAALSTATUS)},
        "labels": {"inschrijfstatus": INSCHRIJFSTATUS, "betaalstatus": BETAALSTATUS},
        "gesloten_tekst": GESLOTEN_TEKST,
    }


def status_zetten(iid: str, veld: str, waarde: str, verwacht: str, door: str) -> dict:
    """Zet inschrijfstatus OF betaalstatus — nooit beide in één actie.

    `verwacht` = de waarde die beheer zag; wijzigde een ander hem intussen, dan weigeren we."""
    labels = _STATUSVELDEN.get(veld)
    if labels is None:
        raise WeekendFout("Onbekend statusveld.")
    if waarde not in labels:
        raise WeekendFout("Onbekende status.")
    with _LOCK:
        staat = _lees_vers()
        rec = staat["inschrijvingen"].get(iid)
        if rec is None:
            raise WeekendFout("Inschrijving niet gevonden.", 404)
        if rec.get(veld) != verwacht:
            raise WeekendFout("Deze status is intussen door iemand anders gewijzigd. Herlaad de lijst.", 409)
        if waarde != verwacht:
            rec[veld] = waarde
            rec.setdefault("historie", []).append(
                {"veld": veld, "van": verwacht, "naar": waarde, "door": door, "op": _nu()})
            _schrijf(staat)
        return beheer_overzicht(staat)


def testinschrijving_verwijderen(iid: str) -> dict:
    """Alleen testinschrijvingen kunnen weg. Een echte inschrijving annuleer je via de status."""
    with _LOCK:
        staat = _lees_vers()
        rec = staat["inschrijvingen"].get(iid)
        if rec is None:
            raise WeekendFout("Inschrijving niet gevonden.", 404)
        if not rec.get("test"):
            raise WeekendFout("Een echte inschrijving verwijder je niet; zet de inschrijfstatus op Geannuleerd.", 409)
        del staat["inschrijvingen"][iid]
        _schrijf(staat)
        return beheer_overzicht(staat)
