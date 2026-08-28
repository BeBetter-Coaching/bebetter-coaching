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


def _home_berekend() -> str:
    """Productie-tijd (`berekend`) van de Home-snapshot — géén sweep (leest _MEM/durable)."""
    try:
        import home_core
        return str((home_core._current() or {}).get("berekend") or "")
    except Exception:
        return ""


def _feedback_marker() -> tuple:
    """Feedback-openset-marker (status + wachten|gepost) — canoniek, geen FS-sweep. Zowel
    Home (uit de getoonde tegel) als Teampuls/Workspace leiden dezelfde marker af, zodat de
    generation-id cross-view gelijk is bij dezelfde state."""
    try:
        import feedback_core
        t = feedback_core.canonical_open_actions()
        return (str(t.get("status") or "UNKNOWN"), f"{t.get('wachten')}|{t.get('gepost')}")
    except Exception:
        return ("UNKNOWN", "")


def _bel_markers(stand: dict) -> tuple:
    """(datum, sig, produced_at) van een belasting-stand — de bron-versie van de belasting."""
    return (str(stand.get("datum") or ""), _belasting_sig(stand),
            str(stand.get("_produced_at") or ""))


def _compose_generation(b_datum: str, b_sig: str, b_prod: str,
                        h_ber: str, f_status: str, f_marker: str) -> dict:
    """Bouw het generation-stempel PUUR uit reeds-gelezen markers (geen tweede source-read).

    - `generation_id` = inhoud-afgeleide identiteit (zelfde bekende state → zelfde id).
    - `generation_at` = MONOTONE, productie-tijd afgeleide bronversie (max van de per-
      component productie-tijden). Hiermee is 'ouder vs nieuwer' deterministisch
      vergelijkbaar: een component-versie beweegt alleen vooruit (recompute/suppressie
      schrijven `now()`), dus het maximum is monotoon niet-dalend. NOOIT de leestijd:
      een oude persisted state die nu gelezen wordt houdt zijn oude `generation_at`.
    - `generated_at` = louter leeslabel; NIET voor ordering (zie boven).
    """
    today = date.today().isoformat()
    gen_id = _sha(b_datum, b_sig, h_ber, f_marker)
    gen_at = max([x for x in (b_prod or b_datum, h_ber) if x] or [""])
    return {
        "generation_id": gen_id,
        "generation_at": gen_at,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_versions": {"belasting": b_prod or b_datum, "home": h_ber},
        "freshness": {
            "belasting": "fresh" if (b_datum and b_datum == today)
                         else ("stale" if b_datum else "unknown"),
            "home": "fresh" if h_ber else "unknown",
            "feedback": (f_status or "UNKNOWN").lower(),
        },
        "sources": {"belasting_datum": b_datum, "belasting_sig": b_sig,
                    "home_berekend": h_ber, "feedback_status": f_status},
    }


def generation(stand: dict | None = None, snap: dict | None = None) -> dict:
    """DE ene read-generation, gebonden aan de CAPTURED payload.

    Belangrijk (external-review fix #1): de belasting-component wordt afgeleid uit exact
    dezelfde stand die de response toont — NIET uit een tweede `laad_stand()`:
      - `snap` met een reeds gereconcilieerd belasting-blok (Home: `snap['belasting']` draagt
        `sig`/`prod`) → gebruik díe markers (bind aan wat de overlay toonde);
      - anders `stand` (Teampuls/Workspace geven hun reeds-gelezen stand mee);
      - alleen als beide ontbreken lezen we de stand één keer (convenience/tests).
    Home-`berekend` komt uit `snap` (de gerenderde snapshot) indien meegegeven; feedback uit
    het getoonde tegel-blok (`snap['feedback']`) of anders één canonieke openset-read."""
    bel = (snap or {}).get("belasting") if isinstance(snap, dict) else None
    if isinstance(bel, dict) and bel.get("sig") is not None:
        b_datum, b_sig, b_prod = str(bel.get("datum") or ""), bel.get("sig") or "", str(bel.get("prod") or "")
    else:
        if stand is None:
            stand = _belasting_stand()
        b_datum, b_sig, b_prod = _bel_markers(stand)

    if isinstance(snap, dict) and snap.get("berekend") is not None:
        h_ber = str(snap.get("berekend") or "")
    elif isinstance(snap, dict) and "berekend" in snap:
        h_ber = ""
    else:
        h_ber = _home_berekend()

    fb = (snap or {}).get("feedback") if isinstance(snap, dict) else None
    if isinstance(fb, dict) and ("wachten" in fb):
        f_status, f_marker = "SNAP", f"{fb.get('wachten')}|{fb.get('gepost')}"
    else:
        f_status, f_marker = _feedback_marker()

    return _compose_generation(b_datum, b_sig, b_prod, h_ber, f_status, f_marker)


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


def _athlete_belasting(user_key: str, stand: dict | None = None) -> dict:
    """Live belasting voor één atleet via de gedeelde stand + `load_metric`. Zelfde
    zichtbaarheidsregel als Teampuls/Home (`zichtbare_resultaten`). `stand` kan worden
    meegegeven zodat de Workspace-shell en zijn generation exact dezelfde captured stand
    delen (review-fix #1)."""
    if stand is None:
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
    stand = _belasting_stand()                               # capture ÉÉN keer (review-fix #1)
    gen = generation(stand=stand)                            # generation ⇄ zelfde captured stand
    row = _home_row(user_key)
    naam = (row or {}).get("naam") or _roster_naam(user_key)
    bel = _athlete_belasting(user_key, stand=stand)          # load metric uit diezelfde stand
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
