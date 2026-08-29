# Fable Visual North Star v1 — gap-analysis & build

Referentiekader: `fable_visual_north_star_pack` (north-star keyframes vs. de echte
renders van branch-tip `f448490`). Architectuur/truth/routes/state: **locked** —
dit document beschrijft uitsluitend de grafische compositielaag.

---

## Fase 1 — Workspace gap-analysis (references/01 vs current/01)

Het verschil zit niet in kleur of spacing; het zit in **grafische massa, glas,
overlap en achtergrondactiviteit**. Concreet, punt voor punt:

| # | Dimensie | North star | Huidig (f448490) | Gap |
|---|----------|-----------|------------------|-----|
| 1 | Focal point | Portretmassa + gelaagd ringsysteem vult ~55% van de verticale ruimte; het oog landt er onontkoombaar | Dunne 1px-ringen (250px) + klein donker medaillon; naam is groter dan het focal object | Focal system met ±2,5× de massa: 480px meerlaags ringsysteem (dashes, ticks, twee gloeiende bogen, satellietpunt) + 170px medaillon-kern + halo |
| 2 | Centrale massa-opbouw | TWEE gestapelde massa's: portret boven, cirkelvormige signaal-schijf eronder, overlappend | Eén dun ringetje, daaronder een kaal zwevend cijfer | De signaal-schijf terugbrengen als **echte cirkelvormige glasschijf** (±390px) die de ringen overlapt en de golfgrafiek door zich heen laat lopen |
| 3 | Depth / background | Radial haze-velden, orbitale lijnen over het hele canvas, vignette, faint constellation | Eén zachte radial blob; verder vlak navy | 4 achtergrondlagen: tone-haze, cyan-haze, canvas-breed orbit-SVG met constellation-dots, vignette |
| 4 | Glass surfaces | Contextkaarten zijn translucent glas: gradient-rand, top-light, zachte schaduw, elk met eigen interne graphic | Contextvelden zijn tekstkolommen met een 1px-accentlijn — precies §20 "tekst met lijnen" | Glass-pane primitive: translucent verloop, 1px gradient-border, backdrop-blur, inner highlight; aandacht-kaart krijgt de oranje border-glow van de referentie |
| 5 | Number/data hierarchy | Elke kaart draagt een echte graphic: volumegrafiek met gloeiende punten, sparkline, feedback-ring, trainingenlijst | Eén mini-sparkline; feedback is een kale "0" | Grafiek als eersteklas element: grote volumegrafiek (glow-dots, area-verloop), golf door de schijf, feedback-ringbadge, échte trainingenlijst uit `bel.runs` (datum+km bestaan al in de payload) |
| 6 | Overlap / layering | Schijf overlapt de ringen; kaarten zweven over achtergrond-arcs | Nul overlap | Schijf met negatieve marge de ringzone in; ringsysteem loopt achter de zijkolommen door; panes boven het orbit-veld |
| 7 | Compositie | Identiteit (medaillon+naam+chips) linksboven als kop; centrum is puur grafisch; 3 kaarten links, 3 rechts; advies/actiebalk onder-midden | Identiteit staat midden op het canvas; kolommen zijn puur tekst; acties zweven als pillencluster | Naam → koprij; centrum → focal object + schijf; kaarten met gevarieerde hoogte; onderaan een geïntegreerde actiebalk met het dominante signaal + primaire actie |
| 8 | Negatieve ruimte | Gevuld tot de randen, gebalanceerd | Dode donkere pools linksonder/rechtsonder en in de bovenhoeken | Actiebalk + hogere kaarten + achtergrondlagen vullen het frame; ruimte die overblijft is ontworpen (rond het focal object) |
| 9 | Schaalcontrast | Naam ±44px, schijfwaarde ±64px, kaartwaarden 22–28px, labels 11px tracked | +202% op 80px zweeft kaal als grootste element zonder verankerend oppervlak | Dominant cijfer ±64–72px **ín** de schijfcompositie; kaartwaarden 22–26px; één duidelijke trap |
| 10 | Asymmetrie/ritme | Kolommen starten op verschillende hoogte, kaarthoogtes variëren, schijf hangt onder het midden | Symmetrische kolommen met alleen translateY-offsets | Linkerkolom start hoog (aandacht), rechterkolom lager; kaarthoogtes bewust ongelijk; schijf onder het optische midden |
| 11 | Acties | Per-kaart contextuele CTA's ("Schema bekijken", "Alle trainingen") + advies/actiebalk onderaan | Pillencluster midden op het canvas | CTA's per kaart (bestaande routes), primaire actie ("Belasting gezien") in de onderbalk; anav-chips bij de kop zoals de referentie |
| 12 | Status-sfeer | Oranje aandacht stroomt door kaartrand, ringboog en golfgrafiek; cyaan draagt rust/merk | Toon stuurt alleen zwak de ambient | Toon stuurt: ringbogen, schijfrand+golf, aandachtkaart-glow, ambient én de onderbalk |

