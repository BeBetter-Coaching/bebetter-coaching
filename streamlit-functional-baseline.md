# BeBetter — Streamlit Functionele Baseline

> **Doel van dit document.** De Streamlit-app is de **bewezen functionele basis** van BeBetter.
> De PWA bouwt daarop voort (reuse-first). Dit is de **vaste referentie** die je bij ELKE nieuwe
> PWA-module éérst raadpleegt: waar zit iets, wat bestaat bewezen, welke source-of-truth geldt,
> wat mag je niet opnieuw uitvinden.
>
> **Vaste ontwikkelregel (projectbreed):** bij elke nieuwe PWA-module →
> 1. dit document raadplegen → 2. de relevante Streamlit-code inspecteren →
> 3. classificeren REUSE / KEEP / MERGE / IMPROVE / MISSING / DO NOT TOUCH →
> 4. pas daarna ontwerpen/implementeren. *Streamlit is de functionele basis; PWA moet beter worden, niet anders om het anders zijn.*
>
> Dit is een **inventarisatie**, geen refactor. Er is geen code gewijzigd. Regelnummers zijn indicatief (peildatum 2026-08-10).

---

## 0. Herkomst-legenda — wie was er eerst

Zodat je bij elke module in één blik ziet wat je **hergebruikt uit Streamlit** vs wat een **PWA-verbetering** is. Vier herkomst-categorieën (kolom "Herkomst" in §2 en §9):

| Code | Betekenis |
|------|-----------|
| **S-only** | Bestaat alleen in Streamlit; nog geen PWA-equivalent (missing). |
| **S+PWA** | Functionaliteit komt uit Streamlit/gedeelde kern; PWA heeft een eigen UI erop (zelfde bewezen logica). |
| **kern-nieuw** | Nieuwe logica in de **gedeelde kern** (`fs_client`/`ai_feedback`/…) — raakt **zowel Streamlit als PWA**, geen PWA-exclusieve UX. |
| **PWA-only** | Bestaat alleen in de PWA-laag (architectuur/UX/infra); Streamlit heeft dit niet. |

**Tijdlijn (git, hard bewijs):**
- **4 jun 2026** — Streamlit initial commit: `main.py`, `ai_feedback`, `fs_client`, `schema_builder`, `admin`, `dossier`, `belasting` → **alle 11 modules + Home zijn Streamlit-origine**.
- **5 aug** — `pwa/` + service worker (`sw.js`) toegevoegd.
- **7 aug** — `feedback_core` (workout-queue), durable Home-snapshot naar GitHub, WebAuthn.
- **10 aug** — mobile composer (keyboard-geometrie-vrij, LOCKED) + `classify_workout_type`/non-run gating (**kern-nieuw**, raakt beide).

**Kernregel bij lezen:** geen enkele *hoofdmodule* is in de PWA ontstaan — het nieuwe zit in **PWA-architectuur/UX** (§8, "puur PWA") en in **gedeelde-kern-uitbreidingen** (`kern-nieuw`). "Nieuw" ≠ automatisch "PWA-only".

**FROZEN QUALITY REFERENCE (net als Home):** sinds 10 aug 2026 is **Feedback afgerond en LOCKED** — semantisch compleet (`generate_reply` type-gegate), mobiele actierij opgeschoond (Kopiëren desktop-only), tijdelijke type-debug verwijderd. Feedback + Home zijn nu de twee bewezen kwaliteitsreferenties waar volgende modules patronen uit hergebruiken (zie [[feedback-mobile-composer-locked]], [[feedback-performance-karakteristiek]]). Niet meer wijzigen zonder expliciete reden.

---

## 1. Architectuur in één blik

Twee frontends op **één gedeelde Python-kern** en **één gedeelde datalaag**:

