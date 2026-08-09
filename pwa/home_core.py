"""Home-cockpit voor de PWA — van signaal naar wie/waarom/actie.

Bundelt de home-intelligentie in één payload: team-status, feedback-voortgang,
en vooral de **Prioriteit vandaag**-lijst: individuele atleten die aandacht of
actie vragen, met de reden erbij en waar de coach naartoe moet. Uitsluitend echte
data — belasting-signalen (opgeslagen stand), afhakers (compliance) en aflopende
schema's. Geen verzonnen scores.

belasting → dossier importeert streamlit+pandas op moduleniveau (niet in de
PWA-omgeving) → stubben, net als teampuls_core/admin_core. We raken alleen de
pure lees-functies aan (laad_stand/zichtbare_resultaten).
"""
from __future__ import annotations

import os
import sys
import threading
import types
from datetime import date, datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

for _m in ("streamlit", "pandas"):
    if _m not in sys.modules:
        try:
            __import__(_m)
        except Exception:
            sys.modules[_m] = types.ModuleType(_m)

import fs_client as FS
import feedback_core                                   # _filter_skipped (geen streamlit)

try:
    import intake_store
except Exception:
    intake_store = None


def _heeft_token() -> bool:
    try:
        return bool(FS.get_token())
    except Exception:
        return False


def _voornaam(naam: str, first: str = "") -> str:
    return first or (naam or "").split(" ")[0]


def _norm_naam(naam: str) -> str:
    return (naam or "").strip().lower()


# Ranking/telling — gedeeld door _bereken en de in-memory hertelling na een actie.
_TIER_RANK = {"actie": 0, "aandacht": 1}
_WEIGHT = {"actie": 3, "aandacht": 1}


def _rec_tot(rec: dict) -> str | None:
    """Einddatum van het dempvenster. Nieuw record heeft 'tot'; oud record (vóór deze
    ronde) niet → afgeleid: 'later' → snooze_until, 'gezien' → handled_at + 7 dagen.
    Zo blijven bestaande records exact werken (geen mass-terugkeer, geen error)."""
    tot = rec.get("tot")
    if tot:
        return tot
    if rec.get("status") == "later" and rec.get("snooze_until"):
        return rec.get("snooze_until")
    ha = rec.get("handled_at")
    if ha:
        try:
            return (date.fromisoformat(ha[:10]) + timedelta(days=7)).isoformat()
        except Exception:
            return None
    return None


def _handled_active(rec: dict | None, severity, vandaag: date) -> bool:
    """Is dit signaal nu uit de werkvoorraad? (True = onderdrukken.) Eén regel voor
    Gezien én Later: verborgen zolang (a) het NIET erger is geworden dan wat de coach
    zag (severity ≤ opgeslagen) én (b) binnen het venster (nu < tot). Stijgt de
    severity → direct opnieuw zichtbaar; anders pas terug na 7d (Gezien) / snooze_until
    (Later). Oud record zonder 'severity' → sla de escalatie-check over (venster telt)."""
    if not rec:
        return False
    sev_opgeslagen = rec.get("severity")
    if sev_opgeslagen is not None:
        try:
            if severity is not None and float(severity) > float(sev_opgeslagen):
                return False                              # verergerd → tonen
        except (TypeError, ValueError):
            pass
    tot = _rec_tot(rec)
    return bool(tot) and vandaag.isoformat() < tot


def _bouw_item(uk: str, naam: str, voornaam: str, zichtbaar: list) -> dict | None:
    """Bouw één prioriteit-rij uit de zichtbare signalen (of None als er geen rest).
    Ook gebruikt om de in-memory snapshot na een deel-actie opnieuw te bepalen."""
    if not zichtbaar:
        return None
    sigs = sorted(zichtbaar, key=lambda s: (_TIER_RANK.get(s["tier"], 9), s["soort"]))
    tier = "actie" if any(s["tier"] == "actie" for s in sigs) else "aandacht"
    return {
        "user_key": uk, "naam": naam, "voornaam": voornaam,
        "tier": tier, "n_signalen": len(sigs),
        "reden": sigs[0]["reden"],
        "chips": [{"tier": s["tier"], "kort": s["kort"]} for s in sigs],
        "signalen": sigs,
        "signature": "|".join(sorted(f"{s['soort']}:{s['fingerprint']}" for s in sigs)),
        "_score": sum(_WEIGHT.get(s["tier"], 1) for s in sigs),
    }


