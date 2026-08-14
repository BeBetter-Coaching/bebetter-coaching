# Dossier — Architecture & Product Design Report

**Status:** AUDIT + DESIGN (geen implementatie). Geen functionele code gewijzigd.
**Datum:** 13 aug 2026
**Scope:** Dossier als derde Masterbrein V2-consumer — human cockpit / geheugenlaag / bron voor rapportages + Teampuls.
**Uitgangspunt:** Masterbrein V2 is production active + locked in (1) Schema Nieuw/Verlengen, (2) Feedback. Dossier mag **geen derde losse intelligence-engine** worden; het is een view/editor over dezelfde centrale evidence.

Zie ook: [platform-roadmap.md](platform-roadmap.md), [streamlit-functional-baseline.md](streamlit-functional-baseline.md).

### Startbeslissingen (genomen 14 aug 2026) — nog niets gebouwd
1. **Capture = vanaf-nu** (geen historische backfill/FS-thread-reconstructie; hooguit klachten/races binnen 120d als aparte stap). Zie §O1.
2. **Feedback-history-hook = additief én niet-fataal**, ná de LOCKED Feedback-flow (raakt de gelockte logica functioneel niet). Zie §O2.
3. **History-store eerst, dan cockpit** (Fase A history-foundation vóór de dossier-view). Zie §P.

---

## A. Current-state audit

### A1. Masterbrein V2 (`pwa/brain/`) — de intelligentie die er al is
Laagmodel bevestigd in code: `sources` (L1, I/O) → `state._base_evidence`+`zones`+`complaints`+`derive`+`patterns`+`contradictions` (L2–L4, puur) → `state.assemble` (L5 AthleteState) → `projections.for_*` (L6) → AI (extern).

- **Evidence** (`models.py:68`) is al een rijk, longitudinaal-geschikt model: `key, domain, value, truth_type, status, strength, source, source_kind, observed_at, effective_from, effective_until, athlete_key, workout_key, reporter, unit, provenance[], detail{}, id`. `stable_id` = deterministisch uit semantische identiteit (geen random UUID) → diffbaar over runs.
- **Truth types** compleet: FACT / DERIVED / ATHLETE_REPORTED / COACH_REPORTED / AI_INTERPRETATION / UNKNOWN.
- **Status** (tijdgebonden) al aanwezig: ACTIVE / RECENT / RECURRING / STRUCTURAL / RESOLVED / STALE / HISTORICAL / CONFLICT / UNKNOWN — dit is precies de set uit de opdracht (§2).
- **SourceHealth** (`models.py:121`) maakt LEEG ≠ GEFAALD hard (`available/stale/last_success/coverage/error`). `state._carry_last_known_good` behoudt bij bronuitval de vorige evidence als STALE (nooit nieuwe HIGH o.b.v. niets).
- **Complaints** (`complaints.py`) leveren al de volledige lifecycle per lichaamsgebied: elke melding = eigen Evidence (provenance), plus één afgeleide groep-Evidence met status ACTIVE/RECENT/RECURRING/RESOLVED/HISTORICAL. Herstel wist niets: history blijft, current=RESOLVED. Recurring = ≥2 datums binnen 90d (`recency.COMPLAINT_RECURRING_*`). Herbruikt `belasting._vind_klachten` (bewezen negatie/opgelost-herkenning).
- **Patterns** (`patterns.py`): `load.well_tolerated`, `load.possible_relation` (associatie, nooit causaal), `capacity.handle_carefully` (na interruption), `zones.structural_over` → ZONE_REVIEW_CANDIDATE. Strength ≥ MEDIUM alleen bij voldoende sample.
- **Contradictions** (`contradictions.py`): auto-resolve (live FS-zones > intake; recent actual load > oud volume) én CONFLICT (on_hold + recent getraind → coach-check, niet stil opgelost). Conflicten worden zelf Evidence.
- **Explainability**: `state.explain(evidence_id)` levert al de volledige provenance-keten + bronnen + truth/strength. Dit is de motor onder een "waarom weet BeBetter dit"-reveal.

