"""Belasting-signalering — wie loopt uit de pas qua volume, gevoel of klachten.

Vier gratis rekenregels bepalen wie gevlagd wordt (geen AI):
  1. Volumesprong   — deze week fors meer km dan het 4-weekse gemiddelde ervoor
  2. Gevoel zakt    — gevoel-score structureel slechter dan de periode ervoor
  3. RPE-drift      — trainingen voelen zwaarder terwijl het volume gelijk blijft
  4. Klachtwoorden  — pijn/blessure/ziek e.d. in recente notities

Alleen voor gevlagde atleten schrijft Haiku één duidende coach-zin.
Resultaat wordt 1x per dag berekend en gedeeld opgeslagen (belasting.json),
zodat beide coaches dezelfde stand zien zonder herberekening.
"""

from __future__ import annotations

import re
import threading
from datetime import date, datetime, timedelta

import fs_client
import intake_store
from dossier import _is_run, _run_km

# ── Gedeelde in-process concurrency-guards (Coach Read Performance v1 — delta) ──
# Puur in-geheugen, geen nieuwe persistent cache/store. Twee losse zorgen:
#
#  _STAND_LOCK  serialiseert elke READ-MODIFY-WRITE op de opgeslagen dagstand
#               (coach-authority `afgehandeld` én de recompute-save). Zo kan een
#               achtergrond-recompute nooit een coachactie (markeer_gezien/undo)
#               overschrijven die tijdens die ~tientallen-seconden-sweep gebeurde,
#               en andersom kan een coachactie nooit verse recompute-resultaten
#               wegschrijven. Beide kanten her-lezen onder de lock de verse stand.
#  Single-flight (_flight_*) zorgt dat maar ÉÉN zware recompute (check_alle + 43d
#               sweep) tegelijk loopt, gedeeld tussen Home en Teampuls: een tweede
#               gelijktijdige caller start geen tweede sweep maar krijgt dezelfde
#               net-berekende eindstand.
_STAND_LOCK = threading.RLock()

_flight_lock = threading.Lock()
_flight_event: "threading.Event | None" = None
_flight_value: "dict | None" = None

# Drempels (praktijkwaarden; bijstellen op basis van ervaring)
VOLUME_RATIO_LET_OP = 1.30   # +30% t.o.v. 4-weeks gemiddelde
VOLUME_RATIO_HOOG = 1.50     # +50%
BASIS_MIN_KM_WEEK = 10.0     # onder deze basis geen volume-signaal (opbouwers/starters)
GEVOEL_DREMPEL = 0.8         # punten verslechtering (1=geweldig … 5=vreselijk)
RPE_DREMPEL = 1.5            # punten zwaarder (schaal 1-10)
RPE_VOLUME_MAX = 1.15        # RPE-drift telt alleen als volume NIET fors steeg
MIN_DATAPUNTEN = 3           # minimaal aantal scores per venster

# Fysieke klachtdetectie op ZINSNIVEAU, met negatieherkenning.
# "Beetje pijn aan mijn knie" = klacht; "geen pijn meer" of "knie voelde
# prima" is er juist géén — anders flagt elk positief bericht een signaal.
_KERN_KLACHTEN = [
    r"blessure", r"geblesseerd", r"\bpijn(?!vrij)", r"pijnlijk", r"fysio",
    r"\bziek\b", r"griep", r"koorts", r"overtraind", r"uitgeput", r"doodmoe",
    r"kramp", r"last van", r"\bstijf", r"gevoelig", r"zeurt", r"geïrriteerd",
    r"ontstoken", r"ontsteking",
]
# Lichaamsdelen tellen alleen mee als in DEZELFDE zin ook een kernklacht staat
_LICHAAMSDELEN = [
    r"scheen", r"achilles", r"hamstring", r"\bkuit", r"\blies\b", r"\benkel",
    r"\bknie", r"\brug\b", r"\bvoet", r"\bheup", r"\bzool", r"\bhiel",
]
_NEGATIES = re.compile(
    r"\b(geen|niet|zonder|nauwelijks|amper|nooit|minder|weinig)\b")
_OPGELOST = re.compile(
    r"\b(weg|over|voorbij|verdwenen|hersteld|opgelost|prima|goed|beter)\b")


