"""Home ↔ Teampuls belasting-coherentie (consistency-laag).

Harde invariant: bij DEZELFDE actuele opgeslagen belastingstand moeten Home en
Teampuls dezelfde load truth zien (zelfde cohort, ernst). Verschillen mogen alleen
uit Home's eigen projectieregels komen (home_handled-suppressie, groepering), NIET
uit verschillende snapshots of refreshmomenten.

Root cause die dit afdekt: Home fast-read toonde de bij zijn laatste `_bereken`
BEVROREN belasting-cohort (uit home_snapshot.json), terwijl Teampuls fast-read de
LIVE belasting.json leest. `_apply_belasting_overlay` reconcilieert Home's belasting
op elk leespad tegen exact diezelfde live stand.

    python3 -m pytest tests/test_home_teampuls_belasting_coherence.py -q
"""
import os
import sys
from datetime import date, datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import belasting as _bel                     # noqa: E402
import home_core as _home                    # noqa: E402
import teampuls_core as _tp                  # noqa: E402

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def _res(uk, naam, ernst, km_r=60.0, km_b=20.0):
    ratio = km_r / km_b
    return {"user_key": uk, "naam": naam, "group": "A", "ernst": ernst,
            "signalen": [f"Volume +{round((ratio - 1) * 100)}% deze week"],
            "codes": ["volume"] if ernst != "hoog" else ["volume", "klachten"],
            "metrics": {"km_recent": km_r, "km_basis_week": km_b, "ratio": ratio,
                        "runs_recent": []}}


def _stand(datum, results, afgehandeld=None):
    return {"datum": datum, "resultaten": results, "afgehandeld": afgehandeld or {}}


def _snap(frozen_results, atleten=10):
    """Home-snapshot met een BEVROREN belasting-cohort (zoals _bereken zou bakken)."""
    items = []
    for b in frozen_results:
        sig = _home._belasting_signal(b)
        it = _home._bouw_item(b["user_key"], b["naam"],
                              _home._voornaam(b["naam"], ""), [sig])
        items.append(it)
    n_actie = sum(1 for i in items if i["tier"] == "actie")
    n_aandacht = sum(1 for i in items if i["tier"] == "aandacht")
    return {"fs": True, "atleten": atleten, "groepen": 3,
            "team": {"actie": n_actie, "aandacht": n_aandacht,
                     "rustig": atleten - n_actie - n_aandacht},
            "feedback": None,                                     # isoleer belasting
            "belasting": {"totaal": len(frozen_results), "hoog": n_actie},
            "prioriteit": items, "prioriteit_totaal": len(items),
            "berekend": datetime.now().isoformat(timespec="seconds"), "datum": TODAY}


def _home_bel(res):
    """{user_key: ernst} van de belasting-signalen die Home toont."""
    out = {}
    for it in res.get("prioriteit", []) or []:
        for s in it.get("signalen", []):
            if s.get("soort") == "belasting":
                out[it["user_key"]] = s["detail"]["ernst"]
    return out


def _tp_bel(res):
    return {i["user_key"]: i["ernst"] for i in res.get("items", []) or []}


def _wire(monkeypatch, stand, handled=None):
    """Home + Teampuls lezen dezelfde live belasting-stand; home_handled leeg tenzij gezet."""
    monkeypatch.setattr(_home, "_heeft_token", lambda: True)
    monkeypatch.setattr(_tp, "heeft_token", lambda: True)
    monkeypatch.setattr(_bel, "laad_stand", lambda: stand)       # ÉÉN gedeelde bron
    monkeypatch.setattr(_home.intake_store, "load_home_handled", lambda: handled or {})


class TestSameStandSameTruth:
    def test_1_home_leest_live_niet_bevroren_cohort(self, monkeypatch):
        # Snapshot bevroren met atleet X; live stand heeft atleet Y (ander cohort).
        snap = _snap([_res("X", "Xander Oud", "hoog")])
        live = _stand(TODAY, [_res("Y", "Yara Nieuw", "hoog")])
        _wire(monkeypatch, live)
        monkeypatch.setattr(_home, "_current", lambda: snap)

        home = _home.cockpit(refresh=False)
        tp = _tp.signalen(force=False)
        # Home toont het LIVE cohort (Y), niet het bevroren (X) — en gelijk aan Teampuls.
        assert _home_bel(home) == {"Y": "hoog"}
        assert _tp_bel(tp) == {"Y": "hoog"}
        assert _home_bel(home) == _tp_bel(tp)

    def test_2_zelfde_stand_zelfde_load_truth_meerdere(self, monkeypatch):
        results = [_res("a", "Anna", "hoog"), _res("b", "Bram", "let_op", km_r=28, km_b=20),
                   _res("c", "Cas", "hoog")]
        live = _stand(TODAY, results)
        # Home-snapshot bevroren met een DEELS ANDER cohort (mist c, heeft stale d).
        snap = _snap([_res("a", "Anna", "let_op", km_r=25, km_b=20),
                      _res("d", "Daan Weg", "hoog")])
        _wire(monkeypatch, live)
        monkeypatch.setattr(_home, "_current", lambda: snap)

        home = _home.cockpit(refresh=False)
        tp = _tp.signalen(force=False)
        assert _home_bel(home) == {"a": "hoog", "b": "let_op", "c": "hoog"}
        assert _home_bel(home) == _tp_bel(tp)                    # identieke load truth

    def test_3_suppressie_consistent_beide(self, monkeypatch):
        morgen = (date.today() + timedelta(days=1)).isoformat()
        live = _stand(TODAY, [_res("a", "Anna", "hoog"), _res("b", "Bram", "hoog")],
                      afgehandeld={"b": {"tot": morgen, "ernst": "hoog"}})
        snap = _snap([_res("a", "Anna", "hoog"), _res("b", "Bram", "hoog")])
        _wire(monkeypatch, live)
        monkeypatch.setattr(_home, "_current", lambda: snap)

        home = _home.cockpit(refresh=False)
        tp = _tp.signalen(force=False)
        # b is afgehandeld (belasting.afgehandeld) → onzichtbaar in BEIDE.
        assert "b" not in _home_bel(home) and "b" not in _tp_bel(tp)
        assert _home_bel(home) == _tp_bel(tp) == {"a": "hoog"}

    def test_4_nieuwe_atleet_verschijnt_op_home(self, monkeypatch):
        live = _stand(TODAY, [_res("nieuw", "Nova", "hoog")])
        snap = _snap([])                                         # snapshot had geen belasting
        _wire(monkeypatch, live)
        monkeypatch.setattr(_home, "_current", lambda: snap)
        home = _home.cockpit(refresh=False)
        assert _home_bel(home) == {"nieuw": "hoog"}


