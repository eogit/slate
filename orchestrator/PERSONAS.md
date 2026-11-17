# User personas of the SLATE orchestrator

The orchestrator is trained to serve five personas:

| id | Persona | Report section it adds |
|---|---|---|
| `policy` | Policy-maker in land use and agricultural policy | Policy relevance |
| `farmer` | Farmer (owner-occupier or tenant) or land manager | What this could mean for your farm |
| `finance` | Green finance manager interested in tokenisation of carbon or nature credits | Credit and market relevance |
| `research` | Research scientist | Methods, uncertainty and reproducibility |
| `ngo` | NGO, including conservation and nature restoration charities | Nature recovery and advocacy relevance |

Anyone else (the public, or no signal about the user) is served as `general`, which is the behaviour the
orchestrator had before personas were added.

The profiles are in [`personas.py`](personas.py). This note explains what "trained for a
persona" means here, summarises each profile, and lists the sources the profiles rest on and
the assumptions we made where the sources are silent. Context reviewed: **November 2026**.

## What "trained for a persona" means

The underlying model is not fine-tuned. A persona is a structured profile that changes what
the orchestrator does at every step, and the orchestrator code (not the model) enforces the
parts that must not be left to chance:

1. **Profiles in the system prompt.** For each persona: who they are, cues that identify them,
   the decisions they take, what they need from the digital twins, the follow-up questions
   worth asking (each with its default and the condition under which to ask it), how to write
   for them, what goes in their report section, and sourced context facts. The profiles are
   part of the static system prompt, so they are cached with the tool definitions.
2. **Persona selection.** Before its first agent call the model must call `set_persona` with
   `policy`, `farmer`, `finance`, `research`, `ngo` or `general` and its rationale. The orchestrator refuses agent
   calls until it has. If the persona is genuinely unclear and it matters, the model may ask
   which persona fits as one of its (at most three) follow-up questions. An application that
   knows its user can fix the persona (`Orchestrator(..., persona="farmer")`, or
   `--persona farmer` on the command line); the model is told and cannot change it.
3. **Adaptation.** The persona steers the follow-up questions (for example tenure for a farmer
   considering rewetting, the target standard for a finance manager, the aggregation geography
   and uptake levels for a policy-maker), the defaults recorded as assumptions, the choice of
   agent calls, and the framing and tone of the report.
4. **Report.** `write_report` must include `persona_section_markdown` for any persona other
   than `general` (the orchestrator sends the call back otherwise). The orchestrator adds the
   section under the persona's heading, appends the persona's standard caveats, records the
   persona and how it was set in "How this was produced", and lists the persona's context
   sources.

The rule that every number in a report comes from an agent applies to every persona. The
context facts are for framing and for naming the relevant policies, schemes and standards;
payment rates, carbon prices and returns are never quoted.

## The personas

### Policy-maker in land use and agricultural policy (`policy`)

**Who.** Analysts and policy leads in Defra, DESNZ, the devolved governments, the Environment
Agency, Natural England, the Forestry Commission, combined and local authorities (Local Nature
Recovery Strategies, spatial planning) and parliamentary committees.

**Decisions.** Where and how much land changes use and the trade-off with food production
(Land Use Framework); design and targeting of Environmental Land Management (SFI, Countryside
Stewardship Higher Tier, Landscape Recovery); progress to net zero and carbon budgets, the
16.5 % canopy target and peat restoration; Green Book appraisal.

**Needs from the twins.** Area-aggregated and per-hectare results, scenarios against a stated
baseline at several uptake levels, inventory consistency (agriculture vs LULUCF, GWP stated),
uncertainty and validation, coverage limits, co-benefits and trade-offs.

**Framing.** Decision-relevant number first, with range and baseline; observed vs modelled kept
apart; strength of evidence graded; options and trade-offs presented neutrally (no advocacy);
concise civil-service style.

### Farmer or land manager (`farmer`)