```
        Streamlit UI (main.py + *_page.py)          PWA UI (pwa/static/*, vanilla JS)
                 │                                            │
                 │                                     FastAPI (pwa/api.py)
                 │                                            │  pwa/*_core.py  (Streamlit-vrije wrappers)
                 └───────────────┬────────────────────────────┘
                                 ▼
         GEDEELDE KERN:  fs_client.py · ai_feedback.py · schema_builder.py ·
                         intake_store.py · dossier.py · admin.py · belasting.py ·
                         briefing.py · rompslomp_client.py · ai_client.py · docgen/
                                 ▼
     FinalSurge API  ·  Anthropic API  ·  Rompslomp API  ·  GitHub-repo `BeBetter-Coaching/bebetter-data` (JSON-persistence)
```

- **Streamlit** draait op Streamlit Cloud (`streamlit==1.61.1`, exact gepind — zie [[bebetter-deploy-pins]]). Entry: `main.py`.
- **PWA** draait op Render (Docker, `pwa/api.py`, FastAPI). De `pwa/*_core.py` laag is bewust **Streamlit-vrij** (importeert nooit `streamlit`) en wrapt de gedeelde kern.
- **Persistentie:** geen database. `intake_store.py` leest/schrijft JSON-bestanden in de GitHub-repo `bebetter-data` (Contents API) met lokale `.<naam>.json`-cache. Zie §4.
- **Auth:** Streamlit = wachtwoord (`_check_password`). PWA = gedeeld wachtwoord + sessie-cookie (HMAC) + optioneel WebAuthn/biometrie.

---

## 2. Functionele modulekaart (bron: `main.py` `_MOD`, r. ~1384)

De home-tegels definiëren de canonieke modulelijst (11 modules + Home-dashboard). Per module: user-waarde · belangrijkste bestanden · PWA-status · herkomst (§0). **Alle 11 modules + Home zijn Streamlit-origine (4 jun 2026); geen enkele hoofdmodule is in de PWA ontstaan.**

| # | Module | Herkomst | Wat de coach ermee doet | Streamlit-bestanden | PWA-core / route |
|---|--------|:---:|--------------------------|---------------------|------------------|
| 0 | **Home / Dashboard** | S+PWA | Dagoverzicht: feedback-pending, races, compliance-alerts, schema-signalen | `main.py` (`page=="home"`, r.1377+) | `home_core.py` → `/api/home/*` |
| 1 | **Feedback** | S+PWA | Atleet reageert op training → AI-concept in coachstijl → 1-klik posten | `main.py` (`page=="feedback"`, r.2160+), `ai_feedback.py`, `fs_client.get_workouts_needing_feedback` | `feedback_core.py` → `/api/feedback/*` |
| 2 | **Schema-verloop** | S+PWA | Bewaking: wiens schema loopt af (≤7 dg / verlopen / geen actief) | `schema_page.py`, `fs_client.get_schema_end_dates` | `schema_verloop_core.py` → `/api/schema-verloop` |
| 3 | **Teampuls** | S+PWA | Belasting-signalen (wie loopt uit de pas) + weekbriefing | `puls_page.py`, `belasting.py`, `briefing.py` | `teampuls_core.py` → `/api/teampuls/*` |
| 4 | **Races** | S+PWA | Aankomende races + AI-raceplan + persoonlijke succeswens | `races_page.py`, `ai_feedback.generate_race_*` | `races_core.py` → `/api/races*` |
| 5 | **Administratie** | S+PWA | KOR-bewaking, omzet/categorie, facturen, klantadmin (pincode) | `admin.py`, `rompslomp_client.py`, `belasting.py` | `admin_core.py` → `/api/admin/*` |
| 6 | **Intake** | S+PWA | Nieuwe atleet vastleggen (doel/niveau/achtergrond); publieke intakelink + inbox | `intake_page.py`, `intake_form.py`, `intake_store.py`, `schema_builder.extract_intake_fields` | `intake_core.py` → `/api/intake/*` |
| 7 | **Schema bouwen** | S+PWA (deels) | Trainingsplan genereren op doel/niveau/datum → CSV → FinalSurge-import incl. workout-builder | `builder_page.py`, `schema_builder.py` | `schema_core.py` → `/api/schema/*` (**lichter**, zie §8) |
| 8 | **Atleet-dossiers** | S+PWA (deels) | Alles per atleet: intake, notities, compliance, trends, races, zones | `dossier.py`, `intake_store` notes/profielen | `dossier_core.py` + `atleten_core.py` → `/api/dossier/*`, `/api/atleten` |
| 9 | **Documenten** | S+PWA | Persoonlijk PDF-document (handleiding/wedstrijd/voeding/kracht) in huisstijl, AI-stukjes | `documenten_page.py`, `docgen/` | `documenten_core.py` → `/api/docs/*` |
| 10 | **Builder bijvullen & zones** | **S-only** | Workout-builder vullen voor bestaande trainingen; heel schema tempo↔hartslag omzetten | `main.py` (`page=="backfill_builder"`, r.2689+), `fs_client.convert_schema_zones` | **MISSING in PWA** |
| 11 | **Strippenkaart** | S+PWA | Losse-trainingen-klanten: strip afboeken + WhatsApp-appje | `main.py` (`page=="strippenkaart"`, r.1815+), `intake_store` strippenkaarten | `strippen_core.py` → `/api/kaarten*`, `/api/import*` |

