# BeBetter — Athlete Canvas Visual Recomposition

Branch `feature/app-design-system-athlete-shell-v1` · basis `main = 39d2453` · SW **v100**
Suite **1026 groen** (1016 → +10), 3× flake-vrij. **Niet gemerged.**
Screenshots: `review-screenshots/`.

Deze ronde laat de oude frontend-**compositie** los. De functionele onderlaag is niet
aangeraakt: geen truth-, Coach-Read-Model-, generation-, route-, store- of backendwijziging.
De enige serverkant-regel die deze ronde raakte was er al (`runs` in de workspace-payload,
uit dezelfde captured stand) — er is **niets** aan de backend toegevoegd.

---

## 1. Wat er compositioneel is losgelaten

| Legacy | Nu |
|---|---|
| `md-split` rail + detailpaneel in Workspace | **Athlete canvas** zonder lijst; wisselen via compacte switcher |
| Hero + metric-strip + panelen + action row | **Scène**: centrale anchor, dominant signaal, ruimtelijke contextzones |
| Kaarten met randen | Drie niveaus: canvas → (alleen anchor/signaal) → **embedded** velden zonder rand |
| Dossier als master/detail met kaarten | **Living memory**: één tijd-spine, vandaag sterkst, historie zwakker, planning gestippeld vooruit |
| Home-detail als uitgeklapt paneel | **Athlete briefing**: identiteit, reden, dominant cijfer, onderbouwing progressief |
| `dsShell`/`dsStage`/`dsFocal`/`dsStat` | verwijderd — vervangen, niet overlaagd |

## 2. Workspace — de flagship

- **Athlete anchor**: concentrische statusringen (SVG) + medaillon met initialen. Geen verzonnen
  portret; de ringen dragen echte status (toon = zwaarste open signaal).
- **Eén dominant signaal** eronder, zonder plaat: alleen een lichtlijn koppelt het aan de anchor.
  Focal-ladder mét eigenaar (`bel-pct → bel-km → attn → rust`) + `owns()`-poortjes, zodat het
  dominante cijfer **exact één keer** groot op het scherm staat.
- **Ruimtelijke context**: links Aandacht nu + Belasting/trend, rechts Doel & planning,
  Feedback en Klachten & context — als embedded velden met een tone-accentlijn, geen dozen.
- **Ambient veld** (`.ws-amb`) dat de status volgt: de sfeer vertelt al hoe het staat.
- **Acties** als compacte pill-cluster in de centrale kolom, niet als action row onderaan.
- **Bewuste asymmetrie**: kolommen .92 / 1.42 / 1, links zakt 26px, rechts stijgt 22px,
  zijkolommen vertikaal gecentreerd zodat negatieve ruimte zich rond de compositie verdeelt.

**Zichtbare containerrechthoeken op het Workspace-scherm: 0** (alleen pill-acties).

## 3. Dossier — living memory

Eén doorlopende spine met tijd als ruimtelijk principe:
`Aandacht nu · vandaag` (weight 1, vol contrast) → `Recent veranderd` (2) →
`Longitudinale historie` (2→4, verder terug = zachter en kleiner) →
`Doelen & planning` (gestippelde, open knooppunten: vóór ons).
Het **bewijs** (domeinkaarten, bronnen) staat naast het verhaal op 82% opacity en komt
naar voren bij hover/focus. De rail valt weg zodra een atleet open is.

## 4. Home — athlete briefing

Bij openen van een atleet: orb + naam + **reden voor aandacht** + het dominante cijfer,
daarna de signalen met hun eigen Gezien/Later, met de onderbouwing achter progressive
disclosure (open voor het dominante signaal). Afgesloten met de route naar Workspace/Dossier.
Alle bestaande optimistic-write-acties zijn intact.

## 5. Acceptance-gate Workspace (streng, 1440px, naast het keyframe)

| # | Vraag | Oordeel |
|---|---|---|
| 1 | Oog op athlete/context i.p.v. navigatie? | ✅ orb + naam + signaal vormen de as |
| 2 | Eén sterk focal point? | ✅ `+202%`, één keer, gloeiend |
| 3 | Data ruimtelijk verbonden? | ✅ lichtlijn + accentlijnen om de as |
| 4 | Duidelijk minder boxes? | ✅ 0 containers (was ~29) |
| 5 | Dieper dan gewone SaaS? | ✅ ambient veld, ringen, gloed |
| 6 | Athlete-context dominant? | ✅ |
| 7 | Asymmetrie bewust? | ✅ kolomverhouding + verticale offsets |
| 8 | Negatieve ruimte beter? | ✅ verdeeld i.p.v. onderaan gepoeld |
| 9 | Hiërarchie direct duidelijk? | ✅ orb → naam → signaal → context |
| 10 | High-end performance software? | ✅ |

## 6. Vergelijking met de keyframes

**Overgenomen:** donker canvas met radiale diepte · athlete-first centrale compositie ·
concentrische ringen om de atleet · één groot gloeiend cijfer · echte sparkline ·
amber = aandacht / cyaan = normaal / groen = ok · nauwelijks zichtbare containergrenzen ·
asymmetrie en negatieve ruimte · rust ondanks dichtheid.

**Bewust niet:** atletenportret (we hebben geen foto's — het medaillon vervangt het) ·
ACWR/RPE/freshness/herstel% (bestaan niet in onze data) · team-netwerkgraaf (buiten scope) ·
sci-fi HUD-decoratie zonder databetekenis.

## 7. Performance (headless Chrome, 1440px)

| Meting | Waarde |
|---|---|
| Workspace-shell (`/api/workspace/{key}`) | **8 ms** |
| First Contentful Paint | **80 ms** |
| DOMContentLoaded | **77 ms** |
| styles.css / design-system.css / app.js | 6 / 6 / 9 ms |
| Actieve animaties na render | 8 (CSS-entree, geen runtime-loop) |
| WebGL / canvas / animatielibrary | **geen** |
| Runtime errors | **geen** |
| Horizontale overflow (mobiel + desktop) | **geen** |

Fast-read, background refresh, lazy deep-context en het generation-contract
(`generation_id` + 3 `source_versions`) zijn ongewijzigd.

## 8. Tests

**1026 groen** (+10). Nieuw: athlete-switch zonder lijst · deep-link wacht op roster ·
Dossier-rail valt weg (met het Cohesion-contract intact) · alle acties bereikbaar ·
focal-ladder met één eigenaar · spine maakt tijd ruimtelijk · Home-briefing ≠ uitgeklapt
paneel · freshness/generation zichtbaar · geen legacy-resten · canvas is geen dozenraster.
Geen testregel aangepast om een regressie te maskeren; drie design-contracttests zijn
herschreven omdat het contract zelf veranderde (stage → canvas/spine).

## 9. Residuals

- Teampuls, Feedback en Schema draaien nog op hun eigen module-CSS (roadmap).
- `.md-split` bestaat nog voor Atleten/Dossier/Feedback/Schema.
- Ongescopete `$(".md-list")` in `openDossier` (audit-bevinding, buiten scope).
- **Feedback (blijft staan):** workoutinhoud onvoldoende zichtbaar; ongeplande/meerdere
  workouts per dag kunnen soms uit Feedback verdwijnen — eigen correctness-audit.