def _vind_klachten(tekst: str) -> list[str]:
    """Vind echte fysieke klachten in een notitie; negaties en 'het gaat weer
    goed'-zinnen tellen niet. Geeft de gevonden kernwoorden terug."""
    gevonden: list[str] = []
    for zin in re.split(r"[.!?\n]+", tekst.lower()):
        if not zin.strip():
            continue
        kern = None
        for pat in _KERN_KLACHTEN:
            m = re.search(pat, zin)
            if m:
                # Negatie vlak vóór ("geen pijn") of oplossing vlak ná
                # ("pijn is weg") → geen klacht
                venster_voor = zin[max(0, m.start() - 30):m.start()]
                venster_na = zin[m.end():m.end() + 25]
                if _NEGATIES.search(venster_voor) or _OPGELOST.search(venster_na):
                    continue
                kern = m.group(0).strip()
                break
        if not kern:
            continue
        # Lichaamsdeel in dezelfde zin maakt de klacht specifieker
        deel = next((dm.group(0).strip() for dp in _LICHAAMSDELEN
                     if (dm := re.search(dp, zin))), "")
        label = f"{kern} ({deel})" if deel else kern
        if label not in gevonden:
            gevonden.append(label)
    return gevonden


def _gem(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def analyse_belasting(entries: list[dict], vandaag: date | None = None) -> dict | None:
    """
    Analyseer trainingslog-entries (dicts met date, actual_km, activity_type,
    completed, felt, effort, post_notes) op belasting-signalen.
    Geeft None als er niets aan de hand is of te weinig data, anders:
    {"ernst": "let_op"|"hoog", "signalen": [tekst], "codes": [code], "metrics": {...}}
    """
    vandaag = vandaag or date.today()
    grens_7d = vandaag - timedelta(days=7)
    grens_14d = vandaag - timedelta(days=14)
    # Klachten alleen uit de laatste 7 dagen: een opmerking van vorige week is
    # geen actueel signaal meer (gevoel/RPE blijven trends over 14 dagen).
    grens_klachten = vandaag - timedelta(days=7)
    grens_basis = grens_7d - timedelta(days=28)      # volume-basis: 28d vóór de recente week
    grens_basis_scores = grens_14d - timedelta(days=28)  # score-basis: 28d vóór de recente 14d

    km_recent = 0.0
    km_basis = 0.0
    n_runs_basis = 0
    felt_recent, felt_basis = [], []
    rpe_recent, rpe_basis = [], []
    klachten: list[str] = []
    runs_recent: list[dict] = []

    for e in entries:
        try:
            d = date.fromisoformat((e.get("date") or "")[:10])
        except ValueError:
            continue
        if d > vandaag or not e.get("completed"):
            continue

        km = _run_km(e)
        if d > grens_7d:
            km_recent += km
            if km > 0:
                # Onderbouwing: precies deze runs zijn geteld (controleerbaar)
                runs_recent.append({"datum": d.isoformat(),
                                    "naam": (e.get("name") or "")[:40],
                                    "km": round(km, 1)})
        elif d > grens_basis:
            km_basis += km
            if _is_run(e) and km > 0:
                n_runs_basis += 1

        # Gevoel (1=geweldig … 5=vreselijk) en RPE (1-10)
        for veld, recent, basis in (("felt", felt_recent, felt_basis),
                                    ("effort", rpe_recent, rpe_basis)):
            try:
                v = float(e.get(veld))
            except (TypeError, ValueError):
                continue
            if v <= 0:
                continue
            if d > grens_14d:
                recent.append(v)
            elif d > grens_basis_scores:
                basis.append(v)

        # Echte klachten in recente notities (negaties/opgelost tellen niet),
        # mét datum zodat de coach het signaal kan plaatsen
        if d > grens_klachten and e.get("post_notes"):
            for k in _vind_klachten(e["post_notes"]):
                _label = f"{k} · {d.strftime('%d-%m')}"
                if _label not in klachten:
                    klachten.append(_label)

    signalen: list[str] = []
    codes: list[str] = []
    basis_week = km_basis / 4 if km_basis else 0.0
    ratio = (km_recent / basis_week) if basis_week else None

    # 1. Volumesprong — alleen bij een serieuze basis (geen starters flaggen)
    if (ratio is not None and basis_week >= BASIS_MIN_KM_WEEK
            and n_runs_basis >= 4 and ratio >= VOLUME_RATIO_LET_OP):
        signalen.append(f"Volume +{(ratio - 1) * 100:.0f}% deze week "
                        f"({km_recent:.0f} km vs gem. {basis_week:.0f} km/wk)")
        codes.append("volume")

    # 2. Gevoel zakt (hogere score = slechter)
    g_rec, g_bas = _gem(felt_recent), _gem(felt_basis)
    if (g_rec is not None and g_bas is not None
            and len(felt_recent) >= MIN_DATAPUNTEN and len(felt_basis) >= MIN_DATAPUNTEN
            and g_rec - g_bas >= GEVOEL_DREMPEL):
        signalen.append(f"Gevoel zakt: gem. {g_rec:.1f} laatste 2 wkn vs {g_bas:.1f} ervoor")
        codes.append("gevoel")

    # 3. RPE-drift: zwaarder bij gelijk werk
    r_rec, r_bas = _gem(rpe_recent), _gem(rpe_basis)
    if (r_rec is not None and r_bas is not None
            and len(rpe_recent) >= MIN_DATAPUNTEN and len(rpe_basis) >= MIN_DATAPUNTEN
            and r_rec - r_bas >= RPE_DREMPEL
            and (ratio is None or ratio < RPE_VOLUME_MAX)):
        signalen.append(f"Trainingen voelen zwaarder: RPE {r_rec:.1f} vs {r_bas:.1f} "
                        f"bij vergelijkbaar volume")
        codes.append("rpe")

    # 4. Klachtwoorden
    if klachten:
        signalen.append("Noemt in notities: " + ", ".join(klachten[:4]))
        codes.append("klachten")

    if not signalen:
        return None

    hoog = len(codes) >= 2 or (ratio is not None and ratio >= VOLUME_RATIO_HOOG)
    return {
        "ernst": "hoog" if hoog else "let_op",
        "signalen": signalen,
        "codes": codes,
        "metrics": {
            "km_recent": round(km_recent, 1), "km_basis_week": round(basis_week, 1),
            "ratio": round(ratio, 2) if ratio is not None else None,
            "gevoel_recent": g_rec, "gevoel_basis": g_bas,
            "rpe_recent": r_rec, "rpe_basis": r_bas,
            "klachten": klachten,
            "runs_recent": sorted(runs_recent, key=lambda r: r["datum"]),
        },
    }


def _ontdubbel_entries(entries: list[dict]) -> list[dict]:
    """
    Dezelfde run kan dubbel binnenkomen: één keer als geplande (afgeronde)
    workout en één keer als losse horloge-sync met een eigen key. Twee
    voltooide runs op dezelfde dag met (vrijwel) dezelfde afstand tellen we
    daarom één keer — de variant mét naam/structuur wint.
    """
    per_dag: dict[str, list[dict]] = {}
    uit: list[dict] = []
    for e in entries:
        if not (e.get("completed") and _is_run(e) and (e.get("actual_km") or 0) > 0):
            uit.append(e)
            continue
        dag = (e.get("date") or "")[:10]
        dubbel = None
        for ander in per_dag.get(dag, []):
            if abs(float(ander.get("actual_km") or 0) - float(e.get("actual_km") or 0)) <= 0.3:
                dubbel = ander
                break
        if dubbel is None:
            per_dag.setdefault(dag, []).append(e)
            uit.append(e)
        elif not dubbel.get("name") and e.get("name"):
            # zelfde run, maar deze variant heeft de workoutnaam → vervang
            uit[uit.index(dubbel)] = e
            per_dag[dag][per_dag[dag].index(dubbel)] = e
    return uit


def _entry_van_workout(w: dict) -> dict:
    """Zet een ruwe FinalSurge-workout om naar een analyse-entry."""
    acts = w.get("Activities") or []
    act = acts[0] if acts else {}
    return {
        "date": (w.get("workout_date") or "")[:10],
        "name": (w.get("name") or "").strip(),
        "activity_type": (w.get("activity_type_name")
                          or act.get("activity_type_name") or ""),
        "actual_km": fs_client._norm_km(act.get("amount"), act.get("amount_type")),
        "completed": fs_client.is_executed_workout(w),
        "felt": w.get("felt"),
        "effort": w.get("effort"),
        "post_notes": (w.get("post_workout_notes") or "").strip(),
    }


def check_alle(athletes: list[dict], on_hold: dict | None = None,
               admin_clients: dict | None = None) -> list[dict]:
    """
    Draai de belasting-analyse voor alle relevante atleten (parallel).
    Uitgesloten: los schema, on hold, opgezegd. Geeft alleen gevlagde atleten.
    """
    on_hold = on_hold or {}
    admin_clients = admin_clients or {}
    vandaag = date.today()
    start = vandaag - timedelta(days=43)

    todo = []
    for a in athletes:
        groepen = a.get("all_groups") or [a.get("group")]
        if any(fs_client.group_is_excluded(g, {"los schema"}) for g in groepen):
            continue
        if a["user_key"] in on_hold:
            continue
        if admin_clients.get(a["user_key"], {}).get("status") == "Opgezegd":
            continue
        todo.append(a)

    def _fetch(a):
        workouts = fs_client.get_workouts_deduped(a["user_key"], start, vandaag)
        entries = _ontdubbel_entries([_entry_van_workout(w) for w in workouts])
        res = analyse_belasting(entries, vandaag)
        if not res:
            return None
        # Alleen verse notities (7 dagen) voeden de AI-duiding — oudere context
        # leidde tot adviezen over trainingen van vorige week
        notities = " | ".join(e["post_notes"] for e in entries
                              if e["post_notes"] and e["date"] >= (vandaag - timedelta(days=7)).isoformat())
        return {"user_key": a["user_key"], "naam": a["name"],
                "group": a.get("group", ""), "notities": notities[:800], **res}

    resultaten = [r for r in fs_client._parallel_per_athlete(todo, _fetch) if r]
    # Hoog eerst, dan alfabetisch
    return sorted(resultaten, key=lambda r: (r["ernst"] != "hoog", r["naam"]))


def laad_stand() -> dict:
    """Alleen de opgeslagen dagstand lezen (géén berekening, geen FS-calls).
    Voor de homepage-tegel: die mag nooit laadtijd kosten."""
    try:
        return intake_store.load_belasting()
    except Exception:
        return {}


def _recompute_stand(athletes: list[dict], vandaag: str) -> dict:
    """De ZWARE recompute (check_alle + 43d-sweep + parallelle AI-duiding), gevolgd
    door een coach-authority-veilige save. Wordt altijd via `_recompute_single_flight`
    aangeroepen zodat Home en Teampuls samen maar één sweep starten."""
    import ai_feedback

    resultaten = check_alle(
        athletes,
        on_hold=_veilig(intake_store.load_on_hold),
        admin_clients=_veilig(intake_store.load_admin_clients),
    )

    # AI-duiding per gevlagde atleet PARALLEL (Coach Read Performance v1). Dit zijn
    # onafhankelijke Anthropic-calls (geen FinalSurge → geen throttle-risico van de
    # seriële FS-sweeps elders); serieel was dit de dominante hap uit de 45-60s.
    # Elke thread muteert alleen zijn eigen `r` → thread-safe.
    def _duid(r: dict) -> None:
        try:
            r["duiding"] = ai_feedback.belasting_duiding(
                r["naam"], r["signalen"], r.get("notities", ""))
        except Exception:
            r["duiding"] = ""
        r.pop("notities", None)  # niet nodig in de opslag

    if resultaten:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(8, len(resultaten))) as _ex:
            list(_ex.map(_duid, resultaten))

    # Coach-authority guard: her-lees ONDER de gedeelde lock de ACTUELE afgehandeld.
    # De recompute duurde tientallen seconden; een coach kan intussen markeer_gezien/
    # undo hebben gedaan. De bij aanvang gelezen afgehandeld is dan verouderd — neem
    # de verse coach-authority over zodat we die actie niet terugdraaien.
    with _STAND_LOCK:
        try:
            huidig = intake_store.load_belasting() or {}
        except Exception:
            huidig = {}
        data = {"datum": vandaag, "resultaten": resultaten,
                "afgehandeld": huidig.get("afgehandeld", {}),
                # Monotone bronversie (productie-tijd) — géén nieuwe store, een versiemarker
                # op de bestaande stand. Het Coach Read Model leidt hieruit `generation_at`
                # af zodat een oudere read-state nooit een nieuwere kan vervangen. NIET de
                # leestijd: dit is het moment waarop DEZE stand-versie werd geproduceerd.
                "_produced_at": datetime.now().isoformat(timespec="seconds")}
        try:
            intake_store.save_belasting(data)
        except Exception:
            pass  # niet-opslaan = morgen opnieuw berekenen, geen blokkade
    return data