class TestFreshnessReconcile:
    def test_5_stale_stand_zelfde_cohort_beide_stale(self, monkeypatch):
        # Stale (gisteren) stand: Home + Teampuls tonen HETZELFDE cohort, beide gemarkeerd stale.
        live = _stand(YESTERDAY, [_res("a", "Anna", "hoog")])
        snap = _snap([_res("a", "Anna", "hoog")])
        _wire(monkeypatch, live)
        monkeypatch.setattr(_home, "_current", lambda: snap)
        home = _home.cockpit(refresh=False)
        tp = _tp.signalen(force=False)
        assert _home_bel(home) == _tp_bel(tp) == {"a": "hoog"}
        assert home["belasting"]["vers"] is False                # Home weet: belasting stale
        assert tp["stale"] is True and tp["vers"] is False       # Teampuls idem

    def test_6_na_recompute_convergeren_beide_naar_today(self, monkeypatch):
        # Vóór refresh: stale gisteren-cohort. Na recompute naar today: beide zien today.
        holder = {"stand": _stand(YESTERDAY, [_res("oud", "Oud", "hoog")])}
        snap = _snap([_res("oud", "Oud", "hoog")])
        monkeypatch.setattr(_home, "_heeft_token", lambda: True)
        monkeypatch.setattr(_tp, "heeft_token", lambda: True)
        monkeypatch.setattr(_bel, "laad_stand", lambda: holder["stand"])
        monkeypatch.setattr(_home.intake_store, "load_home_handled", lambda: {})
        monkeypatch.setattr(_home, "_current", lambda: snap)

        home_pre = _home.cockpit(refresh=False)
        tp_pre = _tp.signalen(force=False)
        assert _home_bel(home_pre) == _tp_bel(tp_pre) == {"oud": "hoog"}

        # Recompute → today-cohort in dezelfde gedeelde store.
        holder["stand"] = _stand(TODAY, [_res("vers", "Vera", "hoog")])
        home_post = _home.cockpit(refresh=False)
        tp_post = _tp.signalen(force=False)
        assert _home_bel(home_post) == _tp_bel(tp_post) == {"vers": "hoog"}
        assert home_post["belasting"]["vers"] is True and tp_post["vers"] is True


class TestTransientNullGuard:
    def test_7_geen_stand_veegt_home_niet_weg(self, monkeypatch):
        # Lege/onbereikbare stand (geen datum) → Home behoudt zijn bekende belasting
        # (nooit een transient wipe die van Teampuls zou verschillen na een echte read).
        snap = _snap([_res("a", "Anna", "hoog")])
        monkeypatch.setattr(_home, "_heeft_token", lambda: True)
        monkeypatch.setattr(_bel, "laad_stand", lambda: {})      # geen datum
        monkeypatch.setattr(_home.intake_store, "load_home_handled", lambda: {})
        monkeypatch.setattr(_home, "_current", lambda: snap)
        home = _home.cockpit(refresh=False)
        assert _home_bel(home) == {"a": "hoog"}                  # niet weggeveegd

    def test_8_bron_fout_laat_snapshot_ongemoeid(self, monkeypatch):
        snap = _snap([_res("a", "Anna", "hoog")])
        def _boom():
            raise RuntimeError("store onbereikbaar")
        monkeypatch.setattr(_home, "_heeft_token", lambda: True)
        monkeypatch.setattr(_bel, "laad_stand", _boom)
        monkeypatch.setattr(_home.intake_store, "load_home_handled", lambda: {})
        monkeypatch.setattr(_home, "_current", lambda: snap)
        home = _home.cockpit(refresh=False)
        assert _home_bel(home) == {"a": "hoog"}


class TestProjectionOnlyDifferences:
    def test_9_home_handled_suppressie_is_projectieregel(self, monkeypatch):
        # Verschil dat WEL mag: home_handled dempt een atleet op Home (projectieregel),
        # terwijl de belasting-load truth (cohort/ernst) identiek uit dezelfde stand komt.
        live = _stand(TODAY, [_res("a", "Anna", "hoog")])
        snap = _snap([_res("a", "Anna", "hoog")])
        morgen = (date.today() + timedelta(days=1)).isoformat()
        handled = {"a|belasting": {"status": "gezien", "tier": "actie", "tot": morgen}}
        _wire(monkeypatch, live, handled=handled)
        monkeypatch.setattr(_home, "_current", lambda: snap)
        home = _home.cockpit(refresh=False)
        # Home onderdrukt 'a' via home_handled; dat is een projectieregel, geen ander cohort.
        assert "a" not in _home_bel(home)
        # De onderliggende load truth is nog steeds die van de gedeelde stand:
        assert _tp_bel(_tp.signalen(force=False)) == {"a": "hoog"}
