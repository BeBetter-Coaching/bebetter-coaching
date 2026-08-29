# BeBetter — Workspace Closure Review

**Branch:** `feature/app-design-system-athlete-shell-v1` · **commit:** zie COMMIT.txt
**Base:** `main = 39d2453` (SW v97 live) — deze branch is NIET gemerged.

## Wat dit is
De volledige stand van de Workspace visual-milestone bij SLUITING (closure-pass verwerkt):
de north-star passes (design system → visual wow → athlete canvas → north-star →
final pass) plus het Visual Design Lab-prototype dat de goedgekeurde eindrichting
draagt (`design-lab/workspace-lab.html` + still + motion-GIF).

## Leeswijzer (relevante bestanden)
- `pwa/static/app.js` — Workspace-render (`wsRender`, `wsAnchor`, `wsSignal`,
  `wsFigure`, `wsChart`, `wsOrbits`, `wsField`), Dossier (`dcRender`),
  Home-briefing (`prioDetailHtml`); generation-client (`noteGeneration`,
  `_genDominates`).
- `pwa/static/design-system.css` — token-laag, statussemantiek, shell/nav,
  Athlete Canvas (Workspace), Dossier living memory, Home-briefing.
- `pwa/static/styles.css` — basis-shell (ongewijzigde module-CSS).
- `pwa/static/index.html` — markup + asset-versies; `pwa/static/sw.js` — SW-cache.
- `pwa/coach_read.py` — Coach Read Model (ONGEWIJZIGD in deze milestone;
  alleen gelezen door de presentatie).
- `tests/test_app_design_system_v1.py` — design-contracttests (37).
- `design-lab/` — standalone prototype (geen productie-code) + renders.
- `review-screenshots/` — acceptance-shots van de laatste productie-stand.
- `FABLE-NORTHSTAR-v1.md` — gap-analyses, bouwlog, self-reviews, residuals.

## Extra in deze closure-versie
- `pwa/static/fonts/` — Space Grotesk (lokaal, preload + SW-cache v103).
- Rim-gauge, weekstrip, perspectiefvloer, cockpit-wrap, eyebrow/gradient-kop.
- `design-lab/workspace-live-recording.gif` — echte interface-opname
  (entree → idle → switcher → atleet-wissel).

## 1:1 North-star pass (deze oplevering)
- **Presentatie-architectuur herbouwd** (frontend-only): identity-zone (één keer),
  centraal cockpit-complex — holografische athlete-BUST (gelaagd, rim-light,
  scanlines, chroma-scheiding, particle-dissolutie) tussen orbit-lagen (ring
  achter het hoofd, gauge-sweep vóór de torso), orbit-gauge = ratio-verhaal
  (gedimde ronde = 100% referentie, felle sweep = overshoot, eindnode wijst
  naar het dominante cijfer, ×-label bij de node), platform-ellipsen (de
  athlete stáát), scène-typografie voor het signaal, cockpit-controls.
- **Maximaal twee glas-panels** (aandacht+belasting links; doel/feedback/
  context/bronnen rechts), zwevend en licht gekanteld de scène in.
- **Focus Shell**: op Workspace collapseert de sidebar tot een 76px icon-rail
  (:has, puur presentationeel; labels als hover-tooltips; routes identiek).
- **Locked architecture: ONAANGERAAKT** — geen wijziging aan Coach Read Model,
  generation/source_versions, stores, caches, routes, acties of businesslogica
  (git-diff vs main bevat backend-only de eerder gereviewde additieve
  `runs`-passthrough).

## Verwijderde superseded presentation-code (deze pass)
`wsField`, `wsFigure` (+ alle `.ws-fig*` CSS), het drie-koloms `ws-stage`/
`ws-col`-grid, de `ws-adv`-actiebalk, de embedded `ws-zone`/`ws-side`-cluster,
de schijf-gauge (`.ws-rim*`), de schijf-CSS van `.ws-signal`,
`.ws-signal-chart`, `.ws-idchip`, de oude hero-`.ws-anchor`/`.ws-halo`/kop-
layout en `.ws-pane-h`. Grep-geverifieerd: 0 restanten in app.js/design-system.css.

## Final visual+code contract-pass (deze oplevering)
- **Athlete-presence = hybride optie 2+3**: profielbust (hoofd/nek/schouders/
  torso) met anatomisch volume (radiaal schaduwvolume, kaakschaduw, sleutel-
  beenderen, kern-gloed in de borst) én digital-twin transparantie (topo-
  contourlijnen op de torso, scanlines, dissolve, chroma-scheiding, rim-light).
  **Drie varianten**: v (haarknot + staart), m (voller achterhoofd/nekhaar),
  x (neutraal, productie-default). Selectie: écht profielveld
  (`vm.profiel.geslacht`) zodra dat bestaat, plus presentatie-override
  `?bust=v|m` — **nooit geraden op voornaam** (bewuste weigering).
- **Drie hoofdpanelen + command dock** (contract §13/§18): Aandacht ·
  Belasting/Training (weekstrip + cumulatieve curve) · Doel/Feedback/Context/
  Bronnen; primary coachactie + rustige secundaire controls in de dock.
- Orbit-gauge, platform, Focus-rail, achtergrondlagen: zie vorige secties.

## BLOCKER-RESIDUAL (expliciet gemeld)
Het contract vraagt gender-passende presence, maar **nergens in de data
bestaat een geslachtsveld** (FinalSurge TeamAthleteList, intake, cockpit-
payload — alle gecontroleerd). Raden op voornaam is een echte misgender-fout
en is geweigerd. De v/m-varianten zijn af en direct activeerbaar zodra één
intake-/profielveld het draagt; tot die tijd is de neutrale variant default
en tonen de flagship-materialen Masja met de v-variant (zoals Jips eigen
referenties haar consistent tonen), via de presentatie-parameter.

## Teststatus
1026 passed — vaste én random volgorde (`python3 -m pytest tests/ -q`).

## Performance sanity (headless Chrome, koud, lokaal)
FCP 772–804 ms (gelijk aan baseline vóór alle visuele werk, A/B gemeten);
0 horizontale overflow op 1440px en 390px; geen nieuwe console-errors
(alleen pre-existing favicon-404 + vibrate-warning); 3 trage orbit-rotaties
als enige doorlopende animatie; geen library/canvas/WebGL in productie.

## Known residuals (bewust NIET in deze milestone)
1. Feedback: workoutinhoud onvoldoende zichtbaar vóór feedback geven.
2. Feedback: ongeplande/meerdere workouts per dag kunnen stil verdwijnen
   (ook coach-self athlete onderzoeken).
3. Teampuls/Feedback/Schema krijgen later ditzelfde visuele systeem.
4. Schema Maintenance v1 (Bijsturen, pace↔HR, Builder bijvullen).
5. Dossier history-capture activation (timeline bewust leeg).
6. Ongescopete `$(".md-list")` in `openDossier` (bekende latente bug).
7. Data-nit: km-afronding verschilt tussen bron-zin (74) en canonieke
   detailvelden (73.8) — percentages zijn overal genormaliseerd.
