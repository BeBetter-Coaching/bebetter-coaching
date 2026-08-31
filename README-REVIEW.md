# BeBetter — Workspace Closure Review

**Branch:** `feature/app-design-system-athlete-shell-v1` · **commit:** zie COMMIT.txt
**Base:** `main = 39d2453` (SW v97 live) — deze branch is NIET gemerged.

## WORKSPACE FINAL NORTH-STAR MATCH — GLASS LENSES (merge-kandidaat `83794f1` → finale)
> Laatste visual-convergence-pass. **Extern-review-besluit:** de eerdere
> volledig-borderless regel is losgelaten. Vier context-gebieden krijgen nu
> **premium spatial glass lenses** (geen cards), zodat de material richness en
> compositiekracht van de referentie daadwerkelijk benaderd worden. Skills in
> volgorde: artifact-design → ui-ux-pro-max (glass-materiaal) → frontend-design
> (guard: lens ≠ card) → ui-animation → web-design-guidelines. Design-lab eerst,
> daarna production. Geen redesign/avatar/fake data/backend; architectuur locked.

**De glass-lens (`.ws-lens`), geen dashboard-card:** translucent donker glas
(`linear-gradient` navy), 1px subtiele rand die van bovenaf oplicht (`::before`),
`backdrop-filter:blur(9px)`, zachte ambient-diepteschaduw (geen web-card-shadow),
**mask-fade** naar de scène onderaan (zweeft, geen hard kader), en een
**accent-glow alléén bij de connector-node** (`::after`, per-context kleur —
nooit de hele lens getint). Niet-uniforme geometrie (verschillende insets/starts).
Toegepast op de **4 kern-contexten**: Aandacht (links-boven), Belasting (links-
onder, rijkst), Planning (rechts-boven, sterkst rechts), Feedback (rechts-midden).
**Bronnen** blijft een subordinate strip (geen 5e lens); **command** blijft apart.

Het **verbindingsweb termineert nu ín de lens** (node op de lensrand, accent-glow
daar). **Data-gestuurd:** in calm tonen alleen plan+feedback een connector; de
aandacht/belasting-lenzen dragen dan een echte lege-staat (geen fake alert), de
scène blijft gebalanceerd (geen collapse). Core blijft het grootste/helderste
object. Plus de eerder geaccepteerde 2 micro-polishes (sphere-luminantie, radar-
platform) behouden.

**Gewijzigde bestanden:** `pwa/static/app.js` (`wsRender`: `.ws-scrim`→`.ws-lens`
op de 4 contexten, `acc-l`/`acc-r`), `pwa/static/design-system.css` (glass-lens-
primitive + per-lens geometrie), `pwa/static/index.html`+`sw.js` (v114a/v110),
`tests/test_app_design_system_v1.py` (`test_37` bijgewerkt, nieuw `test_41`).
Design-lab bijgewerkt. **Geen backend.**

**Teststatus:** 1030 passed — vast + random. **Performance/a11y:** 0 overflow
1440/390; geen nieuwe console-errors; reduced-motion centreert; lenzen zijn
`aria-hidden` glas met `backdrop-filter:blur(9px)` (performant), tekst-contrast
verbetert boven het donkere glas; op mobiel stapelen de lenzen als volle panelen.

**Echte side-by-side:** `05-reference-comparison.png` (North-Star bóven de finale
Workspace, labels in de tussenruimte — niet over de UI). De vraag "same quality
class?" → de glas-lenzen + web + core + platform + horizon brengen beide in
dezelfde klasse.

---

## WORKSPACE NORTH-STAR CONVERGENCE — ATHLETE CORE (`8d15492` → `83794f1`)
> Convergentie-pass richting de nieuwe referentie-afbeelding (visuele benchmark),
> met de vijf skills in rol (artifact-design → ui-ux-pro-max → frontend-design →
> ui-animation → web-design-guidelines). **Geen redesign, geen avatar, geen fake
> data, architectuur locked, frontend-only.** Doel: het huidige Athlete-Core-
> cockpit zichtbaar dichter bij de kwaliteit/ruimtelijkheid/WAUW van de referentie.

