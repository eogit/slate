# How well do the SLATE twins reproduce independent data? Hold-out skill and structural uncertainty in DT2, DT4, DT6 and DT8

*Prepared for: Research scientist (model evaluation) (persona: Research scientist) · 18 November 2026 · SLATE digital-twin orchestrator*

**Question.** Across the SLATE twins, how good is each model at reproducing independent observations, and where is the structural uncertainty largest? Compare the hold-out skill of the forest biomass models at Thetford, of the tree-height models for trees outside woodland in Breckland and the Fens against persistence, of the livestock methane map against the NAEI over Norfolk and Suffolk, and of the peatland model against the UK Peatland Inventory emission factors.

**As understood.** Compare how well four SLATE twins reproduce data not used to fit them: DT4 forest AGB models at Thetford (2018-2024 hold-out against Biomass CCI v7), DT6 tree-height models for trees outside woodland in the Breckland and Fens tiles (against a no-growth persistence forecast), the DT2 livestock CH4 map against NAEI 2020 over Norfolk and Suffolk, and DT8 against the UK Peatland Inventory emission factors. Then identify where structural (model-form) uncertainty is largest.

## Key findings

- DT4 Thetford: hold-out R² against CCI v7 ranges from −0.03 to 0.77 (RMSE 28.8–63.8 Mg ha⁻¹). Skill is best for mixed broadleaves (3-PG R² 0.77) and Corsican pine (0.63–0.66). Letting stand age vary freely raises R² for Scots pine, beech and oak from 0.12–0.30 to 0.51–0.57, so errors in inventory ages matter about as much as the choice of model [R1].
- The two DT4 models disagree most for beech and oak. 3-PG is biased by −29.5 and −28.6 Mg ha⁻¹; the yield curve by −4.7 and +7.0 Mg ha⁻¹. Both models predict steady AGB gains over 2018–2024, but the CCI landscape mean is roughly flat (Corsican pine: 115.7→115.0 Mg ha⁻¹ observed, 112.5→121.9 yield curve) [R1].
- DT6: in Breckland (forecast horizon about 9 years) both models beat persistence (skill 0.50 size_age, 0.47 crown_lue). In the Fens (horizon about 1.4 years) they do not (−0.0002 and −0.35). crown_lue predicts 2.03 m yr⁻¹ of growth against 0.33 m yr⁻¹ observed, the largest model-structure discrepancy found in this comparison [R2].
- DT2 vs NAEI over the Norfolk–Suffolk box: r = 0.39 at 1 km, rising to 0.68 at 20 km, and DT2/NAEI totals = 0.61. The England hold-out gives r = 0.65 at 1 km, 0.97 at 20 km and a ratio of 0.89. East Anglia is therefore one of the regions DT2 reproduces worst [R3, R4].
- DT8 vs UK Peatland Inventory: cropland CO2 is close (27.7 vs 27.1 t CO2 ha⁻¹ yr⁻¹), and so is rewetted-fen CH4 (109.3 vs 111.4 kg ha⁻¹ yr⁻¹). Across the Tier-2 classes CH4 scores NSE = 0.83. However, CH4 for grassland on peat is 6–10× too low (5.8 vs 35.9 and 2.8 vs 29.0 kg ha⁻¹ yr⁻¹), and at 20–30 cm water tables CO2 is 4.6–7.2 t ha⁻¹ yr⁻¹ below the inventory's Eq. 1 [R5].

## Results

### DT4 forest biomass, Thetford: hold-out against CCI v7, 2018–2024 [R1]
The models were fitted on 2005–2017 (11 CCI years) and scored on 2018–2024 pixel-years. Pixels felled or restocked in the hold-out years were excluded, and stand ages come from Forestry England planting years.