def _recompute_single_flight(compute) -> dict:
    """Laat maar ÉÉN zware belasting-recompute tegelijk lopen (gedeeld Home+Teampuls).

    De eerste caller (leider) draait `compute()`; een tweede gelijktijdige caller
    start GEEN tweede check_alle/43d-sweep maar wacht tot de leider klaar is en krijgt
    diens net-berekende eindstand. Puur in-process (geen nieuwe persistent cache).
    De leider-exception propageert naar de leider-caller (bestaande try/except-fallback
    blijft gelden); volgers vallen dan terug op de laatst opgeslagen stand."""
    global _flight_event, _flight_value
    with _flight_lock:
        if _flight_event is not None:
            ev, leider = _flight_event, False
        else:
            ev = _flight_event = threading.Event()
            _flight_value = None
            leider = True

    if not leider:
        ev.wait()
        with _flight_lock:
            val = _flight_value
        if val is not None:
            return val
        try:
            return intake_store.load_belasting() or {}
        except Exception:
            return {}

    # Leider: reken BUITEN _flight_lock (zware sweep mag volgers niet blokkeren op de
    # slot-lock zelf; die wachten op het event). Deel daarna het resultaat en wek ze.
    try:
        result = compute()
    except BaseException:
        with _flight_lock:
            _flight_value = None
            _flight_event = None
            ev.set()
        raise
    with _flight_lock:
        _flight_value = result
        _flight_event = None
        ev.set()
    return result


