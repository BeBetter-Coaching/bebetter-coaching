# BeBetter — Platform Roadmap

> Companion bij [`streamlit-functional-baseline.md`](streamlit-functional-baseline.md). Strategische volgorde
> vóór modulekeuze, getoetst aan de North Star. Vastgesteld 10 aug 2026; bijgewerkt 11 aug 2026 (Schema-lock).
> Geen implementatie-doc — per module geldt principe 3 (baseline lezen → Streamlit inspecteren →
> REUSE/KEEP/MERGE/IMPROVE/MISSING/DO NOT TOUCH → dán bouwen).

## Status — LOCKED (12 aug 2026)
**SCHEMA NIEUW + VERLENGEN END-TO-END V1 = PRODUCTION PROVEN.** Beide live bewezen op desktop mét een
echte gecontroleerde FinalSurge-write. Verlengen (12 aug) visueel gecontroleerd: juiste aansluiting op het
bestaande blok, geen ongewenste overlap, oude planning/doelrace intact, resultaat correct in FinalSurge.
- **Home** ✅ · **Feedback** ✅ · **Schema Nieuw (Slice 1–3)** ✅ · **Schema Verlengen** ✅ · **Masterbrein v1** ✅ = FROZEN references.
- DO NOT TOUCH zonder concrete bug / bewezen performanceprobleem / expliciete nieuwe requirement.
- Kern-coachloop `Home → Feedback → Schema` is compleet voor **Nieuw én Verlengen**. Zie
  [[schema-workbench-slice1]], [[bebetter-masterbrein-context]], [[feedback-frozen-quality-reference]].

## Status — MASTERBREIN V2 FASE B LOCKED (13 aug 2026)
**MASTERBREIN V2 FASE B — SCHEMA NIEUW + VERLENGEN = PRODUCTION ACTIVE + PRODUCTION PROVEN + LOCKED.**
Schema Nieuw en Verlengen consumeren hun atleet-intelligentie nu uit Masterbrein V2 via de backwards-compatible
`athlete_context`-adapter. Live geactiveerd met `BEBETTER_SCHEMA_BRAIN=v2` op Render (commit `56b55fe`) en
handmatig production-gesmoke-test.
- **Live acceptance bevestigd:** Schema Nieuw laadt normaal · Schema Verlengen laadt normaal · cross-training
  lekt niet als running load (run-only) · coach memory komt correct mee · ontbrekende intake wordt niet met
  verzonnen data ingevuld · bij ontbrekend doel blijft doel leeg en wordt dat eerlijk gemeld · geen errors.
- **Shadow-acceptance (GO):** 14 echte atleten live · 0 `UNEXPECTED` · 0 errors · pure runners bleven gelijk ·
  cross-trainers correct run-only · klacht/interruption-case bleef ATTENTION.
- **Bekende v1-sportmixbug is weg** in actieve V2-modus: km/week + runs/week zijn uitsluitend hardlopen
  (via `brain.projections.for_schema`). Geen locked Schema-code, geen FinalSurge write-pad, geen frontend/SW gewijzigd.
- **Rollback beschikbaar (voorlopig behouden):** `BEBETTER_SCHEMA_BRAIN=legacy` — geen codeherstel nodig.
- **DO NOT TOUCH:** feature-gating (`BEBETTER_SCHEMA_BRAIN`), `pwa/brain/adapter.py`, de V2-gate in
  `pwa/athlete_context.build_athlete_context`, en de bewezen brain-kernel. Zie [[bebetter-masterbrein-context]].
- **Volgende geplande Masterbrein-consumer = Feedback** — NOG NIET gestart. Feedback wordt éérst opnieuw
  inhoudelijk beoordeeld op basis van echte gebruikstests vóórdat daar code wordt gewijzigd
  (Feedback blijft tot dan FROZEN). Geen andere consumer (Home/Dossier/Teampuls) migreren zonder aparte GO.

- **(H2-vervolg) MASTERBREIN V2** breidt daarna uit naar de overige consumers. Bijsturen (DELETE-flow) geparkeerd.

## North Star
BeBetter groeit van coach-PWA naar een world-class coaching-platform dat FinalSurge/TrainingPeaks kan
vervangen voor coaches én atleten — met een substantieel betere coach-workflow, intelligentielaag en productbeleving.

