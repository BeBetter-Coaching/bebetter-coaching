# BeBetter — App-wide Design System + Athlete Shell v1

Branch `feature/app-design-system-athlete-shell-v1` · basis `main = 39d2453` · SW **v98**
Suite **1016 groen** (989 → +27), 3× flake-vrij. **Niet gemerged.**

---

## 1. UX-diagnose (analyse-first, verplicht)

De diagnose is uitgevoerd met 6 parallelle auditors over `app.js` (4865 r), `styles.css` (1371 r)
en `index.html`, gevolgd door een adversariële verificatieronde per bevinding (elke bevinding
opnieuw tegen de echte bestanden gehouden, met opdracht te wéérleggen).
**43 bevindingen bevestigd, 5 weerlegd.** De kern:

### 1.1 Er is een palet, geen systeem
`styles.css:1-5` bevat **12 `:root`-variabelen** (11 kleuren + 1 radius). Daaronder improviseert
alles: **113 hardcoded hex-waarden** (56 verschillende), **95 losse `rgba()`**, **147
`border-radius`-declaraties waarvan er 12 de token gebruiken**, **26 verschillende `font-size`-
waarden**, 32 spacing-stappen, 26 eenmalige `box-shadow`s. Drie tokens (`--ok`, `--red`,
`--ok-bg`) worden gebruikt maar **nooit gedefinieerd**.

### 1.2 Dezelfde betekenis, verschillende kleur per module
"klaar/ok" is cyaan op Home én Feedback, mint in Home-prio-detail, bosgroen in Schema-verlengen
en WhatsApp-groen in Dossier. "aandacht" heeft **8 amber-tinten**, "kritiek" **5 roden**. Er zijn
**11 onderling incompatibele ernst-vocabulaires** (`actie/aandacht`, `hoog/let_op`,
`ok/warn/bad`, `green/amber/red`, `gemist/half/gedaan`, …).

### 1.3 Het lijst/split-screen-gevoel is letterlijk de structuur
- **Vijf** met de hand geschreven twee-koloms grids (`.md-split`, `.fb-split`, `.sb-grid`,
  `.sb-cfg`, `.sb-plan-grid`), elk met eigen sticky/scroll-gedrag.
- `.md-detail` heeft **geen enkele container-styling**: de énige regel in de hele stylesheet die
  `.md-detail` noemt is `.md-detail .btn.back{display:none}`. Feedback's rechterpaneel krijgt wél
  echte pane-chrome — precies daarom leest Feedback als een app en Workspace/Dossier als een document.
- **Root cause, gemeten:** Workspace en Dossier misten de brede-canvas-override die Atleten,
  Feedback en Schema wél hebben. Op een 1440px-scherm was de view 960px, de lijst 342px →
  **detailpaneel 596px**, met 230px ongebruikte ruimte ernaast.

### 1.4 Drie athlete-identiteiten, nul hergebruik
`dcRender`, `wsRender` en `prioItem` renderen dezelfde atleet met drie verschillende families.
Workspace overschreef de groep-slot met een statische ondertitel (groep dus onzichtbaar); de
status-badge bestond alleen in Dossier; de generation-banner alleen in Workspace. Atleten/Dossier/
Workspace zijn drie kopieën van hetzelfde `.md-split`-skelet die **dezelfde `/api/atleten`
driemaal** ophalen. De atleetnaam was **19px** — kleiner dan de meeste sectiekoppen elders.

### 1.5 Zes loading-talen, negen empty-states, vier error-talen
Elke module vond zijn eigen staat opnieuw uit. Slechts 2 van ~12 error-paden bieden een retry.

### 1.6 Wat goed is en behouden moet blijven
Het `.ic`-icoonsysteem, `tabular-nums`-discipline, systematische `env(safe-area-inset-*)`, de
signature-curve `cubic-bezier(.2,.7,.3,1)`, de layout-stabiele skeletons, de `.hero`-radial-glow,
`[hidden]{display:none!important}`, en vooral: **`athleteNav()`, `renderPicker()` en
`activeAthleteKey()` zijn al gedeelde componenten** — het systeem moet erop voortbouwen, niet ernaast.

---

## 2. Analyse van de meegestuurde keyframes (art direction, geen blauwdruk)

