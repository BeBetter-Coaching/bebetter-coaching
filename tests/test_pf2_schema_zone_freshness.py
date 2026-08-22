"""PF-2 — FinalSurge zone-change → Schema refresh/freshness (Class B, Finding 3).

Een expliciete coach-refresh forceert ALTIJD een verse zone-read; mislukt die, dan is
de bronstatus expliciet LAST_KNOWN/UNAVAILABLE — nooit stil oude zones als 'fresh'. Een
lokaal draft mag de verse read niet blokkeren, en bestaande schema-inhoud/coach-edits
mogen door de refresh niet verdwijnen. PF-2 gaat over VERSHEID, niet classificatie
(FC-2 blijft ongemoeid).

Server: schema_core.zones_fresh / _resolve_zones / _zone_fingerprint / config_prefill +
/api/schema/zones. Client: source-guards op de refresh/draft-flow in app.js.

    python3 -m pytest tests/test_pf2_schema_zone_freshness.py -q
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pwa"))

import fs_client
import schema_core


ZONES_A = "Z1 (Herstel): >6:00 min/km\nZ2 (Easy): 5:30-6:00 min/km\nZ3 (Tempo): 4:40-5:00 min/km"
ZONES_B = "Z1 (Herstel): >6:10 min/km\nZ2 (Easy): 5:35-6:10 min/km\nZ3 (Tempo): 4:45-5:05 min/km"


def _fresh(text=ZONES_A, zt="tempo"):
    return {"zone_type": zt, "zones_text": text, "zones": [], "endpoint_used": "ZoneList"}


def _intake(zones=ZONES_A, zt="tempo", **extra):
    b = {"athlete_name": "Lisa T", "naam": "Lisa", "zones": zones, "zone_type": zt}
    b.update(extra)
    return b


# ════════════════════════════════════════════════════════════════════════════
# Fingerprint (6, 7) — inhoud-afgeleid, whitespace-stabiel
# ════════════════════════════════════════════════════════════════════════════
class TestFingerprint:
    def test_6_verandert_bij_echte_zonewijziging(self):
        assert schema_core._zone_fingerprint(ZONES_A, "tempo") != schema_core._zone_fingerprint(ZONES_B, "tempo")

    def test_7_equivalente_data_zelfde_fingerprint(self):
        # extra spaties / trailing whitespace / lege regels = semantisch gelijk
        variant = "  " + ZONES_A.replace("\n", "  \n\n") + "   "
        assert schema_core._zone_fingerprint(ZONES_A, "tempo") == schema_core._zone_fingerprint(variant, "tempo")

    def test_zone_type_telt_mee(self):
        assert schema_core._zone_fingerprint(ZONES_A, "tempo") != schema_core._zone_fingerprint(ZONES_A, "hartslag")

    def test_leeg_is_lege_fingerprint(self):
        assert schema_core._zone_fingerprint("", "tempo") == ""


# ════════════════════════════════════════════════════════════════════════════
# _resolve_zones / zones_fresh — bronstatus-contract (1, 3, 4, 8, 9, 10)
# ════════════════════════════════════════════════════════════════════════════
class TestZoneStatusContract:
    def test_1_config_leest_live_zones_fresh(self, monkeypatch):
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: _fresh(ZONES_A))
        zt, ztype, status, fp = schema_core._resolve_zones("A", "OUD", "tempo")
        assert status == "FRESH" and zt == ZONES_A and fp
        assert zt != "OUD"                                       # live overschrijft intake

    def test_3_4_refresh_ziet_gewijzigde_zones(self, monkeypatch):
        # intake heeft ZONES_A; FinalSurge is naar ZONES_B gewijzigd → verse read ziet B.
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: _intake(ZONES_A))
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: _fresh(ZONES_B))
        r = schema_core.zones_fresh("A")
        assert r["zones_status"] == "FRESH"
        assert r["zones"] == ZONES_B                            # nieuwe zones, niet de intake-A
        assert r["zone_fingerprint"] == schema_core._zone_fingerprint(ZONES_B, "tempo")

    def test_4_onafhankelijk_van_intake_stamp(self, monkeypatch):
        # intake_stamp verandert NIET bij een zonewijziging; de verse read ziet B toch.
        base = _intake(ZONES_A)
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: base)
        stamp_voor = schema_core._intake_stamp(base)
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: _fresh(ZONES_B))
        r = schema_core.zones_fresh("A")
        assert schema_core._intake_stamp(base) == stamp_voor    # stamp onveranderd
        assert r["zones"] == ZONES_B and r["zones_status"] == "FRESH"

    def test_8_fs_faalt_geen_silent_fresh(self, monkeypatch):
        # get_athlete_zones geeft {'error': ...} → NOOIT FRESH; val terug op intake als last-known.
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: {"error": "FinalSurge timeout"})
        zt, ztype, status, fp = schema_core._resolve_zones("A", ZONES_A, "tempo")
        assert status == "LAST_KNOWN"
        assert zt == ZONES_A                                    # laatst bekende zichtbaar
        assert status != "FRESH"

    def test_8b_exceptie_ook_geen_silent_fresh(self, monkeypatch):
        def _boom(ak): raise RuntimeError("netwerk")
        monkeypatch.setattr(fs_client, "get_athlete_zones", _boom)
        zt, ztype, status, fp = schema_core._resolve_zones("A", ZONES_A, "tempo")
        assert status == "LAST_KNOWN" and zt == ZONES_A

    def test_9_failure_zonder_last_known_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: {"error": "leeg"})
        zt, ztype, status, fp = schema_core._resolve_zones("A", "", "tempo")
        assert status == "UNAVAILABLE" and fp == ""

    def test_10_na_geslaagde_refresh_weer_fresh(self, monkeypatch):
        seq = [{"error": "timeout"}, _fresh(ZONES_B)]
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: seq.pop(0))
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: _intake(ZONES_A))
        r1 = schema_core.zones_fresh("A")
        r2 = schema_core.zones_fresh("A")
        assert r1["zones_status"] == "LAST_KNOWN"
        assert r2["zones_status"] == "FRESH" and r2["zones"] == ZONES_B


# ════════════════════════════════════════════════════════════════════════════
# config_prefill — draagt status/fingerprint mee (geen stille except:pass meer)
# ════════════════════════════════════════════════════════════════════════════
class TestConfigPrefill:
    def _legacy(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_schema_brain_v2", lambda: False)  # legacy pad, geen brain

    def test_prefill_fresh_bevat_status_en_fingerprint(self, monkeypatch):
        self._legacy(monkeypatch)
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: _intake(ZONES_A))
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: _fresh(ZONES_B))
        out = schema_core.config_prefill("A")
        assert out["zones_status"] == "FRESH"
        assert out["zone_fingerprint"] == schema_core._zone_fingerprint(ZONES_B, "tempo")
        assert out["config"]["zones"] == ZONES_B                # live zones in de config

    def test_prefill_fs_faalt_last_known_niet_fresh(self, monkeypatch):
        self._legacy(monkeypatch)
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: _intake(ZONES_A))
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: {"error": "down"})
        out = schema_core.config_prefill("A")
        assert out["zones_status"] == "LAST_KNOWN"
        assert out["config"]["zones"] == ZONES_A                # laatst bekende, niet leeg


# ════════════════════════════════════════════════════════════════════════════
# Endpoint /api/schema/zones (production-equivalent)
# ════════════════════════════════════════════════════════════════════════════
def _client():
    import api
    from starlette.testclient import TestClient
    return TestClient(api.app)


class TestZonesEndpoint:
    def test_endpoint_forceert_verse_read(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: _intake(ZONES_A))
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: _fresh(ZONES_B))
        r = _client().get("/api/schema/zones?key=A")
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] and j["zones_status"] == "FRESH" and j["zones"] == ZONES_B

    def test_endpoint_faalt_zonder_stille_fresh(self, monkeypatch):
        monkeypatch.setattr(schema_core, "_nieuwste_intake", lambda k: _intake(ZONES_A))
        monkeypatch.setattr(fs_client, "get_athlete_zones", lambda ak: {"error": "x"})
        j = _client().get("/api/schema/zones?key=A").json()
        assert j["ok"] and j["zones_status"] == "LAST_KNOWN"


# ════════════════════════════════════════════════════════════════════════════
# Client source-guards (2, 5, 11) — refresh-/draft-gedrag in app.js
# ════════════════════════════════════════════════════════════════════════════
class TestClientContract:
    APP = open(os.path.join(_ROOT, "pwa", "static", "app.js")).read()

    def _fn(self, name):
        return self.APP.split("function " + name, 1)[1].split("\nfunction ", 1)[0]

    def test_refresh_forceert_endpoint_read(self):
        body = self._fn("sbRefreshZones")
        assert "/api/schema/zones" in body                      # altijd verse bron-read
        assert "sbState.config.zones" in body                   # werkt zonebron bij

    def test_5_refresh_raakt_workbench_niet(self):
        # sbRefreshZones muteert nooit de rows/weken (coach-edits + PF-1 authority blijven).
        body = self._fn("sbRefreshZones")
        assert "sbState.weken" not in body
        assert ".rows" not in body
        # her-rendert de huidige fase (data uit bestaande state), geen rebuild van rows
        assert "sbRenderWorkbench" in body and "sbRenderConfig" in body

    def test_11_refresh_geen_route_reset(self):
        body = self._fn("sbRefreshZones")
        assert "laadSchema" not in body                         # geen terug-naar-lijst
        assert "sbBackToList" not in body
        assert 'pushRoute("schema")' not in body                # geen route-reset

    def test_2_draft_reuse_gate_ongewijzigd(self):
        # normaal reopen mag een niet-stale draft hergebruiken zonder refetch (bestaand gedrag).
        body = self._fn("schemaWerk")
        assert "sbDraftLoad" in body and "configStale" in body
        assert "sbStartConfig" in body                          # alleen zonder geldige draft

    def test_refresh_gewired_in_config_en_workbench(self):
        assert "sbWireZoneRefresh()" in self.APP
        assert self.APP.count("sbWireZoneRefresh()") >= 2       # config + workbench
        assert "sb-zone-refresh" in self.APP                    # de knop bestaat

    def test_status_render_kent_drie_toestanden(self):
        assert "FRESH" in self.APP and "LAST_KNOWN" in self.APP and "UNAVAILABLE" in self.APP

    def test_herstelde_draft_claimt_niet_vers(self):
        # Een hergebruikte draft mag zijn zones niet als 'FRESH' blijven tonen (eerlijkheid).
        body = self._fn("schemaWerk")
        assert 'sbState.zones_status === "FRESH"' in body and '"RESTORED"' in body