### A2. Legacy Streamlit dossier (`dossier.py`, 752 r.) — functionele referentie
- **Live truth, geen legacy:** `_is_run`/`_run_km` (`dossier.py:150/161`) worden geïmporteerd door `pwa/brain/activity.py` → dit bestand is bron-van-waarheid voor run-classificatie, **REUSE AS TRUTH**.
- **Al gereproduceerd in de brain:** `_workout_score`/compliance (→ `derive._compliance`), feeling/RPE-trend (→ `derive._score_trend`), klachtdetectie (→ `complaints`), belastingsignaal (→ `state._base_evidence`).
- **Uniek in Streamlit, ONTBREEKT in de brain:**
  - **Conditie-index** (tempo per hartslag, `(1000/pace)/hr*100`, filter 40–300, ≥3 punten) — de enige fitheids-progressieproxy. `dossier.py:210`.
  - **Race-VDOT** (`schema_builder.calculate_vdot`, races ≥1.5 km) — `dossier.py:241`.
  - **`evaluatie_context`** (`dossier.py:352`): "TOEN (1e helft 90d) → NU (2e helft)"-vergelijking (volume, conditie-index, compliance, gevoel, RPE, races, atleetwoorden, coach-notes) → voedt `ai_feedback.generate_athlete_evaluation` + `generate_athlete_message`. **Dit is al een proto-rapportage.**
- **DO NOT COPY:** pandas-DataFrames/charts (presentatie), compliance-bins n_vol/n_deels/n_gemist (UI-labels, herafleidbaar).

### A3. Huidige PWA Dossier (`pwa/dossier_core.py` + `atleten_core.py` + routes + `app.js`)
- **Puur store-display. Géén brain, géén AI, géén inference, géén timeline, géén provenance, géén deep-linking.**
- Backend: `list_athletes`/`get_dossier`/`add_note`/`delete_note`/`save_profiel`. Routes `/api/dossier/*` + hybride `/api/atleten/{id}` (FinalSurge week/recent + store-dossier).
- Toont: intake (19 velden `_INTAKE_VELDEN`), coach-notities (add/delete, Jip/Remco), documentenlog, coach-geheugen (textarea). Training-blok komt los uit FinalSurge (niet uit de brain).
- Master-detail responsive (desktop sticky lijst 342px + detail; mobiel toggle). Loading/empty/error-states aanwezig maar simpel.
- **Conclusie:** de huidige Dossierpagina is een intake/notitie-viewer, geen cockpit. Het weet niets van klachten-lifecycle, patronen, source-health of contradictions die de brain al berekent.

### A4. Stores & centrale vastlegging (`intake_store.py` + module-cores)
Persistence = GitHub-backed JSON + lokale fallback (`_load_json`/`_save_json`, SHA optimistic lock). Geen database.

| Store | Keying | Timestamp | Append/Overwrite | History | Provenance |
|---|---|---|---|---|---|
| `notes.json` | user_key → [{datum,coach,tekst}] | datum (dag) | **append** | **ja** | coach |
| `documenten.json` | user_key → [{datum,type,onderwerp}] | datum | append | ja | — |
| `profielen.json` (coach memory) | user_key → {profiel, bijgewerkt, n} | dag | **overwrite** | nee | — |
| `intakes.json` / `latest_intakes.json` | athlete_key → intake | dag / ISO | overwrite (1 prev) | nee | — |
| `on_hold.json` | user_key → {reden, since} | since (start) | overwrite | nee | reden |
| `home_handled.json` | `user_key|soort` → {status,handled_at,tot,by} | dag | overwrite | nee | by |
| `skipped.json` | workout_key → ISO | ISO | overwrite | — | — |
| `brain_snapshot.json` | user_key → **huidige** AthleteState | built_at | **overwrite** | **nee** | via evidence |
| zones / races | — | — | **niet lokaal** (FinalSurge live) | nee | — |

**Kernconclusie:** de enige echte history-stores zijn `notes` en `documenten`. Alle overige athlete-kennis is **current-value overwrite** of **live recompute**. Er is **geen centraal event-log**.

---

## B. Gap analysis — wat ontbreekt voor een world-class Dossier