| Wat ik overneem | Wat ik bewust NIET overneem |
|---|---|
| Donker premium canvas met radiale glow-diepte | Fotorealistische athlete-portretten — we hebben geen atletenfoto's; een verzonnen foto is verzonnen data |
| Diep blauw/cyaan basis + subtiele neonaccenten | Sci-fi HUD-ringen, hexagon-rasters, "scanning"-effecten |
| Amber/oranje uitsluitend voor aandacht/hoge belasting | De verzonnen metrics (ACWR 2.57, RPE 5.14, freshness 68%) — die bestaan niet in onze data |
| Grote athlete-hero: de atleet is de actieve wereld | Het volledige "Command Center"-dashboard in één keer |
| Metric strip met grote getallen + sparklines | Zware 3D/WebGL-visualisaties (performance-contract) |
| Kaartgrid met duidelijke hiërarchie i.p.v. lijstjes | Team-netwerkgraaf (Teampuls valt buiten deze slice) |
| Uitgesproken statuschips en rustige sectielabels | Letterlijke kleurwaarden/typografie — we blijven in het bestaande merk |

**Vertaling van "athlete-dominant" zonder fictieve data:** een **medaillon** — initialen in een
cirkel met twee concentrische, toon-gekleurde ringen. Dat geeft het gewicht en de focus van het
keyframe-portret, met echte data (de initialen die we hebben).

**Sparklines zijn echt:** ze tekenen `metrics.runs_recent` uit exact dezelfde captured belasting-
stand die het getal voedt. Bij < 2 punten tekenen we niets in plaats van een gladde nepcurve.

---

## 3. Design principles

1. **Eén betekenis, één kleur.** Statussemantiek loopt door één functie (`dsTone`) en zes
   toonklassen. Componenten lezen uitsluitend `var(--tone/-bg/-bd)` — een module kán geen eigen
   dialect meer introduceren.
2. **De atleet is de wereld, navigatie ondersteunt.** In een athlete-view domineert de identiteit;
   de lijst wordt een rustige rail.
3. **Toon eerst het getal, dan de uitleg.** Wat speelt → hoe erg → waarom → wat nu.
4. **Progressive disclosure boven volledigheid.** Samenvatting eerst, bewijs op verzoek.
5. **Verzin nooit data om een visual te vullen.** Geen ring zonder percentage, geen lijn zonder reeks,
   geen delta zonder referentie.
6. **Motion verduidelijkt of bestaat niet.** ≤ 340ms, alleen CSS, uit bij `prefers-reduced-motion`.
7. **Presentatie raakt waarheid niet aan.** Geen nieuwe store, engine, cache of truth-pad.

---

## 4. Tokens & primitives

**Foundations** (`pwa/static/design-system.css`): surface-ladder (canvas/s1/s2/s3/well),
tekst-hiërarchie (3 niveaus), accent, **6 statusparen** (tone/bg/bd), spacing-schaal (4px-basis,
8 stappen), type-schaal (7 stappen), radii (5), elevatie (3), motion (3 duren + 1 easing).
Van 12 losse variabelen → **een volledige, benoemde schaal**.

**Statusdialect:** `is-calm · is-attention · is-critical · is-success · is-stale · is-unknown`.
`dsTone()` mapt élk server-vocabulaire (`actie/aandacht`, `hoog/let_op`, `green/amber/red`,
`fresh/stale/unknown`) hierop.

**Primitives (12, elk exact één definitie):** `dsShell` (Athlete Shell) · `dsAttnCard` ·
`dsMetric` · `dsPanel` · `dsChip` · `dsFresh` · `dsKv` · `dsStream` · `dsAction` · `dsEmpty` ·
`dsSpark` · `dsRing`, plus `dsWorstTone`, `dsSkeletonBlock`, `dsFoldToggle`.

---

## 5. Before / after UX-architectuur

```
BEFORE                                  AFTER
──────                                  ─────
12 kleurtokens                          volledige token-schaal (surface/type/space/radius/elev/motion)
11 ernst-vocabulaires in CSS            1 statusdialect (6 toonklassen) + 1 mapper (dsTone)
3 athlete-koppen (copy-paste)           1 Athlete Shell (Workspace + Dossier + Home-detail)
3 belasting-%-presentaties              1 (bouwt door op de al gelockte load_metric)
6 loading-talen / 9 empty-states        ds-skel / dsEmpty (tone-aware)
3 refresh-talen                         dsFresh (fresh|stale|unknown) + bestaande gen-banner
detailpaneel 596px, view 960px          detailpaneel 782px, view tot 1320px
athleetnaam 19px                        athleetnaam 30px (desktop) / 20px (mobiel)
kale <ul> label/waarde-dumps            dsKv / dsStream / ds-disc (progressive disclosure)
```