**Stopregel-check huidige staat:** de huidige Workspace valt onder §20
("tekst met lijnen; enkele glows op een vlak canvas") — hercompositie dus terecht.

**Wat NIET verandert:** payload (`/api/workspace/{key}`), routes, acties,
generation/freshness-gedrag, focal-ladder-semantiek (één eigenaar van het
dominante cijfer), lazy deep-context, geen verzonnen data (geen RPE/ACWR/
feedback-percentage/portret — die bestaan niet in de payload en blijven weg).

## Fase 4-voorbereiding — Dossier gap (references/02 vs current/02)

- Referentie: header-band met identiteit + statuskaarten; memory-stream met
  per-event **mini-grafieken naast elk knooppunt**, era-jaartallen op de as,
  glow rond "vandaag"; evidence rechts als rustige glaskaarten; onderaan een
  rij vervolgkaarten. Huidig: kale spine met tekstregels, evidence als lijst.
- Gap: zelfde glas/diepte-taal als Workspace; spine met uitstralend "vandaag",
  event-dots per domein (vorm/gewicht, één kleursysteem), tijd-as-labels;
  evidence in panes met progressive disclosure. Geen mini-grafieken per event
  verzinnen: alleen echte reeksen (belasting-runs) mogen een grafiek dragen.

## Fase 5-voorbereiding — Home briefing gap (references/03)

- Referentie-familie: briefing = identiteit + één aandachtspunt + één dominant
  signaal + 2–3 supporting facts, zwevend als glasobject; de rest van Home
  treedt terug. Huidig: functioneel juist, maar visueel gewone web-UI.
- Gap: briefing wordt een glas-scène in het klein (ambient veld, orb, dominant
  cijfer met glow, supporting facts als embedded regels, acties geïntegreerd);
  geen mini-Workspace en geen nieuwe data.

---

## Bouwlog (Fase 2–5)

**Workspace (flagship, 5 render-iteraties + artefact-jacht):**
- Compositie: identiteit → koprij (naam + statuschip + freshness links, athlete-nav
  rechts); het centrum is puur grafisch — 460px gelaagd ringveld (4 statische ringen,
  gestippelde accentring, 3 gloeiende bogen in twee tonen met satellietpunt, trage
  80/68/56s-orbits) rond een 198px medaillon-kern met halo; daaronder de 344px
  **signaal-schijf** (translucent glas) die het ringveld overlapt en de echte
  runs-golf (`wsChart`, Catmull-Rom + glow-punten) door zich heen laat lopen.
- Context: 3+4 **glas-panes** (`.ws-pane`: gradient-glas, gradient-toplight,
  backdrop-blur, tone-gloed) met échte graphics: volumegrafiek, trainingenlijst met
  volumebalkjes (datum+km uit `bel.runs`), feedback-ringbadge, en een **Bronnen**-pane
  dat de per-source generation-freshness toont die de response al droeg.
