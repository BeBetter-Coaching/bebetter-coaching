# BeBetter — Visual Wow / Experience Gate (composition pass)

Branch `feature/app-design-system-athlete-shell-v1` · basis `main = 39d2453` · SW **v99**
Suite **1016 groen**. **Niet gemerged.** Screenshots: `review-screenshots/`.

Deze pass is **puur compositie + immersie + premium interactie**. Geen backend-, truth-,
route- of scopewijziging; geen Feedback/Schema/Teampuls-uitrol.

---

## 1. Eerlijke zelfbeoordeling van de vorige build (vóór deze pass)

Gerenderd op 1440px, dezelfde atleet (Masja Bolk) in Workspace, Dossier en Home-detail:

| Gate-vraag | Oordeel vóór |
|---|---|
| Onmiddellijk focal point? | **Nee** — de blik landde eerst op de felle 13-rijige athlete-rail |
| Domineert de atleet? | **Nee** — de hero was één rechthoek tussen ~29 |
| Eén cockpit? | **Nee** — keyframe 1 heeft één metric-band met haarlijnen; wij hadden 3 dozen |
| Te veel rechthoeken? | **Ja** — ~29 geteld op één Workspace-scherm |
| Rail als database-lijst? | **Ja** — omrande rijen, avatars, chevrons, vol contrast |
| Voldoende diepte? | **Deels** — alles op één vlak |
| Wauw? | **Nee** — "netjes, veel mooier", precies wat niet genoeg is |

Dat was de aanleiding voor deze pass. Onderstaande wijzigingen zijn allemaal een antwoord
op één van die nee's.

## 2. Wat er compositioneel is veranderd

**A. De STAGE — identiteit, primair signaal en kerncijfers op één oppervlak.**
Hero + 3 metric-kaarten + aandacht-aside (7 rechthoeken) zijn nu **één** doorlopend vlak.
De metric-rail zit ín de stage, gescheiden door haarlijnen — één band, geen vier dozen
(keyframe 1). De stage draagt een **ambient glow die de status volgt**: de sfeer van het
scherm vertelt al hoe het met deze atleet gaat vóór je een cijfer leest.

**B. Het FOCAL POINT is een schijf, geen kaart.** Een cirkel leest als focaal object, een
rechthoek als container. 196px disc met concentrische ring, gloed, het enige grote cijfer
(58px) en de echte sparkline uit `belasting.runs[].km`.

**C. Focal-ladder mét eigenaar — het dominante cijfer staat er precies één keer.**
`focal.owner` (`bel-pct` → `bel-km` → `attn` → `rust`) plus `owns(...)` poortjes:
de rail toont *runs* i.p.v. de al-getoonde km, de aandachtkaart laat zijn `+202%`-chip weg,
en de deep-context herhaalt de belasting-observatie niet. **"+202%" ging van 4× naar 2×**
(de schijf + één keer in de canonieke reden-zin, die de *uitleg* is).

**D. De rail treedt terug.** 274px → 228px, randloos, chevrons weg, kleine avatars, en met
een open atleet zakt hij naar `opacity:.52` (hover/focus brengt hem terug). Zonder open
atleet blijft hij volledig zichtbaar — hij is dan de hoofdingang. Zelfde DOM, zelfde
picker, zelfde routing.

**E. Secties grijpen in elkaar.** Twee panelen i.p.v. vier; "Schema & doel" en "Klachten &
context" delen één oppervlak met een haarlijn. Aandachtkaarten zijn halve vormen (2px
toonbalk + gradient die naar transparant loopt), geen dubbele omranding.

**F. Acties zijn onderdeel van de compositie.** Eén "Volgende stap"-band met randloze
tegels en ronde iconen, in plaats van een los blok met vijf omrande knoppen.

**G. Dossier = verhaal, geen database.** Stage met eigen focal (belastingobservatie) en
eigen stat-rail (aandacht / recent veranderd / historie / bronnen). Daaronder één
doorlopende **spine**: Aandacht nu → Recent veranderd → Longitudinale tijdlijn, met
haarlijnen in plaats van drie kaarten. Domeinkaarten (het bewijs) staan nu op de volle
breedte, want hun evidence-waarden braken in een smalle kolom. Bronvolgorde
`build_diagnostic → dc-attn → dc-planning` blijft gerespecteerd.