1. **Geen persistente longitudinale historie.** `brain_snapshot.json` bewaart één huidige state per atleet en **overschrijft** die elke build (`snapshot.save_snapshot`). `prev` dient alleen voor last-known-good. Elke "gebeurtenis" wordt live herberekend uit een **120-daags** FinalSurge-venster (`sources.gather`: `get_training_log(months=4)`). → Een dossier dat "jaren onthoudt" kan **niet** uit re-fetch komen; het heeft een eigen durable historie nodig.
2. **`for_dossier` is een ruwe dump** (`projections.py:105`): alle evidence plat, geen State/Event/Pattern-scheiding, geen importance, geen chronologie. Niet productwaardig.
3. **Geen event-model.** Evidence beschrijft "wat geldt nu" (current state, recomputed). Er is geen immutable "wat gebeurde op moment T" (klacht gemeld, coach markeert hersteld, doel gewijzigd, zone gewijzigd, blok gestart, race gelopen, interruption/return).
4. **Geen importance/actionability-laag.** Alles is gelijkwaardig; niets bepaalt wat prominent hoort en wat history-only is.
5. **Coach-authority ontbreekt als schrijfpad in de brain.** De brain **leest** coach memory/notes; er is geen "markeer hersteld / corrigeer classificatie / voeg gedateerde context toe / wijs patroon af" die nieuwe COACH_REPORTED-evidence + event maakt.
6. **Coach memory is één ongedateerde string** — ongeschikt als top-level longitudinaal geheugen.
7. **Losse capture-gaten:** klacht-lifecycle-overgangen, zonewijzigingen, races, feedback-posts/athlete-reactions en intake-versies worden **nergens centraal met tijdstip** vastgelegd.
8. **Teampuls = parallelle intelligentie** (`teampuls_core.py` draait `belasting`+`briefing`, niet de brain) — precies de North-Star-fout die vermeden moet worden.
9. **PWA Dossier toont niets van de brain** (klachten, patronen, source-health, contradictions) — de intelligentie bestaat maar is onzichtbaar op de plek waar de coach kijkt.

---

## C. Source map — kennisbronnen en ownership

| Domein | Bron van waarheid | Truth type | Central history? | Downstream (rapport/Teampuls) |
|---|---|---|---|---|
| Identity/profiel | intake + FinalSurge roster | FACT/ATHLETE_REPORTED | intake: overwrite | naam/groep |
| Doelen / race | intake (`goal.doel`, `goal.race`) | ATHLETE_REPORTED | **nee** (1 prev via latest_intakes) | ja |
| Volume/frequentie/trend/interruption | FinalSurge log → `derive` (run-only) | DERIVED | nee (recompute 120d) | ja |
| Compliance | FinalSurge log → `derive._compliance` (8w) | DERIVED | nee | ja |
| Conditie-index / VDOT | FinalSurge log → legacy `dossier.py` | DERIVED | nee | rapport |
| Zones (actueel) | FinalSurge live | FACT | **nee** | ja |
| Zone-review candidate | `patterns.zones.structural_over` | AI_INTERPRETATION | nee | Teampuls |
| Subjectief (gevoel/RPE-trend) | FinalSurge felt/effort → `derive` | DERIVED | nee | ja |
| Klachten (lifecycle) | coach_notes + intake + post_notes → `complaints` | ATHLETE/COACH_REPORTED | **nee** (recompute) | ja |
| Coach memory | `profielen.json` | COACH_REPORTED | nee (overwrite, ongedateerd) | ja |
| Coach-notities | `notes.json` | COACH_REPORTED | **ja** (append, dated, coach) | ja |
| Coach-besluiten | — (nu impliciet in notes) | COACH_REPORTED | **nee** (geen apart type) | ja |
| Schema-config/blokken | `latest_intakes` + FinalSurge schema | FACT | 1 prev | rapport |
| Feedback-threads/reactions | FinalSurge (posted, niet lokaal gelogd) | ATHLETE/COACH_REPORTED | **nee** | ja |
| Races/PR's | FinalSurge live | FACT | nee | rapport |
| On-hold / hervatting | `on_hold.json` (since) | COACH_REPORTED | nee (resume niet gedateerd) | Teampuls |
| Belasting-signaal | `belasting.json` | DERIVED | overwrite (dag) | Teampuls |
| Source health | `SourceHealth` in snapshot | — | nee (huidig) | cockpit |
| Contradictions | `contradictions.detect` | DERIVED | nee (recompute) | cockpit |

---

## D. Canonical data model — State vs Event vs Pattern vs Evidence

**Kernbeslissing: voeg één nieuwe laag toe — een deterministische, append-only `HistoryEvent`-projectie bóven Evidence — en houd Evidence als current-state. Geen dubbele waarheid.**

### D1. De vier begrippen, scherp gescheiden
- **Evidence (bestaand, current-state):** "wat geldt nu / wat is waargenomen", recomputed elke build. Blijft ongewijzigd.
- **HistoryEvent (nieuw, immutable):** "wat gebeurde op moment T". Wordt **deterministisch afgeleid** uit (a) statusovergangen van Evidence tussen twee snapshots, (b) expliciete coach-acties, (c) module-hooks (Schema-publish, Feedback-klacht, race). Eén keer geschreven = nooit gewijzigd (alleen `superseded_by`/`resolved_by`-verwijzing).
- **Pattern (bestaand, `patterns.py`):** "wat blijkt over tijd" — well_tolerated, recurring complaint, structural_over. Krijgt in de projectie zijn eigen sectie, niet vermengd met events.
- **AthleteState (bestaand):** L5-uitkomst = overall + evidence + sources + conflicts + gaps.