**Vier ingrepen (alles op echte data):**
1. **Verbindingsweb (grootste)** — de kern is nu een hub die **elke aanwezige
   context** voedt: orbit-node → gekleurde lijn → context-anchor, per-context
   accent (aandacht/belasting oranje, plan cyaan, feedback groen). **Data-gestuurd:**
   alleen echte context krijgt een verbinding (calm = alleen plan+feedback, geen
   verzonnen aandacht/belasting-lijnen). Vervangt de twee losse `ws-conn`/`ws-conn2`.
   Lijnen **tekenen zich** van de kern naar buiten op entree (`ws-webdraw`).
2. **Luminous particle-core** — dichter deeltjesveld + iets sterker centraal
   bloom (`ws-field`): een actieve energy-sphere i.p.v. een donkere bol. Blijft
   ontglobed (gebroken shell-fragmenten), rim-silhouet blijft.
3. **Planet-horizon** — verre gekromde rand onderin (`ws-horizon`): kosmische
   z-diepte zoals de referentie. Statisch, reduced-motion-neutraal.
4. **Per-context accent-identiteit** — elk contextfragment krijgt via het web zijn
   eigen statuskleur-node (echte semantiek: aandacht/actief=oranje, calm=cyaan,
   feedback-status=groen/amber).

Behouden: geen mens, echte data, `nlNum`-locale, geen data→geen gauge (calm =
serene kern met alleen plan+feedback-verbinding), reduced-motion-centrering.

**Gewijzigde bestanden:** `pwa/static/app.js` (`wsRender` verbindingsweb +
`ws-horizon`; `wsCore` dichter particle-veld + helderder field), `pwa/static/
design-system.css` (`ws-web`/`ws-webline`/`ws-webnode` + draw-on, `ws-horizon`),
`pwa/static/index.html`+`sw.js` (v112a/v108), `tests/test_app_design_system_v1.py`
(`test_37` bijgewerkt, nieuw `test_40`). Design-lab bijgewerkt. **Geen backend.**

**Teststatus:** 1029 passed — vast + random. **Performance/a11y:** 0 overflow
1440/390; geen nieuwe console-errors (alleen favicon-404 + vibrate); web is
`aria-hidden`, verborgen < 1180px, bevroren onder reduced-motion; reduced-motion
centreert. Alleen transform/opacity/SVG-draw-animaties.

**Reference-comparison (echte side-by-side).** Na de referentie als PNG te hebben
ontvangen: `05-reference-comparison.png` legt de North-Star bóven de huidige
Workspace. Beoordeling (compositie/diepte/premium richness/cockpit-feel): de
kandidaat vangt nu de kern-elementen van de referentie — verbindingsweb, centrale
sphere, orbit-ringen, radar-platform, planet-horizon, per-context accenten,
shell+header. **Twee kleine convergentie-polishes toegepast:** (a) sphere
luminanter (occlusie `.6→.46`, helderder particle-nebula), (b) radar-platform
rijker (fijne tick-ring + heldere kern-glow). **Eén bewuste divergentie
gemarkeerd, niet geforceerd:** de referentie gebruikt gedefinieerde glas-panelen
voor de context; deze kandidaat houdt de eerder gemandateerde **borderless**
richting aan (web + horizon i.p.v. cards). Die keuze is voor externe review.

**Acceptance-renders:** `01-workspace-desktop.png`, `02-hero-closeup.png`,
`08-calm-core.png`, `04-mobile-sanity.png`, `07-before-after.png` (`8d15492` →
finale), `05-reference-comparison.png` (referentie ↔ huidige Workspace),
`09-entrance.gif`.

---

