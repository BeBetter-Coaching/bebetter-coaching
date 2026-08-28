"""Coach Read Model (v2) — één ephemeral read-projection met generation/freshness.

Doel (Athlete Workspace / Coach Cockpit v2): Home, Teampuls, Dossier en de nieuwe
Athlete Workspace mogen niet langer verschillende *generaties* van dezelfde waarheid
tegelijk tonen (de Tom `+46%` vs `+64%`-aanleiding). Dit model is een **compositie /
read-projection**, GEEN nieuwe business-truth:

  * het herberekent niets en bezit geen state;
  * het leest uitsluitend de bestaande canonieke bronnen (belasting-stand,
    Home-snapshot, Feedback open-set, brain AthleteState via bestaande endpoints);
  * `generation_id` is een **inhoud-afgeleide** signatuur over die bestaande bronnen,
    berekend op leesmoment — geen nieuwe persistente store, geen tweede AthleteState,
    geen extra GitHub-snapshot (zie ANALYSIS-coach-read-model.md §A).

Twee dingen die dit model canoniek maakt:
  1. `load_metric()` — DE ene belasting-%/ernst-projectie, gedeeld door Home, Teampuls
     én Dossier (voorheen drie losse formules → rondings-/formule-divergentie).
  2. `generation()` — één generation/freshness-stempel dat elke coach-read-response
     draagt, zodat een client "zelfde bekende state" vs "nieuwere state beschikbaar"
     kan bepalen i.p.v. `46` naast `64` als co-actueel te tonen.

Alle zware imports (belasting → dossier → streamlit/pandas) zijn lui, net als in
home_core/teampuls_core; en er is GEEN top-level import van home_core/feedback_core
zodat home_core dit veilig kan importeren zonder cycle.
"""
from __future__ import annotations

import hashlib
import os
import sys
import types
from datetime import date, datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# belasting → dossier importeert streamlit+pandas op moduleniveau; stub net als de
# andere cores zodat de pure lees-functies laden op Render.
for _m in ("streamlit", "pandas"):
    if _m not in sys.modules:
        try:
            __import__(_m)
        except Exception:
            sys.modules[_m] = types.ModuleType(_m)


# ── 1. DE ENE belasting-projectie ────────────────────────────────────────────
def load_metric(res: dict | None) -> dict:
    """Projecteer één belasting-resultaat naar het canonieke load-metric.

    ÉÉN formule, gedeeld door Home (`_belasting_signal`), Teampuls (`_norm`) en Dossier
    (`_load_observation`) zodat `+X%`/ernst nooit per view divergeren. `pct` = signed
    volume-percentage `round((ratio-1)*100)`; None als er geen ratio/km beschikbaar is.
    Prefereert de rúwe km-verhouding (precies) boven het voor-afgeronde `ratio`-veld —
    zo blijft het km-pad (Home) én het ratio-pad (Dossier) exact zoals voorheen."""
    res = res or {}
    m = res.get("metrics") or {}
    km_r, km_b = m.get("km_recent"), m.get("km_basis_week")
    ratio = None
    try:
        if km_r is not None and km_b:
            ratio = float(km_r) / float(km_b)
        elif m.get("ratio") is not None:
            ratio = float(m.get("ratio"))
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = None
    pct = round((ratio - 1) * 100) if ratio is not None else None
    return {
        "ernst": res.get("ernst", ""),
        "pct": pct,
        "km_recent": km_r,
        "km_basis_week": km_b,
        "signalen": res.get("signalen") or [],
        "reden": (res.get("signalen") or ["belasting-signaal"])[0],
    }


# ── 2. Generation / freshness (ephemeral, inhoud-afgeleid) ───────────────────
def _sha(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:12]


def _belasting_sig(stand: dict) -> str:
    """Inhoudssignatuur van de belasting-stand: verandert zodra de resultaten of de
    afgehandeld-map wijzigen — óók bij een same-day force-refresh die `datum` niet
    verandert maar de inhoud wél. Onafhankelijk van wall-clock."""
    rows = sorted(
        f"{r.get('user_key')}:{r.get('ernst')}:{(r.get('metrics') or {}).get('ratio')}"
        for r in (stand.get("resultaten") or []))
    afg = sorted((stand.get("afgehandeld") or {}).keys())
    return _sha(str(stand.get("datum") or ""), "|".join(rows), "|".join(afg))


def _belasting_stand() -> dict:
    try:
        import belasting
        return belasting.laad_stand() or {}
    except Exception:
        return {}


