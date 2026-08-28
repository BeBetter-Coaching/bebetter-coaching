# Athlete Workspace / Coach Cockpit v2 — build summary (voor externe review)

Branch: `feature/athlete-workspace-cockpit-v2` (basis `main = ddac155`). **Niet gemerged.**
SW **v95** · **978 tests groen** (957 → +21). Analyse-artefact: `ANALYSIS-coach-read-model.md`.

**Kernbeslissing (GO-pad):** het Coach Read Model is een **ephemeral read-projection** — geen
nieuwe persistente server-state, geen tweede AthleteState, geen extra snapshot/cache. `generation_id`
is een inhoud-afgeleide signatuur over de bestaande canonieke bronnen, berekend op leesmoment. De
§8-STOP ("persistence noodzakelijk") is dus NIET van toepassing.

---

## 1. Architectuur before/after

**Before (ddac155):** Home (snapshot + belasting-overlay), Teampuls (live `belasting.json`) en Dossier
(`_load_observation`) interpreteerden de belasting elk apart, met drie `+X%`-formules en drie ad-hoc
freshness-afleidingen. Geen gedeelde generation-identiteit → op één scherm konden generatie T0 (Home-
snapshot), T1 (belasting) en T2 (feedback) tegelijk zichtbaar zijn zonder dat de client dat wist
(de Tom `+46%` vs `+64%`-aanleiding).

**After:** één `pwa/coach_read.py` (compositie, bezit geen truth):
- `load_metric(res)` — **DE ene** belasting-%/ernst-projectie (Home = Teampuls = Dossier).
- `generation()` — **één** inhoud-afgeleide `generation_id` + `generated_at` + per-component `freshness`
  (belasting/home/feedback), over de bestaande markers (belasting-inhoud, `home_snapshot.berekend`,
  feedback open-set). Elke Home/Teampuls/Workspace-response draagt dit stempel.
- `team()` — team-belasting-cohort via `load_metric` + generation (Home/Teampuls stempelen hiermee).
- `athlete(key)` — **Workspace fast-read shell**: identity · aandacht-nu · live belasting · schema-
  signaal · feedback-status · generation, uit **alleen goedkope stores** (geen FS/AI-sweep). De rijke
  context (doel/planning/klachten/timeline) komt LAZY + parallel uit het bestaande `/api/cockpit`.

Nieuwe route `GET /api/workspace/{key}`. Nieuwe view `data-view="workspace"` + nav (sidebar + Meer) +
route-branch (`#workspace/<key>`, reload-safe). Entry points: Home-prioriteitsrij ("Workspace"),
`athleteNav`-chip, sidebar/Meer.

## 2. Removed / simplified paths (§9 — verplicht)

| Vóór | Na |
|---|---|
| 3 `+X%`-formules: `home_core._belasting_signal` (km), `dossier._load_observation` (`ratio`), Teampuls-client | **1** `coach_read.load_metric()` — Home/Teampuls/Dossier delegeren; byte-identiek (km-pad + ratio-pad behouden) |
| 3 losse freshness-gissingen per view voor "ouder/nieuwer" | **1** gedeeld `generation`/`freshness`-stempel; de client leidt "zelfde/nieuwer" er canoniek uit af |
| Geen per-atleet "wat speelt er nu"-compositie (coach klikte Home→Dossier→Schema→Teampuls los) | **1** `coach_read.athlete()` shell die de bestaande canonieke bronnen composeert |

**Bewust behouden (canoniek, géén duplicatie):** `_apply_handled_overlay` (home_handled-suppressie),
`_apply_feedback_overlay`/`canonical_open_actions` (Class 1 parity), Home-snapshot + single-flight +
`_STAND_LOCK` (Coach Read Performance-fundament). **Read-contracten vóór:** 4 bronnen los geïnterpreteerd
voor belasting. **Na:** dezelfde 4 bronnen, met één `load_metric` + één `generation` eroverheen; Workspace
voegt **geen** 5e truth toe.

## 3. Generation-contract

`generation_id` = `sha1(belasting_datum · belasting_inhoud-sig · home_berekend · feedback-sig)[:12]` —
inhoud-afgeleid, dus: **zelfde bekende state → zelfde id; nieuwere state → ander id** (óók bij een
same-day force-refresh die `datum` niet verandert). `generated_at` is louter een label. `freshness`
per component (fresh/stale/unknown) zodat een trage belasting-refresh de schema-/klacht-context niet als
stale meesleept. Client: `noteGeneration()` adopteert de laatst ontvangen generatie; `bbGenSync()` flipt
elke nog-zichtbare view die een oudere generatie toont naar **"Bijgewerkt HH:MM · nieuwe state
beschikbaar"** — zonder de lijst te laten verspringen (journey C).

**Live bewezen:** Home en Workspace toonden dezelfde `generation_id` (`85c5c17c7294`) op dezelfde stand.

## 4. Timing (§10)

- Workspace-shell (`/api/workspace/{key}`): alleen goedkope stores (belasting-stand, Home-snapshot,
  feedback open-set, roster-memo) → **geen** FS/AI-sweep in het renderpad (test 6/13 bewijzen dit met
  een sweep-die-gooit). Rijke context lazy/parallel via `/api/cockpit`.
- Home fast-read en Teampuls fast-read ongewijzigd snel (generation is een goedkope store-read).
- Coach Read Performance v1 (snapshot/single-flight/`_STAND_LOCK`) ongemoeid.

## 5. Tests (`tests/test_athlete_workspace_cockpit_v2.py`, 21) → §12-mapping

1 load_metric = één formule · 1b team-items via load_metric · 2 Home=Teampuls pct + zelfde generation ·
3 Dossier-delta via load_metric · 4 inhoud-wijziging → andere generation · 4b zelfde inhoud → zelfde
generation · 5 elke response draagt generation · 5b freshness per component · 6 shell triggert nooit een
sweep · 7 trage load blokkeert schema-context niet · 8 trage feedback blokkeert andere secties niet ·
9 handled = bestaande teampuls-authority · 10 schema-context = canonieke Home-projectie · 11 Dossier-
route/load_observation intact · 12 Cohesion `_ATHLETE_VIEWS`-literal byte-identiek · 13 Home fast-read
nog steeds geen sweep + pending draagt generation · + client-wiring source-guards. **Volledige suite 978
groen.**

## 6. Product journeys

- **A Home → Workspace:** prioriteitsrij-actie "Workspace" (+ athleteNav-chip) → `openWorkspace(key)`;
  dezelfde aanleiding direct zichtbaar (Aandacht nu). ✓ (live gerenderd)
- **B load generation:** Home/Teampuls/Workspace op dezelfde stand → dezelfde `+X%` (load_metric) én
  dezelfde `generation_id`. ✓
- **C background refresh:** refresh maakt generatie B; de actieve Home-lijst verspringt niet, maar de
  banner flipt naar "nieuwe state beschikbaar" (`noteGeneration` zonder herstempel). ✓
- **D complaint:** Home/Workspace/Dossier delen dezelfde load/complaint-truth (load_metric + zelfde
  `/api/cockpit`-bron). ✓
- **E schema:** Workspace toont schema-signaal (canonieke Home-rij) + doel/huidig blok (lazy cockpit). ✓
- **F speed:** Workspace bruikbaar vóór de zware refresh klaar is (shell = goedkope stores). ✓