## WORKSPACE FINAL POLISH — ATHLETE CORE (`da1ed78` → `8d15492`)
> Laatste polish-pass op de `da1ed78`-cockpit met de vier design-skills in de
> voorgeschreven rol: `/artifact-design` (art-direction review), **ui-ux-pro-max**
> (diepte/material/dataviz — bevestigde glassmorphism-multilayer + trend-endpoint),
> **frontend-design** (guard tegen generiek: spend boldness in de Core, houd de
> rest stil → de "perfecte globe" is de veilige sci-fi-default en moest gebroken),
> **ui-animation** (entree-emanation), **web-design-guidelines** (a11y-audit).
> Géén reset/avatar/nieuw concept; architectuur locked; frontend/presentation-only.

**Vijf ingrepen (alles op echte data):**
1. **Core: van globe naar gelaagd intelligence-object** — de complete latitude/
   longitude-wireframe (de "veilige globe") is vervangen door **onvolledige,
   asymmetrische shell-fragmenten** + **drie brightness-gescheiden dieptelagen**
   (outer glass rim → intermediate intelligence-field `ws-ifield` met eigen
   rand-highlight → inner active core-light). Datastromen convergeren nu coherent
   (4e flow, opacity-taper). Bol-silhouet blijft via de rim → leest nog als volume.
2. **Load-instrument minder chart** — dag-energie als **smalle glowing pulse-columns**;
   referentie als **thin threshold-beam** (fade-gradient `ws-liref`, geen full-width
   gridline meer); eind-node blijft de origin van de kern-connector.
3. **Command uit het platform (causaal)** — eenmalige entree-sequence: output-node
   pulseert → **light-track tekent zich** naar de command-plug (`ws-trackdraw`/
   `ws-poutpulse`, reduced-motion-safe basis-state).
4. **Eén extra dieptelaag** — horizontale **ambient depth-haze** (`ws-haze`) die
   héél traag drift; de cockpit loopt door voorbij de UI.
5. **A11y-audit** — expliciete `:focus-visible`-ring op command/utility/CTA; geen
   `transition:all`, geen `outline:none` zonder vervanging; decoratieve SVG's
   `aria-hidden`; nieuwe motion volledig onder `prefers-reduced-motion`.

Behouden: geen mens, echte data, `nlNum`-locale, geen data→geen gauge (calm =
serene kern), reduced-motion-centrering in de basis-regel.

**Gewijzigde bestanden:** `pwa/static/app.js` (`wsCore` de-globe + `ws-ifield`,
`wsLoadInstrument` beam/pulse-columns, haze), `pwa/static/design-system.css`
(ifield/shell-rim/f4-flow, li-beam+glow, haze, platform-track-emanation,
focus-visible), `pwa/static/index.html`+`sw.js` (v111a/v107),
`tests/test_app_design_system_v1.py` (`test_37` bijgewerkt, nieuw `test_39`).
Design-lab: `design-lab/workspace-athlete-core-final.html`. **Geen backend.**

**Teststatus:** 1028 passed — vaste én random volgorde. **Performance/a11y:** 0
horizontale overflow op 1440px en 390px; geen nieuwe console-errors (alleen
pre-existing favicon-404 + vibrate-warning); reduced-motion centreert + bevriest
alle nieuwe motion; alleen transform/opacity/SVG-draw-animaties; geen library/
canvas/WebGL.

**Acceptance-renders:** `review-screenshots/01-workspace-desktop.png` (flagship),
`02-hero-closeup.png` (ontglobed kern), `08-calm-core.png`, `04-mobile-sanity.png`,
`07-before-after.png` (`da1ed78` → finale), `05-northstar-comparison.png`,
`09-entrance.gif`.

---

## WORKSPACE FINAL 10% — ATHLETE CORE (`ac62b83` → `da1ed78`)
> Laatste refinement-pass op de `ac62b83`-cockpit. **Géén reset, géén avatar, géén
> nieuw concept:** de abstracte **Athlete Core** + spatial cockpit blijven; de
> architectuur blijft volledig locked (Coach Read / AthleteState / generation /
> `source_versions` / stores / routes / focal-ladder / acties ongemoeid).
> Frontend/presentation-only. Doel: de laatste ~10% kwaliteit — meer wauw,
> futuristische intelligentie en ruimtelijke samenhang zónder de coachfunctie te
> verliezen.