**Who.** Owner-occupiers, tenants on Farm Business Tenancies (1995 Act) or lifetime and
succession tenancies (1986 Act), and land managers of estates, conservation charities and
utilities.

**Decisions.** Field- and farm-scale management (stocking, feed, manure, water levels,
cropping, hedges and trees); whether to enter SFI, Countryside Stewardship, Woodland Carbon
Code, Peatland Code or biodiversity net gain agreements; for tenants, what the tenancy allows
and who holds carbon and natural capital rights; carbon footprint reporting to buyers and
lenders.

**Needs from the twins.** Results for their holding per hectare, per head and for the whole
farm; side-by-side options; honest statement of what the model knows about their farm.

**Framing.** Plain language; respectful of farming knowledge (evidence, not instructions);
schemes and codes named as options to look into, never promised; no payment rates or prices;
tenure flagged for tenants.

### Green finance manager: carbon and nature credits, tokenisation (`finance`)

**Who.** Managers in investment firms, banks, funds, brokers, project developers and fintechs
that originate, buy, finance or tokenise UK carbon and nature credits.

**Decisions.** Investability (credible volume, timing, risk); integrity due diligence
(baseline, additionality, permanence and reversal, leakage, quantification uncertainty, MRV);
how units are issued, held and transferred, and whether a token can represent a registry unit
without double counting; buyer claims and disclosure.

**Needs from the twins.** Baseline and project-scenario quantities per hectare and per project
over time with uncertainty, clearly distinct from issued units; MRV-supporting evidence
(remote-sensing state variables, validation, provenance-logged repeatable runs); sensitivity
and reversal scenarios.

**Framing.** Due-diligence memo style; model estimates never called credits or verified units;
what the twin contributes to tokenisation (repeatable, provenance-logged MRV data) and what it
cannot (legal title, registry status, regulatory classification); no investment advice, prices,
returns or ratings.

### Research scientist (`research`)

**Who.** Researchers in universities and institutes (NERC centres, UKCEH, Rothamsted Research,
Forest Research, the James Hutton Institute), doctoral and postdoctoral researchers, and agency
science teams, working in Earth observation, ecosystem and biogeochemical modelling, ecology,
physical geography and agricultural science.

**Decisions.** Whether the twins are fit for a research purpose (process representation,
resolution, calibration and validation status); which experiments to run (scenarios,
sensitivity and uncertainty analysis, comparison with observations and IPCC Tier 1-3
inventories); which data to collect next to test or constrain the models; how to report, cite
and archive results reproducibly.

**Needs from the twins.** Methods first (model and version, equations or references, parameter
state, drivers and datasets with DOIs, resolution); uncertainty and validation metrics exactly
as the agents report them, with calibration and validation kept apart; sensitivity to the main
assumptions; a reproducible record of every call.

**Framing.** Scientific register with units, sign conventions and the GWP set stated; methods
before results; no inflated precision or untested significance; limitations, alternative
explanations and falsifiable next tests; data and model sources cited.

**Follow-ups.** The research aim (response variable, hypothesis or comparison); extent,
resolution and period; central run or a sensitivity sweep (default: central run plus a
one-at-a-time sweep of the most influential input the agent exposes).

### NGO, including conservation and nature restoration charities (`ngo`)

**Who.** Staff of conservation and nature restoration charities (e.g. the Wildlife Trusts,
RSPB, National Trust, Woodland Trust, Plantlife, Rewilding Britain, rivers trusts),
environmental campaign groups and sustainable farming and food NGOs: reserve and estate
managers, landscape-scale restoration leads, conservation scientists, policy and advocacy
officers, fundraising and communications teams. Many are large landowners and work with
farmers (e.g. farm clusters, Landscape Recovery).

**Decisions.** Where and how to restore or create habitat; which policy positions and campaigns
to pursue and on what evidence; how to fund restoration (grants, Landscape Recovery, BNG habitat
banks, carbon codes, philanthropy); how to monitor and report outcomes to members and funders.

