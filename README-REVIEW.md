# BeBetter — Workspace Closure Review

**Branch:** `feature/app-design-system-athlete-shell-v1` · **commit:** zie COMMIT.txt
**Base:** `main = 39d2453` (SW v97 live) — deze branch is NIET gemerged.

## WORKSPACE FINAL REFINEMENT — ATHLETE CORE (merge-kandidaat)
> Finale visuele refinement-pass op de `8f7a1cb`-richting. **Géén nieuw concept,
> géén avatar:** de abstracte **Athlete Core** en de spatial cockpit blijven; de
> architectuur blijft locked (Coach Read / AthleteState / generation /
> `source_versions` / stores / routes ongemoeid). Doel: van ~85–90% naar een
> overtuigende, merge-waardige eindstaat.

**Vier ingrepen (frontend-only):**
1. **Rijkere kern** — glazen sphere is nu een intelligentie-object i.p.v. een
   platte bol: tweede inner shell (parallax-diepte), meridianen die naar het hart
   doven (helder aan de rand, `url(#ws-merid)`), zacht inner-field, glasrand-
   refractie, sparse segment-ticks en een vertikale **core-light** (emaneert
   omhoog i.p.v. een losse witte blob). Instrument-eindkap markeert de meting.
2. **De context lost op in de scène** — Doel&planning / Feedback / Bronnen én het
   belasting-cluster zijn **geen cards meer** (`.ws-field` verlaten). Ze hangen
   borderless in de scène met een randloze **scrim** (leesbaarheid zonder kader)
   en een hang-node; hiërarchie planning > feedback > bronnen(-telemetrie).
3. **Rijkere periferie** — dunne gebroken traces, coördinaat-ticks en kleine
   data-ankers die naar de kern wijzen. Puur ruimtelijke cue, **geen verzonnen
   waarden** (geen tekstlabels met fake data).
4. **Premium command-layer** — de pill is een **instrument-strip**: lead-in
   (waaróm: "belastingssignaal verhoogd") + één dominante trigger op een dunne
   command-rail + stille utility-commando's. Koppelt zichtbaar aan het platform.

Plus: load↔kern-connector hertekend (duidelijke origin+destination), lichtkolom
core→platform, en de **locale netjes** (`36,4` / `14,6` i.p.v. `36.4`, lokaal via
`nlNum()` — ratio blijft `1,9×`). Reduced-motion-fix: de centrering van signaal
én command staat nu in de **basis-regel** (overleeft `animation:none`).

Behouden: geen mens, alleen echte data, geen fake readiness/ACWR/RPE/HRV/doelen;
lege staten ontworpen; toon volgt het zwaarste signaal; geen data → geen gauge.

**Gewijzigde bestanden:** `pwa/static/app.js` (rijkere `wsCore`, telemetrie in
`wsRender` Z1, fragmenten ontkaderd, instrument-dock, `nlNum()`-locale),
`pwa/static/design-system.css` (kern-verrijking, scrim/hang, command-instrument,
reduced-motion-centrering), `pwa/static/index.html` + `pwa/static/sw.js`
(asset/cache-bump v109a/v105), `tests/test_app_design_system_v1.py` (test 37 →
refinement-contract). Design-lab: `design-lab/workspace-athlete-core-final.html`.
**Geen backend-bestanden gewijzigd.**

**Teststatus:** 1026 passed — vaste én random volgorde (`python3 -m pytest tests/ -q`).
**Performance (headless Chrome, lokaal):** 0 horizontale overflow op 1440px en
390px (body/doc scrollWidth == viewport); alleen compositor-animaties; geen
nieuwe console-errors (alleen pre-existing favicon-404 + vibrate-warning); geen
library/canvas/WebGL in productie.

**Acceptance-renders:** `review-screenshots/01-workspace-desktop.png` (flagship),
`02-hero-closeup.png` (kern), `08-calm-core.png` (geen signaal → geen gauge),
`04-mobile-sanity.png`, `07-before-after.png` (`8f7a1cb` vs finale),
`05-northstar-comparison.png`, `09-entrance.gif` (echte entree-interactie).

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
layout en `.ws-pane-h`, plus in deze kandidaat: de profiel-bust (v5), losse gauge-label-chip
(`.ws-gaugelbl`) en de scène-typografie-variant van het signaal. Grep-geverifieerd:
0 restanten in app.js/design-system.css.

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