Ondersteunend (niet als tegel): **belasting** (rekenmodule, gedeeld door Home+Teampuls), **briefing** (weekbriefing-generator), **rompslomp_client** (boekhoud-API), **webauthn** (alleen PWA), **belasting.py** los tabblad `belasting`/`belastingaangifte` in admin.

---

## 3. Per-module kern (compact)

### 1. Feedback — *het kroonjuweel, meest bewezen*
- **Workflow:** sweep haalt trainingen op die coaching nodig hebben → queue → coach opent → deterministische context (zones + workout_type) → AI-concept → coach bewerkt → post als FinalSurge-comment (of Overslaan).
- **Kern:** `fs_client.get_workouts_needing_feedback()` (3 parallelle fasen: roster-fanout / comments / details; r.765). `ai_feedback.generate_feedback()` + `generate_reply()`.
- **Businessregels:** een training vraagt aandacht bij atleet-notitie/comment zonder coach-reactie; `exclude_groups={"los schema"}` krijgt geen feedback; `posted_today` telt coach-comments van vandaag; skip = tot atleet weer reageert (`.feedback_skipped.json`, snapshot-fingerprint via `_skip_snapshot`/`_filter_skipped`). **workout_type deterministisch vóór AI** — UNKNOWN is NOOIT run (zie [[feedback-generate-reply-workouttype-todo]]).
- **State:** durable snapshot + SWR + single-flight (PWA); skip-set gedeeld via GitHub.
- **PWA:** bewezen patronen LOCKED — mobile composer, optimistic+undo skip, performance-karakteristiek. Zie [[feedback-mobile-composer-locked]], [[feedback-performance-karakteristiek]], [[feedback-ai-schrijfstijl-vraagdrempel]].

### 2. Schema-verloop
- `fs_client.get_schema_end_dates(horizon, on_hold_keys)` → per atleet dagen-tot-einde. `<4` geplande trainingen = "los schema" (`_MIN_SCHEMA_WORKOUTS`), telt niet mee. On-hold-atleten (`intake_store.load_on_hold`) uitgezonderd. Urgent = None / ≤7 dagen.

### 3. Teampuls (belasting + briefing)
- **belasting.py:** vier signaalregels (getest, `TestBelasting`): volume-ratio ≥1.30 (let op) / ≥1.50 (hoog) t.o.v. 4-weeks gemiddelde, mits basis ≥10 km/wk; gevoel-verslechtering ≥0.8; RPE-drift ≥1.5 (alleen als volume niet fors steeg); klacht-detectie met negatie-filter ("pijnvrij" ≠ klacht). Alleen hardloop-km tellen (wandelen=‘Lopen’ eruit). Snooze 7 dg via `markeer_gezien`.
- **briefing.py:** maandagochtend-weekbriefing (AI) over eigen atleten per coach; `verzamel_week` → `genereer_briefing_tekst`.