**Needs from the twins.** Site and landscape results comparing restoration options with current
land use; co-benefits and trade-offs, with a clear statement of what is not modelled (most
biodiversity outcomes); evidence that withstands public scrutiny; material for plain-language
messages plus a technical annex.

**Framing.** Balanced and transparent about uncertainty; climate outcomes the twins compute kept
apart from biodiversity outcomes they do not; sector language (Lawton's more, bigger, better,
joined-up; nature-based solutions with safeguards) without advocating a campaign position; a
clear line between statements the evidence supports for public use and those needing
qualification.

**Follow-ups.** Which outcome matters most (default: GHG and carbon, others named as not
modelled); the reserve or project boundary vs the wider landscape; the use of the result (land
management decision, campaign or policy submission, funder report).

## Sources

The profiles cite these sources (keys as in `personas.py`). "Checked" means the page or its
content was read on 16 November 2026 while writing the profiles; the other links are the
publishers' standard landing pages and were not re-checked because the build environment
cannot reach gov.uk directly.

**Policy**

| Key | Source | Checked |
|---|---|---|
| luf | Defra (18 March 2026). Land Use Framework. Press release: national map of spatial priorities, Land Use Unit, tenants farm about a third of England's farmland | yes |
| luc | Defra (January 2025). Land Use Consultation | |
| atp | Agriculture Act 2020 and the Agricultural Transition Plan (BPS phase-out, ELM) | |
| sfi26 | Defra / RPA (2026). SFI26 scheme rules and guidance: two windows (closed 28 Aug and 22 Sep 2026), ≥ 3 ha, management control, £100,000 cap per agreement year, usually 3-year agreements, FBT and 1986 Act tenants eligible | yes |
| elm | Defra. Countryside Stewardship Higher Tier and Landscape Recovery | |
| envact | Environment Act 2021; Environmental Targets (England) Regulations 2023 (16.5 % canopy by 2050) | |
| eip | Defra. Environmental Improvement Plan (2023, revised) | |
| cca | Climate Change Act 2008 (net zero 2050, carbon budgets) | |
| ccc7 | Climate Change Committee (2025). The Seventh Carbon Budget | |
| peatap | Defra (2021). England Peat Action Plan | |
| treeap | Defra (2021). England Trees Action Plan 2021-2024 | |
| foodsec | Defra (2024). UK Food Security Report | |
| greenbook | HM Treasury. The Green Book (2022) and Magenta Book (2020) | |
| lnrs | Defra. Local Nature Recovery Strategies | |
| naei | DESNZ / NAEI. UK Greenhouse Gas Inventory | |

**Farmer and land manager**

| Key | Source | Checked |
|---|---|---|
| ata1995 | Agricultural Tenancies Act 1995 | |
| aha1986 | Agricultural Holdings Act 1986 | |
| rock | Defra (2022). Rock Review of the agricultural tenanted sector | |
| tfc | Defra / Tenant Farming Commissioner (2025). Code of Practice for agricultural tenancies | partly (existence via press coverage) |
| fbs | Defra. Farm Business Survey | |
| water | Defra / EA. Farming rules for water; NVZs | |
| ahdb | AHDB. Carbon footprinting guidance | |

**Green finance**

