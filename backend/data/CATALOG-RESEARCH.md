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

### `cool_roof_membrane`

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