- Acties: per-pane CTA's (Schema/Cockpit, bestaande routes), onderaan een
  geïntegreerde actiebalk met een korte semantische kop
  ("Belasting hoog · +X% t.o.v. referentie") + Belasting gezien / Teampuls / Profiel.
- Achtergrond doet mee: ambient haze (status-gestuurd) + canvas-brede orbit-SVG met
  vaste constellation (`wsOrbits`, decoratief) + vignette.
- Artefact opgelost: de grote box-shadow-gloed op het medaillon rasterde als vierkant
  → alle grote gloed verhuisd naar de ronde `.ws-halo`-gradientlaag.
- Focal-ladder (één eigenaar van het dominante cijfer) ongewijzigd; de aandacht-regel
  herhaalt het percentage niet wanneer de schijf het bezit.

**Dossier (living memory):** zelfde wereld — dc-bg (haze+orbits+vignette), halo-orb
in de kop, nav-chips rechtsboven; de spine is nu een grafisch element (2px verloop
mét glow-kop op "nu", era-markers op de lijn, w1-nodes met dubbele gloed, planning
gestippeld vooruit); het bewijs staat in dezelfde glas-panes, gedempt (0.86) tot
hover/focus. Zwervende `.dc-sec`-borderlijn uit styles.css geneutraliseerd.

**Home-briefing:** de uitgeklapte athlete-state is een glasobject in het klein —
eigen ambient, halo-orb (62px), naam 22px, dominant cijfer 44px met dubbele gloed;
onderbouwing achter progressive disclosure; alle per-signaal Gezien/Later-acties en
routes intact. Oude `.prio-detail`-definitie verwijderd (geen dubbele CSS-laag).

## Self-review tegen de north star (§9-gate, 1440px)

Alle 15 punten doorlopen op de echte render: oog landt op het athlete-centrum (1);
één focal-systeem (2) met echte massa zonder foto (3); achtergrond met haze/orbits/
vignette (4); context als glas met eigen graphics i.p.v. tekstkolommen (5); schijf,
ringen, badges en balkjes breken het rechthoekras (6); schijf overlapt het ringveld,
halo achter het medaillon, panes boven het orbit-veld (7); duidelijke gewichten
+92 → 36.4 → runs → meta (8-9); kolommen met ongelijke hoogtes en offsets (10);
negatieve ruimte rond het focal-systeem is de compositie (11); status stuurt bogen,
schijf, panes, ambient én actiebalk (12); acties in de scène (13). Punt 14-15: de
screenshot staat herkenbaar naast `01_WORKSPACE_NORTH_STAR.png` als dezelfde
productvisie — het abstracte focal-systeem draagt de portretzone-massa.

Eerdere iteraties afgekeurd om: dood zwart medaillon (iter1), onzichtbaar ringveld
(iter1), hoekige area-fill buiten de schijf (iter1-2), verstopte bogen (iter2),
vierkant gloed-artefact (iter3), losgeslagen space-between-kolommen bij weinig
panes (kalme atleet).

## Performance (§26, gemeten)

Zelfde methodiek (headless Chrome, koude start, lokale server), A/B tegen baseline
`f448490` via aparte worktree: FCP baseline 908–924ms vs **nieuw 912–924ms**
(identiek binnen ruis); DCL idem; **0 nieuwe console-errors** (alleen pre-existing
favicon-404 + vibrate-warning); horizontale overflow: **baseline had 90px
scroller-overflow (1250>1160), de nieuwe build 0** (achtergrond-bleed geclipt);
mobiel 390px: 0 overflow. Animaties: 3 trage orbit-rotaties (compositor-transform,
geen runtime-loop), entry-fades ≤400ms, alles uit onder `prefers-reduced-motion`.
Geen library, geen canvas/WebGL, geen extra requests; assets ±12KB groter.

## Nieuwe/gewijzigde primitives

- `wsChart(vals, o)` — gladde datalijn met glow-punten (alleen echte reeksen, leeg
  bij <2 punten; `area:false` voor de schijf).