| Key | Source | Checked |
|---|---|---|
| wcc | Woodland Carbon Code (v3.0, 2025) and UK Land Carbon Registry | yes (registry name, v3.0) |
| wcc_icvcm | Woodland Carbon Code (23 March 2026). First government-run standard to enter full ICVCM assessment; not yet approved | yes |
| pc | IUCN UK Peatland Programme. Peatland Code (v2.1) | yes (page exists) |
| bng | Defra / Natural England. Biodiversity net gain | |
| nmf | Defra (2023). Nature Markets Framework | |
| bsi | BSI / Defra. Nature Investment Standards programme | |
| vcnm | DESNZ / Defra. Voluntary carbon and nature markets: raising integrity. Consultation 17 April 2025 (six principles; proposed endorsement of ICVCM CCPs and VCMI Claims Code); government response 12 November 2026 (guidance on responsible use in spring 2027; UK Carbon and Nature Markets Regulator Forum) | yes |
| icvcm | ICVCM. Core Carbon Principles and Assessment Framework | |
| vcmi | VCMI. Claims Code of Practice | |
| tnfd | TNFD (2023). Recommendations | |
| issb | ISSB IFRS S1/S2; UK Sustainability Reporting Standards | |
| sdr | FCA. PS23/16 Sustainability Disclosure Requirements and anti-greenwashing rule | |
| fcacrypto | FCA (2026). Final rules for the UK cryptoasset regime: authorisation gateway from 30 September 2026; regime applies from 25 October 2027 | yes (via legal commentary; FCA page exists) |
| dss | Bank of England / FCA. Digital Securities Sandbox | |
| pdaa | Property (Digital Assets etc) Act 2025 (Royal Assent December 2025) | yes |

**Research scientist**

| Key | Source | Checked |
|---|---|---|
| fair | Wilkinson et al. (2016). The FAIR Guiding Principles. Scientific Data 3, 160018 | |
| ukrioa | UKRI open access policy (articles submitted from 1 April 2022 open on publication) | |
| nercdata | UKRI-NERC data policy: deposit in a NERC data centre, openly available within two years of collection | yes (17 Nov 2026) |
| ipcc2019 | IPCC (2019). 2019 Refinement to the 2006 Guidelines (Tier 1-3 methods) | |
| ar6gwp | Forster et al. (2021). IPCC AR6 WG I Chapter 7 (GWP100) | |
| ceoslpv | CEOS WGCV Land Product Validation: validation stages 1-4 | yes (17 Nov 2026) |
| olofsson | Olofsson et al. (2014). Good practices for estimating area and assessing accuracy of land change. RSE 148, 42-57 | |
| gcos | GCOS (2022). Essential Climate Variables | |
| ebv | Pereira et al. (2013). Essential Biodiversity Variables. Science 339, 277-278 | |
| gemini | Centre for Digital Built Britain (2018). The Gemini Principles | |
| swcite | Smith et al. (2016). Software citation principles. PeerJ CS 2, e86 | |
| gum | JCGM 100:2008. Guide to the expression of uncertainty in measurement | |
| naei | DESNZ / NAEI. UK Greenhouse Gas Inventory | |

The peer-reviewed sources are cited by DOI; the profile uses only their well-established core
statements.

**NGO**

| Key | Source | Checked |
|---|---|---|
| son23 | State of Nature Partnership (2023). State of Nature 2023: 19 % average decline in abundance of monitored species since 1970; about one in six species at risk of extinction in Great Britain | yes (17 Nov 2026, via NHM summary) |
| lawton | Lawton et al. (2010). Making Space for Nature (more, bigger, better, joined) | |
| gbf | CBD (2022). Kunming-Montreal Global Biodiversity Framework, Target 3 (30by30) | |
| wcl30 | Wildlife and Countryside Link (2023-2025). 30by30 progress assessments for England | yes (page exists; figures vary by criteria, so none quoted) |
| envbio | Environmental Targets (Biodiversity) (England) Regulations 2023: halt species decline by 2030, increase by 2042 | |
| cc9 | Charity Commission (2022). Speaking out: campaigning and political activity by charities (CC9) | yes (page exists) |
| iucnnbs | IUCN (2020). Global Standard for Nature-based Solutions | |
| ser | Gann et al. (2019). SER International principles and standards for ecological restoration, 2nd ed. | |

The NGO profile also uses the policy sources for the Environment Act, Land Use Framework, ELM,
LNRS, BNG, and the Peatland and Woodland Carbon Codes.

## Assumptions