### 4. Races
- `fs_client.get_upcoming_races()`. Wens = coach-comment; race telt als "nog geen wens" tot comment bestaat. `ai_feedback.generate_race_wish` + `generate_race_plan` (systeemprompts r.671/781).

### 5. Administratie *(financiële cockpit; getest KOR/btw/matching)*
- **KOR:** grens €20.000, KOR eindigt 1-8-2026 (`KOR_TOT`), 21% btw daarna. `kor_projectie`, `btw_stand`, `potjes_advies` (IB-pot 45% winst bovenop loondienst — zie [[jip-werk-defensie]]).
- **Rompslomp:** facturen/omzet/kosten via `rompslomp_client`. `factuur_categorie` (Coaching/Clinics/Lactaat/Strippen/Overig) op naam+omschrijving. `match_contact_fs` koppelt factuur↔FS-atleet op achternaam-kern. Strippenkaarten/clinics niet koppelbaar (zie [[bebetter-rompslomp-koppeling]]).

### 6. Intake
- Coach-intake (`intake_page`) + **publieke intakelink** (`intake_form.render_publieke_intake`) met token + resume + inbox. `schema_builder.extract_intake_fields` (AI) parseert vrije tekst/bestand → gestructureerde velden. Opslag `intake_store.save_intakes`. Feedt de builder (prefill).

### 7. Schema bouwen *(rijkste module; zie plan `vast-napping-quill.md`)*
- **Pipeline:** intake → `build_prompt` (plan-prompt) → `generate_plan` → `build_csv_prompt` → `generate_csv` → `parse_csv_text` → `import_to_finalsurge` (+ `generate_builder_steps` → WorkoutBuilder-JSON).
- **Kernbeslissing (LOCKED):** **zones = enige waarheid**, geen VDOT-tempo's in de output (zie [[bebetter-app-koers-en-roadmap]]). VDOT-functies bestaan maar sturen zones-tekst, geen pace-targets.
- **Bekende zwaktes (open plan):** AI negeert coach-eisen (harde-eisen-blok nodig bovenaan prompt); off-by-one weken; atleetnaam-prefill; trainingsdagen vrije tekst → multiselect. Zie Fase 1/2 in `vast-napping-quill.md`.
- **Modi (gepland):** Nieuw / Verlengen / Bijsturen — `builder_page._render_bijsturen_flow`, `_prefill_builder_from_prev`, `get_planned_workouts_from`, `delete_workout`.

### 8. Atleet-dossiers
- `dossier.render_dossier(athlete, intake, on_hold_info)`. `_analyse_log` (trends, compliance), `_run_km` (5526km-bug getest: alleen echte runs), coachnotities (`intake_store.notes`), coach-profiel/geheugen (`_coach_profiel`, `_leer_profiel`, `ai_feedback.update_athlete_profiel`), zones, evaluatie (`evaluatie_context` → `generate_athlete_evaluation`), Garmin-paneel (light).

### 9. Documenten
- `docgen/`-engine (ReportLab). Templates: handleiding, wedstrijd, voeding_training, kracht + vrij document. AI schrijft persoonlijke stukjes in huisstijl (`house_style.py`). Bibliotheek/hergebruik in `intake_store.doc_library`. Zie [[bebetter-doc-generator]].

### 10. Builder bijvullen & zones — **alleen Streamlit**
- Backfill workout-builder voor bestaande trainingen; `convert_schema_zones(user_key, start, end, naar)` zet heel schema tempo↔hartslag (`convert_builder_target_type`, `_flip_zone_targets`). Getest (`TestZoneOmzetten`): wandel-herstel blijft vaste pace, zone-nummers ongewijzigd.

### 11. Strippenkaart
- Afboeken/terug/verwijderen (`intake_store.strippenkaarten`), WhatsApp één-tik `wa.me`-link (`_wa_link`, `normalize_number`), contact-import (vCard/tekst). Zie [[strippenkaart-whatsapp]].

---

## 4. Gedeelde business-logica (voorkom parallelle versies in PWA)

