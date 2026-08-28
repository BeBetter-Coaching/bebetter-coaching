# Athlete Workspace / Coach Cockpit v2 — architectuuranalyse (vóór bouw)

Branch: `feature/athlete-workspace-cockpit-v2` · basis `main = ddac155` · SW v94 · 957 groen.
Aard: **eerst analyse** (verplicht, §3). Geen code in dit document; het legt de matrix, de
before/after-dataflow, de vereenvoudigings-inventaris en de kern-architectuurbeslissing vast.

---

## A. Kern-architectuurbeslissing (de §8 / GO-NO-GO gate)

**Vraag:** vereist één server-side Coach Read Model met een generation/freshness-contract een
**nieuwe persistente server-state**, of kan het een **ephemeral read-projection** zijn?

**Bevinding: ephemeral kan.** Elke bouwsteen van een read-generation bestaat al persistent:

| Bron | Bestaande generatie-marker (persistent) | Granulariteit |
|---|---|---|
| belasting-stand (`belasting.json`) | `datum` + inhoud (`resultaten[].ernst/ratio`, `afgehandeld`) | dag + inhoud |
| Home-snapshot (`home_snapshot.json`) | `berekend` (ISO, seconde) | seconde |
| Feedback open-set | `canonical_open_actions()` → `status` + `open_ids` + `gepost` | per-read |
| coach handled/suppression | `home_handled` + `belasting.afgehandeld` inhoud | per-mutatie |

Een **`generation_id`** = een deterministische content-signatuur (hash) over deze bestaande
markers, berekend **op leesmoment**. Geen nieuwe store, geen tweede AthleteState, geen extra
GitHub-snapshot. `generated_at` = wall-clock alleen als label; de identiteit zelf is inhouds-
afgeleid (zodat "zelfde bekende state → zelfde id; nieuwere state → ander id" klopt, óók bij een
same-day force-refresh die `datum` niet verandert maar de inhoud wél).

→ **Conclusie: GO-pad.** Het Coach Read Model wordt een compositie/projectie die de canonieke
bronnen leest en stempelt, en **geen** waarheid herberekent of bezit. De §8-STOP ("persistence
noodzakelijk") is **niet** van toepassing. (Zou later blijken dat cross-proces generation-consensus
persistente coördinatie eist — dat is dezelfde multi-worker RESIDUAL als bij Coach Read Performance
v1 — dan is dát een aparte beslissing; niet in deze milestone.)

---

## B. UI-concern → bron → huidige generation/freshness → gewenste CoachRead-consument

| UI concern | Huidige bron | Huidige generation/freshness | Gewenste CoachRead-consument |
|---|---|---|---|
| Home belasting-meter (`totaal/hoog`) | `_apply_belasting_overlay` → live `belasting.json` | `belasting.datum`/`vers` (dag) | `coach_read.team()` belasting-blok + `generation_id` |
| Home belasting-signaal +X% per atleet | `home_core._belasting_signal` (km-formule) | snapshot-cohort, live-gereconcilieerd | `coach_read.load_metric()` (één formule) |
| Home werklijst-tallies (`actie/aandacht`) | `_bereken` → `_apply_handled_overlay` | snapshot `berekend` + home_handled | blijft (Home-projectie); stempelt `generation_id` |
| Home feedbacktegel | `_apply_feedback_overlay` → `canonical_open_actions` | open-set FRESH/STALE/UNKNOWN | blijft (canoniek); freshness ván generation-blok |
| Teampuls signalen | `teampuls_core.signalen` → live `belasting.json` | `datum`/`vers`/`stale` | `coach_read` belasting-blok + `generation_id` |
| Teampuls +X% / ernst | `_norm` metrics passthrough (client leidt %) | idem stand | `coach_read.load_metric()` (zelfde formule als Home) |
| Dossier belasting-observatie | `dossier_cockpit._load_observation` (`ratio`-formule) | `_stand_datum` + LOAD_SIGNAL_FRESH | `coach_read.load_metric()` (zelfde formule) |
| Dossier context/klachten/planning | `dossier_cockpit.cockpit` → brain AthleteState | AthleteState-snapshot + source-health | Workspace **deep-section** hergebruikt exact deze |
| Workspace "wat speelt er nu" | *(nieuw)* | *(nieuw)* | `coach_read.athlete()` shell (snel) |

**Divergentie die dit sluit:** vandaag leidt Home `+X%` af via `km_recent/km_basis_week` en Dossier
via `metrics.ratio` (voor-afgerond) — twee formules voor dezelfde grootheid (rondings-/formule-
divergentie). En Home toont het snapshot-cohort-moment terwijl Teampuls het live-stand-moment leest
(de Tom `+46%` vs `+64%`-aanleiding): geen **temporele** divergentie in de waarheid, maar het
ontbreken van een expliciete **generation-identiteit** waarmee de client "ouder/nieuwer" kan zien.

---

## C. Before/after dataflow

**BEFORE (ddac155):**
```
Home    GET /api/home/stats  → cockpit(refresh=False) → _current() [home_snapshot.json | _MEM]
                                → _reconcile = belasting-overlay(live belasting.json)
                                              → home_handled-overlay → feedback-overlay
                                (elk leespad; belasting %/ernst via _belasting_signal km-formule)
Teampuls GET /api/teampuls/signalen → signalen(force=False) → laad_stand() [belasting.json]
                                → _stand_payload (eigen freshness datum/vers/stale)
Dossier  GET /api/cockpit/{key} → dossier_cockpit.cockpit → brain build_state
                                → _load_observation (ratio-formule, eigen freshness)
→ Drie onafhankelijke belasting-projecties; geen gedeelde generation-identiteit.
```