Where the sources do not settle a point, the profiles rest on these assumptions. Each is a
reasonable reading of practice, not a legal statement, and the reports carry caveats that send
users to the authoritative source.

1. **Scope is England first.** The digital twins cover England (and pilot landscapes in it), so
   the policy context is Defra's. Devolved policy (Scotland, Wales' Sustainable Farming Scheme,
   Northern Ireland) is mentioned only as a limit.
2. **Policy-makers want neutrality and evidence grading.** Civil-service analysts need options
   and trade-offs, not recommendations, and need to know whether a result is validated,
   calibrated or indicative. This follows Green Book and Magenta Book practice but the grading
   words are ours.
3. **Pilot results are indicative.** Up-scaling a pilot landscape to England assumes
   representativeness; reports say so for policy users.
4. **Carbon and natural capital rights follow ownership unless agreed otherwise**, and
   long-term changes (woodland creation, rewetting) normally need landlord consent. This is our
   reading of standard tenancy practice and of the issues raised by the Rock Review and the
   Tenant Farming Commissioner; individual tenancies differ.
5. **Farmers should not be quoted payment rates or prices.** Rates change between scheme rounds
   and prices vary by project; quoting them risks misleading business decisions, and they are
   outside what the twins compute.
6. **Model estimates are not credits.** Units under the Woodland Carbon Code and Peatland Code
   are issued only after validation and verification, with the code's own baseline, methods
   and buffer. A twin can support monitoring and due diligence but its numbers must not be
   presented as creditable volumes.
7. **Tokenisation is assessed on structure.** Whether a tokenised credit is a regulated
   investment depends on how it is structured; spot carbon credits are not generally regulated
   financial instruments in the UK, while derivatives and fund-like structures can be. Tokens
   should map one-to-one to registry units, with retirement mirrored on the registry, to avoid
   double issuance and double counting (the problem seen with tokenised retired credits in
   2022). The orchestrator does not give a regulatory view.
8. **Researchers want methods and uncertainty first.** The research persona puts the
   provenance, parameter state, calibration vs validation and the reproducible call record at
   the centre of the report, and defaults to a one-at-a-time sensitivity sweep when results
   will support conclusions. One-at-a-time sweeps are a pragmatic default, not a global
   sensitivity analysis; a researcher can ask for more.
9. **Learned state matters for reproducibility.** Some twins learn or assimilate parameters
   during a session (e.g. DT8), so the research persona's caveats ask users to cite the model
   version and the logged calls rather than treat a run as fixed.
10. **Validation language follows the agents.** The profile names CEOS LPV validation stages as
   a reference frame, but the orchestrator does not assign a stage to a twin; it reports only
   the validation the agents return.
11. **NGOs need defensible evidence more than persuasive evidence.** NGO outputs are often
   public and contested, so the profile emphasises ranges, sources and which statements are
   safe for public use, and keeps the orchestrator out of campaign positions. Charity law (CC9)
   allows campaigning in support of charitable purposes; that is the NGO's call, not the
   twin's.
12. **Biodiversity is mostly outside the twins.** The current twins model greenhouse gases and
   biomass carbon, not species or habitat condition. NGO reports always say so, and habitat
   benefits are named only as unassessed possibilities.
13. **NGOs are a persona; the public stays general.** Before this change NGOs were served as
   `general`; `general` now covers the public and questions with no signal about the user.
14. **Persona cues are heuristics.** The cue lists help the model infer a persona; a fixed
   persona from the application is preferred when the application knows its user.

## Keeping the personas current

Policy and markets in this area change several times a year (SFI rounds, the Land Use
Framework's implementation, the government's carbon and nature market guidance due in spring
2027, ICVCM's assessment of the Woodland Carbon Code, the FCA cryptoasset regime from October
2027). Review `personas.py` at least yearly and when any of these lands; update `REVIEWED`,
the context facts and the sources table above together. `test_personas.py` checks that every
context fact cites a known source and that key facts are present.