def dagelijkse_check(athletes: list[dict], forceer: bool = False) -> dict:
    """
    Geef de belasting-stand van vandaag. Herberekent alleen als de opgeslagen
    stand niet van vandaag is (of forceer=True); anders 1 goedkope opslag-load.
    Structuur: {"datum": iso, "resultaten": [...], "afgehandeld": {user_key: {...}}}
    De zware recompute loopt achter een gedeelde single-flight (Home+Teampuls delen
    één sweep); de goedkope same-day fast read passeert die guard niet.
    """
    try:
        data = intake_store.load_belasting()
    except Exception:
        data = {}
    vandaag = date.today().isoformat()
    if not forceer and data.get("datum") == vandaag:
        return data

    return _recompute_single_flight(lambda: _recompute_stand(athletes, vandaag))


def zichtbare_resultaten(data: dict) -> list[dict]:
    """Filter de resultaten op 'gezien' (7 dagen gedempt, behalve bij escalatie)."""
    vandaag = date.today().isoformat()
    afg = data.get("afgehandeld", {})
    zichtbaar = []
    for r in data.get("resultaten", []):
        a = afg.get(r["user_key"])
        if a and a.get("tot", "") >= vandaag and not (
                r["ernst"] == "hoog" and a.get("ernst") == "let_op"):
            continue  # gezien en niet geëscaleerd
        zichtbaar.append(r)
    return zichtbaar