### D2. `HistoryEvent` (conceptueel — nog geen code)
```
id                stable_id(athlete, event_type, effective_at, key)  # deterministisch, dedupe-safe
athlete_key
event_type        COMPLAINT_REPORTED | COMPLAINT_RESOLVED | COMPLAINT_RECURRED |
                  GOAL_SET | GOAL_CHANGED | RACE_PLANNED | RACE_COMPLETED |
                  ZONES_CHANGED | ZONE_REVIEW_FLAGGED |
                  INTERRUPTION_STARTED | TRAINING_RESUMED |
                  ON_HOLD | RESUMED |
                  SCHEMA_BLOCK_STARTED | SCHEMA_RECALIBRATED |
                  COACH_DECISION | COACH_CONTEXT_ADDED | COACH_CORRECTION |
                  PATTERN_CONFIRMED | INTERPRETATION_REJECTED | CONTRADICTION_RAISED | CONTRADICTION_RESOLVED
domain            health | load | goal | zones | training_response | coach | schema | source
effective_at      moment waarop het gold (ISO)
recorded_at       moment van vastleggen (ISO)  # scheidt "gebeurde toen" van "gezien nu"
title             korte samenvatting (deterministisch, geen AI voor de feiten)
truth_type        FACT | DERIVED | ATHLETE_REPORTED | COACH_REPORTED | AI_INTERPRETATION
status            ACTIVE | RESOLVED | HISTORICAL | SUPERSEDED
strength          HIGH | MEDIUM | LOW
reporter          athlete | coach | system
importance        HIGH | MEDIUM | LOW  # deterministisch, zie F
evidence_refs[]   ids van onderliggende Evidence (provenance-brug)
related_ref       workout_key | race | schema_block (optioneel)
transition        {from: <status/value>, to: <status/value>}  # optioneel
resolved_by       event_id (optioneel)
superseded_by     event_id (optioneel)
detail{}
```

### D3. Aanvullende concepten die Evidence nog mist (advies)
1. **`event_type` + `title` + `transition`** — niet in Evidence; horen op HistoryEvent (Evidence beschrijft toestand, niet overgang).
2. **`importance/actionability`** — nieuwe deterministische laag (F), niet in Evidence stoppen.
3. **`resolved_by`/`superseded_by`** — expliciete correctie-/opvolgingsketen (coach-authority).
4. **`recorded_at` ≠ `effective_at`** — Evidence heeft `observed_at`/`effective_from`; voeg voor events een aparte "vastgelegd op" toe zodat late correcties niet de tijdlijn vervuilen.
5. **`coach.decision` als apart truth/genre** — nu verdwijnt een besluit in een vrije notitie; maak het een eigen event-type met `effective_at`.

> Advies: **breid Evidence NIET uit** (locked, door 2 consumers gebruikt). Leg de nieuwe concepten in de HistoryEvent-laag die ernaast staat en via `evidence_refs` terugverwijst.

---

## E. Longitudinal history design — opbouw, opslag, projectie

### E1. Hoe historie ontstaat (drie deterministische bronnen)
1. **Snapshot-diff (motor):** bij elke brain-build de nieuwe `AthleteState` vergelijken met de vorige (die er al is via `prev`). Statusovergangen in Evidence → events. Voorbeeld: `complaint.kuit` ACTIVE→RESOLVED ⇒ `COMPLAINT_RESOLVED`; afwezig→ACTIVE ⇒ `COMPLAINT_REPORTED`; RESOLVED→ACTIVE ⇒ `COMPLAINT_RECURRED`. Dit hergebruikt de **bestaande** lifecycle-logica; geen nieuwe intelligentie.
2. **Expliciete coach-acties (H):** markeer hersteld / corrigeer / voeg context toe / wijs patroon af → direct een event + nieuwe COACH_REPORTED-evidence.
3. **Module-hooks (best-effort, niet-fataal):** Schema-publish → `SCHEMA_BLOCK_STARTED`/`SCHEMA_RECALIBRATED`; Feedback-klacht → `COMPLAINT_REPORTED`; race voltooid → `RACE_COMPLETED`. Hooks zijn additioneel: als een hook faalt, vangt de snapshot-diff het later alsnog.

