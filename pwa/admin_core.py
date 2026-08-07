"""Administratie voor de PWA — financiële cockpit (lezend).

Hergebruikt exact de pure rekenfuncties uit admin.py (KOR-projectie, btw-stand,
omzet per categorie/pakket, niet-gefactureerde klanten, potjes-advies) zodat de
cijfers 1-op-1 gelijk zijn aan Streamlit. admin.py trekt streamlit+pandas mee die
in de PWA-omgeving niet staan; die gebruikt admin.py alleen in de render-functies.
Daarom stubben we ze vóór de import — de pure functies raken ze nooit.

Afgeschermd met ADMIN_PIN (net als Streamlit). Zonder ADMIN_PIN: vergrendeld.
Puur lezend — schrijft niets terug.
"""
from __future__ import annotations

import hmac
import os
import sys
import types
from datetime import date

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Stub streamlit + pandas zodat admin.py importeerbaar is zonder die packages.
for _m in ("streamlit", "pandas"):
    if _m not in sys.modules:
        try:
            __import__(_m)
        except Exception:
            sys.modules[_m] = types.ModuleType(_m)

import fs_client as FS
import admin                                           # nu veilig (gestubd)
import intake_store

try:
    import rompslomp_client
except Exception:
    rompslomp_client = None


def _pin() -> str:
    return (os.environ.get("ADMIN_PIN", "") or "").strip()


def status() -> dict:
    """Of de module bruikbaar is: pincode ingesteld + FinalSurge gekoppeld."""
    return {
        "vergrendeld": not bool(_pin()),
        "fs": _heeft_token(),
        "rompslomp": bool(rompslomp_client and rompslomp_client.is_configured()),
    }


def check_pin(pin: str) -> bool:
    p = _pin()
    return bool(p) and hmac.compare_digest((pin or "").strip(), p)


def _heeft_token() -> bool:
    try:
        return bool(FS.get_token())
    except Exception:
        return False


def _atleten() -> list:
    try:
        return FS.get_athletes()
    except Exception:
        return []


def _facturen(jaar: int) -> tuple[list, str]:
    if not (rompslomp_client and rompslomp_client.is_configured()):
        return [], "Rompslomp niet gekoppeld — facturen/btw ontbreken."
    try:
        return rompslomp_client.get_invoices(jaar)
    except Exception as e:
        return [], f"Rompslomp-fout: {e}"


def _eur(v) -> float:
    try:
        return round(float(v or 0), 2)
    except Exception:
        return 0.0


def overzicht(pin: str) -> dict:
    """Volledige cockpit-payload. Vereist een geldige pincode."""
    if not check_pin(pin):
        return {"ok": False, "err": "pin"}

    jaar = date.today().year
    atleten = _atleten()
    admin_clients = {}
    try:
        admin_clients = intake_store.load_admin_clients() or {}
    except Exception:
        pass
    prijzen = admin._prijzen()
    revenue = admin._revenue()
    try:
        correctie = intake_store.load_kor_correctie()
    except Exception:
        correctie = 0.0
    revenue_corr = admin._met_correctie(revenue, correctie)

    facturen, fx_err = _facturen(jaar)

    # KOR / btw — de app is per 1 aug 2026 in btw-modus.
    modus = "kor" if date.today() < admin.KOR_TOT else "btw"
    proj = admin.kor_projectie(revenue_corr)
    kor = {
        "huidig": _eur(proj["huidig"]),
        "grens": admin.KOR_GRENS,
        "resterend": _eur(proj["resterend"]),
        "per_week": _eur(proj["per_week"]) if proj["per_week"] else None,
        "gepasseerd": bool(proj["gepasseerd"]),
        "datum_grens": proj["datum_grens"].isoformat() if proj["datum_grens"] else None,
        "laatste_maand": proj["laatste_maand"],
        "pct": round(min(_eur(proj["huidig"]) / admin.KOR_GRENS * 100, 100), 1) if admin.KOR_GRENS else 0,
    }
    btw = admin.btw_stand(facturen)

    # Klantstatus-telling
    tel = {"actief": 0, "on_hold": 0, "opgezegd": 0, "gratis": 0}
    for a in atleten:
        v = admin_clients.get(a["user_key"], {})
        st_ = v.get("status", "Actief")
        if st_ == "Actief":
            tel["actief"] += 1
        elif st_ == "On hold":
            tel["on_hold"] += 1
        elif st_ == "Opgezegd":
            tel["opgezegd"] += 1
        if v.get("gratis"):
            tel["gratis"] += 1

    jaaromzet = _eur(admin.geschatte_jaaromzet(atleten, admin_clients, prijzen, "Actief"))

    # Omzet per categorie (werkelijk gefactureerd) + kleuren
    cat = admin.omzet_per_categorie(facturen)
    categorie = [{"naam": k, "bedrag": _eur(v),
                  "kleur": admin.CATEGORIE_KLEUR.get(k, "#8FA8CE")}
                 for k in admin.CATEGORIE_VOLGORDE if cat.get(k)]
    # eventuele categorieën buiten de vaste volgorde
    for k, v in cat.items():
        if k not in admin.CATEGORIE_VOLGORDE:
            categorie.append({"naam": k, "bedrag": _eur(v), "kleur": "#8FA8CE"})

    # Verwachte jaaromzet per pakket
    pak = admin.omzet_per_pakket(atleten, admin_clients, prijzen)
    pakketten = [{"naam": k, "bedrag": _eur(v)}
                 for k, v in sorted(pak.items(), key=lambda x: -x[1])]

    # Niet-gefactureerde actieve klanten (hint)
    try:
        nf = admin.niet_gefactureerde_klanten(atleten, admin_clients, facturen)
        niet_gefactureerd = [a["name"] for a in nf]
    except Exception:
        niet_gefactureerd = []

    return {
        "ok": True,
        "jaar": jaar,
        "modus": modus,
        "kor": kor,
        "btw": btw,
        "tellen": tel,
        "jaaromzet": jaaromzet,
        "categorie": categorie,
        "pakketten": pakketten,
        "niet_gefactureerd": niet_gefactureerd,
        "rompslomp": bool(rompslomp_client and rompslomp_client.is_configured()),
        "fx_err": fx_err or "",
    }