## Horizonten
- **H1 — Coach-workflow compleet & superieur.** Coach draait de hele week in de PWA, zonder Streamlit/FS-admin. *Bijna af.*
- **H2 — Intelligentielaag.** Longitudinale atleet-intelligentie, proactief coachen. *Nauwelijks begonnen.*
- **H3 — Platform & athlete-facing.** Eigen data-eigendom + atleten-app; FS-afhankelijkheid afbouwen. *Toekomst.*

## Kern-coachloop
`Home (triage) → Feedback (reageren) → Schema (voorschrijven)`. Alle drie ✅ FROZEN. Schema is compleet
voor **Nieuw**; **Verlengen** en **Bijsturen** zijn de resterende modi (Streamlit-bewezen, nog niet in PWA).

## Schema bouwen — modus-status
- **Nieuw** = end-to-end PWA production proven (config → masterbrein-context → conceptplan → AI-chat →
  workbench → preview → veilige write). LOCKED.
- **Verlengen** = nog te bouwen (Streamlit-bewezen: `_prefill_builder_from_prev` + `get_last_planned_date`).
- **Bijsturen** = nog te bouwen (Streamlit-bewezen: `_render_bijsturen_flow` + `get_planned_workouts_from` +
  `delete_workout`; hoog risico = externe DELETE).
- **Veilige write voor Nieuw** = bewezen (`publish_preview`/`publish`, per-rij, partial-failure/retry/idempotency).
- **Masterbrein v1** = centrale contextbasis (`pwa/athlete_context.py`), gebruikt door Schema-chat.
- **Volledige Feedback-thread als contextbron** = later te beoordelen (kost FS-calls; Feedback frozen).
- **Dossier** = blijft de belangrijke toekomstige menselijke view van het masterbrein.

## Volgende kandidaten (NOG NIET BOUWEN — beslissing bij Jip)
A. **Schema Verlengen** · B. **Schema Bijsturen** · C. **Atleet-dossier diepte**. Strategische vergelijking
(coachwaarde/platformwaarde/afhankelijkheden/risico/patroonhergebruik/masterbrein-bijdrage/complexiteit) staat in
[[bebetter-platform-roadmap]]. Niet automatisch aannemen dat Verlengen volgt omdat het in dezelfde module zit.
Per module blijft principe 3 gelden (reuse-first classificatie vóór code).

## Herbruikbare bewezen patronen (Home/Feedback → volgende modules)
Streamlit businesslogica reuse-first · durable snapshot+SWR · single-flight · active-state niet muteren tijdens
refresh · master-detail · drafts · irreversibele send vs reversibele optimistic (Undo) · mobile composer
(keyboard-geometrie-vrij) · lazy detail/preload · deterministische data vóór AI · `workout_type` central source ·
debug/instrumentatie · performance als productfeature · echte device-acceptance vóór lock. Zie
[[feedback-frozen-quality-reference]], [[bebetter-streamlit-is-basis-reuse-first]].

## Cross-module intelligence direction — masterbrein v1 (gebouwd)
Shared athlete context + task-specific recency/relevance filtering staat als **`pwa/athlete_context.py`**
(profile/training/recovery/health/feedback/goals/coach; recency-beleid per type; traceability; anti-hallucinatie).
Nu gebruikt door Schema-chat; later herbruikbaar door Home/Feedback/Dossier/Teampuls — geen kopie van waarheid.
Nog GEEN centraal intelligence-platform/DB/RAG bouwen; relevantie + recency blijven leidend (geen alles-ooit).
Zie [[bebetter-masterbrein-context]].

## Vastgestelde productprincipes (11 aug 2026)
Streamlit-logica reuse-first · zones = enige intensiteitswaarheid · canonieke planrepresentatie = parsed rows ·
AI is niet de bron van deterministische regels · plan-chat gebruikt rijke atleetcontext · masterbrein = centrale
context + taakgerichte projectie · recency/relevance > contextdump · desktop = primaire acceptance / iPhone =
periodieke lock-gate · irreversibele writes nooit optimistic · stateverlies = productbug · geen AI/API-call als
onderliggende state ongewijzigd is · bewezen patterns hergebruiken i.p.v. opnieuw uitvinden.