def _atleten_objs() -> list:
    """Vlakke atletenlijst (met all_groups) — voor belasting.check_alle."""
    try:
        groepen = FS.get_athletes_by_group()
        return [a for members in groepen.values() for a in members]
    except Exception:
        return []


def _belasting_vandaag(atleten: list) -> list:
    """Belasting-signalen van vandaag — ONAFHANKELIJK van of Teampuls geopend is.

    Is de opgeslagen dagstand niet van vandaag, dan berekenen we de signalen hier
    (belasting.dagelijkse_check, per dag gecachet). Op Render draait dat inclusief
    AI-duiding; faalt de AI/berekening (bv. lokaal zonder key), dan vallen we terug
    op de laatst opgeslagen stand — nooit een leeg scherm door een AI-hapering.
    Home gebruikt alleen de rúwe signaaltekst, niet de AI-duiding."""
    try:
        import belasting
    except Exception:
        return []
    try:
        if belasting.laad_stand().get("datum") != date.today().isoformat():
            try:
                belasting.dagelijkse_check(atleten)     # berekent + slaat op (per dag gecachet)
            except Exception:
                pass                                     # val terug op opgeslagen stand
        return belasting.zichtbare_resultaten(belasting.laad_stand())
    except Exception:
        return []


# ── Snapshot (stale-while-revalidate) — twee lagen, duurzaam en gedeeld ──────
# Doel: na een Render-deploy/restart NOOIT meer een koude 20-30s Home-load, en
# beide coaches (later meerdere instances) delen dezelfde snapshot.
#
# Laag 1  in-memory (_MEM): warme reads ~0 ms; verdwijnt bij restart.
# Laag 2  GitHub-store (intake_store.load/save_home_snapshot): overleeft deploys,
#         gedeeld tussen coaches/instances, SHA-based concurrency in _save_json.
#
# Leespad (refresh=False) doet NOOIT de zware berekening — dat houdt het kritieke
# renderpad snel: geheugen → anders één GitHub-GET (~honderden ms) → anders een
# 'pending'-payload zodat de client skeletons toont en op de achtergrond ververst.
# De ~26s sweep gebeurt uitsluitend in refresh=True, met single-flight zodat twee
# gelijktijdige verouderde loads niet allebei dezelfde zware refresh starten.

_MEM: dict = {}                          # laatst bekende snapshot in dit proces
_FLAG_LOCK = threading.Lock()
_REFRESHING = False                      # draait er al een refresh op deze instance?


def _valid(snap) -> bool:
    """Een bruikbare snapshot: FS antwoordde écht (atleten>0) en prioriteit is
    berekend. Zo herkennen we een mislukte/incomplete sweep (transiënte nullen,
    FS onbereikbaar) en overschrijven we goede data er niet mee."""
    return bool(snap and snap.get("fs") and snap.get("prioriteit") is not None
                and snap.get("atleten", 0) > 0)


def _current() -> dict:
    """Beste bekende snapshot: eerst geheugen, anders de duurzame store (die dan
    ook het geheugen opwarmt — het post-restart-pad, ~GET i.p.v. 26s rebuild)."""
    global _MEM
    if _valid(_MEM):
        return _MEM
    if intake_store is not None:
        try:
            durable = intake_store.load_home_snapshot()
        except Exception:
            durable = {}
        if _valid(durable):
            _MEM = durable
            return durable
    return {}


def _persist(data: dict) -> None:
    """Bewaar in beide lagen. GitHub-fout mag Home nooit breken (geheugen blijft)."""
    global _MEM
    _MEM = data
    if intake_store is not None:
        try:
            intake_store.save_home_snapshot(data)
        except Exception:
            pass