**Vijf ingrepen (alles op echte data, geen fake density):**
1. **Levende intelligence-core** — de glazen sphere is nu een actieve kern: interne
   **datastromen** (`ws-dataflow`/`ws-flow` — comet-segmenten die naar het hart
   convergeren, geen labels/waarden), een **reading-plane** (`ws-readplane`) zodat
   de waarde uit de kern lijkt te komen, bodem-**occlusie** + inner-shell-rim
   (≥3 dieptelagen), een phase-offset **heartbeat** (`cl-*`, serene staten koeler/
   rustiger), rijkere asymmetrische segment-ticks en een eenmalige scan-cue.
2. **Eén load-instrument** — `wsLoadInstrument()` fuseert weekstrip + curve tot één
   cockpit-instrument: dag-energie (pulsen op de baseline) + **cumulatieve trend**
   die daarbovenuit stijgt (VLAK op rustdagen) + referentiedrempel + **eind-node**
   (= origin van de kern-connector). Zelfde bronvelden (`runs`/`km_recent`/
   `km_basis_week`), geen plot-rechthoek, randen faden in de scène.
3. **Command uit het platform** — het platform krijgt een **output-node + light-track**
   (`ws-pout`/`ws-ptrack`, alleen bij een actie) en de command een **plug**
   (`ws-plug`); de coachactie is zichtbaar de uitvoerzijde van de Core, niet een
   losse onderbalk. Hover geeft rail-respons. Actie-semantiek onveranderd.
4. **Ruimtelijke periferie** — een **vloer-perspectief** (`ws-floor`: convergerende
   lijnen + concentrische ringen) onder het platform. Puur diepte, geen fake data.
5. **Rechter context nog iets minder blok** — verschillende horizontale startlijnen +
   diepte/opacity (planning > feedback > bronnen-als-infrastructuur), geen borders.

Behouden: geen mens, alleen echte data, `nlNum()`-locale (`36,4`/`14,6`, ratio
`1,9×`), toon volgt het zwaarste signaal, **geen data → geen gauge** (calm =
serene kern zonder instrument), reduced-motion-centrering in de **basis-regel**.

**Gewijzigde bestanden:** `pwa/static/app.js` (levende `wsCore`, nieuwe
`wsLoadInstrument`, platform-output + vloer + command-plug in `wsRender`),
`pwa/static/design-system.css` (core-datastromen/reading-plane/heartbeat,
load-instrument `li-*`, platform-track, command-plug, vloer-perspectief,
context-stagger, reduced-motion), `pwa/static/index.html` + `pwa/static/sw.js`
(asset/cache-bump v110a/v106), `tests/test_app_design_system_v1.py` (nieuw
`test_38` → finale-10%-contract). Design-lab: `design-lab/workspace-athlete-core-final.html`.
**Geen backend-bestanden gewijzigd.**

**Teststatus:** 1027 passed — vaste én random volgorde (`python3 -m pytest tests/ -q`).
**Performance (headless Chrome, lokaal):** 0 horizontale overflow op 1440px en
390px (body/doc scrollWidth == viewport); alleen compositor-/kleine SVG-animaties;
geen nieuwe console-errors (alleen pre-existing favicon-404 + vibrate-warning);
geen library/canvas/WebGL in productie; reduced-motion centreert correct (read +
command op scène-midden).

**Acceptance-renders:** `review-screenshots/01-workspace-desktop.png` (flagship),
`02-hero-closeup.png` (levende kern), `08-calm-core.png` (geen signaal → geen
gauge), `04-mobile-sanity.png`, `07-before-after.png` (`ac62b83` → finale),
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