def generation() -> dict:
    """DE ene read-generation over de canonieke bronnen. `generation_id` is inhoud-
    afgeleid (zelfde bekende state → zelfde id; nieuwere state → ander id). `generated_at`
    is louter een label. `freshness` markeert per component wat vers/stale/unknown is
    zodat een trage belasting-refresh de schema-/klacht-context niet als stale meesleept."""
    today = date.today().isoformat()

    # belasting-stand (goedkope store-read)
    stand = _belasting_stand()
    b_datum = str(stand.get("datum") or "")
    b_sig = _belasting_sig(stand)
    b_fresh = bool(b_datum) and b_datum == today

    # Home-snapshot berekend-moment (geen sweep; leest _MEM/durable)
    h_ber = ""
    h_fresh = False
    try:
        import home_core
        snap = home_core._current() or {}
        h_ber = str(snap.get("berekend") or "")
        h_fresh = home_core._snap_recent(snap)
    except Exception:
        pass

    # Feedback open-set (canoniek; geen FS-sweep)
    f_status = "UNKNOWN"
    f_sig = ""
    try:
        import feedback_core
        t = feedback_core.canonical_open_actions()
        f_status = str(t.get("status") or "UNKNOWN")
        ids = t.get("open_ids") or []
        f_sig = _sha(f_status, "|".join(sorted(map(str, ids))), str(t.get("gepost")))
    except Exception:
        pass

    gen_id = _sha(b_datum, b_sig, h_ber, f_sig)
    return {
        "generation_id": gen_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "freshness": {
            "belasting": "fresh" if b_fresh else ("stale" if b_datum else "unknown"),
            "home": "fresh" if h_fresh else ("stale" if h_ber else "unknown"),
            "feedback": f_status.lower(),
        },
        "sources": {
            "belasting_datum": b_datum, "belasting_sig": b_sig,
            "home_berekend": h_ber, "feedback_status": f_status,
        },
    }


# ── 3. Team-niveau compositie (Home + Teampuls stempelen hiermee) ────────────
def team() -> dict:
    """Team-belasting-cohort via `load_metric` + één `generation`. Home en Teampuls
    dragen dezelfde generation wanneer ze dezelfde stand lezen → gelijke id én gelijke
    load-value (parity by construction)."""
    stand = _belasting_stand()
    items = []
    try:
        import belasting
        for r in belasting.zichtbare_resultaten(stand):
            lm = load_metric(r)
            items.append({"user_key": r.get("user_key"), "naam": r.get("naam", ""),
                          "ernst": lm["ernst"], "pct": lm["pct"]})
    except Exception:
        pass
    hoog = sum(1 for i in items if i["ernst"] == "hoog")
    return {
        "belasting": {"totaal": len(items), "hoog": hoog,
                      "datum": stand.get("datum"), "items": items},
        "generation": generation(),
    }


# ── 4. Athlete Workspace shell (snel — alleen goedkope stores) ───────────────
def _home_row(user_key: str) -> dict | None:
    """De canonieke Home-prioriteitsrij voor één atleet (attention/action), uit de
    bestaande Home-snapshot (_MEM/durable) — géén sweep. None als (nog) niet aanwezig."""
    try:
        import home_core
        snap = home_core._current() or {}
        for it in snap.get("prioriteit") or []:
            if it.get("user_key") == user_key:
                return it
    except Exception:
        pass
    return None


def _roster_naam(user_key: str) -> str:
    try:
        import fs_client as FS
        for a in FS.get_athletes():                      # roster-memo (90s) → goedkoop
            if a.get("user_key") == user_key:
                return a.get("name", "") or ""
    except Exception:
        pass
    return ""


def _athlete_belasting(user_key: str) -> dict:
    """Live belasting voor één atleet via de gedeelde stand + `load_metric`. Zelfde
    zichtbaarheidsregel als Teampuls/Home (`zichtbare_resultaten`)."""
    stand = _belasting_stand()
    try:
        import belasting
        zichtbaar = belasting.zichtbare_resultaten(stand)
    except Exception:
        zichtbaar = []
    res = next((r for r in zichtbaar if r.get("user_key") == user_key), None)
    if not res:
        return {"actief": False, "ernst": "", "pct": None,
                "datum": stand.get("datum")}
    lm = load_metric(res)
    return {"actief": True, "ernst": lm["ernst"], "pct": lm["pct"],
            "km_recent": lm["km_recent"], "km_basis_week": lm["km_basis_week"],
            "signalen": lm["signalen"], "reden": lm["reden"],
            "datum": stand.get("datum")}