def cockpit(refresh: bool = False) -> dict:
    """Home-cockpit. Standaard direct uit de cache (geheugen→store); refresh=True
    herbouwt (single-flight) en behoudt bij mislukking de laatst geldige snapshot."""
    if not _heeft_token():
        return {"fs": False}

    if not refresh:
        snap = _current()
        if snap:
            return {**snap, "cached": True}
        # Nog nooit opgebouwd (eerste-ooit): geen zware sweep in het renderpad.
        # Client toont shell + skeletons en triggert de achtergrond-refresh.
        return {"fs": True, "prioriteit": None, "pending": True, "cached": False,
                "datum": date.today().isoformat(), "berekend": None}

    # ── refresh=True: single-flight ──
    global _REFRESHING
    with _FLAG_LOCK:
        bezig = _REFRESHING
        if not bezig:
            _REFRESHING = True
    if bezig:
        # Er draait al een refresh op deze instance → geen tweede zware sweep.
        snap = _current()
        if snap:
            return {**snap, "cached": True, "verversen_bezig": True}
        return {"fs": True, "prioriteit": None, "pending": True, "cached": False}

    try:
        data = _bereken()
        if _valid(data):
            data["cached"] = False
            _persist(data)
            return data
        # Mislukte/incomplete refresh → gooi bruikbare oude data niet weg.
        oud = _current()
        if oud:
            return {**oud, "cached": True, "refresh_mislukt": True}
        return {**data, "cached": False}
    finally:
        with _FLAG_LOCK:
            _REFRESHING = False


