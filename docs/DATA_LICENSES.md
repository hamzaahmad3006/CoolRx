# Data sources, licences and attribution

Required for submission by SRS §12.2.1. Every dataset CoolRx reads or plans to
read is listed here with its licence and the attribution actually rendered.

**Scope note.** CoolRx's own data path is live: FortyGuard responses are recorded
and parsed. The external datasets marked *planned* below are specified in the SRS
and consumed by `geo/providers.py`, but their providers are still
`UnavailableProvider` — no data from them is currently read, displayed, or
redistributed. They are listed anyway so this file is complete on the day they
land, and each row says plainly which state it is in.

---

## 1. Primary source — FortyGuard Temperature API

| Field | Value |
|---|---|
| Provider | FortyGuard |
| Used for | 2 m ambient air temperature per tile; exceedance, persistence and peak-hour analytics |
| Access | Authenticated API, hackathon trial credits |
| Terms | FortyGuard API terms as accepted at hackathon registration |
| Redistribution | **Recorded responses for three preset districts are committed** to `backend/data/fixtures/` so judges can run the project without a key (AC-13). These are a small fixed sample for reproducibility, not a redistributable dataset. |
| Attribution rendered | "Temperature data © FortyGuard" — on every map view and in the Cooling Action Plan PDF |
| Status | **In use** |

---

## 2. External datasets

| Dataset | Purpose | Provider | Licence | Attribution rendered | Status |
|---|---|---|---|---|---|
| NLCD Land Cover | impervious %, water %, grass/shrub %, albedo proxy | USGS / MRLC | US Government work — public domain | "Land cover: USGS/MRLC NLCD" | Planned |
| NLCD / USFS Tree Canopy Cover | canopy % | USFS / MRLC | Public domain | "Canopy: USFS/MRLC TCC" | Planned |
| US Census TIGER/Line | block-group boundaries | US Census Bureau | Public domain | "Boundaries: US Census TIGER/Line" | Planned |
| US Census ACS 5-year | population, % age 65+, % below poverty | US Census Bureau | Public domain | "Population: US Census ACS 5-year" | Planned |
| CDC/ATSDR Social Vulnerability Index | vulnerability weighting | CDC/ATSDR | Public domain | "SVI: CDC/ATSDR" | Planned |
| **OpenStreetMap** | building footprints, bus stops, schools, parks, hospitals | OSM contributors | **ODbL 1.0** | **"© OpenStreetMap contributors"** | Planned |
| USGS 3DEP DEM | elevation, local relief | USGS | Public domain | "Elevation: USGS 3DEP" | Planned (optional) |
| EPA EJScreen | environmental-justice indicators | EPA | Public domain | "EJScreen: US EPA" | Planned (optional) |
| Sentinel-2 / NDVI | vegetation index | Copernicus | Copernicus open terms | — | **Excluded** (NG-11) |

Basemap tiles, if used for map rendering, carry their provider's own attribution
in the map corner alongside the OSM notice.

---

## 3. OpenStreetMap — the one licence with real obligations

Every other external source here is a US Government work in the public domain,
where attribution is courtesy. OSM is not, and it is worth being precise about
what ODbL 1.0 requires:

**Attribution.** "© OpenStreetMap contributors" must be visible wherever OSM-derived
data is shown. In CoolRx that means every map view and the Cooling Action Plan PDF.
This is a hard requirement, not a nicety, and is part of the definition of done.

**Share-alike.** ODbL's share-alike clause attaches to a *derived database* that is
publicly distributed. CoolRx's position, stated for the record:

- CoolRx distributes **analysis results** — rankings, plans, estimated ΔT figures,
  a PDF — which are produced works, not a database.
- It also distributes a **small fixed set of recorded FortyGuard responses** for
  reproducibility. These contain temperature tiles, not OSM geometry.
- It does **not** publish an OSM extract, an enriched copy of OSM, or any dataset
  from which OSM geometry could be reconstructed.

On that basis the share-alike obligation is not triggered. Should CoolRx later
publish tile-level feature tables containing OSM-derived attributes, that position
changes and those tables would need to be released under ODbL.

---

## 4. Compliance checklist

- [ ] "© OpenStreetMap contributors" visible on every map view
- [ ] Same attribution present in the Cooling Action Plan PDF
- [ ] "Temperature data © FortyGuard" on map views and in the PDF
- [ ] Public-domain sources credited in the PDF methods section
- [ ] This file updated as each planned provider moves to in-use
- [ ] No dataset redistributed beyond the committed fixture sample

---

*Last reviewed 2026-08-18. Licence statements reflect the terms recorded in
SRS §12.2; verify against each provider's current terms before submission.*