## Presence-layer per bindende CODE-SPEC (deze kandidaat)
- **Gelaagde 3/4-frontale digital-human** (geen zijprofiel, geen masker, geen
  icoon): schaduwmassa → donker-translucent basisvolume → gelaatsvlakken als
  suggestie (crown/glow/wangen/kaak/vorm-schaduw — géén ogen/mond) → topo-banen
  die schouders/borst volgen → scanlines → borstkern met trage puls → dubbele
  rim-light (koel links, cyaan→status rechts) → particles → orbit vóór/achter →
  platform → RING-DOCK op de borst met het dominante cijfer + "1,9× referentie"
  (gauge gekoppeld aan de presence, niet los).
- **Bouwkeuze gedocumenteerd**: contract v2 §5 noemt losse assets, de
  PRESENCE-LAYER-CODE-SPEC (specifieker, bindend) schrijft een gelaagde
  SVG/CSS-opbouw voor — die is gekozen omdat de statuskleur live door kern/
  onderzijde/orbit moet reageren (calm/attention/critical), wat een statisch
  plaatje niet kan. Referentie-exports staan in `design-lab/presence/`.
- Varianten v/m/x; selectie: écht profielveld → `?presence=female|male|neutral`
  (of legacy `?bust=`) → neutraal. Nooit naam-gokken (test-geborgd).

## SPATIAL COCKPIT RESET v3 (deze kandidaat)
**Fase A-audit:** dashboard-makers in `20ba128` waren het wing-kolommengrid,
drie omrande glas-kaarten, de perfecte reuzenring + KPI-dock, de pill-knoppenrij
en de gespiegelde symmetrie. Die presentatiestructuren zijn verwijderd;
data/fetching/routes/acties/focal-ladder bleven onaangeraakt.

**Nieuwe compositie — vijf z-vlakken:**
- **Z0 omgeving**: haze, constellation, verre traces, perspectiefveld dat naar
  de atleet convergeert, vignette.
- **Z1 geometrie**: vier GEBROKEN bogen op verschillende radii/offsets (één
  bewust uit het centrum), gidslijnen, data-nodes (aandacht-node + curve-tip).
- **Z2 athlete**: geschilderde digital-human (zie hieronder) + aura +
  borstkern + platform-ellipsen + compact signaal-INSTRUMENT (partial-ring,
  eerlijke ratio-mapping) op de platformrand; identiteit één keer, klein.
- **Z3 fragmenten**: borderless (mask-fade, geen borders) — aandacht-anker met
  licht-connector naar de boog-node, load-instrument (km + weekstrip +
  cumulatieve curve + REF), plan-fragment, feedback/context-fragment, bronnen
  als lage-contrast telemetrie. Bewust asymmetrisch en op verschillende dieptes.
- **Z4 command**: één dominante coachactie + stille tekst-controls met
  separators (geen pill-rij).

**Presence (reset §8, optie 2):** de mensmassa is een PRE-RENDERED alpha-asset
— digitaal geschilderd in `design-lab/presence-paint*.html` (gestapelde
soft-gradient sculpt-lagen: vormschaduwen, oogkas-schaduw zonder ogen,
neus/jukbeen/kin-modellering, rim-lights) en geëxporteerd als
`pwa/static/presence/presence-{female,male,neutral}.webp` (1160px, ±131KB,
alpha). Live overlays blijven code: scanlines, status-licht, borstkern, aura,
orbit vóór/achter. Gecodeerde SVG-anatomie is volledig verwijderd.
Selectie: profielveld → `?presence`-override → neutraal; nooit naam (test-geborgd).

## Verwijderde superseded presentation-code (deze pass)
`wsBust` (gecodeerde anatomie), de dock-ring/schijf-CSS, `ws-wing`/`ws-panel`-
kolommen, `ws-pane`-glaskaarten, de grote gauge-ring (`ws-gauge-lap*` rond de
figuur), `ws-orbit-back/front`-svg's, `ws-sec`-secties, de oude command-dock-
CSS. Grep-geverifieerd: 0 restanten.

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