def _bereken() -> dict:
    """De zware berekening (alleen bij refresh). SERIEEL: elke sweep parallelt
    intern al over de roster; vier tegelijk → throttling/transiënte nullen.

    TIER-LOGICA (per atleet, gededupliceerd op user_key): één rij per atleet,
    HOOGSTE ernst wint (actie > aandacht). actie = afhakers, belasting 'hoog',
    schema verlopen. aandacht = belasting 'let op', schema loopt af binnen 7 dagen.
    Team-status telt DISTINCT atleten per tier; rustig = atleten − actie − aandacht.
    Geen samengestelde/fysiologische score — enkel telling van bestaande signalen."""
    if not _heeft_token():
        return {"fs": False}

    try:
        on_hold = set((intake_store.load_on_hold() or {}).keys()) if intake_store else set()
    except Exception:
        on_hold = set()

    # Generieke werklijst-status (gedeeld tussen coaches, GitHub-backed): per
    # (atleet, signaaltype) een 'Gezien' of 'Later'. Bepaalt of een signaal nu uit
    # de werkvoorraad is; zie _handled_active voor de eerlijke terugkeer-regels.
    try:
        _handled = (intake_store.load_home_handled() or {}) if intake_store else {}
    except Exception:
        _handled = {}
    _vandaag = date.today()

    # ── Sweeps (serieel, betrouwbaar) ──
    wachten = gepost = 0
    try:
        wk, stats = FS.get_workouts_needing_feedback(7, None, False, True,
                                                     {"los schema"}, True)
        wachten = len(feedback_core._filter_skipped(wk))
        gepost = stats.get("posted_today", 0)
    except Exception:
        pass
    try:
        alerts = FS.get_compliance_alerts(7, on_hold, {"los schema"})
    except Exception:
        alerts = []
    try:
        schema_rows = FS.get_schema_end_dates(60, on_hold)
    except Exception:
        schema_rows = []
    try:
        races = sum(1 for r in FS.get_upcoming_races(7) if not r.get("wish_given"))
    except Exception:
        races = 0
    atleten_objs = _atleten_objs()
    try:
        atleten = len(FS.get_athletes())
    except Exception:
        atleten = len(atleten_objs)
    groepen = 0
    try:
        groepen = len(FS.get_athletes_by_group())
    except Exception:
        pass

    # Belasting-signalen van vandaag — berekend als de dagstand ontbreekt (los van Teampuls)
    bel = _belasting_vandaag(atleten_objs)
    bel_hoog = sum(1 for b in bel if b.get("ernst") == "hoog")

    # ── Prioriteit vandaag: ÉÉN atleet = ÉÉN rij ──────────────────────────────
    # We dedupliceren niet meer wég maar GROEPEREN alle signalen per atleet in één
    # rij (coach-first: "welke atleten vragen aandacht?"). Elk signaal draagt zijn
    # eigen tier/reden/detail/fingerprint. Suppressie is PER signaal (Gezien/Later);
    # blijft er geen signaal over, dan valt de atleet uit de werklijst.
    # Alle detail wordt TIJDENS deze sweep gevuld → uitklappen kost 0 requests.
    atl: dict[str, dict] = {}

    def _sig(uk, naam, first, soort, tier, reden, kort, fingerprint, severity, detail, context):
        if not uk:
            return
        rij = atl.get(uk)
        if rij is None:
            rij = atl[uk] = {"user_key": uk, "naam": naam,
                             "voornaam": _voornaam(naam, first), "signalen": []}
        rij["signalen"].append({
            "soort": soort, "tier": tier, "reden": reden, "kort": kort,
            "fingerprint": fingerprint, "severity": severity, "detail": detail, "context": context,
        })

    # Afhakers (compliance) = actie (rood). severity = aantal gemist (meer = erger).
    for a in alerts:
        n_low, n_pl = a.get("n_low", 0), a.get("n_planned", 0)
        _sig(a.get("user_key"), a.get("name", ""), a.get("first_name", ""),
             "compliance", "actie", f"{n_low} van {n_pl} trainingen gemist",
             f"{n_low} gemist", f"c{n_low}", n_low,
             {"n_low": n_low, "n_planned": n_pl, "groep": a.get("group", "")},
             [])                                         # context = Dossier (universeel)

    # Schema verlopen (actie, severity 2) / loopt af ≤7d (aandacht, severity 1)
    for r in schema_rows:
        d = r.get("days_left")
        if d is None:
            continue
        det = {"days_left": d, "einddatum": r.get("last_date"), "groep": r.get("group", ""),
               "verborgen": r.get("hidden_count", 0), "zichtbaar_tot": r.get("visible_until")}
        ctx = [{"act": "schema", "label": "Schema", "icon": "clock"}]
        if d < 0:
            _sig(r.get("user_key"), r.get("name", ""), r.get("first_name", ""),
                 "schema", "actie", f"schema {abs(d)} dag{'en' if abs(d) != 1 else ''} verlopen",
                 "schema verlopen", f"s{r.get('last_date')}:v", 2, det, ctx)
        elif d <= 7:
            _sig(r.get("user_key"), r.get("name", ""), r.get("first_name", ""),
                 "schema", "aandacht", f"schema loopt af over {d} dag{'en' if d != 1 else ''}",
                 f"schema nog {d}d", f"s{r.get('last_date')}:a", 1, det, ctx)

    # Belasting (hoog = actie/severity 2, let op = aandacht/severity 1) — escalatie = erger
    for b in bel:
        hoog = b.get("ernst") == "hoog"
        tier = "actie" if hoog else "aandacht"
        reden = (b.get("signalen") or ["belasting-signaal"])[0]
        m = b.get("metrics") or {}
        km_r, km_b = m.get("km_recent"), m.get("km_basis_week")
        pct = None
        try:
            if km_r is not None and km_b:
                pct = round((float(km_r) / float(km_b) - 1) * 100)
        except (TypeError, ValueError, ZeroDivisionError):
            pct = None
        det = {
            "ernst": b.get("ernst", ""),
            "signalen": b.get("signalen") or [],
            "groep": b.get("group", ""),
            "km_recent": km_r, "km_basis": km_b, "pct": pct,
            "gevoel_recent": m.get("gevoel_recent"), "gevoel_basis": m.get("gevoel_basis"),
            "rpe_recent": m.get("rpe_recent"), "rpe_basis": m.get("rpe_basis"),
            "runs": (m.get("runs_recent") or [])[:5],
        }
        _sig(b.get("user_key"), b.get("naam", ""), "", "belasting", tier, reden,
             reden, f"b{b.get('ernst', '')}", 2 if hoog else 1, det,
             [{"act": "teampuls", "label": "Teampuls", "icon": "pulse"}])

    # ── Suppressie (severity-gated) + rij opbouwen ──
    items = []
    for uk, rij in atl.items():
        zichtbaar = [s for s in rij["signalen"]
                     if not _handled_active(_handled.get(f"{uk}|{s['soort']}"),
                                            s["severity"], _vandaag)]
        it = _bouw_item(uk, rij["naam"], rij["voornaam"], zichtbaar)
        if it:
            items.append(it)

    # Deterministische, uitlegbare ranking binnen tier: meer signalen eerst, dan
    # ernst-score, dan alfabetisch (stabiel = geen springen bij gelijke stand).
    items.sort(key=lambda i: (_TIER_RANK.get(i["tier"], 9), -i["n_signalen"],
                              -i["_score"], _norm_naam(i["naam"])))

    n_actie = sum(1 for i in items if i["tier"] == "actie")
    n_aandacht = sum(1 for i in items if i["tier"] == "aandacht")
    rustig = max(atleten - n_actie - n_aandacht, 0)
    totaal = wachten + gepost
    pct = int(gepost / totaal * 100) if totaal else 100

    return {
        "fs": True,
        "atleten": atleten,
        "groepen": groepen,
        "team": {"actie": n_actie, "aandacht": n_aandacht, "rustig": rustig},
        "feedback": {"wachten": wachten, "gepost": gepost, "pct": pct},
        "info": {"races": races, "gepost": gepost},
        "belasting": {"totaal": len(bel), "hoog": bel_hoog},
        "prioriteit": items,                       # gegroepeerd per atleet = werkbare lijst
        "prioriteit_totaal": len(items),
        "berekend": datetime.now().isoformat(timespec="seconds"),
        "datum": date.today().isoformat(),
    }