### E2. Opslag — twee-store-model (hot + deep)
- **Hot (bestaand):** `brain_snapshot.json` = huidige AthleteState per atleet. Snel, klein, overschrijfbaar. Ongewijzigd.
- **Deep (nieuw):** `athlete_history.json` (of per-atleet shard) = **append-only** lijst HistoryEvents per `athlete_key`. Zelfde `intake_store`-patroon (GitHub-backed + lokale fallback), **geen database**. Deterministische `id` ⇒ herbouwen/dupliceren schrijft geen dubbele events (idempotent).
- **Retentie:** alles bewaren; niet alles laden. Cockpit leest huidige state uit hot-snapshot; historie is **lazy** (periode-/domeinfilter, pagination). Geen full-FinalSurge-fetch bij openen, geen comments-fan-out.

### E3. Projectie
`for_dossier(state, history)` levert de secties uit I. De feiten/selectie zijn deterministisch; AI mag pas daarna prozatekst maken (nooit voor canonieke waarheid).

### E4. Backfill-realiteit (STOP-punt, zie O)
De diff-motor produceert historie **vanaf activering vooruit**. Terugwerkende historie is beperkt: post_notes-klachten en races zitten in het 120d-FinalSurge-venster (deels backfillbaar), maar zonewijzigingen, feedback-threads en oude coach-besluiten zijn **niet** betrouwbaar te reconstrueren. Advies: **geen big-bang backfill**; start capture nu, backfill hooguit klachten/races binnen het bestaande venster als aparte, expliciete stap.

---

## F. Importance / information-compression model (deterministisch)

Geen AI beslist wat "waar" of "belangrijk" is. Regelgebaseerd, afgeleid van bestaande status/strength:

**HIGH (prominent — Current state + Active attention):**
- complaint-groep status ACTIVE of RECURRING;
- CONFLICT (contradiction);
- `load.signal = hoog`; `load.possible_relation`;
- `zones.structural_over = ZONE_REVIEW_CANDIDATE`;
- nieuw of gewijzigd doel; target race binnen `RACE_UPCOMING` (90d);
- `load.interruption` / training resumed;
- coach-besluit; grote volumeshift (trend opbouwend/afbouwend met MEDIUM+).

**MEDIUM (Recent meaningful events + Patterns):**
- complaint RECENT of RESOLVED (overgang);
- well_tolerated (MEDIUM+); compliance-shift; RPE/gevoel-trend;
- zonewijziging; blok gestart/gerekalibreerd; race gelopen.

**LOW (history-only, samengevouwen):**
- individuele workout / normale feedbackreply;
- `distance_deviation` NOTABLE/CLEAR van één training;
- complaint HISTORICAL; ongedateerde coach memory; dagelijkse stat-updates.

**Onderscheid dat de laag maakt:** raw evidence (alles) → meaningful history event (importance ≥ MEDIUM) → current signal (status ACTIVE/RECURRING/CONFLICT) → long-term pattern (`patterns.py`). Prominentie volgt uit importance; retentie is onafhankelijk (§2: history ≠ prominence).

---

## G. `for_dossier` projectie — velden/secties die het moet leveren

`for_dossier(state, history)` → dict met:
```
task, athlete_key, naam, overall, built_at

current_state:        # I.A — één oogopslag
  goal, race, km_per_week, runs_per_week, trend, compliance,
  active_complaints[], capacity (interruption/handle_carefully),
  zones_summary, source_confidence (uit SourceHealth), overall
  key_changes[]       # top 3 belangrijkste recente veranderingen

attention[]:          # I.C — importance HIGH, openstaand
  {type, title, since, evidence_refs, coach_action?}

changes[]:            # I.B — meaningful events, importance>=MEDIUM, periode-gefilterd (30/60/90d)
  [HistoryEvent...]   # GEEN workout-feed

patterns[]:           # I.D — uit patterns.py, met bewijs/periode/strength + reject-actie

goals_history[]:      # I.E — huidige + eerdere doelen/blokken

training_evolution:   # I.F — km/compliance/conditie-index/subjectief trends (betekenisvol, geen 20 tabellen)

complaints_lifecycle[]: # I.G — per gebied volledige cyclus (reported→recurred→resolved)

coach_memory:         # I.H — profiel + gedateerde coach-notes/besluiten

timeline[]:           # I.I — alle events chronologisch, filterbaar, resolved/historical standaard ingeklapt

sources[]:            # source-health, mens-leesbaar (§21)
conflicts[]:          # contradictions (§22)
source_gaps[]
```
`for_dossier` blijft **puur** (state+history in, dict uit); geen I/O, geen AI.

---

## H. Coach-editing semantiek (correctie = nieuwe evidence, nooit delete)