- `wsOrbits()` — statische decoratieve achtergrond-SVG (orbits + constellation).
- `wsField` → glas-pane met optionele note + contextuele CTA.
- `wsAnchor` → focal-systeem (ringveld + medaillon + halo); naam verhuisd naar de
  scène-kop (test 12 bewust bijgewerkt).
- `wsSignal` → cirkelvormige signaal-schijf (word + waarde + sub + golf).
- Verwijderd: `.ws-field`/embedded-kolommen-CSS, `ws-acts`-pillencluster,
  dubbele `.prio-detail`-laag, oude anchor/signaal-CSS.

## Bewust bijgewerkte design-contracttests

- `test_12`: naam staat in de scène-kop (referentie-compositie), anchor draagt
  orb + initialen.
- `test_37`: "geen dozen" → "diepte uit glas, licht en overlap" (panes translucent
  + blur, schijf rond + negatieve marge, ambient/orbits/vignette aanwezig,
  `.ws-line` blijft randloos). Geen enkele test versoepeld om een regressie te
  maskeren; alle overige 1024 tests ongewijzigd groen.

## Residuals (expliciet bewaard, niet opgelost)

1. Feedback: workoutinhoud onvoldoende zichtbaar vóór feedback geven (bestaand).
2. Feedback: ongeplande/meerdere workouts per dag kunnen stil verdwijnen; ook
   coach-self athlete onderzoeken (bestaand).
3. Teampuls, Feedback en Schema krijgen later ditzelfde visuele systeem.
4. Schema Maintenance v1 (Bijsturen, pace↔HR, Builder bijvullen) — apart.
5. Dossier history-capture activation — aparte beslissing (timeline is nu leeg;
   de living-memory-compositie toont dat eerlijk als ontworpen lege staat).
6. Ongescopete `$(".md-list")` in `openDossier` — bekend, niet geraakt.
7. Nieuw genoteerd (data-level, niet visueel): de belasting-signaaltekst kan ±1%
   afwijken van de canonieke `load_metric`-pct (afronding in de bron-zin, bv.
   "+91%" in de zin vs +92% canoniek); en het bewijspaneel toont soms rauwe
   registry-sleutels als label (bv. `DISTANCE DEVIATION.<uuid>`).

## Final pass (ronde 2) — shell, presence, semantiek, consistentie