# ── Werklijst-actie: één generieke Gezien/Later per atleet ───────────────────
# 'Gezien' = beoordeeld (komt terug bij verergering of na 7 dagen). 'Later' =
# snooze tot een datum. Wordt per aanwezig signaaltype vastgelegd (met fingerprint)
# in de gedeelde home_handled-store. DUAL-WRITE naar de bestaande per-type stores
# (alerts_handled / belasting.afgehandeld) houdt Teampuls + Streamlit-home in sync.

def _mem_demp(user_key: str, soorten: set) -> None:
    """Werk de in-memory snapshot bij na een actie: verwijder de gedempte soorten uit
    de rij; blijft er niets over → atleet valt weg. Zo blijft een tweede lezer (andere
    coach) consistent vóór de volgende refresh. Client blijft leidend voor de UI."""
    global _MEM
    if not _valid(_MEM):
        return
    nieuw = []
    for it in _MEM.get("prioriteit", []):
        if it.get("user_key") != user_key:
            nieuw.append(it)
            continue
        rest = [s for s in it.get("signalen", []) if s["soort"] not in soorten]
        herbouwd = _bouw_item(user_key, it.get("naam", ""), it.get("voornaam", ""), rest)
        if herbouwd:
            nieuw.append(herbouwd)
    _MEM = {**_MEM, "prioriteit": nieuw, "prioriteit_totaal": len(nieuw)}


def _dual_write(user_key: str, naam: str, soort: str, sig: dict, tot: str, undo: bool) -> None:
    """Houd de bestaande pagina's in sync — met de ECHTE einddatum (tot) en severity,
    zodat 3/7/14 dagen én escalatie overal gelijk werken. Per signaaltype:
    compliance → alerts_handled (Streamlit-home), belasting → belasting.afgehandeld
    (Teampuls). Schema heeft geen legacy-dempstore."""
    if soort == "compliance":
        try:
            h = intake_store.load_alerts_handled() or {}
            if undo:
                h.pop(user_key, None)
            else:
                n_low = (sig.get("detail") or {}).get("n_low", sig.get("severity", 0))
                h[user_key] = {"tot": tot, "n_low": n_low, "naam": naam,
                               "datum": date.today().isoformat()}   # datum = backward-compat
            intake_store.save_alerts_handled(h)
        except Exception:
            pass
    elif soort == "belasting":
        try:
            import belasting
            data = belasting.laad_stand()
            afg = data.setdefault("afgehandeld", {})
            if undo:
                afg.pop(user_key, None)
            else:
                ernst = (sig.get("detail") or {}).get("ernst") or "let_op"
                afg[user_key] = {"tot": tot, "ernst": ernst}        # zichtbare_resultaten honoreert tot + escalatie
            intake_store.save_belasting(data)
        except Exception:
            pass


