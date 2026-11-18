# East Anglia nature-based carbon: how Fen peat rewetting, Thetford Corsican pine and Fenland hedgerow trees compare on abatement, uncertainty and validation

*Prepared for: Green finance portfolio manager (carbon credits, possible tokenisation) (persona: Green finance manager (carbon and nature credits, tokenisation)) · 18 November 2026 · SLATE digital-twin orchestrator*

**Question.** We are building a portfolio of UK nature-based carbon projects that we may later tokenise. For East Anglia, compare the expected abatement per hectare and its uncertainty for a Peatland Code rewetting project on Fenland cropland, a new Corsican pine woodland near Thetford of the kind registered under the Woodland Carbon Code, and hedgerow agroforestry on Fenland farms. How well validated is each model, and which project type is the most robust basis for credits?

**As understood.** For three East Anglian project types, compare model-estimated abatement per hectare and its uncertainty: (1) Peatland Code-style rewetting of drained Fenland cropland, (2) new Corsican pine woodland near Thetford of the kind registered under the Woodland Carbon Code (WCC), and (3) hedgerow and agroforestry trees on Fenland farms. Then say how well validated each model is and which type gives the most robust basis for credits.

## Key findings

- Peat rewetting gives by far the most abatement per hectare. Drained Fen cropland emits about 37 t CO2e/ha/yr (winter wheat 37.3, potato 37.0, AR6 GWP100) [R1, R2]. Rewetted reed fen emits 0.9–2.5 t CO2e/ha/yr at a water table 0.05–0.2 m below the surface [R3]. That is roughly 34–36 t CO2e/ha/yr of avoided emissions (derived), which starts in year one.
- New Corsican pine at Thetford removes an average of 16.5–20.2 t CO2/ha/yr over 50 years with no thinning, depending on the growth model. The 90 % range is very wide, roughly 3–33 t/ha/yr (derived from 50-year totals of −1,010 t/ha [−1,653 to −145] and −824 t/ha [−1,310 to −154]) [R5]. With thinning and felling the average drops to 10.9–11.9 t/ha/yr [R6]. Removals start slowly: under 5 t/ha/yr in the first 6 to 7 years.
- Hedgerow and agroforestry trees on Fenland farms add little per hectare. At an assumed 100 trees/ha they remove about 0.3–1.0 t CO2/ha/yr over 50 years (derived from 1,000-tree runs: hedgerow −182 to −481 t, agroforestry −142 to −373 t in total) [R8, R9]. They also do nothing about the roughly 37 t CO2e/ha/yr the drained peat underneath keeps emitting.
- Validation strength differs by type. The woodland model was tested on later years it was not fitted to (2018–2024), against satellite biomass maps (ESA Biomass CCI v7): it explains about 63–66 % of the variation (R² 0.63–0.66), with an error of about 36–37 Mg/ha (RMSE) and a small overestimate on average (bias +1.7 to +2.4 Mg/ha) [R7]. The peat model matches the UK Peatland Inventory's standard (Tier-2) emission factors closely, for example rewetted-fen CH4 109 vs 111 kg/ha/yr [R4], but this is a check against the inventory, not against independent flux measurements. The Fenland tree model does no better than assuming the trees stop growing (skill −0.0002 and −0.35) and predicts 2.3–6 times the height growth seen in lidar [R10].
- On this evidence, peat rewetting is the most robust basis for credits: it has the largest abatement, a tight model range and agreement with the inventory. Its main risks are whether the target water table is actually reached and kept, and the lack of an uncertainty ensemble in the model. Thetford pine comes second: its validation is independent but its spread is wide. Fenland hedgerow and agroforestry trees are not a robust credit basis on these models.

## Results

**Units and signs.** Positive flux means emission. Abatement for peat is avoided emissions (drained baseline minus the rewetted project). For trees it is the net CO2 taken up (removals) by new planting on land with no trees. All figures are model estimates for one representative hectare, not issued units.