Op de externe feedbackronde ("nog te SaaS, te veel hokjes, initialen te arm,
+91 naast +92") is een tweede decisive pass gebouwd:

1. **Shell** — de linker navigatie bewoont nu dezelfde wereld: gradient-materiaal
   met radial licht, gloeiende actieve pill met accent-balk, tracked
   sectielabels, brand-glow, glas-`iconbtn` utilities. Puur CSS op bestaande
   markup; bottomnav/routes byte-gelijk.
2. **Holografische athlete-presence** — `wsFigure()`: een abstracte hardloper
   uit lichtstroken (capsule-strokes langs een skelet, gloed-onderlaag,
   motion-trails, verloop cyaan→statuskleur) stáát op de signaal-schijf; de
   identiteit zit in een compact `ws-idchip`-medaillon als satelliet op het
   ringveld. Niet-herleidbaar, geen foto-afhankelijkheid, veel meer presence
   dan initialen.
3. **Minder dozen** — links twee glas-panes (Aandacht + één samengevoegd
   Belasting-oppervlak met runs-balkjes); rechts één glas-pane (Doel) + een
   randloze embedded cluster (Feedback/Klachten/Bronnen) met accentlijnen:
   7 kaarten → 3 glas + zones, mix van glas en canvas zoals de referentie.
4. **Grafieksemantiek** — de schijfgrafiek is nu het CUMULATIEVE weekvolume
   (som van de echte runs) met de échte referentie (km_basis_week) als
   gestippelde lijn: de curve klimt vóórbij de referentie bij +X% en leest in
   dezelfde richting als het signaal.
5. **Waarde-consistentie** — de belasting-zin wordt overal opgebouwd uit
   dezelfde canonieke `load_metric`-velden (Workspace-aandachtregel, Home-
   briefing) of pct-genormaliseerd uit `delta_pct` (Dossier-spine): nooit meer
   +91% naast +92% op één scherm. Home-briefing-reden gebruikt de korte
   semantische vorm zodat dezelfde zin niet 2× gestapeld staat. Dossier-
   bewijslabels worden opgeschoond van registry-uuid-suffixen (weergave-only).

Gemeten na de pass: FCP 772–804ms (zelfde band als baseline), 0 overflow op
1440/390, geen nieuwe console-errors, 3 orbit-spins als enige doorlopende
animatie (compositor-transform). Tests: 1026 groen, geen testwijzigingen in
deze ronde.

## Closure-pass (Workspace Final Milestone)

Na het goedgekeurde Visual Design Lab-concept is de productie-Workspace op
lab-niveau gebracht — licht en binnen alle locks:

1. **Typografie** — Space Grotesk (3× woff2, lokaal gehost, ±40KB, preload +
   SW-cache) op de shell en de home/workspace/dossier-views; Feedback (FROZEN)
   behoudt bewust de systeemstack.
2. **Stage** — perspectiefvloer + vloergloed, rijkere constellation met enkele
   twinkelende sterren, warmere halo. Statisch/compositor-only; geen canvas.
3. **Hero** — anchor 508px, tweede satelliet, chroma-echo + trage energiepuls
   (4,5s, klein SVG-oppervlak) door de lichtstroken-atleet.
4. **Rim-gauge** — het weekvolume t.o.v. de referentie als (dubbele) ronde om
   de signaal-schijf: gedimde volle ronde = 100% van de referentie, felle boog
   = de overshoot (gemaximeerd op één extra ronde; het ×-label draagt de
   exacte verhouding, bv. "1,9×"). ratio<1 → alleen voortgangsboog; geen data
   → geen gauge. Sweep-animatie bij binnenkomst.
5. **Weekstrip** — de 7 dagen t/m de stand met echte dagtotalen (runs
   gesommeerd per dag); rustdagen eerlijk leeg. Vervangt de runs-balkjes
   (superseded CSS verwijderd).
6. **Kop** — eyebrow "BeBetter · Athlete Command", gradient-naam, actieve
   Workspace-pill naast de bestaande athleteNav-chips.
7. **Cockpit-wrap** — de vleugels kantelen ±6° naar het centrum
   (perspective 1600px); actiebalk-primary als gevulde tone-knop.
8. **Zelfcheck** — backend-diff sinds main = alleen de eerder gereviewde
   additieve `runs`-passthrough; `.ds-skel-panel`-wees verwijderd; overige
   DS-primitives bewust behouden als contract-gepinde gedeelde bibliotheek.

Gemeten: FCP 900–940ms (zelfde band als baseline 908–924ms), 0 overflow op
1440/390, geen nieuwe console-errors; doorlopende animaties = 3 orbit-spins +
2 trage pulsen + enkele twinkles (transform/opacity/kleine SVG-dash), alles
uit onder `prefers-reduced-motion`. 1026 tests groen (vast + random), geen
testwijzigingen in deze pass. Live-dynamiek geverifieerd: een echte nieuwe
open reactie verscheen tijdens de acceptance-run consistent in aandacht,
feedback-badge (amber "1"), actiebalk-meta én bronnen-freshness.

Screen recording: `design-lab/workspace-live-recording.gif` — echte interface
(entree-choreografie → idle → switcher-overlay → wissel naar kalme atleet).

## Tool-/modeladvies (§5)

Geen zwaardere tooling nodig gebleken: CSS + inline SVG haalden het ambitieniveau;
Three.js/GSAP/canvas zouden alleen kosten toevoegen. De render-iteratielus liep via
headless Chrome + CDP (echte pixels, 2× DPR).