def _muteer_afgehandeld(mutator) -> dict:
    """Enige coach-authority-mutatie op de belasting-stand. Leest ONDER _STAND_LOCK
    de VERSE stand (zodat een gelijktijdige recompute of tweede coachactie geen verse
    resultaten of elkaars afgehandeld-mutatie overschrijft), laat `mutator(afgehandeld)`
    alleen de afgehandeld-map aanpassen, ruimt verlopen vermeldingen op, en slaat op."""
    with _STAND_LOCK:
        try:
            data = intake_store.load_belasting() or {}
        except Exception:
            data = {}
        afg = data.setdefault("afgehandeld", {})
        mutator(afg)
        vandaag = date.today().isoformat()
        for k in list(afg.keys()):
            if afg[k].get("tot", "") < vandaag:
                del afg[k]
        # Coach-suppressie is óók een nieuwe stand-versie → productie-tijd vooruit
        # (monotone generation_at; de content-signatuur verandert sowieso al).
        data["_produced_at"] = datetime.now().isoformat(timespec="seconds")
        try:
            intake_store.save_belasting(data)
        except Exception:
            pass
        return data


def markeer_gezien(data: dict, user_key: str, ernst: str,
                   undo: bool = False, tot: str | None = None) -> dict:
    """Demp een atleet 7 dagen (of hef de demping op bij undo); bij escalatie naar
    'hoog' komt hij eerder terug. Muteert alleen de afgehandeld-map, coach-authority-
    veilig onder de gedeelde stand-lock (zie [[_muteer_afgehandeld]]). Geeft de verse
    volledige stand terug (bestaande callers gebruiken de retour als sessiestand)."""
    def _mut(afg: dict) -> None:
        if undo:
            afg.pop(user_key, None)
        else:
            afg[user_key] = {
                "tot": tot or (date.today() + timedelta(days=7)).isoformat(),
                "ernst": ernst}

    nieuw = _muteer_afgehandeld(_mut)
    if isinstance(data, dict):
        # Houd het in-place-contract voor bestaande callers: hun dict weerspiegelt
        # de verse afgehandeld-stand.
        data["afgehandeld"] = dict(nieuw.get("afgehandeld", {}))
    return nieuw


def _veilig(fn):
    try:
        return fn()
    except Exception:
        return {}