| Concept | Gedeelde bron | Belangrijkste functies |
|---------|---------------|------------------------|
| FinalSurge-client | `fs_client.py` | `get_athletes(_by_group)`, `get_workouts*`, `get_comments/post_comment`, `save_workout(_builder)`, `get_athlete_zones` |
| Activity types | `fs_client.ACTIVITY_TYPE_KEYS` + `classify_workout_type` (r.171/215) | GUID+naam → run/bike/swim/cross_training/strength/other; **single source** |
| Zones | `fs_client.get_athlete_zones` + `zone_van_waarde` (r.1374/1483) | ZoneList-endpoint; run-zones; waarde→zone (bug 147bpm=Z1 getest) |
| Workout uitvoerd/gepland | `is_executed_workout`, `is_planned_workout` (`has_actual_data` onbetrouwbaar — getest) | |
| km-normalisatie | `_norm_km`, `dossier._run_km` | mijlen→km, alleen echte runs |
| Feedback-selectie | `get_workouts_needing_feedback` | één functie, `include_details` schakelt Streamlit(True)/PWA-queue(False) |
| Belasting-signalen | `belasting.py` | vier regels, getest |
| Persistentie | `intake_store.py` | ALLE JSON-state via GitHub `bebetter-data` + lokale cache |
| Athlete identity | `fs_client._extract_athlete` + `admin._achternaam_kern`/`match_contact_fs` | naam-matching (FS↔Rompslomp) |
| AI-calls | `ai_client.create_message` | retry op 429/5xx/529 |
| AI-feedback/prompts | `ai_feedback.py` | zie §6 |
| Coach-identiteit/groepen | `fs_client.get_coach_key`, `get_athletes_by_group`, `group_is_excluded` | "los schema" e.d. |

---

## 5. Source-of-truth kaart

| Concept | ✅ Bron van waarheid | ❌ Niet |
|---------|----------------------|---------|
| workout_type | `fs_client.classify_workout_type` (GUID→naam→titel-fallback→unknown) op **detail-object** (`WorkoutPlannedCompleted`) | light WorkoutList (type vaak null); losse UI-mappings |
| zones | `fs_client.get_athlete_zones` (FinalSurge ZoneList) | VDOT-afgeleide pace-targets |
| trainingsintensiteit in schema | **zones** (zie [[bebetter-app-koers-en-roadmap]]) | VDOT/tempo's |
| uitgevoerd vs gepland | `is_executed_workout` / `is_planned_workout` | `has_actual_data` |
| feedback-noodzaak | `get_workouts_needing_feedback` | UI-heuristiek |
| alle app-state | `intake_store.py` (GitHub) | losse lokale bestanden als primair |
| omzet/KOR/btw | `admin.py` + `rompslomp_client.py` | handmatige tellingen |
| atleet↔factuur | `admin.match_contact_fs` (achternaam-kern) | e-mail/losse naam |
| AI-schrijfstijl/coachstijl | `ai_feedback` systeemprompts | ad-hoc prompts per laag |

---

## 6. AI / prompt-inventarisatie (bron: `ai_feedback.py`, `schema_builder.py`, `briefing.py`)

Alle LLM-calls lopen via `ai_client.create_message` (retry). Deterministische preprocessing gaat **altijd** vóór de AI.