| Species group | n (pixel-yr) | Yield curve RMSE / bias / R² | 3-PG RMSE / bias / R² | R² with free age (YC / 3-PG) |
|---|---|---|---|---|
| CP Corsican pine | 13 209 | 37.2 / +1.7 / 0.63 | 35.7 / +2.4 / 0.66 | 0.69 / 0.70 |
| MB mixed broadleaves | 12 964 | 30.2 / +3.9 / 0.75 | 28.8 / −5.2 / 0.77 | 0.78 / 0.81 |
| SP Scots pine | 11 375 | 45.9 / −11.8 / 0.30 | 43.3 / −11.6 / 0.38 | 0.57 / 0.60 |
| DF Douglas fir etc. | 5 201 | 41.5 / −16.2 / 0.59 | 41.2 / −16.1 / 0.60 | 0.68 / 0.67 |
| BE beech | 5 670 | 47.7 / −4.7 / 0.22 | 51.4 / −29.5 / 0.10 | 0.52 / 0.50 |
| LA larches | 2 128 | 63.8 / −38.7 / 0.21 | 52.6 / −30.6 / 0.46 | 0.44 / 0.42 |
| BI birch | 2 198 | 35.6 / −4.6 / 0.45 | 36.5 / −5.5 / 0.42 | 0.51 / 0.47 |
| OK oak | 2 275 | 42.9 / +7.0 / 0.12 | 46.5 / −28.6 / −0.03 | 0.57 / 0.54 |

RMSE and bias are in Mg AGB ha⁻¹. 3-PG scores better for 5 of the 8 groups, and the yield curve for BE, BI and OK (Figure 1).

### DT6 trees outside woodland: forecast of the latest lidar epoch vs persistence [R2]
The test is two-fold: each half of the objects is forecast using a pilot prior learned from the other half.

| Pilot | n | Horizon (median, yr) | Model | RMSE (m) | Bias (m) | Persistence RMSE / bias (m) | Skill | Growth obs → pred (m yr⁻¹) |
|---|---|---|---|---|---|---|---|---|
| Breckland | 544 | 9.0 | size_age | 2.51 | +0.27 | 3.55 / −2.59 | 0.50 | 0.19 → 0.23 |
| Breckland | 544 | 9.0 | crown_lue | 2.60 | +1.17 | 3.55 / −2.59 | 0.47 | 0.19 → 0.37 |
| Fens | 705 | 1.4 | size_age | 2.58 | +0.06 | 2.58 / −0.93 | −0.0002 | 0.33 → 0.76 |
| Fens | 705 | 1.4 | crown_lue | 2.99 | +1.47 | 2.58 / −0.93 | −0.35 | 0.33 → 2.03 |

The skill figures match 1 − (RMSE_model/RMSE_persistence)², which makes this an MSE-based skill score (our arithmetic check).

### DT2 livestock CH4 vs NAEI 2020 SNAP 10 [R3, R4]
- **Norfolk–Suffolk box** [555 000–655 000 E, 215 000–345 000 N]: r = 0.39 (1 km), 0.49 (5 km), 0.61 (10 km), 0.68 (20 km). DT2 total 9 990 t CH4 against NAEI 16 411 t CH4, a ratio of 0.61.
- **Shipped England hold-out** (20 km checkerboard): r = 0.65 (1 km), 0.87 (5 km), 0.93 (10 km), 0.97 (20 km), ratio 0.89. On the calibration squares r is 0.66 at 1 km. The reference allocation without Living England scores r = 0.50 at 1 km (Figure 3).

### DT8 peatland vs UK Peatland Inventory (Evans et al. 2023) [R5]
- **CO2 against water-table depth:** the model slope is 0.419 against 0.492 in the report's Eq. 1. Cropland CO2 is 27.67 vs Tier-2 27.06 t CO2 ha⁻¹ yr⁻¹. The model falls below Eq. 1 by 4.6 t at 20 cm (−1.08 vs +3.49) and by 7.2 t at 30 cm (1.21 vs 8.41).
- **CH4 against Eq. 3:** NSE 0.88 and RMSE 14.3 kg ha⁻¹ yr⁻¹ over 5–70 cm; NSE 0.83 and RMSE 3.6 over 20–70 cm.
- **CH4 against Tier-2 classes:** NSE 0.83, r 0.98, bias −6.6 kg ha⁻¹ yr⁻¹. Class by class (Figure 2): near-natural fen 171.7 vs 143.3; rewetted fen 109.3 vs 111.4; extensive grassland 5.8 vs 35.9; intensive grassland 2.8 vs 29.0; cropland −0.98 vs 1.96.
- **N2O (kg N ha⁻¹ yr⁻¹):** cropland 16.28 vs 16.28; grassland 7.89 vs 7.39.