**H. Home-detail stapt de productwereld binnen.** Dezelfde aandachtkaarten, hetzelfde
oppervlak, DS-pillen voor Gezien/Later en compacte athlete-acties. De volvlakke groene
knop (het meest verzadigde element op het scherm) is een rustige pil geworden: de
aandacht is het luidst, niet de knop.

## 3. Meetbaar resultaat

| | vóór v1 | na DS v1 | na deze pass |
|---|---|---|---|
| Zichtbare containervlakken (Workspace) | ~29 | ~5 panelen | **5 oppervlakken** |
| Athleetnaam | 19px | 30px | **40px** |
| Grootste cijfer | — | 27px | **58px** (schijf) |
| Detailpaneel (1440px) | 596px | 782px | **828px** |
| Rail | 342px, vol contrast | 274px | **228px, opacity .52** |
| `+202%` op het scherm | 3× | 4× | **2×** |
| Elementen > 26px | meerdere | 2 | **1 cijfer + de naam** |

## 4. Vergelijking met de keyframes

| Keyframe-eigenschap | Overgenomen | Hoe |
|---|---|---|
| Donker premium canvas + radiale gloed | ✅ | `.ds-stage::before` ambient glow op `--tone` |
| Athlete-hero, naam zeer groot | ✅ | `clamp(26px,3.1vw,40px)` + medaillon met dubbele ring |
| Metric-rij als één band met haarlijnen | ✅ | `.ds-stage-rail` + `.ds-stat+.ds-stat::before` |
| Eén dominant gloeiend getal | ✅ | `.ds-focal-disc` 196px, 58px cijfer, tekstgloed |
| Sparkline onder het cijfer | ✅ | echte `runs_recent`-reeks, inline SVG |
| Onzichtbare containergrenzen, diepte uit gradiënt | ✅ | haarlijnen + `--ds-well` + 3-staps elevatie |
| Amber = aandacht, cyaan = normaal, groen = ok | ✅ | één statusdialect (`dsTone`) |
| **Atletenportret** | ❌ bewust | we hébben geen foto's; een verzonnen portret is verzonnen data → medaillon |
| **ACWR 2.57 / RPE 5.14 / freshness 68%** | ❌ bewust | die metrics bestaan niet in onze data |
| Sci-fi HUD-ringen, hexrasters, team-netwerkgraaf | ❌ bewust | gimmick / buiten scope |

## 5. Performance (gemeten, headless Chrome 1440px)

| Meting | Waarde |
|---|---|
| Workspace-shell (`/api/workspace/{key}`) | **11 ms** |
| DOMContentLoaded | **75 ms** |
| `design-system.css` laadtijd | **5 ms** |
| Actieve animaties na render | **3** (CSS-entree, geen runtime-loop) |
| WebGL / canvas / animatielibrary | **geen** |
| Deep context (`/api/cockpit`) | lazy, blokkeert de shell niet |

`prefers-reduced-motion` schakelt stage-, focal-, kaart- en rail-transitions uit.

## 6. Journeys

- **A Home → athlete** — Home-detail draagt dezelfde aandachtkaart en oppervlakken; Workspace
  opent met dezelfde aanleiding, nu als dominante schijf. ✅
- **B Workspace 5–10 s** — shell in 11 ms; naam, toon, schijf en rail staan er vóór de zware refresh. ✅
- **C Dossier** — stage + spine (aandacht → veranderingen → tijdlijn) leest als geheugen. ✅
- **D Navigatie** — één stage, één nav (`athleteNav`), één statusdialect over drie views. ✅
- **E Refresh** — `dsFresh` (cyaan / pulserend grijs / gedimd) + ongewijzigde generation-banner. ✅

## 7. Contracten (ongewijzigd, zonder één testregel aan te passen)

35 top-level `function NAME(`; `openModuleFromNav(b.dataset.openView)` exact 4×; `applyRoute`
onaangeraakt; `dcRender`-bronvolgorde + copy-contract; `.anav-chip{` in `styles.css`;
`athleteNav` enige nav (`dsShell` is opgeruimd — één shell-primitive); generation/
`source_versions`-ordening; geen nieuwe store/cache/route/truth.

## 8. Residuals

Teampuls/Feedback/Schema draaien nog op eigen module-CSS (klaar voor dezelfde primitives);
`.md-split` bestaat nog 5× hand-geschreven; de ongescopete `$(".md-list")` in `openDossier`
(audit-bevinding, buiten scope); de twee Feedback-punten (workoutinhoud, verdwijnende
ongeplande workouts) blijven staan voor een eigen correctness-audit.