| Flow | Entrypoint | System-prompt | Deterministische preprocessing | Status |
|------|-----------|---------------|-------------------------------|--------|
| Feedback (run) | `ai_feedback.generate_feedback` | `SYSTEM_PROMPT` (hardloopcoach) | `_build_workout_context`: zones, laps, builder-steps, afwijking | **BEWEZEN — niet herontwerpen** |
| Feedback (non-run) | idem, branch op `workout_type` | `_NONRUN_SYSTEM` (neutraal, geen zones/pace/run-termen) | `_build_nonrun_context` (feitelijk) | **kern-nieuw** (10 aug) — raakt Streamlit + PWA, geen PWA-only UX. Classificatie via `fs_client.classify_workout_type`. LOCKED |
| Vervolgreactie | `generate_reply(thread)` | run→`SYSTEM_PROMPT` · non-run/unknown→`_NONRUN_SYSTEM` | run→`_build_workout_context` · non-run→`_build_nonrun_context` | **kern-nieuw, gegate op `workout_type`** (10 aug). Run-pad byte-identiek; unknown nooit run. PWA-replies lopen via `generate_feedback` (ook gegate). LOCKED |
| Coachstijl-regels | in prompts | geen em-dash, geen AI-taal, default géén vraag | — | LOCKED, zie [[feedback-ai-schrijfstijl-vraagdrempel]] |
| Race-wens | `generate_race_wish` | `RACE_WISH_SYSTEM_PROMPT` | `_dag_aanduiding` | bewezen |
| Raceplan | `generate_race_plan` | `RACE_PLAN_SYSTEM_PROMPT` | zones/afstand | bewezen |
| Kwartaalevaluatie (intern) | `generate_athlete_evaluation` | `_EVALUATIE_SYSTEM` | `dossier.evaluatie_context` | bewezen |
| Klantbericht (warm appje) | `generate_athlete_message` | `_KLANTBERICHT_SYSTEM` | context uit dossier | bewezen |
| Coach-geheugen/profiel | `update_athlete_profiel` | `_PROFIEL_SYSTEM` | compacte accumulatie | bewezen |
| Dossier-signaal-check | `check_dossier_signal` | `_DOSSIER_CHECK_SYSTEM` + `_SIGNAAL_PATRONEN` | patroon-prefilter | bewezen |
| Belasting-duiding | `belasting_duiding` | `_BELASTING_SYSTEM` | belasting-signalen | bewezen |
| Sessie-samenvatting | `generate_session_summary` | inline | items-lijst | bewezen |
| Weekbriefing | `briefing.genereer_briefing_tekst` | `_BRIEFING_SYSTEM` | `verzamel_week`/`aggregeer_week` | bewezen |
| Schema-plan | `schema_builder.generate_plan` | `SYSTEM_PROMPT` (bouwer) | `build_prompt` (+harde-eisen, open) | ⚠️ adherentie-zwakte, zie plan |
| Schema→CSV | `generate_csv` | inline | `build_csv_prompt` (maandag-uitgelijnd, weekkalender) | bewezen parsing (`parse_csv_text` getest) |
| Workout-builder JSON | `generate_builder_steps` | `BUILDER_SYSTEM_PROMPT` | duur/afstand-berekening (getest) | bewezen |
| Chat over plan | `chat_about_plan` | `CHAT_SYSTEM_PROMPT` | — | bewezen |
| Intake-extractie | `extract_intake_fields` | `_INTAKE_VELDEN_SPEC` | bestand→tekst (`extract_file_content`) | bewezen |
| Schema-bericht (appje) | `genereer_schema_bericht` | inline | — | bewezen |

**Markering:** run-feedback + race + evaluatie + briefing + builder-conversie zijn inhoudelijk sterk/bewezen → **hergebruiken, niet opnieuw ontwerpen**. `generate_reply`-typing is nu gesloten (10 aug, LOCKED); alleen schema-plan-adherentie is nog open werk.

---

## 7. Belangrijkste dataflows

**Feedback:** FinalSurge → `get_workouts_needing_feedback` (roster-fanout → comments → details) → deterministische context (zones+type) → `ai_feedback.generate_feedback` → coach edit → `post_comment` (WRITE) → skip-state (`.feedback_skipped.json` via GitHub).

**Schema bouwen:** intake (`intake_store`) → `build_prompt` → `generate_plan` → `build_csv_prompt` → `generate_csv` → `parse_csv_text` → `import_to_finalsurge` (+ `generate_builder_steps`) → FinalSurge-kalender (WRITE).

**Home/cockpit:** parallel (`ThreadPoolExecutor`) feedback-count + races + `belasting`-alerts + schema-einddata → session_state/`home_core` snapshot → dashboard.

**Admin:** Rompslomp API → `rompslomp_client` (facturen/omzet/kosten) → `admin` (KOR/btw/categorie/matching) → cockpit; correcties terug naar `.revenue.json`/GitHub.

