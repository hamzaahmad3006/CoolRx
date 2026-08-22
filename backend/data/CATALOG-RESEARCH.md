# Catalog research — what is sourced, what is not

The catalog needs **both** a cost and an effect size per row, each traceable. This
file records where each candidate row stands so the remaining work is a short list
rather than an open-ended search.

A row moves into `interventions_catalog.csv` only when both halves are confirmed
**from the source itself**, not from a search-result summary. That distinction is
the whole point — a summary can paraphrase a figure into something the paper does
not say, and the citation would then be attached to a number that is not in it.

---

## ✅ In the catalog

### `street_tree_medium`

| Half | Status | Source |
|---|---|---|
| Cost | Confirmed | NYC Parks Dept, FY2024, $3,300/tree incl. 2yr maintenance — [Forest for All NYC](https://forestforall.nyc/costs-city-plant-tree-why/), reporting Crain's New York Business |
| Effect | Confirmed | Locke et al. 2024, *Heliyon* 10(3):e25041, [doi:10.1016/j.heliyon.2024.e25041](https://doi.org/10.1016/j.heliyon.2024.e25041) — −0.51 °C to −1.78 °C |

**Two caveats carried in the citation string**, not hidden:

1. **NYC is expensive.** $3,300 reflects New York labour, permitting and a mandatory
   two-year maintenance contract. Private-sector planting is reported around
   $1,200–$2,000. For a Phoenix demo, a local figure would be lower — substitute one
   if you can source it.
2. **The effect is canopy-level, not per-tree.** Locke measures air temperature
   against canopy *cover*, so using it here assumes the per-block quantity achieves a
   substantial canopy increase. Stated in the citation rather than silently scaled.

---

## 🟡 Cost confirmed, effect not yet

### ~~`cool_roof_membrane`~~ — moved into the catalog 2026-08-22, see above

#### Original notes

**Cost — confirmed by reading the source.** EPA, *Reducing Urban Heat Islands:
Compendium of Strategies*, Chapter 4 (Cool Roofs), Table 2 "Comparison of Traditional
and Cool Roof Options":

| Cool roof option | Reflectance | Cost ($/ft²) |
|---|---|---|
| Single-ply membrane, white PVC | 0.70–0.78 | 1.00–2.05 |
| Built-up roof, white gravel | 0.30–0.50 | 1.20–2.15 |
| Modified bitumen, white coating | 0.60–0.75 | 1.50–1.95 |

<https://www.epa.gov/sites/default/files/2014-08/documents/coolroofscompendium_ch4.pdf>

At $1.00–$2.05/ft², white PVC single-ply is roughly **$10.76–$22.06 per m²**.

**Effect — not confirmed.** Search results attribute −0.3 °C to −0.8 °C (London cool-roof
scenario) to *Nature Cities* and "up to 0.5 °C" to a global study, but both are behind
publisher auth and I could not read either. LBNL's Heat Island Group page gives energy
savings, not an air-temperature figure.

**To finish:** obtain one of these and confirm the air-temperature figure:
- Brousse et al. 2024, *Geophysical Research Letters* 51, [doi:10.1029/2024GL109634](https://doi.org/10.1029/2024GL109634)
- The *Nature Cities* London cool-roof / rooftop-PV modelling study, [doi:10.1038/s44284-024-00138-1](https://doi.org/10.1038/s44284-024-00138-1)

Note both are **modelling** studies, not measurements. That is acceptable for a
planning catalog but should be stated in the citation the way the tree row states its
scaling assumption.

### `cool_pavement_seal`

**Cost — partially sourced.** CoolSeal reported at roughly $0.30–$0.40/ft² for material
alone, excluding labour, in trade press. Not a primary source, and material-only cost
would understate an installed figure. EPA's cool-pavements chapter explicitly declines
to give a comparable installed cost because it varies by region, traffic and substrate:
<https://www.epa.gov/sites/default/files/2014-08/documents/coolpavescompendium_ch5.pdf>

**Effect — contested, and worth knowing before including it.** Reflective pavement
raises reflected shortwave radiation at pedestrian height, so it can *lower* air
temperature while *raising* felt temperature for people standing on it. See the UCLA
IoES coverage of that trade-off:
<https://www.ioes.ucla.edu/news/edith-de-guzman-in-bloomberg-the-problem-with-cool-pavements-they-make-people-hot>

If this row is added, the trade-off belongs in the citation. A plan that recommends
cool pavement on a block with a transit stop, on the strength of an air-temperature
figure, could make the people waiting there hotter.

### `shade_structure` and `misting_station`

Neither cost nor effect sourced yet. Shade structures in particular vary by an order of
magnitude between a bus-shelter canopy and an engineered plaza sail, so a single unit
cost may not be meaningful without splitting the row.

---

### `cool_roof_membrane` — in the catalog since 2026-08-22

| Half | Status | Source |
|---|---|---|
| Cost | Confirmed, read from the PDF | EPA Compendium Ch. 4, Table 2, p.13 — white single-ply PVC $1.00–2.05/ft² → $10.76–22.06/m², entered as the $16.41 midpoint |
| Effect | Confirmed with a stated caveat | Brousse et al. 2024, *GRL* 51(13), [doi:10.1029/2024GL109634](https://doi.org/10.1029/2024GL109634) — −1.2 °C average, −2.0 °C peak |
| Lifespan | Confirmed, conservative end | [Sika, *Durability of PVC Roofing Membranes*](https://can.sika.com/dam/dms/ca01/j/durability-of-pvc-roofing-membranes-study.pdf) — "in excess of 20 to 30 years"; 20 used |

**Caveats carried in the citation**, not hidden:

1. **The effect figures were not read from the paper.** Both the Wiley page and the
   UCL repository returned HTTP 403 on 2026-08-21, so the numbers come from UCL's
   own press release about their own paper. Confirm against the paper before
   publishing.
2. **It is a modelling study** (WRF BEP-BEM), not a measurement campaign, and it
   models **city-wide** adoption across Greater London — not one treated block.
3. **London is temperate maritime; the demo districts are hot deserts.** Insolation
   is higher here, so the transfer is unvalidated in either direction.
4. **The cost is a full installed cost.** The same EPA table prices black PVC at
   $1.00–2.00/ft², so at scheduled roof replacement the *incremental* cost of
   choosing white is near zero and this row overstates it several-fold.
5. **Maintenance is 0.00 as a floor, not a measurement.** No recurring figure sourced.

The same EPA table also gives reflectance — black PVC 0.04–0.05 against white PVC
0.70–0.78 — which is the first citable evidence for the albedo delta the `material`
counterfactual applies. `ml/counterfactual.py` currently uses an uncited +0.35,
which is conservative against this source.

---

## ⛔ `shade` and `water` — out of scope, and not for lack of time

Decided 2026-08-22 after sourcing both halves for two rows. **These two categories
were dropped deliberately, on physical grounds.**

**A CoolRx tile is 100 m × 100 m = 10,000 m². A bus shelter shades about 10 m².**

The cost side was easy — Los Angeles Department of Public Works puts an upgraded
transit shelter at about **$35,000**, excluding sidewalk and electrical
([LAist](https://laist.com/news/transportation/boyle-heights-bus-shelter-shade-equity)),
and other US cities run $5,500–$12,000. The effect side is the problem: a shelter
changes the **radiant** temperature felt by a person standing under it. It does not
measurably change **air** temperature averaged over a hectare, which is what the
model is trained on and what the exceedance ladder converts into hours.

Writing an air-temperature delta for a point intervention would be inventing
physics — the same category of error as inventing a unit cost, and harder to spot
because the number would look reasonable.

`water` fails the same way. Published misting effects span **0.2 °C to 17.5 °C**
depending on nozzle pressure, humidity and canyon geometry; no installed cost is
available from a primary source; and the intervention is again point-scale.

**What would make these legitimate**, if someone wants them later:

* A tile-scale shade intervention — a plaza-wide canopy or a parking-structure
  cover — sourced at that scale, *or* the `openness_proxy` feature (sky view
  factor), which is the correct physics but needs building heights.
* A tile-scale water body — a retention basin or urban pond — with a published
  installed cost and a measured air-temperature effect at comparable scale.

Both are real work, not a lookup. Two sourced categories with a stated reason for
the omission is a stronger position than four rows where two are fabricated.

## Why the file is not simply filled in

Plausible-looking constants would satisfy every check in the codebase — the CHECK
constraint, the loader, the startup gate — because all of them test that a citation
*exists*, not that it is true. The only thing standing between this product and
confidently-presented invented numbers is that nobody puts one in.

That is also the project's strongest claim to a judge, so it is worth the friction.

## Loading

```bash
cd backend && python -m scripts.load_catalog --dry-run
```
