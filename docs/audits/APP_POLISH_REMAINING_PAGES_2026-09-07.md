# App Polish + Remaining Pages Alignment — 7 september 2026

**Basis:** `7cd278f` · **Aard:** finite presentatie-mijlpaal, geen nieuwe logica.
Geen echte writes; alle verificatie read-only.

Doel: een coach die door BeBetter klikt kan niet meer zien welke pagina's "later"
zijn aangebouwd. Alles hieronder is presentatie, copy of layout — geen truth, geen
routes, geen cache, geen Feedback-architectuur.

---

## 1. Inventaris van de visuele systemen

Drie families in gebruik, in volgorde van rijpheid:

| Familie | Pagina's | Kenmerken |
|---|---|---|
| **Design System v1** (`design-system.css`, `.ds-view`) | Workspace, Dossier, Feedback | eigen page-head met titel + doelregel, `--ds-*` tokens, panelen met eigen grid, tone-chips |
| **Home-familie** (`styles.css`) | Home, Schema-workbench | hero/segmentbalk, `.sec-label`-secties, `.rij-kaart`, `.listcard`, skeletons |
| **Legacy-appbar** | Atleten, Intake, Strippenkaart, Schema-lijst, Documenten, Races, Schema-verloop, Teampuls, Administratie, Meer | kale `<header class="appbar"><h1>…` zonder doelregel |

Gedeelde bouwstenen die al overal werkten en dus hergebruikt zijn (géén nieuw
design system): `.rij-kaart`, `.listcard`, `.panel`, `.sec-label`, `.btn`-familie
(`primary` / neutraal / `ghost` / `danger-ghost`), `.mrow-tag`, `.anav-chip`,
`.leeg`, `skeleton()`, `nlDatum`/`nlAantal`, `athleteNav()`.

## 2. Gevonden legacy-drift

1. **Paginakop.** Tien modules openden met alleen een titel; de vijf kernpagina's met
   titel + één regel die zegt waar de pagina voor is. Dit was de luidste "oude
   pagina"-aanwijzing.
2. **Rauwe ISO-datums** in coach-facing kaarten: Races (`2026-09-20`), Schema-verloop
   (`laatste 2026-09-11`, `zichtbaar t/m 2026-09-20`), Intake (`2026-09-01T11:53`),
   Teampuls-stand, Dossier-klachtkaart (`· 2026-08-18`), Home-prioriteit (einddatum,
   zichtbaar t/m), Atleten (notities, documenten), Strippenkaart (laatst afgeboekt),
   Administratie (KOR-projectiedatum), Dossier-stream.
3. **Twee foutfamilies.** 12× de rustige `.leeg` (icoon + zin) tegenover 14×
   `<p class="muted center">Geen verbinding.</p>` — geen icoon, geen uitleg, geen weg
   terug. Dat leest als een doodlopende pagina.
4. **Lege waarden als data.** `Klacht: onbekend — actief — - · 2026-08-18` (Tymo) en
   `Recente week ? km · basis ? km/wk · gevoel — vs — · RPE — vs —` (Teampuls-
   onderbouwing). Een kaal streepje leest als een meting.
5. **Meervoud/copy:** `race(s)`, `training(en)`, `afboeking(en)`, en het ambigue
   `laatste 11 sep` (laatste wát?).
6. **`athleteNav` had twee ritmes:** rechts-inline in de kopregel op Schema
   (`margin:0 0 0 auto`), links onder de identiteit op Profiel, Workspace en Dossier.
7. **Zelfde bestemming, twee labels:** de zijbalk zei "Praktijk & account", de pagina
   zelf "Meer".
8. **Meer/Praktijk** zette account-acties visueel gelijk aan praktijkmodules.
9. **Documenten** gaf de uitkomst als kale statustekst, inclusief de rauwe serverfout
   (`"Mislukt: " + await res.text()`).

## 3. Doeltaal (afgeleid uit de sterkste bestaande oppervlakken)

