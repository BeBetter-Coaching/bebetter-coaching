# BeBetter — Platform Roadmap

> Companion bij [`streamlit-functional-baseline.md`](streamlit-functional-baseline.md). Strategische volgorde
> vóór modulekeuze, getoetst aan de North Star. Vastgesteld 10 aug 2026. Geen implementatie-doc —
> per module geldt principe 3 (baseline lezen → Streamlit inspecteren → REUSE/KEEP/MERGE/IMPROVE/MISSING/DO NOT TOUCH → dán bouwen).

## North Star
BeBetter groeit van coach-PWA naar een world-class coaching-platform dat FinalSurge/TrainingPeaks kan
vervangen voor coaches én atleten — met een substantieel betere coach-workflow, intelligentielaag en productbeleving.

## Horizonten
- **H1 — Coach-workflow compleet & superieur.** Coach draait de hele week in de PWA, zonder Streamlit/FS-admin. *Bijna af.*
- **H2 — Intelligentielaag.** Longitudinale atleet-intelligentie, proactief coachen. *Nauwelijks begonnen.*
- **H3 — Platform & athlete-facing.** Eigen data-eigendom + atleten-app; FS-afhankelijkheid afbouwen. *Toekomst.*

## Kern-coachloop
`Home (triage) → Feedback (reageren) → Schema (voorschrijven)`. Home ✅ + Feedback ✅ zijn FROZEN quality
references. **Schema bouwen is de ontbrekende helft** → grootste voelbare gap en scherpste pariteitsmijlpaal.

## Aanbevolen modulevolgorde (BESLOTEN)
1. **Schema bouwen (rijke flow)** — *gekozen als volgende module.* Voltooit de loop; hoogste zichtbare waarde;
   Streamlit-baseline + plan [`vast-napping-quill.md`](.claude/plans/vast-napping-quill.md) bestaan al. Gefaseerd;
   hergebruik Feedback-patronen. Risico HOOG (WRITE naar FS + AI-adherentie).
2. **Atleet-dossier diepte** — H2-substraat; laag risico; compoundt in Schema + Feedback.
3. **Builder bijvullen & zones** (enige MISSING-module) — smal/onderhoud; deelt zones-conversie met Schema.
4. **Admin belasting-aangifte** — opportunistisch, buiten het coaching-pad.

## Gating & eerstvolgende stap
- **Gate:** fysieke iPhone + desktop Feedback-acceptatietest moet groen zijn. Zo ja → Feedback niet heropenen.
- **Daarna, vóór één regel Schema-code:** reuse-first classificatie van `builder_page.py` + `schema_builder.py` +
  `schema_core.py`/`schema_page.py` (REUSE/KEEP/MERGE/IMPROVE/MISSING/DO NOT TOUCH), en vergelijk met plan
  `vast-napping-quill.md`. Analyse eerst, akkoord, dán bouwen.

## Herbruikbare bewezen patronen (Home/Feedback → volgende modules)
Streamlit businesslogica reuse-first · durable snapshot+SWR · single-flight · active-state niet muteren tijdens
refresh · master-detail · drafts · irreversibele send vs reversibele optimistic (Undo) · mobile composer
(keyboard-geometrie-vrij) · lazy detail/preload · deterministische data vóór AI · `workout_type` central source ·
debug/instrumentatie · performance als productfeature · echte device-acceptance vóór lock. Zie
[[feedback-frozen-quality-reference]], [[bebetter-streamlit-is-basis-reuse-first]].

## Cross-module intelligence direction
Shared athlete context + task-specific recency/relevance filtering. Schema-chat (Slice 2) bouwt de AI-context
al modulair op (`schema_core._actuele_context`: Garmin + kalenderlabels + trainingslog, best-effort, bounded) —
later verplaatsbaar naar één gedeelde athlete-context waar Home/Feedback/Dossier/Teampuls/Schema op aansluiten.
Nog GEEN centraal intelligence-platform bouwen; relevantie + recency blijven leidend (geen alles-ooit).