| Actie | Effect (deterministisch) |
|---|---|
| **Markeer hersteld** | nieuwe COACH_REPORTED-evidence `complaint.<area>` resolved + event `COMPLAINT_RESOLVED(effective_at=nu)`; athlete-melding blijft provenance; current herberekend → RESOLVED. |
| **Corrigeer classificatie** (generiek "pijn" → "linker kuit") | nieuwe COACH_REPORTED-evidence met correcte area + `COACH_CORRECTION`; oorspronkelijke tekst blijft als provenance (niet verwijderd). |
| **Voeg context toe** ("minder getraind door vakantie") | **gedateerde** COACH_REPORTED-evidence + `COACH_CONTEXT_ADDED(effective_at)`; wordt géén eeuwige ongedateerde memory-string. |
| **Bevestig patroon** ("terugkerende kuit klopt") | `PATTERN_CONFIRMED`; verhoogt strength van het pattern naar HIGH; coach = reporter. |
| **Wijs interpretatie af** (AI/pattern klopt niet) | `INTERPRETATION_REJECTED`; het pattern krijgt status SUPERSEDED (blijft in history), verdwijnt uit current/attention; nieuwe COACH_REPORTED-evidence legt de correcte lezing vast. |
| **Pin / markeer belangrijk** | vlag op event/evidence (importance→HIGH) zonder waarheid te wijzigen. |

**Invariant:** coach-authority wint voor *current* ("wat geldt nu"), maar **verwijdert nooit** athlete- of systeem-evidence. Alles blijft in de timeline. Dit hergebruikt de bestaande complaints-lifecycle (die "herstel wist niets" al implementeert).

---

## I. Informatiearchitectuur (desktop + mobiel)

Topniveau cockpit, in prioriteitsvolgorde:
- **A. Current state** (bovenaan, altijd): doel · belasting/consistency · actieve aandacht · klachten · capacity · zones · source-confidence · belangrijkste veranderingen. Coach begrijpt de atleet binnen seconden.
- **B. Recent meaningful changes** (30/60/90d): alleen events importance ≥ MEDIUM — géén workout-feed.
- **C. Active attention:** open klacht · contradiction · source-gap · coach-follow-up · zone-review · interruption/return. Met coach-actieknoppen (H).
- **D. Patterns:** met bewijs, periode, strength, "waarom", en reject-actie.
- **E. Goals & planning history:** huidig + eerdere doelen/blokken.
- **F. Training evolution:** betekenisvolle trends (volume/compliance/conditie-index/subjectief), niet 20 losse tabellen.
- **G. Complaints & recovery history:** volledige lifecycle per gebied.
- **H. Coach memory / decisions:** expliciete, gedateerde coachkennis.
- **I. Full timeline:** filters all/training/complaints/goals/coach/feedback/races/zones/system-patterns; resolved/historical standaard ingeklapt.

**Desktop:** master-detail zoals bestaand (`.md-split`, sticky lijst 342px) + cockpit-detail met sticky sub-navigatie naar A–I. **Mobiel:** verticale stack, A altijd bovenaan, B–I als ingeklapte secties met scherpe defaults; historie op aanvraag (lazy).

---

## J. Visual / interaction spec (verplichte kwaliteitsronde vóór build)

Concreet, aansluitend op het bewezen dark-thema en de Home/Feedback-patronen (zie [bebetter-design-system], [feedback-frozen-quality-reference]):
- **Density:** cockpit = rustig; per sectie max de HIGH/MEDIUM-items, rest achter "toon meer".
- **Chips/badges:** status (ACTIVE/RECURRING/RESOLVED/STALE/CONFLICT) en truth-type (athlete/coach/afgeleid/AI) als kleurige chips; strength als subtiele indicator. Herbruik bestaande chip-stijl.
- **Timeline:** verticale rail met datum-groepering; resolved/historical dimt + ingeklapt; event-titel deterministisch, detail op tik.
- **Evidence/provenance reveal (progressive disclosure):** klik op een claim → `state.explain`-keten (bron, datum, provenance, strength). Coach hoeft techniek niet standaard te zien.
- **Inline expansion + collapsible history:** geen paginanavigatie voor detail.
- **Sticky sub-nav (desktop) / sectiesprong (mobiel).** Scroll-state retentie bij terugkeer (Home-patroon).
- **Deep-linking:** naar bron-workout/race/feedback-item (nu ontbreekt deep-linking volledig — nieuw).
- **Inline coach-acties** (H) met optimistic UI + Undo voor reversibele acties; irreversibele (verzenden) apart, zoals Feedback.
- **States:** loading (skeleton), stale/source-gap (mens-leesbaar, §21), empty ("Doel onbekend / coach-check", §23), error.
- **Touch targets ≥44px, safe-area, keyboard-gedrag** volgens de bewezen Feedback-composer (geen nieuwe keyboard-geometrie uitvinden).
- **Transitions:** rustig; geen springende layout.