![Pixel-year R² against ESA Biomass CCI v7 AGB, fitted 2005-2017 with Forestry England inventory ages; harvested pixels excluded [R1].](across-the-slate-twins-how-goo-fig1.png)

*Figure 1. Pixel-year R² against ESA Biomass CCI v7 AGB, fitted 2005-2017 with Forestry England inventory ages; harvested pixels excluded [R1].*

![Annual CH4 (kg CH4 ha-1 yr-1) from the DT8 calibrated baseline at each class's mean water-table depth versus the Tier-2 EF (Evans et al. 2023) [R5].](across-the-slate-twins-how-goo-fig2.png)

*Figure 2. Annual CH4 (kg CH4 ha-1 yr-1) from the DT8 calibrated baseline at each class's mean water-table depth versus the Tier-2 EF (Evans et al. 2023) [R5].*

![Correlation of DT2 livestock CH4 with NAEI agricultural CH4 over a Norfolk-Suffolk box and on the shipped England checkerboard hold-out [R3, R4].](across-the-slate-twins-how-goo-fig3.png)

*Figure 3. Correlation of DT2 livestock CH4 with NAEI agricultural CH4 over a Norfolk-Suffolk box and on the shipped England checkerboard hold-out [R3, R4].*

## What this means

**How good is each twin?** On their own terms the twins rank roughly as follows. DT8 matches the inventory's aggregate emission-factor structure closely, with NSE around 0.83–0.88 for CH4 and cropland CO2 within about 2 %. DT2 reproduces NAEI well at 10–20 km across England (r ≥ 0.93) but only moderately at 1 km. The DT4 models explain about 60–77 % of pixel AGB variance for the main Thetford stands, but much less for minor and broadleaved groups. DT6 has useful multi-year skill in Breckland and none at the short Fens horizon.

These benchmarks differ in how independent they are, so the scores are not directly comparable:
- **DT4 and DT6** are tested against observations, and the time periods or objects used for testing are separate from those used for fitting.
- **DT2** is scored against NAEI. NAEI is itself a modelled allocation of census data, and DT2's allocation settings were tuned to NAEI on the other checkerboard squares.
- **DT8** is compared with inventory regressions and emission factors, not with flux data. Its cropland N2O matches the Tier-2 value to the last digit, which suggests that factor served as a calibration target rather than an independent test.

**Where structural uncertainty is largest.** The question can be answered directly only where a twin runs two model structures on the same data (DT4 and DT6). Elsewhere it shows up as systematic, regime-dependent bias.
1. **DT6 crown_lue in the Fens.** Predicted height growth is about 6× the observed rate (2.03 vs 0.33 m yr⁻¹), against 0.76 m yr⁻¹ from size_age. Over a 1.4-year horizon this error swamps the small real signal. It points to the light-use and climate-driven growth term rather than the height–age prior. Even size_age overpredicts growth in the Fens by more than 2×.
2. **DT4 3-PG for beech and oak.** 3-PG has a bias of about −29 Mg ha⁻¹ and an R² of 0.10 or below, while the yield curve has small biases. Here 3-PG also projects a nearly flat AGB trajectory (oak about 97–98 Mg ha⁻¹) far below the observed CCI mean of about 122–131. For the conifers the two structures agree closely (Douglas fir: RMSE 41.5 vs 41.2), so model form matters less there than inputs do.
3. **DT4 age and saturation rather than model form.** Freeing stand age raises R² by 0.25–0.45 for SP, BE and OK under both models. Error in inventory planting years, or in uneven-aged structure, is a larger source of uncertainty than the yield-curve-vs-3-PG choice. In addition, both models keep accumulating AGB through 2018–2024 while CCI stays flat. This is consistent with the stated CCI saturation at about 150 Mg ha⁻¹, with unrecorded thinning, or with drought years; the agents do not distinguish between these.
4. **DT8 CH4 at intermediate water tables (35–45 cm).** The model is 6–10× below the grassland Tier-2 factors, even though it fits Eq. 3 well. Its single exponential water-table response cannot reproduce the CH4 that grazed or ditched grasslands emit (the inventory classes probably include ditch and hotspot emissions). In the same range, CO2 is several t ha⁻¹ yr⁻¹ lower than Eq. 1. Both gases therefore diverge from the inventory in the 20–45 cm range that matters for partial-rewetting scenarios.
5. **DT2 in East Anglia.** Over Norfolk and Suffolk, r at 1 km is 0.39, against 0.65 for England, and DT2 captures only 61 % of the NAEI total, against 89 % nationally. DT2 notes that NAEI SNAP 10 also contains pigs, poultry, horses and deer. A plausible but untested hypothesis is that the region's large pig and poultry sector explains much of the shortfall and the weak spatial match. Other candidate causes are misallocated cattle in a mainly arable landscape where Living England grassland is a weak predictor, and the box including parts of neighbouring counties and the sea.

## Methods, uncertainty and reproducibility

**Models and data.**
- **DT4 0.2.0** [R1]: yield curves and 3-PG, calibrated pixel by pixel on ESA Biomass CCI v7.0 (100 m; Santoro & Cartus 2026, CEDA catalogue uuid 6429d1aa…). Woodland mask from NFI 2024; ages and species from the Forestry England sub-compartment database; 3-PG climate from HadUK-Grid 1991–2020 with Hargreaves–Samani radiation. Parameters are the shipped calibration (scripts/calibrate_pilots.py). Up to 2000 sample pixels per species group; each pixel is treated as an unthinned even-aged stand.
- **DT6 0.1.0** [R2]: size_age and crown_lue models on the National Trees Outside Woodland map V1 and EA lidar DSM/DTM since 1998, with Jucker et al. (2017) allometry. Hold-out: latest epoch, two-fold pilot prior.
- **DT2** [R3, R4]: June Survey 2020 livestock allocated to 1 km. Configuration chosen by grid search (alpha_other 0, block 10 km, ACN weight 0.5), ranked by r at 1 km on a 20 km checkerboard and scored on the complementary squares. Default site, no NAEI assimilation.
- **DT8 0.1.0** [R5]: PIGNN CO2 and N2O models and a CH4 model with a flood-litter pool, all on calibrated baseline parameters. Reference: Evans et al. (2023), Eq. 1 and Eq. 3, Fig. 3.9 and the Tier-2 emission factors. GWP100 AR6 (CH4 27, N2O 273), although no CO2e figures are used here.

**Calibration vs validation.** Only the DT4 and DT6 results are true out-of-sample tests against observations. The DT2 England hold-out is out-of-sample spatially but not in its reference dataset. Calibration r (0.663) and hold-out r (0.653) are close, so overfitting of the three allocation hyperparameters is small. The DT8 comparison is a consistency check against an empirical synthesis.

**Dominant uncertainties.**
- DT4: stand age (free-age R² gains up to 0.45) and CCI saturation; model structure only for broadleaves.
- DT6: the growth formulation of crown_lue, and the horizon.
- DT2: non-ruminant sources in the reference, and the allocation proxy in arable regions.
- DT8: the shape of the CH4 response at 30–45 cm and the CO2 response at 20–30 cm.

**Reproducibility.** The calls were dt4__validate(landscapes=[thetford]), dt6__validate(pilots=[breckland, fens]), dt2__validate_naei(bbox_bng=[555000,215000,655000,345000]), dt2__calibration_report() and dt8__validate_inventory(site=default). All use shipped parameters and are deterministic.

**Suggested tests.**
- **DT4:** repeat the hold-out with GEDI L4A or EA lidar-derived AGB to separate CCI saturation from model error. Test 3-PG broadleaf parameters (e.g. the allocation and mortality terms for BE and OK) against FE yield class.
- **DT6:** rerun the Fens validation with a longer gap between epochs, or with matched horizons across pilots. Constrain crown_lue's light-use efficiency using the Breckland growth rates.
- **DT2:** subtract the NAEI pig, poultry, horse and deer components, or compare against NAEI cattle and sheep sub-sectors if available, over East Anglia. Compute r on county polygons.
- **DT8:** assimilate chamber or eddy-covariance CH4 from Fenland grassland sites at 30–45 cm water tables with dt8__assimilate_ch4, and test whether ditch CH4 explains the gap to the Tier-2 grassland factors.

## Possible next steps

- Run DT2 with NAEI non-ruminant sources removed over East Anglia to test the pig and poultry hypothesis.
- Run a DT6 horizon-matched validation (Fens vs Breckland) to separate model error from forecast horizon.
- Assimilate DT8 CH4 against grassland-on-peat flux data, using a separate site id so the baseline stays untouched.
- Compare DT4 with an independent lidar or GEDI AGB source to check whether the modelled 2018–2024 trend is real or a CCI saturation artefact.

## Caveats

- The four benchmarks are not equally independent. DT4 and DT6 are tested against observations held out in time or across object folds. DT2 is compared with another model product (NAEI) that its allocation was tuned to on other squares. DT8 is compared with inventory regressions and emission factors, some of which may have been calibration targets (cropland N2O matches exactly).
- CCI v7 saturates at about 150 Mg ha⁻¹ in these forests. Hold-out RMSE therefore partly measures retrieval error and saturation, not model error alone. CCI is the only AGB source used (no GEDI, ICESat-2 or lidar).
- The DT6 skill scores depend strongly on forecast horizon (9 vs 1.4 years). The Fens result says little about long-horizon skill. Trees removed before the TOW map was made are not in the inventory.
- The DT2 'Norfolk and Suffolk' area is a rectangular BNG box, not the county boundaries. NAEI includes non-ruminant livestock that DT2 does not model.
- DT8 runs on one synthetic representative Fenland climate year. It has not been validated against eddy-covariance or chamber fluxes in this analysis.
- Structural uncertainty is directly estimable only where two model structures exist (DT4, DT6). For DT2 and DT8 it is inferred from systematic bias patterns.
- Results are outputs of research-grade models at the versions and parameter state reported in the provenance; learned or assimilated parameters can change between runs, so cite the version and the logged calls.
- Validation statements cover only what the agents report; skill outside the calibration domain (sites, years, management) has not been established here.
- Uncertainty ranges are those the agents compute; structural uncertainty between alternative models is generally not included.

## How this was produced

**Persona.** Research scientist (set by the application).

**Assumptions made before calling the agents**

| Topic | Assumption | Why |
|---|---|---|
| Norfolk and Suffolk extent | Approximated by a BNG box [555000, 215000, 655000, 345000] (EPSG:27700), which includes slivers of Cambridgeshire, Essex and the sea. | DT2 accepts BNG boxes, not county polygons. |
| DT4 hold-out design | Use the agent's shipped hold-out (fit 2005-2017, score 2018-2024, felled/restocked pixels excluded) for all calibrated species groups at Thetford. | This is the independent-data test the agent provides. |
| DT6 hold-out design | Use the shipped forecast of the latest lidar epoch from earlier epochs, against no-growth persistence, for the Breckland and Fens tiles. | Matches the question. |
| DT2 independence | Validate with the default site (no learned factors) so the comparison with NAEI is not contaminated by assimilating NAEI itself. | Keeps calibration and validation apart. |
| DT8 parameter state | Default calibrated parameters (site 'default'), compared with UK Peatland Inventory Tier-2 emission factors. | No learned parameters should be used for an independent comparison. |

**Agent calls**

| # | Agent | Tool | Inputs | Outcome |
|---|---|---|---|---|
| R1 | DT4 forest biomass | `validate` | `{"landscapes": ["thetford"]}` | ok |
| R2 | DT6 trees outside woodland | `validate` | `{"pilots": ["breckland", "fens"]}` | ok |
| R3 | DT2 livestock methane | `validate_naei` | `{"area": {"bbox_bng": [555000, 215000, 655000, 345000]}}` | ok |
| R4 | DT2 livestock methane | `calibration_report` | `{}` | ok |
| R5 | DT8 peatland greenhouse gases | `validate_inventory` | `{}` | ok |

**Data and models (as reported by the agents)**

- model: DT4 forest biomass twin 0.2.0
- observations: ESA Biomass CCI v7.0 (100 m AGB and SD), https://catalogue.ceda.ac.uk/uuid/6429d1aafe1e43b9b414e4a5a7f8b903
- citation: Santoro, M.; Cartus, O. (2026): ESA Biomass Climate Change Initiative (Biomass_cci): Global datasets of forest above-ground biomass for the years 2005-2012 and 2015-2024, v7.0. NERC EDS Centre for Environmental Data Analysis.
- licence: ESA CCI Biomass terms and conditions v2: free and open, citation required
- inventory: National Forest Inventory Woodland GB 2024 and Forestry England Subcompartments, Forestry Commission open data. Contains, or is based on, information supplied by the Forestry Commission; Open Government Licence v3.0.
- parameters: shipped calibration (scripts/calibrate_pilots.py)
- model: DT6 trees-outside-woodland twin 0.1.0
- observations: Environment Agency LIDAR: National LIDAR Programme DSM/DTM and LIDAR Tiles DSM (1998 onwards), environment.data.gov.uk
- inventory: National Trees Outside Woodland Map V1 (Forest Research / Forestry Commission, NCEA, 2025) and Environment Agency LIDAR (National LIDAR Programme and LIDAR Tiles DSM/DTM). Open Government Licence v3.0.
- allometry: Jucker et al. 2017, Allometric equations for integrating remote sensing imagery into forest monitoring programmes, Global Change Biology 23, 177-190
- licence: Open Government Licence v3.0 (TOW map, EA lidar, HadUK-Grid)
- parameters: 
- model: DT8 peatland three-gas twin 0.1.0
- source: CO2 and N2O: eogit/digital_twin peatland_pignn.py (main), peatland_crop_validation.py and peatland_n2o.py (peatland-ghg-twin). CH4: standalone CH4 notebook peatland_ch4_model_with_litter_extension.ipynb, Sections 1-10 and 14 (flood-killed litter pool); no plant-functional-type extension
- drivers: UK Fens regional daily climatology (synthetic seasonal drivers, one representative year)
- parameters: co2: calibrated baseline; ch4: calibrated baseline; n2o: calibrated baseline
- gwp100: IPCC AR6: CH4 27 (non-fossil), N2O 273

**Policy and market context sources for this persona (reviewed November 2026)**

- Scientific Data (2016). Wilkinson et al. The FAIR Guiding Principles for scientific data management and stewardship. Scientific Data 3, 160018. https://doi.org/10.1038/sdata.2016.18
- UK Research and Innovation (2021/2022). UKRI open access policy (peer-reviewed articles submitted from 1 April 2022 open on publication). https://www.ukri.org/manage-your-award/publishing-your-research-findings/making-your-research-publications-open-access/
- UKRI-NERC (2019/2023). NERC data policy (deposit in a NERC data centre; openly available within two years of collection). https://www.ukri.org/who-we-are/nerc/our-policies-and-standards/nerc-data-policy/
- IPCC (2006/2019). 2019 Refinement to the 2006 IPCC Guidelines for National Greenhouse Gas Inventories (Tier 1-3 methods). https://www.ipcc-nggip.iges.or.jp/public/2019rf/
- IPCC (2021). Forster et al. The Earth's energy budget, climate feedbacks and climate sensitivity (IPCC AR6 WG I, Chapter 7: GWP100 values). https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-7/
- CEOS Working Group on Calibration and Validation (ongoing). Land Product Validation subgroup: validation stages 1-4. https://lpvs.gsfc.nasa.gov
- Remote Sensing of Environment (2014). Olofsson et al. Good practices for estimating area and assessing accuracy of land change. Remote Sensing of Environment 148, 42-57. https://doi.org/10.1016/j.rse.2014.02.015
- GCOS / WMO (2022). Essential Climate Variables (GCOS Implementation Plan 2022). https://gcos.wmo.int/en/essential-climate-variables
- Science (2013). Pereira et al. Essential Biodiversity Variables. Science 339, 277-278. https://doi.org/10.1126/science.1229931
- Centre for Digital Built Britain (2018). The Gemini Principles (purpose, trust, function for national digital twins). https://www.cdbb.cam.ac.uk/DFTG/GeminiPrinciples
- PeerJ Computer Science (2016). Smith et al. Software citation principles. PeerJ Computer Science 2, e86. https://doi.org/10.7717/peerj-cs.86
- JCGM / BIPM (2008). Evaluation of measurement data: Guide to the expression of uncertainty in measurement (JCGM 100:2008). https://www.bipm.org/en/doi/10.59161/jcgm100-2008e
- DESNZ / NAEI (annual). UK Greenhouse Gas Inventory / National Atmospheric Emissions Inventory. https://naei.energysecurity.gov.uk/

*Scenario results are model responses to assumed changes, not observations.*
