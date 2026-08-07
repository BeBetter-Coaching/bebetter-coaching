"""Verenigde atletenlaag voor de PWA: FinalSurge-roster + gedeelde store-data.

De PWA had tot nu toe alleen atleten mét een opgeslagen intake (store). Met de
FinalSurge-koppeling (fs_core) tonen we nu de VOLLEDIGE roster, en voegen we per
atleet de store-data (intake/notities/documenten) toe waar die er is — gematcht
op genormaliseerde naam. FinalSurge is leidend voor "wie zijn mijn atleten"; de
store voegt "wat weet/bewaar ik over ze" toe.

Sleutel-conventie: FinalSurge `user_key` is de primaire id. Store-data die we
nieuw aanmaken (notities/geheugen voor een FS-atleet zonder intake) sleutelen we
óók op `user_key`, zodat alles samenkomt. Store-atleten zonder FS-match (bv. een
publieke intake die nog niet in FinalSurge staat) blijven gewoon zichtbaar op hun
eigen store-key.

Degradeert netjes: zonder FS-token val je terug op puur de store (gedrag van
vóór de koppeling), zodat de app altijd blijft werken.
"""
from __future__ import annotations

import re

import dossier_core
import fs_core


def _norm(naam: str) -> str:
    return re.sub(r"\s+", " ", (naam or "").strip().lower())


def verenigde_roster() -> dict:
    """Alle atleten: FinalSurge-roster verrijkt met store-data (op naam gematcht)."""
    store = dossier_core.list_athletes()
    store_by_name = {_norm(s["naam"]): s for s in store}
    gebruikt: set[str] = set()

    rijen: list[dict] = []
    for a in fs_core.roster():                          # leeg als geen token → val terug op store
        s = store_by_name.get(_norm(a["naam"]))
        if s:
            gebruikt.add(s["key"])
        rijen.append({
            "id": a["user_key"],                       # primaire id = FS user_key
            "user_key": a["user_key"],
            "store_key": s["key"] if s else None,
            "naam": a["naam"],
            "voornaam": a["voornaam"],
            "groep": a["groep"],
            "heeft_intake": bool(s),
            "n_notities": s["n_notities"] if s else 0,
            "n_documenten": s["n_documenten"] if s else 0,
        })

    # Store-atleten zonder FS-match: tóch tonen (bv. publieke intake, nog niet in FS)
    for s in store:
        if s["key"] in gebruikt:
            continue
        rijen.append({
            "id": s["key"],
            "user_key": None,
            "store_key": s["key"],
            "naam": s["naam"],
            "voornaam": (s["naam"] or "").split(" ")[0],
            "groep": "",
            "heeft_intake": True,
            "nieuw": s.get("nieuw", False),
            "n_notities": s["n_notities"],
            "n_documenten": s["n_documenten"],
        })

    rijen.sort(key=lambda x: _norm(x["naam"]))
    return {"atleten": rijen, "fs": fs_core.heeft_token(), "totaal": len(rijen)}


def _match_store_key(user_key: str, naam: str) -> str | None:
    """Vind de store-key voor een FS-atleet (op naam), of None."""
    for s in dossier_core.list_athletes():
        if _norm(s["naam"]) == _norm(naam):
            return s["key"]
    return None


def detail(ident: str) -> dict | None:
    """Detail voor één atleet. `ident` = FS user_key OF een store-key.

    Combineert FinalSurge-trainingsdata (weeksignaal + recente trainingen) met het
    store-dossier (intake/notities/documenten/geheugen) waar beschikbaar.
    """
    fs_rows = {a["user_key"]: a for a in fs_core.roster()} if fs_core.heeft_token() else {}

    if ident in fs_rows:                                # FS-atleet
        a = fs_rows[ident]
        naam = a["naam"]
        store_key = _match_store_key(ident, naam)
        training = {
            "week": fs_core.weeksamenvatting(ident),
            "recent": fs_core.recente_trainingen(ident, dagen=14),
        }
    else:                                               # puur store-atleet
        store_key = ident
        naam = None
        training = {"week": {"deze_week": 0}, "recent": []}

    dossier = dossier_core.get_dossier(store_key) if store_key else None
    if dossier and not naam:
        naam = dossier.get("naam")

    if naam is None and not dossier:
        return None

    return {
        "id": ident,
        "user_key": ident if ident in fs_rows else None,
        "store_key": store_key,
        "naam": naam or ident,
        "groep": fs_rows.get(ident, {}).get("groep", ""),
        "training": training,
        "dossier": dossier,          # None als er nog geen store-data is
    }