### 1. Peatland rewetting of Fenland cropland (DT8)
| | Net GHG, t CO2e/ha/yr (AR6) | of which CO2 / CH4 / N2O |
|---|---|---|
| Drained winter wheat, water table about 0.66 m (baseline) [R1] | **37.3** | 33.1 / −0.01 / 4.3 |
| Drained potato (baseline) [R2] | **37.0** | 29.8 / −0.03 / 7.2 |
| Reed, water table 0.05 m [R3] | 2.5 | −2.0 / 4.3 / 0.3 |
| Reed, water table 0.10 m [R3] | 1.7 | −2.3 / 3.6 / 0.4 |
| Reed, water table 0.20 m (model's net-GHG optimum) [R3] | 0.9 | −1.1 / 1.0 / 0.9 |
| Reed, water table 0.0 m (flooded) [R3] | 4.5 | −0.7 / 5.1 / 0.2 |

Derived abatement is **35.6 t CO2e/ha/yr** (winter wheat baseline, water table 0.10 m), with a range of **34.4–36.5** across baseline crop and water-table target. Over 50 years that is about 1,780 t CO2e/ha (simple arithmetic, assuming the water table holds). DT8 gives a single deterministic run for one representative year, so there is no ensemble 90 % range.

**Validation against the UK Peatland Inventory (Evans et al. 2023)** [R4]:
- Cropland CO2: 27.7 vs Tier-2 27.1 t/ha/yr.
- Rewetted-fen CH4: 109 vs 111 kg/ha/yr.
- Cropland N2O: 16.28 vs 16.28 kg N/ha/yr. The exact match suggests calibration to this value.
- CH4 against the inventory's water-table equation: r = 0.98, Nash–Sutcliffe efficiency (NSE) 0.88.
- The model's CO2 response to water table is shallower than the inventory's (slope 0.42 vs 0.49).
- The model is more optimistic than the inventory equation at intermediate water tables: at 0.20 m it gives −1.1 t CO2/ha/yr against +3.5. At 0.05 m it gives −2.0 against −3.9.

Applying the inventory equations at 0.20 m would give a project net of about 6.3 t CO2e/ha/yr (derived), against the model's 0.9. At 0.10 m the two agree: about 1.7 t CO2e/ha/yr either way (derived).

### 2. New Corsican pine woodland at Thetford (DT4, planted 2026, 50 years)
| Regime / model | Mean net flux, t CO2/ha/yr | 50-year total, t CO2/ha (mean [90 % range]) |
|---|---|---|
| No intervention, yield curve [R5] | −20.2 | −1,010 [−1,653 to −145] |
| No intervention, 3-PG [R5] | −16.5 | −824 [−1,310 to −154] |
| Thin and fell, yield curve [R6] | −10.9 | −547 [−894 to −79] |
| Thin and fell, 3-PG [R6] | −11.9 | −597 [−981 to −105] |

The productivity calibrated to satellite biomass is very uncertain: yield class 14 ± 11.1 and 3-PG fertility rating 0.55 ± 0.42 [R5]. For a 100 ha project, the 50-year totals are −101 kt (yield curve) and −82 kt (3-PG) with no intervention [R5].

**Hold-out validation (fitted 2005–2017, scored 2018–2024, 13,209 pixel-years)** [R7]:

| Model | RMSE | Bias | R² |
|---|---|---|---|
| Yield curve | 37.2 Mg/ha | +1.7 | 0.63 |
| 3-PG | 35.7 Mg/ha | +2.4 | 0.66 |

Both models drift upwards over the hold-out years: about 122 Mg/ha modelled in 2024 against 115 observed. The satellite product (CCI) saturates at about 150 Mg/ha.

### 3. Hedgerow and agroforestry trees on Fenland farms (DT6, Fens pilot tile, 1,000 trees, 2025–2075)
| Kind / model | 50-year total, t CO2 per 1,000 trees (mean [90 % range]) | Derived per ha/yr at 100 trees/ha |
|---|---|---|
| Hedgerow, size-age [R8] | −182 [−353 to −76] | −0.36 |
| Hedgerow, crown LUE [R8] | −481 [−644 to −335] | −0.96 |
| Agroforestry, size-age [R9] | −142 [−275 to −60] | −0.28 |
| Agroforestry, crown LUE [R9] | −373 [−501 to −261] | −0.75 |

Establishment survival is 0.85 for hedgerow and 0.90 for agroforestry; about 72–76 % of trees are alive after 40 years [R8, R9].

**Validation** [R10]:
- Fens: skill against assuming no growth is −0.0002 (size-age) and −0.35 (crown LUE). Predicted height growth is 0.76 and 2.03 m/yr against 0.325 m/yr observed. The median forecast horizon is only 1.4 years.
- Breckland, the nearby tile: skill is better at 0.50 and 0.47.

Figure 1 compares all three types.

![Peat: drained-cropland baseline (WW/potato) minus rewetted reed at 0.05–0.2 m water table, AR6 GWP100 [R1–R3]. Woodland: new Corsican pine at Thetford, 50-year mean net CO2 removal, low/high = annualised 90 % ensemble range [R5, R6]. Hedgerow/agroforestry: Fens pilot, 1,000 trees scaled to 100 trees/ha (derived), 90 % range [R8, R9]. Model estimates, not credits.](we-are-building-a-portfolio-of-fig1.png)

*Figure 1. Peat: drained-cropland baseline (WW/potato) minus rewetted reed at 0.05–0.2 m water table, AR6 GWP100 [R1–R3]. Woodland: new Corsican pine at Thetford, 50-year mean net CO2 removal, low/high = annualised 90 % ensemble range [R5, R6]. Hedgerow/agroforestry: Fens pilot, 1,000 trees scaled to 100 trees/ha (derived), 90 % range [R8, R9]. Model estimates, not credits.*

## What this means

**Scale.**
- Per hectare, rewetting drained Fen cropland avoids about twice the CO2e that unthinned Corsican pine removes on average over 50 years.
- It avoids about three times what a commercially thinned stand removes.
- It avoids roughly 35–120 times what Fenland hedgerow or agroforestry trees remove at 100 trees/ha (derived from R1–R9).
- The peat benefit is immediate. Woodland removals build up over two decades and level off at about 28 t CO2/ha/yr in the yield-curve run [R5].

**Uncertainty and what drives it.**
- **Peat.** The result rests mainly on one variable: the water table actually achieved. Between 0.0 and 0.2 m the model's project emissions vary from 0.9 to 4.5 t CO2e/ha/yr [R3]. That barely changes abatement against a baseline of about 37. The bigger risk is partial rewetting. At 0.3 m the project net rises to 3.5, and at 0.5 m to 16.4 t CO2e/ha/yr [R3]. The inventory equations are also less favourable than the model at about 0.2 m [R4].
- **Woodland.** The 90 % range spans almost an order of magnitude. This reflects how poorly the satellite biomass data constrain productivity on Breckland sands (yield class 14 ± 11) [R5]. Thinning roughly halves the in-forest removals; 34–41 t C/ha moves into wood products [R6].
- **Hedgerow and agroforestry.** The two tree-growth models differ by a factor of about 2.6, and neither beats a no-growth forecast in the Fens [R10]. The higher (crown LUE) estimate is probably an overestimate.

**Validation ranking.**
1. Thetford woodland has the most independent validation: a temporal hold-out against satellite biomass across more than 13,000 pixel-years. Skill is moderate (R² about 0.65), and new planting is extrapolated from mature-stand calibration.
2. The peat model reproduces the national inventory's emission factors closely, but that test is against another model-based synthesis rather than site flux data. It also uses synthetic climate drivers for one representative year.
3. The Fenland tree model is effectively not validated.

**Which is most robust?** Rewetting comes out as the most robust basis, because:
- it has the largest effect;
- its signal is large relative to uncertainty in the water-table response;
- it agrees with the inventory factors that the Peatland Code itself builds on;
- its key performance variable (water table) can be monitored directly with dipwells or Earth-observation data.

Woodland is a credible second. Its permanence and growth risk are better understood, but its volume is very uncertain, so conservative crediting and a buffer would be needed. Fenland hedgerow and agroforestry trees are small, poorly constrained and sit on soils that are still emitting.

## Credit and market relevance

**These are model estimates, not creditable units.** Under the Peatland Code and the WCC, claimable quantities come from the code's own methods:
- Peatland Code: emission-factor tables by condition category and a code risk buffer.
- WCC: the Carbon Calculation Spreadsheet, a baseline deduction, a leakage check and a buffer.

Units are listed on the UK Land Carbon Registry as Pending Issuance Units. They become verified units only after independent verification. The figures here could support due diligence and monitoring, reporting and verification (MRV), but they do not replace a code calculation.

**Integrity points the results speak to**

*Baseline*
- Peat: the drained-cropland baseline (about 37 t CO2e/ha/yr) matches inventory cropland factors, which makes it defensible [R1, R4].
- Woodland: the runs start from bare land and omit soil carbon and baseline vegetation. Code baselines would reduce the net figure.

*Permanence and reversal*
- Peat: reversal happens through re-drainage or drought. Re-drying to 0.5 m brings emissions back to about 16 t CO2e/ha/yr [R3], so water-level control and neighbouring drainage are the main risks.
- Woodland: risks are fire, wind and pests on Breckland. The runs used no stochastic disturbance, so this is not quantified here. Thinning cuts mean in-forest removals by about 40–45 % [R5, R6].

*Leakage*
- Taking high-value Fen cropland out of production is a material leakage and food-production issue. These models do not quantify it.

*Uncertainty*
- Peat: no ensemble range (deterministic run). Treat 34–36 t CO2e/ha/yr as a sensitivity range, not a confidence interval.
- Woodland: 90 % ranges are very wide, so issuance planned on the mean is exposed to overestimation.
- Fenland trees: unvalidated.

*MRV*
- Peat: the measurable state variable (water table) maps directly onto the abatement, a strong basis for digital MRV (dMRV).
- Woodland: satellite biomass (CCI) saturates at about 150 Mg/ha. Mature-stand stock would need lidar or plot data to verify.
- Fenland trees: lidar heights exist, but the model does not yet track them.

**Tokenisation**
- What the twin can provide: repeatable, provenance-logged model runs and observation-based state variables (water table, satellite and lidar biomass) that a token's metadata could reference.
- What it cannot establish: legal title, carbon rights, registry status or regulatory classification.
- Any token should link one-to-one to a specific UK Land Carbon Registry unit (PIU or verified). It must not be issued against these model estimates, and retirement must be mirrored on the registry to avoid double counting.
- Whether a tokenised structure falls within FCA regulation (cryptoasset regime from 25 October 2027) depends on how it is structured and needs legal review.

**Claims and disclosure**
- Peat rewetting is avoided emissions (an emission reduction). Woodland is a removal. Buyers' claims under the VCMI Claims Code and the forthcoming UK guidance (spring 2027) differ by type, so the portfolio should be labelled accordingly.
- WCC is under ICVCM Core Carbon Principles assessment but not approved.
- Disclose model uncertainty under TNFD and ISSB/UK SRS so that any claims meet the FCA anti-greenwashing rule.

This is not investment advice, and no prices or returns are implied.

## Possible next steps

- Run Peatland Code emission-factor calculations for candidate Fen sites, and use DT8 with site dipwell or Earth-observation water-table series (run_ch4_drivers) to stress-test drought years and partial rewetting.
- For Thetford woodland, run DT4 with stochastic disturbance (fire, wind) and compare with the WCC Carbon Calculation Spreadsheet to size a conservative volume and buffer.
- Treat Fenland hedgerow and agroforestry as a co-benefit rather than a credit asset unless new lidar or field heights (assimilate_heights) show the growth model can be constrained.

## Caveats

- Peat results (DT8) come from one representative year with synthetic Fenland climate drivers and give no ensemble uncertainty. The N2O term in the rewetting runs uses the winter wheat fertiliser regime. The model is more optimistic than the inventory CO2 equation at water tables of 0.2–0.4 m [R4].
- Woodland results (DT4) assume new planting on bare land with the Thetford calibration from mature stands. They exclude soil carbon change, baseline vegetation and the substitution and decay of wood products after harvest, and use no stochastic disturbance. The satellite calibration data (CCI v7) saturate at about 150 Mg/ha.
- Hedgerow and agroforestry results (DT6) are per tree. The per-hectare figures assume 100 trees/ha, which is my design assumption. The Fens tile stands in for all Fenland farms, and the model has no forecast skill there [R10]. Soil and peat emissions under the trees are not included.
- The Peatland Code and WCC carbon calculations, buffers, additionality tests and leakage were not run. The model figures are not credit volumes.
- Food-production loss, water and biodiversity effects were not modelled by these agents.
- Model estimates are not carbon or nature credits: units are issued only after validation and verification under a code (e.g. Woodland Carbon Code, Peatland Code), which applies its own baseline, buffer and methods.
- This report is not investment, legal or regulatory advice. The regulatory status of a tokenised credit depends on its structure and should be confirmed with the FCA's rules and legal counsel.
- Market and regulatory context reflects the position in November 2026.

## How this was produced

**Persona.** Green finance manager (carbon and nature credits, tokenisation) (set by the application).

**Assumptions made before calling the agents**

| Topic | Assumption | Why |
|---|---|---|
| Peatland baseline | Baseline is drained Fenland cropland under the DT8 Fenland water-table climatology (~0.66 m), crops winter wheat (WW) and potato as bracketing arable cases at typical fertiliser rates. | Peatland Code baseline is the current drained land use; WW and potato are common Fen crops. |
| Peatland project | Rewetting to reed (paludiculture/wet fen) with annual mean water table 0.05-0.10 m below surface; established regime (3 years since rewetting) plus a first-year check; AR6 GWP100 as DT8 uses. | Typical Peatland Code rewetted-fen target water table; DT8 reed class. |
| Woodland project | New Corsican pine (CP) planted 2026 on bare land at Thetford, 100 ha, 50-year horizon, no-intervention and thin-and-fell regimes, both growth models, landscape-calibrated productivity. | Represents a typical WCC project near Thetford; 50 years is within common WCC crediting periods. |
| Hedgerow agroforestry | DT6 'fens' pilot tile stands in for Fenland farms; 1,000 new trees planted in 2025 (run as both 'hedgerow' and 'agroforestry' kinds), 50 years. Per-hectare values derived assuming 100 trees per ha of farmland (i.e. ~10 ha), stated as a derived illustration. | DT6 models per tree, not per hectare; density is a project design choice, so results are scaled transparently. |
| Comparability | Abatement for peat is avoided emissions (baseline minus project, t CO2e/ha/yr); for trees it is removals (net CO2 flux, negative = removal). Annualised over the horizon for comparison. Model estimates only, not credits. | Different credit mechanics (emission reduction vs removal). |

**Agent calls**

| # | Agent | Tool | Inputs | Outcome |
|---|---|---|---|---|
| R1 | DT8 peatland greenhouse gases | `ghg_balance` | `{"crop": "WW"}` | ok |
| R2 | DT8 peatland greenhouse gases | `ghg_balance` | `{"crop": "Potato"}` | ok |
| R3 | DT8 peatland greenhouse gases | `water_table_scenario` | `{"mean_wtd_m": [0, 0.05, 0.1, 0.2, 0.3, 0.5, 0.66], "crop": "WW"}` | ok |
| R4 | DT8 peatland greenhouse gases | `validate_inventory` | `{}` | ok |
| R5 | DT4 forest biomass | `afforestation_scenario` | `{"landscape": "thetford", "species": "CP", "horizon_years": 50, "area_ha": 100}` | ok |
| R6 | DT4 forest biomass | `afforestation_scenario` | `{"landscape": "thetford", "species": "CP", "horizon_years": 50, "area_ha": 100, "regime": "thin_and_fell"}` | ok |
| R7 | DT4 forest biomass | `validate` | `{"landscapes": ["thetford"], "species": "CP"}` | ok |
| R8 | DT6 trees outside woodland | `planting_scenario` | `{"pilot": "fens", "n_trees": 1000, "kind": "hedgerow"}` | ok |
| R9 | DT6 trees outside woodland | `planting_scenario` | `{"pilot": "fens", "n_trees": 1000, "kind": "agroforestry"}` | ok |
| R10 | DT6 trees outside woodland | `validate` | `{"pilots": ["fens", "breckland"]}` | ok |

**Data and models (as reported by the agents)**

- model: DT8 peatland three-gas twin 0.1.0
- source: CO2 and N2O: eogit/digital_twin peatland_pignn.py (main), peatland_crop_validation.py and peatland_n2o.py (peatland-ghg-twin). CH4: standalone CH4 notebook peatland_ch4_model_with_litter_extension.ipynb, Sections 1-10 and 14 (flood-killed litter pool); no plant-functional-type extension
- drivers: UK Fens regional daily climatology (synthetic seasonal drivers, one representative year)
- parameters: co2: calibrated baseline; ch4: calibrated baseline; n2o: calibrated baseline
- gwp100: IPCC AR6: CH4 27 (non-fossil), N2O 273
- model: DT4 forest biomass twin 0.2.0
- observations: ESA Biomass CCI v7.0 (100 m AGB and SD), https://catalogue.ceda.ac.uk/uuid/6429d1aafe1e43b9b414e4a5a7f8b903
- citation: Santoro, M.; Cartus, O. (2026): ESA Biomass Climate Change Initiative (Biomass_cci): Global datasets of forest above-ground biomass for the years 2005-2012 and 2015-2024, v7.0. NERC EDS Centre for Environmental Data Analysis.
- licence: ESA CCI Biomass terms and conditions v2: free and open, citation required
- inventory: National Forest Inventory Woodland GB 2024 and Forestry England Subcompartments, Forestry Commission open data. Contains, or is based on, information supplied by the Forestry Commission; Open Government Licence v3.0.
- parameters: yield_curve: calibrated baseline: Biomass CCI v7 pixel calibration of CP in thetford; 3pg: calibrated baseline: Biomass CCI v7 pixel calibration of CP in thetford
- parameters: shipped calibration (scripts/calibrate_pilots.py)
- model: DT6 trees-outside-woodland twin 0.1.0
- observations: Environment Agency LIDAR: National LIDAR Programme DSM/DTM and LIDAR Tiles DSM (1998 onwards), environment.data.gov.uk
- inventory: National Trees Outside Woodland Map V1 (Forest Research / Forestry Commission, NCEA, 2025) and Environment Agency LIDAR (National LIDAR Programme and LIDAR Tiles DSM/DTM). Open Government Licence v3.0.
- allometry: Jucker et al. 2017, Allometric equations for integrating remote sensing imagery into forest monitoring programmes, Global Change Biology 23, 177-190
- licence: Open Government Licence v3.0 (TOW map, EA lidar, HadUK-Grid)
- parameters: calibrated baseline: crown-by-crown EA lidar calibration in fens
- parameters: 

**Policy and market context sources for this persona (reviewed November 2026)**

- Scottish Forestry / Woodland Carbon Code (2025). Woodland Carbon Code (v3) and UK Land Carbon Registry. https://www.woodlandcarboncode.org.uk/
- Woodland Carbon Code (23 March 2026). Woodland Carbon Code enters full ICVCM assessment. https://www.woodlandcarboncode.org.uk/news-events/world-first-woodland-carbon-code
- IUCN UK Peatland Programme (2024-2026). Peatland Code (v2.1). https://www.iucn-uk-peatlandprogramme.org/funding-finance/peatland-code
- Defra / Natural England (2024). Biodiversity net gain (statutory metric, register, statutory credits). https://www.gov.uk/government/collections/biodiversity-net-gain
- Defra (2023). Nature Markets Framework. https://www.gov.uk/government/publications/nature-markets
- BSI / Defra (2024-2026). Nature Investment Standards programme (BSI Flex 701 and successors). https://www.bsigroup.com/en-GB/insights-and-media/insights/brochures/nature-investment-standards-programme/
- DESNZ / Defra (2025/2026). Voluntary carbon and nature markets: raising integrity (consultation, April 2025; government response, 12 November 2026). https://www.gov.uk/government/consultations/voluntary-carbon-and-nature-markets-raising-integrity
- Integrity Council for the Voluntary Carbon Market (2023/2024). Core Carbon Principles and Assessment Framework. https://icvcm.org/core-carbon-principles/
- Voluntary Carbon Markets Integrity Initiative (2023). Claims Code of Practice. https://vcmintegrity.org/vcmi-claims-code-of-practice/
- TNFD (2023). Recommendations of the Taskforce on Nature-related Financial Disclosures. https://tnfd.global/recommendations-of-the-tnfd/
- ISSB / DBT (2023/2025). IFRS S1 and S2 / UK Sustainability Reporting Standards. https://www.gov.uk/guidance/uk-sustainability-reporting-standards
- Financial Conduct Authority (2023/2024). Sustainability Disclosure Requirements and the anti-greenwashing rule (PS23/16). https://www.fca.org.uk/publications/policy-statements/ps23-16-sustainability-disclosure-requirements-investment-labels
- Financial Conduct Authority / HM Treasury (2026). Final rules for the UK cryptoasset regime (authorisation gateway from 30 September 2026; regime applies from 25 October 2027). https://www.fca.org.uk/firms/cryptoassets
- Bank of England / FCA (2024). Digital Securities Sandbox. https://www.bankofengland.co.uk/financial-stability/digital-securities-sandbox
- UK Parliament / Law Commission (2025). Property (Digital Assets etc) Act 2025. https://lawcom.gov.uk/news/the-property-digital-assets-etc-act-2025-has-received-royal-assent/

*Scenario results are model responses to assumed changes, not observations.*