* **Paginakop** — `<h1>` + `.pagesub` (één regel, wat de pagina doet).
* **Sectietitel** — `.sec-label`.
* **Kaarten** — `.rij-kaart` (data), `.panel` (formulier), `.listcard` (navigatie).
* **Knoppen** — één `.btn.primary` per oppervlak → `.btn` → `.btn.ghost` →
  `.btn.danger-ghost` voor destructief (altijd met `confirm`).
* **Chips** — `.anav-chip` navigeert, `.mrow-tag`/`.sb-chip`/`.puls-tag` zeggen status.
* **Datum** — `nlDatum` → `3 sep`; met tijd `nlDatumTijd` → `1 sep · 11:53`;
  afstand-in-tijd `nlDagenTot` → `over 13 dagen`. Feedback houdt bewust zijn eigen
  `Vandaag`/`Gisteren`-labels: daar is de relatieve dag de betekenis.
* **Leeg** — `leegState(icoon, zin, subzin)`: kalm, waar, zegt wat er wél kan.
* **Fout** — `foutState(box, opnieuw)`: zelfde vorm, expliciete retry, en de eerlijke
  toevoeging "er is niets gewijzigd".
* **Onbekend** — nooit `-`, `?` of `—` als waarde; benoemen dat het onbekend is.

## 4. Geïmplementeerde polish-items (12)

| # | Item | Bestanden |
|---|---|---|
| 1 | Gedeelde paginakop (titel + doelregel) op alle 10 legacy-modules | `index.html`, `styles.css` |
| 2 | Datum-primitieven `nlDatumTijd` / `nlDagenTot` / `nlWaarde` + normalisatie op elke resterende coach-facing datum | `app.js` |
| 3 | Eén familie lege/fout-staten (`leegState` / `foutState`) — 14 doodlopende meldingen vervangen, elk met retry | `app.js`, `styles.css` |
| 4 | Races: leesbare datum + afstand-in-dagen, statusregel, gelabelde composer, actie volgt de staat (`Plaats wens` / `Wens bijwerken`) | `app.js`, `styles.css` |
| 5 | Schema-verloop: `laatste training 11 sep`, `zichtbaar t/m 20 sep`, meervoud via `nlAantal`, kalender-icoon i.p.v. klok | `app.js` |
| 6 | Intake: `1 sep · 11:53`, statuschip `nieuw`, orphan-chip `kandidaat` / `niet gekoppeld`, kalme lege inbox | `app.js` |
| 7 | Dossier-presentatie: nette datum in klacht-, planafwijking- en bronvervalkaarten; een leeg bronveld wordt "geen omschrijving vastgelegd" i.p.v. een kaal streepje | `dossier_cockpit.py` |
| 8 | `athleteNav` overal hetzelfde ritme: eigen regel onder de identiteit, links uitgelijnd | `styles.css` |
| 9 | Meer/Praktijk: paginatitel gelijk aan het zijbalklabel, account-blok achter een zichtbare scheiding | `index.html`, `styles.css` |
| 10 | Copy-sweep: Nederlandse meervouden, geen `?`/`—`-placeholders meer als data (`pulsMaten`), Documenten-uitkomst als staat i.p.v. rauwe servertekst | `app.js`, `styles.css` |
| 11 | Feedback responsive: tussenstap 1101–1359px (2 kolommen, context eronder) + meer ruimte voor het midden op 1360–1499px | `design-system.css` |
| 12 | Dossier responsive: JS en CSS delen één drempel (1280) en de layout schakelt nu écht om bij een resize over die grens | `app.js`, `design-system.css` |

## 5. Responsive-bevindingen

**Gemeten in de browser (read-only, 1150×900 en 1400×900):**

| Situatie | Vóór | Ná |
|---|---|---|
| Feedback @1150px | 3 kolommen, case-detail **~231px** | 2 kolommen, case-detail **524px** |
| Feedback @1400px | 3 kolommen, case-detail **418px** | 3 kolommen, case-detail **476px** |
| `athleteNav` in `.d-head` | rechts-inline naast de naam | eigen regel, links uitgelijnd (`eigenRegel: true`) |