De visual spec wordt een **apart LOCKED document** vóór implementatie (zoals Feedback mobile composer), inclusief desktop- én iPhone-acceptance.

---

## K. Reporting-architectuur (basis nu ontwerpen, niet bouwen)

`AthleteState + longitudinal history + selected patterns → report_projection` (deterministisch) → AI genereert alleen proza.
- **`report_projection(state, history, periode=8–12w)`** levert: trainingsvolume/frequentie, compliance, progressie (incl. conditie-index/VDOT), races, subjectieve respons, klachten + interruption, doelen, coach-besluiten, belangrijke veranderingen, patterns, actuele next focus.
- Feiten/selectie deterministisch onderbouwd (provenance), AI = laatste laag — precies zoals `evaluatie_context` nu al "toen→nu" doet, maar dan gevoed uit de centrale truth i.p.v. ad-hoc herberekening.
- Rapportages combineren **nooit** zelf losse bronnen; ze consumeren de projectie. Zo blijft er één waarheid.

## L. Teampuls-downstream (privacy-safe projectie)

`for_teampuls` is nu een triviale stub (domain-counts). Ontwerp: **team-projectie = aggregaat van individuele brain-state, task-specific, zonder gevoelige detail-tekst**:
- per atleet alleen tellers/vlaggen: active-attention count · recurring-complaint (ja/nee) · source-gap · interruption/return · zone-review · unanswered coach-follow-up · meaningful-change count.
- **geen** volledige klachthistorie, **geen** vrije tekst, **geen** irrelevante detaildata.
Teampuls analyseert dan **niet opnieuw** alle atleten (weg van het huidige parallelle `belasting`+`briefing`-model) maar leest deze projectie. Migratie van Teampuls is een **latere** fase, geen onderdeel van Dossier-build.

---

## M. Performance / storage-architectuur

- **Hot read** = huidige state uit `brain_snapshot.json` (bestaand, snel).
- **Deep history** = append-only `athlete_history.json` (nieuw), **lazy** geladen met periode-/domeinfilter + pagination.
- **Geen** full-FinalSurge-history-fetch bij openen; **geen** comments-fan-out; centrale zones-cache blijft.
- **Incremental:** de diff-motor voegt per build alleen nieuwe events toe (idempotent via stable_id, dedupe, geen dataverlies).
- **Schaal:** "alles bewaren" ≠ "alles in één JSON laden". Bij groei: per-atleet shard-bestanden (`athlete_history/<key>.json`) i.p.v. één groot object; retentiebeleid alleen voor ruwe low-importance events (samenvouwen), nooit voor coach-evidence of klacht-lifecycle.
- **Indexes:** lichte per-atleet index (laatste event-datum, open-attention-count) voor snelle roster/Teampuls-tellers zonder de volle history te lezen.

---

## N. Migratieplan (gefaseerd, met rollback + acceptance — geen big-bang)

Elke fase: gated (env-flag zoals `BEBETTER_DOSSIER_*`), shadow → acceptance → activatie, met desktop- én iPhone-acceptance en rollback.

- **Fase A — History-foundation (backend, shadow):** HistoryEvent-model + append-only store + snapshot-diff-motor + idempotentie/dedupe-tests. Schrijft in shadow mee bij elke build; **niets** in de UI. Rollback = flag uit, store blijft ongebruikt. Acceptance: events kloppen op N echte atleten, 0 duplicaten, geen invloed op Schema/Feedback.
- **Fase B — Read-only cockpit:** enrich `for_dossier` (State/Event/Pattern/Attention/Patterns/source-health/contradictions) + nieuwe PWA-cockpit (I) + visual spec (J, LOCKED). **Alleen lezen**, geen coach-writes. Bouwt op de dan al gevulde history uit Fase A. Acceptance: coach herkent status/patronen; desktop+iPhone PASS.
- **Fase C — Coach-corrections/actions (H):** markeer hersteld / corrigeer / context / reject, als nieuwe evidence + events. Optimistic UI + Undo. Acceptance: correcties wijzigen current, verwijderen niets, verschijnen in timeline.
- **Fase D — Report-projection (K):** deterministische projectie + AI-proza; herbruik `evaluatie_context`-idee uit centrale truth.
- **Fase E — Teampuls-projectie (L):** privacy-safe aggregaat; Teampuls consumeert i.p.v. herberekent.