**Opgeruimd (niet alleen toegevoegd):** `wsChip()` verwijderd; **6 superseded `ws-*`-CSS-blokken**
en **30 dode `dc-*`-selectors** verwijderd; de `dc-head`-wrapper weg. Netto is `styles.css`
kleiner geworden terwijl de UI rijker werd.

---

## 6. Gekozen slice & scope-gate

**GO**, met één correctie op het auditadvies. De risk-lens adviseerde eerst een test-ontkoppelings-PR
("NO-GO voor een naïeve refactor"). Dat advies gold een refactor die functies hernoemt/verplaatst.
Deze slice doet dat bewust níét: **markup en CSS veranderen, contracten niet.** Concreet gehonoreerd:
35 functies blijven top-level `function NAME(`; `openModuleFromNav(b.dataset.openView)` blijft exact
4×; `applyRoute` is niet aangeraakt (byte-window had 39 tekens speling); de `dcRender`-ordening
(diagnostic → `dc-attn` → `dc-planning`) en het copy-contract blijven staan; `.anav-chip{` blijft in
`styles.css`. **Geen enkele testregel is aangepast om de build groen te krijgen.**

**Gebouwd:** Design System foundations · Athlete Shell · Workspace · Dossier · Home attention/detail.
**Niet gebouwd (klaar om te volgen):** Teampuls, Feedback, Schema — die kunnen dezelfde primitives
overnemen zonder herontwerp.

---

## 7. Performance

| Meting | Waarde |
|---|---|
| Workspace-shell (`/api/workspace/{key}`) | **5 ms** (doel < 2 s) |
| Deep context (`/api/cockpit`) | 3651 ms — **lazy**, blokkeert de shell niet |
| Nieuwe runtime-afhankelijkheden | geen (alleen CSS + inline SVG) |
| Extra asset | `design-system.css`, in de SW-shell → offline + gecachet |

Fast-read, background-refresh, generation-coherentie en het niet-blokkeren op FS/AI zijn ongewijzigd
(afgedekt door tests 17/21 en de bestaande 989).

---

## 8. Product journeys

| | Journey | Uitkomst |
|---|---|---|
| A | Home → athlete | PASS — Home-detail gebruikt dezelfde attention-card; Workspace opent met dezelfde aanleiding, nu dominant in beeld |
| B | Workspace binnen 5–10 s | PASS — shell (5 ms) toont naam + toon + aandachtkaart + metric strip vóór de zware refresh |
| C | Dossier | PASS — Athlete Shell + attention-cards + stream/kv i.p.v. kale master-detail |
| D | Navigatie Workspace ↔ Dossier ↔ Home-detail | PASS — één shell, één nav (`athleteNav`), één statusdialect |
| E | Refresh STALE → refreshing → fresh | PASS — één `dsFresh`-component (cyaan / pulserend grijs / gedimd) + ongewijzigde generation-banner; geen verspringen |

---

## 9. Residuals & roadmap

**Residuals (bewust niet in deze slice):**
- Teampuls, Feedback en Schema draaien nog op hun eigen module-CSS — klaar voor uitrol op dezelfde primitives.
- `.md-split` bestaat nog 5× hand-geschreven; alleen de athlete-views zijn nu opgewaardeerd.
- Latente bug uit de audit (niet in scope, wel genoteerd): `openDossier`/`toonDossierLijstView`
  gebruiken een **ongescopete** `$(".md-list")` (eerste match in het document) waar de siblings wél
  scopen — DOM-volgorde-afhankelijk en onbedekt door tests.
- De audit-testadviezen (5 count-guards, 13 byte-window slices met 39–242 tekens speling) blijven
  staan als toekomstige, puur test-zijdige opruiming.

**Bewaard uit de vorige ronde (Feedback):** workoutinhoud onvoldoende zichtbaar tijdens Feedback;
ongeplande/meerdere workouts per dag lijken soms stil te verdwijnen — **niet half opgelost hier**;
vraagt een eigen correctness-audit.

---

## 10. Definition of Done

Aantoonbaar één gedeelde taal die Workspace, Dossier en Home-detail samenbrengt (tests 12–16),
zonder core-truth-wijziging (tests 17–22, 26–27), zonder performance-regressie (§7), en uitrolbaar
naar Teampuls/Feedback/Schema zonder herontwerp — de primitives zijn view-agnostisch en de
statussemantiek dekt hun vocabulaires (`ok/warn/bad`, `green/amber/red`) al.