**Persistentie (overal):** load → lokale `.json`-cache → GitHub Contents API; save → GitHub commit + lokale cache. `is_cloud_backed()` bepaalt of GitHub actief is.

**Waar data verloren/vervormd kan raken:** workout_type in light-lijst (null → moet uit detail); wandelen als ‘Lopen’ (km-vervuiling); `has_actual_data` false-positives; weken maandag-uitlijning vs floor-deling (off-by-one).

---

## 8. REUSE / KEEP / MERGE / IMPROVE / PWA-SPECIFIC / MISSING / DO NOT TOUCH

**REUSE (Streamlit-logica direct):** `fs_client.*` (client, `classify_workout_type`, zones, feedback-sweep), `ai_feedback.*` prompts, `belasting.py` signaalregels, `intake_store.py` persistentie, `admin.py` KOR/btw/matching, `schema_builder` CSV-parsing/builder-berekeningen, `rompslomp_client`, `briefing`, `docgen/`.

**KEEP PWA — `PWA-only`, met commit/datum-anker (bestaat NIET in Streamlit):**
- Service-worker / offline-queue — `pwa/static/sw.js`, **5 aug** (f12739d).
- Workout-level feedback-queue — `pwa/feedback_core.py`, **7 aug** (24fab60).
- Durable snapshot + SWR + single-flight (Home/Feedback) — `home_core._persist` naar GitHub, **7 aug** (26bba88).
- WebAuthn / biometrie — `pwa/webauthn_core.py`, **7 aug** (a558f82).
- Mobile composer (keyboard-geometrie-vrij) — `styles.css` kb-open, **10 aug** (1244259), LOCKED.
- Optimistic UI + Undo (skip/gezien/wens), master-detail desktop, lazy detail/preload, performance-instrumentatie — `app.js`/`feedback_core`.

Zie [[feedback-mobile-composer-locked]]. Streamlit-equivalenten die NIET overgenomen worden: `_check_password` (i.p.v. WebAuthn), `st.session_state` (i.p.v. snapshot), server-side rerun (i.p.v. SWR/optimistic).

**MERGE (naar één bron):** workout_type (klaar: centraal in `fs_client`); zones-interpretatie; athlete-identity/naam-matching; coachstijl-prompts (één set in `ai_feedback`).

**IMPROVE (goed, PWA kan beter):** schema-bouwer adherentie (harde-eisen-blok, plan `vast-napping-quill.md`); intake-UX; `generate_reply` typing.

**PWA-SPECIFIC (niet letterlijk overnemen):** alle Streamlit-UI (`st.*`, `_MOD`-tegels, hero/CSS in `main.py`), `_check_password`, sidebar-navigatie. PWA heeft eigen `pwa/static/*` + FastAPI.

**MISSING in PWA (bestaat alleen in Streamlit):**
- **Builder bijvullen & zones** (module 10: backfill workout-builder + `convert_schema_zones`).
- **Schema bouwen — volledige flow**: `schema_core.py` doet plan/csv/push, maar de rijke `builder_page` (Nieuw/Verlengen/Bijsturen-modi, prefill, state-save, chat-over-plan) is **nog niet** in PWA.
- **Dossier-diepte**: `dossier_core` is lichter dan `dossier.py` (evaluatie/klantbericht/Garmin-paneel deels).
- **Belasting-aangifte-tab** (admin sub-tab) in PWA onvolledig.

**DO NOT TOUCH (stabiel/kritiek, niet onnodig wijzigen):** `fs_client.get_workouts_needing_feedback` (fasen+timings), `zone_van_waarde`, `is_executed_workout`, `intake_store` GitHub-persistentie, feedback skip-state-machine, PWA Home (viewport/touch-engine/state — bevroren), deploy-pins (`streamlit==1.61.1`). Zie [[bebetter-deploy-pins]], [[feedback-herbouw-handoff]].

---

## 9. Migratiekaart Streamlit → PWA