## O. Risico's / open beslissingen (STOP-punten voor Jip)

**Betrouwbaar vast te stellen uit de code (geen aanname):** het bovenstaande model, de lifecycle, source-health, de twee-store-aanpak.

**NIET betrouwbaar uit huidige code/data — expliciete beslissing nodig vóór de history-fase:**
1. **Backfill vs vanaf-nu — BESLIST (13 aug 2026): vanaf-nu capturen.** Capture vanaf activering vooruit; hooguit klachten/races binnen het 120d-venster als aparte stap. Geen fragiele FS-thread-reconstructie voor zones/besluiten.
2. **Feedback-capture-hook — BESLIST (13 aug 2026): ja, additieve event-write ná de flow.** Best-effort, niet-fatale event-write ná de bestaande (LOCKED) Feedback-flow — raakt de gelockte logica functioneel niet. Klachten/coach-responses uit Feedback landen zo in de centrale history.
3. **Coach memory-migratie.** De ongedateerde `profiel`-string ondersteunt geen tijdlijn. *Beslissing: nieuw model (persistent profile-knowledge / dated note / decision / resolved context / temporary) invoeren en de bestaande string als één ongedateerd "profiel v0"-item behouden — geen automatische migratie in deze fase.*
4. **Store-granulariteit.** Eén `athlete_history.json` vs per-atleet shards. *Aanbeveling: shards bij >~30 atleten of >~500 events/atleet; start met één bestand, split-drempel vooraf vastleggen.*
5. **On-hold/resume-events.** Resume is nu niet gedateerd. *Beslissing: on-hold/resume als expliciete events vastleggen going-forward (kleine toevoeging in de on_hold-schrijfpaden) — of afleiden uit trainingsgaten (bestaande interruption-derivatie, minder precies).*

**Bekende Masterbrein-Fase-A-risico's (§24) — advies per punt:**
| Risico | Advies |
|---|---|
| Generieke klacht-groepen ("pijn/last van/gevoelig/stijf") | **zichtbaar maken + coach-correctie** (H) i.p.v. auto-oplossen (Fase C) |
| Recurring te lang actief | **zichtbaar + coach kan resolven**; drempel later herijken |
| Klacht-keyword-coverage beperkt | zichtbaar maken; buiten Dossier-scope om de detector te wijzigen |
| Structural-zone heuristiek conservatief | zichtbaar als pattern met reject-actie |
| Recency-windows provisional | zichtbaar in provenance ("provisional"); niet nu wijzigen |
| Snapshot-schaalbaarheid | **oplossen tijdens Dossier-build** (M: two-store + shards) |
| Coach memory ongedateerd | **oplossen tijdens build** (O3) |
| Beperkte multi-block history | going-forward capturen (Fase A); geen Schema-writecode aanraken |

## P. Voorgestelde implementatiefasen — BESLIST (13 aug 2026): history-store eerst

Volgorde per Jip's keuze (spec-volgorde §26 P):
1. **Fase A — History-foundation EERST (shadow):** HistoryEvent-model + append-only `athlete_history.json` + snapshot-diff-motor + idempotentie/dedupe-tests + de additieve Feedback-capture-hook (O2). Schrijft in shadow mee bij elke build; niets in de UI. Capture vanaf-nu (O1). Rollback = flag uit.
2. **Fase B — Read-only cockpit:** verrijkte `for_dossier` (State/Event/Pattern/Attention/patterns/source-health/contradictions) + PWA-cockpit (I) + LOCKED visual spec (J). Alleen lezen. Leest zowel hot-snapshot (current) als de dan al gevulde history.
3. **Fase C — Coach-corrections/actions (H).**
4. **Fase D — Report-projection (K).**
5. **Fase E — Teampuls-projectie (L).**

> Jip koos history-store vóór de cockpit (spec-volgorde). Voordeel: bij livegang van de cockpit is er al echte historie i.p.v. alleen live-berekende current-state; de timeline is vanaf dag 1 gevuld met wat sinds Fase A is gecaptured.

---

## Wat NIET gewijzigd is / wordt (§25)
Geen implementatie, geen refactor. Ongemoeid: locked Schema, locked Feedback, Masterbrein production-behavior, Home, FinalSurge-writes, feature-gates, complaint-thresholds, zones-semantiek. Geen nieuwe DB, geen event-sourcing-framework, geen Streamlit-kopie, geen history-migratie, geen AI voor canonieke waarheid.

## Eindoordeel
Zie het GO/NO-GO-blok in de begeleidende rapportage.