def handled(user_key: str, status: str = "gezien", snooze_dagen: int = 7,
            undo: bool = False, by: str = "", soort: str | None = None) -> tuple[bool, str]:
    """Zet de werklijst-status (Gezien/Later) voor een atleet. soort=None → BULK over
    alle huidige signalen (swipe); soort gezet → alleen dat ene signaal (detail).
    Legt severity + einddatum (tot) vast → severity-gated terugkeer, en dual-write
    houdt Teampuls/Streamlit consistent."""
    if not user_key or intake_store is None:
        return False, "geen opslag"
    # Huidige signalen uit de laatste snapshot (met severity/fingerprint/detail).
    sig_per_soort, naam = {}, ""
    for it in (_MEM.get("prioriteit") or []):
        if it.get("user_key") == user_key:
            naam = it.get("naam", "")
            for s in it.get("signalen", []):
                sig_per_soort[s["soort"]] = s
            break
    try:
        store = intake_store.load_home_handled() or {}
    except Exception:
        store = {}
    vandaag = date.today()
    # Doel-soorten: één (detail) of alle huidige (bulk). Bij undo zonder snapshot
    # kennen we de soorten niet meer → dan ruimen we alle uk|* op.
    doelen = [soort] if soort else list(sig_per_soort.keys())

    if undo:
        keys = [f"{user_key}|{soort}"] if soort else [k for k in store if k.startswith(f"{user_key}|")]
        undo_soorten = {k.split("|", 1)[1] for k in keys} or {"compliance", "belasting"}
        for k in keys:
            store.pop(k, None)
        for s in undo_soorten:
            _dual_write(user_key, naam, s, {}, "", True)
    else:
        for s in doelen:
            sg = sig_per_soort.get(s)
            if sg is None:
                continue
            if status == "later":
                tot = (vandaag + timedelta(days=max(1, int(snooze_dagen or 7)))).isoformat()
            else:
                tot = (vandaag + timedelta(days=7)).isoformat()
            store[f"{user_key}|{s}"] = {
                "status": status, "fingerprint": sg.get("fingerprint"),
                "severity": sg.get("severity"), "handled_at": vandaag.isoformat(),
                "snooze_until": tot if status == "later" else None, "tot": tot, "by": by,
            }
            _dual_write(user_key, naam, s, sg, tot, False)

    grens = (vandaag - timedelta(days=45)).isoformat()               # oude records opruimen
    for k in [k for k in store if (store.get(k) or {}).get("handled_at", "") < grens]:
        del store[k]
    ok, msg = intake_store.save_home_handled(store)
    if not undo:
        _mem_demp(user_key, set(doelen))                             # snapshot bijwerken (geen volle refresh)
    return ok, msg


def prio_trainingen(user_key: str) -> dict:
    """Lazy detail voor een afhaker: WELKE geplande trainingen (laatste 7 dagen)
    gemist/half/gedaan zijn. Eén atleet — geen roster-sweep. Client cachet dit."""
    if not user_key or not _heeft_token():
        return {"trainingen": []}
    today = date.today()
    start, end = today - timedelta(days=7), today - timedelta(days=1)
    try:
        workouts = FS.get_workouts_deduped(user_key, start, end)
    except Exception:
        return {"trainingen": []}
    rijen = []
    for w in workouts:
        if w.get("is_race"):
            continue
        act = (w.get("Activities") or [{}])[0]
        p_km = float(act.get("planned_amount") or 0)
        p_sec = float(act.get("planned_duration") or 0)
        if not (p_km or p_sec or (w.get("description") or "").strip()):
            continue                                    # geen echte geplande training
        if not w.get("has_actual_data"):
            score = 0.0
        elif p_km:
            score = min(float(act.get("amount") or 0) / p_km, 1.0)
        elif p_sec:
            score = min(float(act.get("duration") or 0) / p_sec, 1.0)
        else:
            score = 1.0
        status = "gemist" if score <= 0 else ("half" if score < 0.5 else "gedaan")
        rijen.append({
            "datum": (w.get("workout_date") or "")[:10],
            "type": act.get("name") or w.get("name") or "Training",
            "status": status,
            "km_planned": round(p_km, 1) if p_km else None,
            "km_actual": round(float(act.get("amount") or 0), 1) if p_km else None,
        })
    rijen.sort(key=lambda r: r["datum"])
    return {"trainingen": rijen}
