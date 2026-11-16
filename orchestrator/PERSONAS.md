# User personas of the SLATE orchestrator

The orchestrator is trained to serve three personas:

| id | Persona | Report section it adds |
|---|---|---|
| `policy` | Policy-maker in land use and agricultural policy | Policy relevance |
| `farmer` | Farmer (owner-occupier or tenant) or land manager | What this could mean for your farm |
| `finance` | Green finance manager interested in tokenisation of carbon or nature credits | Credit and market relevance |

Anyone else (NGOs, researchers, the public) is served as `general`, which is the behaviour the
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
   `policy`, `farmer`, `finance` or `general` and its rationale. The orchestrator refuses agent
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
8. **Persona cues are heuristics.** The cue lists help the model infer a persona; a fixed
   persona from the application is preferred when the application knows its user.

## Keeping the personas current

Policy and markets in this area change several times a year (SFI rounds, the Land Use
Framework's implementation, the government's carbon and nature market guidance due in spring
2027, ICVCM's assessment of the Woodland Carbon Code, the FCA cryptoasset regime from October
2027). Review `personas.py` at least yearly and when any of these lands; update `REVIEWED`,
the context facts and the sources table above together. `test_personas.py` checks that every
context fact cites a known source and that key facts are present.