def _athlete_feedback(user_key: str, naam: str) -> dict:
    """Best-effort per-atleet open-feedback-status uit de canonieke open-set (geen
    FS-sweep). Mapt op athlete_key (uit `_volle`) en valt terug op naam. `status` volgt
    de gedeelde generation-freshness; bij een ongeldige queue → unknown."""
    try:
        import feedback_core
        snap = feedback_core._queue_current()
        if not feedback_core._queue_valid(snap):
            return {"status": "unknown", "open": None}
        open_snap = feedback_core._apply_skips(snap)
        open_ids = {it.get("id") for it in open_snap.get("items", [])}
        volle = open_snap.get("_volle") or {}
        n = 0
        if volle:
            for wid, w in volle.items():
                if wid in open_ids and str(w.get("athlete_key")) == str(user_key):
                    n += 1
        else:                                            # lichte snapshot → naam-match
            nn = (naam or "").strip().lower()
            n = sum(1 for it in open_snap.get("items", [])
                    if (it.get("naam") or "").strip().lower() == nn) if nn else 0
        return {"status": "fresh", "open": n}
    except Exception:
        return {"status": "unknown", "open": None}


def _schema_signal(row: dict | None) -> dict | None:
    """Schema-signaal (verlopen / loopt-af) uit de Home-rij, indien aanwezig — anders
    None (de client haalt de rijke schema/doel-context lazy uit de deep-sectie)."""
    if not row:
        return None
    for s in row.get("signalen") or []:
        if s.get("soort") == "schema":
            det = s.get("detail") or {}
            return {"tier": s.get("tier"), "kort": s.get("kort"),
                    "days_left": det.get("days_left"), "einddatum": det.get("einddatum")}
    return None


def _attention(row: dict | None, bel: dict, fb: dict) -> list:
    """Compacte 'wat vraagt nu aandacht'-lijst (Aandacht nu), samengesteld uit de reeds
    canonieke signalen — geen nieuw oordeel. Volgorde: actie vóór aandacht."""
    out = []
    if bel.get("actief"):
        pct = bel.get("pct")
        kort = bel.get("reden") or "belasting-signaal"
        out.append({"soort": "belasting",
                    "tier": "actie" if bel.get("ernst") == "hoog" else "aandacht",
                    "kort": kort, "pct": pct})
    for s in (row or {}).get("signalen") or []:
        if s.get("soort") == "belasting":
            continue                                     # al via de live stand hierboven
        out.append({"soort": s.get("soort"), "tier": s.get("tier"),
                    "kort": s.get("kort")})
    if fb.get("open"):
        out.append({"soort": "feedback", "tier": "aandacht",
                    "kort": f"{fb['open']} open reactie{'s' if fb['open'] != 1 else ''}"})
    out.sort(key=lambda a: 0 if a.get("tier") == "actie" else 1)
    return out


def athlete(user_key: str) -> dict:
    """Workspace fast-read shell voor één atleet: identity · aandacht nu · live belasting ·
    schema-signaal · feedback-status · generation. Leest ALLEEN goedkope stores (belasting
    -stand, Home-snapshot, feedback open-set, roster-memo) → nooit een FS/AI-sweep in het
    renderpad (< 2s shell). De rijke context (klachten/planning/timeline/doel) haalt de
    client lazy en parallel uit het bestaande `/api/cockpit/{key}` (deep-sectie), zodat een
    trage load-/feedback-refresh de shell of de andere secties niet blokkeert."""
    if not user_key:
        return {"ok": False, "err": "geen atleet"}
    gen = generation()
    row = _home_row(user_key)
    naam = (row or {}).get("naam") or _roster_naam(user_key)
    bel = _athlete_belasting(user_key)
    fb = _athlete_feedback(user_key, naam)
    return {
        "ok": True,
        "key": user_key,
        "naam": naam,
        "voornaam": (row or {}).get("voornaam") or (naam.split(" ")[0] if naam else ""),
        "generation": gen,
        "attention": _attention(row, bel, fb),
        "belasting": bel,
        "schema": _schema_signal(row),
        "feedback": fb,
        # Deep-secties (klachten/planning/context/timeline + doel/huidig blok) zijn
        # canoniek en FS-duur → de client laadt ze lazy via deze bestaande endpoints.
        "deep": {"cockpit": f"/api/cockpit?key={user_key}"},
    }