| Streamlit-module | Herkomst | Bewezen kern (REUSE) | Gedeelde helpers | PWA vandaag | PWA-verbeterkans | Migratierisico |
|---|---|---|---|---|---|---|
| Feedback | S+PWA | `get_workouts_needing_feedback`, `ai_feedback` | fs_client, ai_client, intake_store | **volledig** (`feedback_core`) | — (LOCKED) | laag; niet aanraken |
| Home | S+PWA | belasting, schema-einddata, races | fs_client, belasting | **volledig** (`home_core`) | — (bevroren) | hoog als aangeraakt |
| Schema-verloop | S+PWA | `get_schema_end_dates` | fs_client | volledig (`schema_verloop_core`) | filters | laag |
| Teampuls | S+PWA | `belasting`, `briefing` | fs_client, intake_store | volledig (`teampuls_core`) | — | laag |
| Races | S+PWA | `generate_race_*` | fs_client, ai_feedback | volledig (`races_core`) | — | laag |
| Admin | S+PWA | KOR/btw/matching, rompslomp | admin, rompslomp_client | volledig (`admin_core`, pincode) | UX | midden (financieel) |
| Intake | S+PWA | `extract_intake_fields`, publieke link | intake_store, schema_builder | volledig (`intake_core`) | UX | midden |
| Schema bouwen | S+PWA (deels) | `build_prompt`→`import_to_finalsurge`, `generate_builder_steps` | schema_builder, fs_client | **licht** (`schema_core`: plan/csv/push) | modi + adherentie (plan) | **hoog** (WRITE naar FS) |
| Atleet-dossiers | S+PWA (deels) | `dossier._analyse_log`, evaluatie | dossier, intake_store | licht (`dossier_core`+`atleten_core`) | evaluatie/klantbericht/trends | midden |
| Documenten | S+PWA | `docgen/` | intake_store | volledig (`documenten_core`) | — | laag |
| Builder bijvullen & zones | **S-only** | `convert_schema_zones` | fs_client | **MISSING** | nieuw bouwen | hoog (WRITE) |
| Strippenkaart | S+PWA | wa-link, import | intake_store | volledig (`strippen_core`) | Cloud API-verzending | laag |

---

## 10. Onzeker / nog te bewijzen / dead candidates

- ~~**`generate_reply` typing**~~: **GESLOTEN (10 aug)** — nu gegate op `workout_type` (run-pad byte-identiek, non-run/unknown via `_NONRUN_SYSTEM`). Feedback is hiermee semantisch compleet.
- **Schema-bouwer adherentie**: plan `vast-napping-quill.md` beschrijft de fix (harde-eisen-blok, weken off-by-one, naam-prefill, trainingsdagen-multiselect). Nog niet geïmplementeerd/gemeten.
- **`schema_core` (PWA) vs `builder_page`**: PWA-flow gebruikt (waarschijnlijk) de opgeslagen intake; de rijke modi (Verlengen/Bijsturen), chat-over-plan en backfill ontbreken — nog niet volledig getraceerd of PWA de builder-steps genereert.
- **Activity-type mapping volledigheid**: rehab/walk/HYROX/rest-GUIDs niet volledig bekend — pas mappen bij echte data, niet gokken.
- **`generate_pdf.py` (820 r.)**: **bevestigd dead** — geen enkele module importeert het; de `docgen/`-engine (`template`/`generator`/`reportlab_gen`/`templates/*`) heeft het vervangen (`documenten_page` gebruikt alléén docgen). Kandidaat voor opruimen in een aparte ronde, niet nu.
- **`.builder_state.json` / `builder_debug.txt`**: **NIET dead** — `builder_state` wordt live gebruikt door `builder_page`, `main.py`, `schema_builder`, `intake_store` (`_save/_load_builder_state`). `builder_debug.txt` is debug-scratch. Niet verwijderen.
- **`assets/` vs `pwa/static/`**: dubbele logo/foto-assets; functioneel maar dubbel.

---

*Onderhoud: werk dit document bij zodra een module structureel verandert (nieuwe source-of-truth, nieuwe gedeelde helper, PWA-module opgeleverd). Houd het een index — dupliceer geen broncode.*
