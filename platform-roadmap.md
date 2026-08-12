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
- **Hoogste prioriteit nu: MASTERBREIN V2** (H2-intelligentielaag). Kwaliteitsronde: eerst volledige
  technische inventarisatie (geen code) vóór de definitieve architectuur. Bijsturen (DELETE-flow) geparkeerd.

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