**AFTER (deze milestone):**
```
coach_read.load_metric(res)      ← ÉÉN belasting-%/ernst-projectie (Home = Teampuls = Dossier)
coach_read.generation()          ← ephemeral content-signatuur over belasting+home-snap+feedback
                                    → {generation_id, generated_at, freshness{belasting,feedback,home}}

Home     /api/home/stats     → cockpit → _reconcile (belasting-overlay roept nu load_metric)
                                + response.generation = coach_read.generation()
Teampuls /api/teampuls/signalen → signalen → _stand_payload (%/ernst via load_metric)
                                + response.generation = coach_read.generation()
Dossier  /api/cockpit/{key}  → _load_observation gebruikt load_metric
Workspace /api/workspace/{key} → coach_read.athlete(key):
            shell (snel, alleen goedkope stores):
              identity · belasting(load_metric) · schema-status · feedback-status · generation
            deep-secties (lazy, client parallel): dossier cockpit (klachten/context/planning)
```
Home en Teampuls dragen nu dezelfde `generation_id` wanneer ze dezelfde stand lezen → de client
kan "zelfde state" vs "nieuwere state beschikbaar" tonen i.p.v. `46` naast `64` als co-actueel.

---

## D. Vereenvoudiging (§9 — verplicht: niet alleen toevoegen)

**Verdwijnt / wordt één bron:**
- Drie belasting-`%`-derivaties (`home_core._belasting_signal` km-formule; `dossier_cockpit._load_observation`
  `ratio`-formule; Teampuls client-afleiding) → **één** `coach_read.load_metric()`. `_belasting_signal`
  behoudt zijn signaal-shape maar delegeert de %-berekening; Dossier's `delta_pct` idem. Byte-identiek
  voor bestaande tests (km-pad en ratio-pad blijven exact).
- Drie ad-hoc freshness-afleidingen (Home `vers`, Teampuls `vers/stale`, Dossier LOAD_SIGNAL_FRESH voor
  de observatie) blijven functioneel maar krijgen **één** gedeelde generation/freshness-stempel bovenop,
  zodat cross-view "ouder/nieuwer" niet meer per view apart geraden wordt.

**Blijft bewust bestaan (canoniek, géén duplicatie):**
- `_apply_handled_overlay` (home_handled-suppressie) — Home-eigen werklijst-projectie, canonieke
  coach-authority; geen belasting-duplicatie.
- `_apply_feedback_overlay` + `canonical_open_actions` — Class 1 parity-by-construction; blijft de bron.
- Home-snapshot (stale-while-revalidate) + single-flight + `_STAND_LOCK` — load-bearing performance-
  fundament (Coach Read Performance v1); **niet** vervangen door het Coach Read Model.

**Read-contracten vóór:** Home-snapshot, belasting-stand, feedback open-set, Dossier AthleteState (4 los
geïnterpreteerd voor belasting). **Na:** dezelfde 4 canonieke bronnen, maar met **één** `load_metric`-
projectie + **één** `generation`-stempel eroverheen; Workspace voegt geen 5e truth toe (compositie).

---

## E. Wat `generation_id` prec, en niet, betekent

- **Wel:** een server-side, inhoud-afgeleide identiteit van de gelezen coach-state. Gelijk id = dezelfde
  bekende belasting/feedback/home-generatie; ander id = er is een nieuwere generatie.
- **Niet:** een frontend-timestamp, niet een garantie dat twee views hetzelfde *moment* lezen. Als de
  achtergrond-refresh de stand muteert tussen twee reads, krijgen die reads verschillende id's — precies
  het signaal waarmee de UI "nieuwe state beschikbaar" toont zonder de lijst stil te verspringen.
- Per-component `freshness` (belasting/feedback/home) markeert welk deel STALE/refreshing is, zodat een
  trage belasting-refresh de schema-/klacht-context niet als stale meesleept.

---

## F. Workspace-productcontract (§4/§10)

- **Shell < 2s / fast-state < 3s:** `coach_read.athlete(key)` shell leest **alleen goedkope stores**
  (belasting.json, home_snapshot, schema-einddatum-cache, roster-memo) — nooit een FS/AI-sweep in het
  renderpad. Deep context (klachten/planning/timeline via brain AthleteState = FS-duur) is een **lazy**
  client-call op het bestaande `/api/cockpit/{key}`. Feedback-status idem lazy.
- Compacte hiërarchie: **Aandacht nu → Recente training/context → Schema/doel → Klachten/belasting →
  Feedback/status → snelle acties.** Geen dashboardmuur.
- Snelle acties (§5) hergebruiken bestaande routes/authority: Schema (`openAthleteModule('schema')`),
  Dossier (`atleten`), Cockpit (`dossier`), Feedback (deeplink), en markeer-gezien via de bestaande
  `home_handled`/`teampuls/gezien` canonical action — **geen** duplicate write-logica.

---

## G. Testplan (§12) — mapping

1 één generation draagt één load metric · 2 Home+Teampuls zelfde generation→zelfde load value ·
3 complaint truth idem · 4 nieuwere generation→oude state herkenbaar old/stale · 5 geen silent mixed
generations · 6 Workspace fast-read blokkeert niet op refresh · 7 trage load-refresh blokkeert
schema/complaint niet · 8 trage Feedback blokkeert andere secties niet · 9 handled action blijft
canonical · 10 schema-context canonical · 11 Dossier-route blijft correct · 12 Cohesion groen ·
13 Coach Read Performance fast-path groen · 14 volledige suite groen.

→ Nieuwe tests in `tests/test_athlete_workspace_cockpit_v2.py`; bestaande suites ongewijzigd groen.