**Dossier.** De CSS-collapse stond op ≤1180px terwijl de JS het scene-tableau pas vanaf
1280px rendert — die regel kon dus nooit vuren. Beide staan nu op 1280 via één gedeelde
`dcIsNarrow()`. De resize-handler tekende alleen connectoren; sleepte je het venster over
de drempel, dan bleef het verkeerde tableau staan. Nu her-rendert hij met dezelfde
`dcRender` (geen tweede layout-pad, geen nieuwe fetch).

**Residu (niet opgelost, bewust):** onder ~1500px blijft het Feedback-middenpaneel onder
500px. Verder verruimen vraagt een herontwerp van de rechter contextkolom — dat is geen
polish. Niet visueel geverifieerd op een fysiek toestel; zie de checklist hieronder.

### Checklist voor een echte-apparaat-ronde
- iPhone portrait: Races-kaart (wanneer-blok naast de naam), Intake-statuschip,
  `athleteNav` op Schema en Profiel, Meer-scheiding.
- iPad portrait (768px) en landscape (1024px): Feedback-stapeling, Dossier-stack.
- Laptop 1280–1440px: Feedback 3-koloms band, Dossier scene ↔ stack bij resize.
- Donker/licht en `prefers-reduced-motion`: `.leeg.fout`-icoonkleur, `.docs-ok/-err`.

## 6. Architectuurbevindingen — gedocumenteerd, NIET geïmplementeerd

1. **Schema-chip landt altijd op "Nieuw".** Er bestaat al een veilige deep-link
   (`openSchemaMode(key, "verlengen")`), maar de atleet-pagina's WETEN niet of er een
   actief plan is: `/api/schema/atleten` levert geen plan-status en de schema-roster
   draagt geen einddatum. De chip laten mikken op Verlengen vraagt dus een nieuw
   datapad — buiten deze mijlpaal. Verzachtend: `sbRenderConfig` toont de
   `Nieuw | Verlengen`-schakelaar, dus de coach kan in één klik wisselen. **Blijft staan.**
2. **`sbStartConfig`-laadschil mist die schakelaar** (hij verschijnt pas als de config
   geladen is). Cosmetisch, één regel, maar het raakt de schema-workbench-flow;
   bewust buiten de 12 gehouden.
3. **Teampuls en Home-Monitoring delen al `pulsItem`/`svItem`** — er is geen visuele
   drift tussen de standalone route en het Home-segment. Geen actie nodig.
4. **`heeft_thread` in het queue-item wordt nergens gebruikt** (client leest het niet).
   Dode payload-veld; opruimen raakt de queue-payload en dus de Feedback-lock.

## 7. Bestanden gewijzigd

`pwa/static/app.js`, `pwa/static/index.html`, `pwa/static/styles.css`,
`pwa/static/design-system.css`, `pwa/static/sw.js`, `pwa/dossier_cockpit.py`,
plus tests en deze notitie.

## 8. Locks die aantoonbaar intact blijven

AthleteState-truth, `coach_read.load_metric`, begrensde caches, `is_executed_workout`,
run-deviation-logica, Feedback-queue (inclusie, ordering, `_CAT_RANK`), MetricAuthority,
Feedback safety/copy, klacht-ranking, UNKNOWN-semantiek, Home-suppressie/handled,
Workspace signaal→actie-mapping, routegrammatica en de volledige view-set,
`activeAthleteKey`, de `nieuw:`-intake-guard, Dossier-deeplinks, Schema draft/publish,
FS-write-paden (`/api/races/wens`, admin-PIN) en de geheugengrenzen.

Afgedwongen door `tests/test_app_polish_remaining_pages.py::TestLocks`, inclusief een
diff-toets die aantoont dat de wijziging in `dossier_cockpit.py` geen selectie,
ordening of afleiding raakt.
