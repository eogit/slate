"""User personas the SLATE orchestrator adapts to.

A persona is a profile of a type of user: who they are, the decisions they take, what they need
from the digital twins, which follow-up questions are worth asking them (with sensible
defaults), how to frame the answer, what the persona-specific section of the report contains,
and the caveats every report for that persona carries.

The orchestrator is not fine-tuned for a persona. "Trained for" means: the profiles below are
part of the system prompt, the model selects (or is given) a persona before calling any agent,
the orchestrator records the choice, and the report adds a persona section and fixed caveats
that the orchestrator itself appends. The profiles are grounded in the official and standard-
setting sources listed in ``SOURCES``; where the sources are silent we made assumptions, which
are listed in ``orchestrator/PERSONAS.md`` together with the sources. Policy and markets change
quickly: the profiles describe the position as of November 2026 and should be reviewed at least
yearly.

Facts in a profile are context for framing. They are not data: the orchestrator's rule that
every number in a report comes from an agent applies to persona reports too.
"""

from __future__ import annotations

from dataclasses import dataclass, field

REVIEWED = "November 2026"


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    publisher: str
    year: str
    url: str


@dataclass(frozen=True)
class FollowUp:
    """A follow-up question worth asking this persona, with the default used otherwise."""
    question: str
    default: str
    when: str


@dataclass(frozen=True)
class Persona:
    id: str
    label: str
    audience: str                       # "Prepared for" line of the report
    who: str
    recognise_by: list[str]             # cues in a question that suggest this persona
    decisions: list[str]                # decisions the persona uses evidence for
    needs: list[str]                    # what they need from the digital twins
    follow_ups: list[FollowUp]
    framing: list[str]                  # how to write for them
    section_title: str                  # persona section of the report
    section_brief: str                  # what goes in it
    context: list[tuple[str, str]]      # (fact used for framing, source key)
    caveats: list[str]                  # appended to every report for this persona
    sources: list[str] = field(default_factory=list)


SOURCES: dict[str, Source] = {s.key: s for s in [
    # --- policy -------------------------------------------------------------------------
    Source("luf", "Land Use Framework", "Defra", "18 March 2026",
           "https://www.gov.uk/government/publications/land-use-framework"),
    Source("luc", "Land Use Consultation", "Defra", "2025 (January)",
           "https://www.gov.uk/government/consultations/land-use-consultation"),
    Source("atp", "Agricultural Transition Plan / Agriculture Act 2020", "Defra / UK Parliament",
           "2020-2026", "https://www.legislation.gov.uk/ukpga/2020/21/contents"),
    Source("sfi26", "Sustainable Farming Incentive 2026 (SFI26): scheme rules and guidance",
           "Defra / Rural Payments Agency", "2026",
           "https://www.gov.uk/government/publications/sustainable-farming-incentive-2026-sfi26/"
           "sfi26-scheme-rules-and-guidance"),
    Source("elm", "Environmental Land Management schemes: Countryside Stewardship Higher Tier "
           "and Landscape Recovery", "Defra", "2024-2026",
           "https://www.gov.uk/government/collections/environmental-land-management-schemes"),
    Source("envact", "Environment Act 2021 and the Environmental Targets (England) "
           "Regulations 2023 (incl. 16.5% tree and woodland canopy by 2050)",
           "UK Parliament", "2021/2023", "https://www.legislation.gov.uk/ukpga/2021/30/contents"),
    Source("eip", "Environmental Improvement Plan for England (revised)", "Defra", "2023/2025",
           "https://www.gov.uk/government/publications/environmental-improvement-plan"),
    Source("cca", "Climate Change Act 2008 (net zero by 2050) and carbon budgets",
           "UK Parliament", "2008/2019", "https://www.legislation.gov.uk/ukpga/2008/27/contents"),
    Source("ccc7", "The Seventh Carbon Budget (agriculture and land use pathway)",
           "Climate Change Committee", "2025",
           "https://www.theccc.org.uk/publication/the-seventh-carbon-budget/"),
    Source("peatap", "England Peat Action Plan", "Defra", "2021",
           "https://www.gov.uk/government/publications/england-peat-action-plan"),
    Source("treeap", "England Trees Action Plan 2021-2024", "Defra", "2021",
           "https://www.gov.uk/government/publications/england-trees-action-plan-2021-to-2024"),
    Source("foodsec", "UK Food Security Report", "Defra", "2024",
           "https://www.gov.uk/government/statistics/united-kingdom-food-security-report-2024"),
    Source("greenbook", "The Green Book: appraisal and evaluation in central government "
           "(and the Magenta Book on evaluation)", "HM Treasury", "2022/2020",
           "https://www.gov.uk/government/publications/the-green-book-appraisal-and-evaluation-"
           "in-central-government"),
    Source("lnrs", "Local Nature Recovery Strategies", "Defra", "2023-2026",
           "https://www.gov.uk/government/publications/local-nature-recovery-strategies"),
    Source("naei", "UK Greenhouse Gas Inventory / National Atmospheric Emissions Inventory",
           "DESNZ / NAEI", "annual", "https://naei.energysecurity.gov.uk/"),
    # --- farmer / land manager -----------------------------------------------------------
    Source("ata1995", "Agricultural Tenancies Act 1995 (Farm Business Tenancies)",
           "UK Parliament", "1995", "https://www.legislation.gov.uk/ukpga/1995/8/contents"),
    Source("aha1986", "Agricultural Holdings Act 1986", "UK Parliament", "1986",
           "https://www.legislation.gov.uk/ukpga/1986/5/contents"),
    Source("rock", "Rock Review: working together for a thriving agricultural tenanted sector",
           "Defra", "2022", "https://www.gov.uk/government/publications/the-rock-review-"
           "working-together-for-a-thriving-agricultural-tenanted-sector"),
    Source("tfc", "Tenant Farming Commissioner: Code of Practice for agricultural tenancies",
           "Defra", "2025", "https://www.gov.uk/government/organisations/tenant-farming-"
           "commissioner"),
    Source("fbs", "Farm Business Survey: farm business income", "Defra", "annual",
           "https://www.gov.uk/government/collections/farm-business-survey"),
    Source("water", "Farming rules for water and Nitrate Vulnerable Zones", "Defra / "
           "Environment Agency", "2018/ongoing",
           "https://www.gov.uk/government/publications/applying-the-farming-rules-for-water"),
    Source("ahdb", "AHDB guidance on farm carbon footprinting and net zero",
           "Agriculture and Horticulture Development Board", "ongoing",
           "https://ahdb.org.uk/knowledge-library/carbon-footprinting"),
    # --- green finance ------------------------------------------------------------------
    Source("wcc", "Woodland Carbon Code (v3) and UK Land Carbon Registry",
           "Scottish Forestry / Woodland Carbon Code", "2025",
           "https://www.woodlandcarboncode.org.uk/"),
    Source("wcc_icvcm", "Woodland Carbon Code enters full ICVCM assessment",
           "Woodland Carbon Code", "23 March 2026",
           "https://www.woodlandcarboncode.org.uk/news-events/world-first-woodland-carbon-code"),
    Source("pc", "Peatland Code (v2.1)", "IUCN UK Peatland Programme", "2024-2026",
           "https://www.iucn-uk-peatlandprogramme.org/funding-finance/peatland-code"),
    Source("bng", "Biodiversity net gain (statutory metric, register, statutory credits)",
           "Defra / Natural England", "2024",
           "https://www.gov.uk/government/collections/biodiversity-net-gain"),
    Source("nmf", "Nature Markets Framework", "Defra", "2023",
           "https://www.gov.uk/government/publications/nature-markets"),
    Source("bsi", "Nature Investment Standards programme (BSI Flex 701 and successors)",
           "BSI / Defra", "2024-2026",
           "https://www.bsigroup.com/en-GB/insights-and-media/insights/brochures/"
           "nature-investment-standards-programme/"),
    Source("vcnm", "Voluntary carbon and nature markets: raising integrity (consultation, "
           "April 2025; government response, 12 November 2026)", "DESNZ / Defra",
           "2025/2026", "https://www.gov.uk/government/consultations/voluntary-carbon-and-"
           "nature-markets-raising-integrity"),
    Source("icvcm", "Core Carbon Principles and Assessment Framework",
           "Integrity Council for the Voluntary Carbon Market", "2023/2024",
           "https://icvcm.org/core-carbon-principles/"),
    Source("vcmi", "Claims Code of Practice", "Voluntary Carbon Markets Integrity Initiative",
           "2023", "https://vcmintegrity.org/vcmi-claims-code-of-practice/"),
    Source("tnfd", "Recommendations of the Taskforce on Nature-related Financial Disclosures",
           "TNFD", "2023", "https://tnfd.global/recommendations-of-the-tnfd/"),
    Source("issb", "IFRS S1 and S2 / UK Sustainability Reporting Standards", "ISSB / DBT",
           "2023/2025", "https://www.gov.uk/guidance/uk-sustainability-reporting-standards"),
    Source("sdr", "Sustainability Disclosure Requirements and the anti-greenwashing rule "
           "(PS23/16)", "Financial Conduct Authority", "2023/2024",
           "https://www.fca.org.uk/publications/policy-statements/ps23-16-sustainability-"
           "disclosure-requirements-investment-labels"),
    Source("fcacrypto", "Final rules for the UK cryptoasset regime (authorisation gateway from "
           "30 September 2026; regime applies from 25 October 2027)",
           "Financial Conduct Authority / HM Treasury", "2026",
           "https://www.fca.org.uk/firms/cryptoassets"),
    Source("dss", "Digital Securities Sandbox", "Bank of England / FCA", "2024",
           "https://www.bankofengland.co.uk/financial-stability/digital-securities-sandbox"),
    Source("pdaa", "Property (Digital Assets etc) Act 2025", "UK Parliament / Law Commission",
           "2025", "https://lawcom.gov.uk/news/the-property-digital-assets-etc-act-2025-has-"
           "received-royal-assent/"),
    # --- research scientist -------------------------------------------------------------
    Source("fair", "Wilkinson et al. The FAIR Guiding Principles for scientific data "
           "management and stewardship. Scientific Data 3, 160018", "Scientific Data", "2016",
           "https://doi.org/10.1038/sdata.2016.18"),
    Source("ukrioa", "UKRI open access policy (peer-reviewed articles submitted from 1 April "
           "2022 open on publication)", "UK Research and Innovation", "2021/2022",
           "https://www.ukri.org/manage-your-award/publishing-your-research-findings/"
           "making-your-research-publications-open-access/"),
    Source("nercdata", "NERC data policy (deposit in a NERC data centre; openly available "
           "within two years of collection)", "UKRI-NERC", "2019/2023",
           "https://www.ukri.org/who-we-are/nerc/our-policies-and-standards/nerc-data-policy/"),
    Source("ipcc2019", "2019 Refinement to the 2006 IPCC Guidelines for National Greenhouse "
           "Gas Inventories (Tier 1-3 methods)", "IPCC", "2006/2019",
           "https://www.ipcc-nggip.iges.or.jp/public/2019rf/"),
    Source("ar6gwp", "Forster et al. The Earth's energy budget, climate feedbacks and climate "
           "sensitivity (IPCC AR6 WG I, Chapter 7: GWP100 values)", "IPCC", "2021",
           "https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-7/"),
    Source("ceoslpv", "Land Product Validation subgroup: validation stages 1-4",
           "CEOS Working Group on Calibration and Validation", "ongoing",
           "https://lpvs.gsfc.nasa.gov"),
    Source("olofsson", "Olofsson et al. Good practices for estimating area and assessing "
           "accuracy of land change. Remote Sensing of Environment 148, 42-57",
           "Remote Sensing of Environment", "2014", "https://doi.org/10.1016/j.rse.2014.02.015"),
    Source("gcos", "Essential Climate Variables (GCOS Implementation Plan 2022)", "GCOS / WMO",
           "2022", "https://gcos.wmo.int/en/essential-climate-variables"),
    Source("ebv", "Pereira et al. Essential Biodiversity Variables. Science 339, 277-278",
           "Science", "2013", "https://doi.org/10.1126/science.1229931"),
    Source("gemini", "The Gemini Principles (purpose, trust, function for national digital "
           "twins)", "Centre for Digital Built Britain", "2018",
           "https://www.cdbb.cam.ac.uk/DFTG/GeminiPrinciples"),
    Source("swcite", "Smith et al. Software citation principles. PeerJ Computer Science 2, e86",
           "PeerJ Computer Science", "2016", "https://doi.org/10.7717/peerj-cs.86"),
    Source("gum", "Evaluation of measurement data: Guide to the expression of uncertainty in "
           "measurement (JCGM 100:2008)", "JCGM / BIPM", "2008",
           "https://www.bipm.org/en/doi/10.59161/jcgm100-2008e"),
]}


PERSONAS: dict[str, Persona] = {p.id: p for p in [
    Persona(
        id="policy",
        label="Policy-maker (land use and agricultural policy)",
        audience="a land use and agricultural policy team",
        who=("An analyst or policy lead in Defra, DESNZ, a devolved government, the Environment "
             "Agency, Natural England, the Forestry Commission, a combined or local authority "
             "(Local Nature Recovery Strategy, spatial planning) or a parliamentary committee. "
             "Works on land use change, agricultural transition and environmental targets in "
             "England (or the UK)."),
        recognise_by=["policy", "Defra", "ELM", "SFI", "scheme design", "target", "net zero",
                      "carbon budget", "Land Use Framework", "region", "national", "England",
                      "uptake", "spending", "evidence for", "ministers", "consultation",
                      "LNRS", "local authority"],
        decisions=[
            "where and how much land should change use (woodland, peatland rewetting, "
            "habitat) and the trade-off with food production",
            "design, targeting and payment of land management schemes (SFI, Countryside "
            "Stewardship Higher Tier, Landscape Recovery)",
            "progress towards statutory and policy targets (net zero and carbon budgets, "
            "16.5% canopy cover by 2050, peat restoration, 30by30)",
            "appraisal of options under HM Treasury Green Book and evaluation under the "
            "Magenta Book",
        ],
        needs=[
            "spatially explicit, area-aggregated results (region, landscape, catchment, 1 km "
            "grid) with totals and per-hectare values",
            "scenario comparisons against a stated baseline and the counterfactual, at "
            "different uptake levels",
            "consistency with the UK GHG inventory and its categories (agriculture vs LULUCF), "
            "with GWP stated",
            "uncertainty ranges, validation against observations, and clear limits of coverage",
            "co-benefits and trade-offs (food output, water, biodiversity) where the agents "
            "report them",
        ],
        follow_ups=[
            FollowUp("Which geography should results be aggregated to (a named region, county, "
                     "catchment, LNRS area, or England)?",
                     "the pilot landscape the agent covers, presented as indicative for England",
                     "the place is vague or national and the agent covers only pilot areas"),
            FollowUp("What uptake or scale should the scenario assume?",
                     "a low, central and high uptake (e.g. 10, 25, 50 % of eligible land)",
                     "the question asks about a policy without a size"),
            FollowUp("Which accounting frame matters: the national inventory (GWP100, AR5 as "
                     "used in the UK inventory) or a scheme-level per-hectare figure?",
                     "inventory-consistent GWP100 as the agent uses, plus per-hectare values",
                     "the answer will be compared with targets or carbon budgets"),
        ],
        framing=[
            "Lead with the decision-relevant number, its range and what it is relative to.",
            "Separate what is observed or calibrated from what is a modelled scenario.",
            "State the scale of the result relative to useful national benchmarks that the "
            "agents return (inventory totals, England averages) and what drives it.",
            "Spell out trade-offs and who is affected (farm types, tenants, regions); be "
            "neutral about policy choices: present options, do not advocate.",
            "Rate the strength of evidence (validated, calibrated, indicative) and name gaps.",
            "Concise, quantitative, civil-service style; British English; no jargon without "
            "a definition.",
        ],
        section_title="Policy relevance",
        section_brief=(
            "Which policies, targets and schemes the result bears on (e.g. Land Use Framework, "
            "SFI/CSHT/Landscape Recovery, carbon budgets, canopy or peat targets) and how; "
            "options and their trade-offs; how strong the evidence is (validated, calibrated "
            "or indicative) and what further evidence would change the conclusion. No "
            "advocacy and no numbers that did not come from the agents."),
        context=[
            ("England's first Land Use Framework (March 2026) sets out how England's finite "
             "land is managed for food, nature, climate, housing and energy, promises a "
             "national map of spatial priorities and a Land Use Unit, and notes that tenants "
             "farm about a third of England's farmland.", "luf"),
            ("Direct payments (BPS) are being phased out under the Agriculture Act 2020; "
             "public money for public goods is paid through Environmental Land Management: "
             "SFI (SFI26 opened in two windows in 2026, with a cap per agreement), "
             "Countryside Stewardship Higher Tier and Landscape Recovery.", "sfi26"),
            ("Statutory targets include net zero by 2050 with five-yearly carbon budgets, and "
             "16.5% tree and woodland canopy cover in England by 2050.", "envact"),
            ("The Climate Change Committee's Seventh Carbon Budget pathway relies on "
             "peatland restoration, woodland creation and lower livestock emissions.", "ccc7"),
            ("Agricultural emissions (e.g. enteric methane) and land use emissions and "
             "removals (e.g. drained peat, forests) sit in different inventory sectors "
             "(agriculture vs LULUCF).", "naei"),
            ("Options are appraised with the Green Book, including distributional effects "
             "and non-market values.", "greenbook"),
        ],
        caveats=[
            "Results from pilot landscapes are indicative for wider areas; scaling them up "
            "assumes the pilot is representative, which this report does not test.",
            "The digital twins estimate biophysical effects; costs, payment rates, uptake "
            "behaviour and Green Book appraisal are outside their scope.",
            f"Policy context reflects the position in {REVIEWED}; check current Defra "
            "guidance before relying on it.",
        ],
        sources=["luf", "luc", "atp", "sfi26", "elm", "envact", "eip", "cca", "ccc7", "peatap",
                 "treeap", "foodsec", "greenbook", "lnrs", "naei"],
    ),
    Persona(
        id="farmer",
        label="Farmer (owner-occupier or tenant) or land manager",
        audience="a farmer or land manager",
        who=("A farmer who owns their land or rents it (a Farm Business Tenancy under the "
             "1995 Act, or a lifetime or succession tenancy under the 1986 Act), or a land "
             "manager of an estate, a conservation charity or a utility. Runs a business "
             "with tight margins, often dependent on scheme income, and decides at field "
             "and farm scale."),
        recognise_by=["my farm", "my field", "my herd", "our land", "tenant", "landlord",
                      "estate", "I farm", "cows", "sheep", "crop", "SFI", "grant", "payment",
                      "per hectare", "rewet", "plant trees", "hedges", "carbon credits for my"],
        decisions=[
            "which management changes to make on which fields (stocking, feed, manure "
            "handling, water levels, cropping, hedges and trees)",
            "whether to enter a scheme or private agreement (SFI, Countryside Stewardship, "
            "Woodland Carbon Code, Peatland Code, biodiversity net gain) and for how long",
            "for tenants: what the tenancy allows, who holds carbon and natural capital "
            "rights, and what needs the landlord's consent",
            "how to report the farm's carbon footprint to buyers, lenders or processors",
        ],
        needs=[
            "results for their own holding or fields, per hectare and per head, in plain units",
            "a before-and-after comparison of practical options",
            "what the results mean for the business and for scheme or market opportunities, "
            "without unsupported promises of income",
            "honesty about what the model knows about their farm and what it assumes",
        ],
        follow_ups=[
            FollowUp("Where is the farm (postcode, grid reference or nearest village)?",
                     "the centre of the place named in the question",
                     "the location is not given; most agents need coordinates"),
            FollowUp("What does the farm run: herd sizes, main crops, area?",
                     "the agent's local averages for the 1 km cells around the farm",
                     "farm-scale results are asked for and the agents accept farm inputs"),
            FollowUp("Do you own the land or rent it (and on which kind of tenancy)?",
                     "not known; tenure implications are flagged as a caveat",
                     "the question involves long-term land use change, carbon or nature "
                     "credits, rewetting or tree planting"),
        ],
        framing=[
            "Plain language, short sentences, practical meaning; explain any technical term.",
            "Per hectare, per head and whole-farm figures; compare options side by side.",
            "Say what drives the result on this farm and which levers the farmer controls.",
            "Be respectful of farming knowledge: present evidence, not instructions.",
            "Mention relevant schemes and markets by name as options to look into, never "
            "promise eligibility or income, and do not quote payment rates or carbon prices.",
            "For tenants, note what may need the landlord's agreement and who may own "
            "carbon or nature credits.",
        ],
        section_title="What this could mean for your farm",
        section_brief=(
            "Practical options suggested by the results, ordered by size of effect; what each "
            "would involve; which schemes or codes might be relevant (SFI, Countryside "
            "Stewardship, Woodland Carbon Code, Peatland Code, biodiversity net gain) to look "
            "into; tenure points for tenants; where to get advice. No payment rates or "
            "prices, and no numbers that did not come from the agents."),
        context=[
            ("SFI26 was open to farmers and land managers with at least 3 ha and management "
             "control for each action's duration; tenants on FBTs and 1986 Act tenancies can "
             "apply if they do not breach their tenancy; agreements usually run three years "
             "and are capped per year.", "sfi26"),
            ("Tenants farm about a third of England's farmland (Land Use Framework); the Rock "
             "Review and the Tenant Farming Commissioner's Code of Practice address "
             "landlord-tenant cooperation, including on environmental schemes and natural "
             "capital.", "rock"),
            ("Carbon and natural capital rights usually follow land ownership unless the "
             "tenancy or a separate agreement says otherwise; long-term changes such as "
             "woodland creation or rewetting normally need landlord consent (our reading of "
             "standard tenancy practice; see PERSONAS.md).", "tfc"),
            ("Woodland Carbon Code and Peatland Code projects are validated and verified by "
             "independent bodies and commit the land for decades (permanence).", "wcc"),
            ("Farm incomes vary widely by farm type and year, and many farms depend on "
             "scheme payments.", "fbs"),
        ],
        caveats=[
            "The digital twins describe typical conditions in the area around the farm; they "
            "do not know your fields, herd or records unless you supplied them.",
            "This is not financial, legal or agronomic advice. Check scheme eligibility and "
            "current payment rates with the Rural Payments Agency or Natural England, and "
            "talk to an adviser before changing the business.",
            "Tenants: check your tenancy agreement and talk to your landlord before land use "
            "change or selling carbon or nature credits.",
        ],
        sources=["sfi26", "elm", "ata1995", "aha1986", "rock", "tfc", "fbs", "water", "ahdb",
                 "wcc", "pc", "bng", "luf"],
    ),
    Persona(
        id="finance",
        label="Green finance manager (carbon and nature credits, tokenisation)",
        audience="a green finance and natural capital investment team",
        who=("A manager in an investment firm, bank, fund, broker, project developer or "
             "fintech that originates, buys, finances or tokenises UK carbon and nature "
             "credits (Woodland Carbon Code, Peatland Code, biodiversity units, emerging "
             "nature credits) for voluntary markets and corporate buyers. Thinks in terms of "
             "integrity, risk, volume, timing and regulation."),
        recognise_by=["credit", "carbon unit", "PIU", "WCU", "offset", "investor", "token",
                      "tokenise", "blockchain", "registry", "MRV", "dMRV", "ICVCM", "VCMI",
                      "TNFD", "portfolio", "due diligence", "green bond", "nature market",
                      "biodiversity unit", "buffer", "additionality", "permanence"],
        decisions=[
            "whether a project or portfolio is investable: credible volume, timing and risk "
            "of credits",
            "due diligence on integrity: additionality, baseline, permanence and reversal "
            "risk, leakage, quantification and its uncertainty, monitoring (MRV)",
            "how credits are issued, held and transferred (UK Land Carbon Registry; whether "
            "and how a token can represent a registry unit without double counting)",
            "which claims buyers can make (VCMI Claims Code, UK guidance) and how holdings "
            "are disclosed (TNFD, ISSB/UK SRS, FCA anti-greenwashing rule)",
        ],
        needs=[
            "baseline and project-scenario quantities per hectare and per project area over "
            "time, with uncertainty, as model estimates distinct from issued units",
            "evidence that can support MRV: remote-sensing state variables, validation "
            "against independent data, repeatable model runs with provenance",
            "risk indicators: sensitivity to assumptions, reversal and disturbance scenarios",
            "a clear statement of what is and is not eligible or verified under a code",
        ],
        follow_ups=[
            FollowUp("Which standard or market is the credit intended for (Woodland Carbon "
                     "Code, Peatland Code, biodiversity net gain, another nature credit)?",
                     "the UK code that matches the land use (WCC for woodland, Peatland Code "
                     "for peat)", "the credit type is not stated"),
            FollowUp("What project area, start year and crediting period should be assumed?",
                     "the agent's pilot site, starting this year, over the horizon the agent "
                     "can model", "volumes or timing are asked for"),
            FollowUp("Is the question about one project or a portfolio across sites?",
                     "one representative project", "it is unclear"),
        ],
        framing=[
            "Concise and structured, like an investment or due-diligence memo.",
            "Give model-estimated abatement or removals per hectare and for the project, "
            "with ranges; never call them credits, units or verified; credits are issued only "
            "after independent validation and verification under a code.",
            "Assess integrity drivers the results speak to: baseline, additionality cues, "
            "permanence and reversal risk, leakage, uncertainty, and MRV evidence.",
            "For tokenisation, say what the digital twin can contribute (repeatable, "
            "provenance-logged MRV data) and what it cannot (legal title, registry status, "
            "regulatory classification).",
            "Do not give investment advice, prices, returns or ratings.",
        ],
        section_title="Credit and market relevance",
        section_brief=(
            "How the modelled quantities relate to creditable quantities under the relevant "
            "code (baseline, buffer, verification) without converting them into units; "
            "integrity and risk points the results bear on (additionality, permanence and "
            "reversal, leakage, uncertainty, MRV); points for tokenisation (one-to-one link "
            "to registry units, no double issuance or double counting, retirement mirrored "
            "on the registry, regulatory status to be checked); and relevant disclosure and "
            "claims frameworks. No prices, returns or investment advice, and no numbers that "
            "did not come from the agents."),
        context=[
            ("The Woodland Carbon Code and the Peatland Code are the UK's government-backed "
             "standards for woodland and peatland carbon; projects are validated and then "
             "verified by accredited bodies, units are listed on the UK Land Carbon "
             "Registry, Pending Issuance Units become verified units only after "
             "verification, and a share of units goes to a buffer against reversal.", "wcc"),
            ("In March 2026 the Woodland Carbon Code became the first government-run "
             "standard to enter full assessment against ICVCM's Core Carbon Principles; it "
             "has not (yet) been approved.", "wcc_icvcm"),
            ("UK government consulted in 2025 on six integrity principles for voluntary "
             "carbon and nature markets, proposing to endorse ICVCM CCP-labelled credits and "
             "the VCMI Claims Code; its response (12 November 2026) commits to guidance on "
             "responsible use in spring 2027 and a UK Carbon and Nature Markets Regulator "
             "Forum.", "vcnm"),
            ("Biodiversity net gain is mandatory for most development in England (10% "
             "using the statutory metric), creating demand for off-site biodiversity units "
             "registered on the national register.", "bng"),
            ("The Property (Digital Assets etc) Act 2025 confirms that digital assets can "
             "be personal property in English law; the FCA's cryptoasset regime applies "
             "from 25 October 2027. Whether a tokenised credit is a regulated investment "
             "depends on its structure; spot carbon credits themselves are not generally "
             "regulated financial instruments, but derivatives and fund-like structures can "
             "be.", "fcacrypto"),
            ("Firms disclose nature- and climate-related risks under TNFD and ISSB/UK SRS; "
             "the FCA anti-greenwashing rule requires sustainability claims to be fair, "
             "clear and not misleading.", "sdr"),
        ],
        caveats=[
            "Model estimates are not carbon or nature credits: units are issued only after "
            "validation and verification under a code (e.g. Woodland Carbon Code, Peatland "
            "Code), which applies its own baseline, buffer and methods.",
            "This report is not investment, legal or regulatory advice. The regulatory "
            "status of a tokenised credit depends on its structure and should be confirmed "
            "with the FCA's rules and legal counsel.",
            f"Market and regulatory context reflects the position in {REVIEWED}.",
        ],
        sources=["wcc", "wcc_icvcm", "pc", "bng", "nmf", "bsi", "vcnm", "icvcm", "vcmi", "tnfd",
                 "issb", "sdr", "fcacrypto", "dss", "pdaa"],
    ),
    Persona(
        id="research",
        label="Research scientist",
        audience="a research scientist",
        who=("A researcher in a university or research institute (e.g. NERC centres, UKCEH, "
             "Rothamsted Research, Forest Research, the James Hutton Institute), a doctoral "
             "or postdoctoral researcher, or an analyst in an agency science team. Works in "
             "Earth observation, ecosystem and biogeochemical modelling, ecology, physical "
             "geography or agricultural science, and uses the digital twins to explore "
             "hypotheses, compare models with data, design experiments or produce results "
             "for publication."),
        recognise_by=["hypothesis", "paper", "publication", "PhD", "research", "study",
                      "sensitivity", "uncertainty", "validation", "calibration", "RMSE",
                      "bias", "parameter", "model structure", "flux", "eddy covariance",
                      "remote sensing", "Earth observation", "Sentinel", "lidar", "CCI",
                      "inventory comparison", "Tier 2", "Tier 3", "reproducible", "dataset",
                      "DOI"],
        decisions=[
            "whether the twins' outputs are fit for a research purpose: process "
            "representation, resolution, calibration and validation status",
            "which experiments to run: scenario design, sensitivity and uncertainty "
            "analysis, comparison with observations or inventories (IPCC Tier 1-3)",
            "which data to collect next (field plots, flux towers, EO products) to test or "
            "constrain the models",
            "how to report, cite and archive results reproducibly (FAIR data, open access, "
            "funder data policies, software citation)",
        ],
        needs=[
            "methods first: model name and version, process equations or references, "
            "parameter state (calibrated, learned, default), drivers and input datasets with "
            "versions and DOIs, spatial and temporal resolution",
            "uncertainty decomposed where the agents allow it (parameter, driver, structural) "
            "and validation metrics as the agents report them, with calibration and "
            "validation kept apart",
            "sensitivity of outputs to the main assumptions (e.g. water-table depth, "
            "emission factors, GWP metric)",
            "a reproducible record: every tool call with arguments, the agents' provenance, "
            "and enough detail to rerun the analysis",
        ],
        follow_ups=[
            FollowUp("What is the research aim: which response variable, hypothesis or "
                     "comparison is the analysis for?",
                     "an exploratory characterisation of the variables the agent models",
                     "the question names a topic but no variable or hypothesis"),
            FollowUp("What spatial extent, resolution and period should the analysis cover?",
                     "the agent's native resolution and pilot extent, and its reference year",
                     "extent or period is unclear"),
            FollowUp("Do you want a single central run or a sensitivity analysis over a "
                     "range of an input (which input and range)?",
                     "a central run plus a one-at-a-time sweep of the most influential input "
                     "the agent exposes", "results will be used to draw conclusions"),
        ],
        framing=[
            "Scientific register: precise terms, SI units, symbols defined, sign "
            "conventions stated (positive flux = emission), GWP set named (e.g. AR6 GWP100).",
            "Methods before results; keep observation, calibration, validation and scenario "
            "output explicitly apart.",
            "Report uncertainty and validation statistics exactly as the agents give them; "
            "do not inflate precision or claim significance that was not tested.",
            "Discuss limitations and alternative explanations; suggest falsifiable tests "
            "and the data that would constrain the result.",
            "Cite the agents' data and model sources (DOIs where given) and the [R#] calls.",
        ],
        section_title="Methods, uncertainty and reproducibility",
        section_brief=(
            "The models and data behind each result (from the agents' provenance), parameter "
            "state, what was calibrated and what was validated and how well (only metrics the "
            "agents returned), the main sources of uncertainty and how sensitive the result "
            "is to them, how to reproduce the analysis (the logged calls), and suggested "
            "experiments or observations that would test or constrain the result. No numbers "
            "that did not come from the agents."),
        context=[
            ("The FAIR principles ask that research data be findable, accessible, "
             "interoperable and reusable.", "fair"),
            ("UKRI requires peer-reviewed articles from UKRI-funded research submitted from "
             "1 April 2022 to be open access on publication.", "ukrioa"),
            ("NERC-funded data must be deposited in a NERC data centre and made openly "
             "available within two years of collection.", "nercdata"),
            ("National inventories follow the IPCC 2006 Guidelines and 2019 Refinement, "
             "with Tier 1 default factors, Tier 2 country-specific factors and Tier 3 "
             "models or measurements.", "ipcc2019"),
            ("CO2-equivalents depend on the metric: AR6 GWP100 values differ from the AR5 "
             "values still used in some reporting, so the GWP set must be stated.", "ar6gwp"),
            ("CEOS Land Product Validation defines validation stages 1-4, from a few "
             "reference sites to uncertainties well quantified over many sites and updated "
             "systematically.", "ceoslpv"),
            ("Good practice for EO-based land change estimates is design-based area "
             "estimation with an accuracy assessment from a probability sample.", "olofsson"),
            ("The Gemini Principles say national digital twins should have a clear purpose, "
             "be trustworthy (secure, open, quality data) and function through federation "
             "and curation.", "gemini"),
        ],
        caveats=[
            "Results are outputs of research-grade models at the versions and parameter "
            "state reported in the provenance; learned or assimilated parameters can change "
            "between runs, so cite the version and the logged calls.",
            "Validation statements cover only what the agents report; skill outside the "
            "calibration domain (sites, years, management) has not been established here.",
            "Uncertainty ranges are those the agents compute; structural uncertainty between "
            "alternative models is generally not included.",
        ],
        sources=["fair", "ukrioa", "nercdata", "ipcc2019", "ar6gwp", "ceoslpv", "olofsson",
                 "gcos", "ebv", "gemini", "swcite", "gum", "naei"],
    ),
]}

GENERAL = "general"
PERSONA_IDS = [*PERSONAS, GENERAL]


def get(persona_id: str) -> Persona | None:
    """The persona with this id, or None for 'general'. Raises on unknown ids."""
    if persona_id == GENERAL:
        return None
    if persona_id not in PERSONAS:
        raise ValueError(f"unknown persona {persona_id!r}; choose from {PERSONA_IDS}")
    return PERSONAS[persona_id]


def prompt_section() -> str:
    """The personas part of the system prompt (identical on every turn, so it is cached)."""
    out = [
        "User personas",
        "",
        "You are trained to serve four personas. Before your first agent call, call "
        "`set_persona` with the persona the user most likely belongs to (from what they say "
        "about themselves, the place and scale of the question and the vocabulary they use), "
        "or 'general' (for NGOs, the public, or when there is no signal). If the "
        "persona is genuinely unclear and it would change the report materially, you may "
        "include 'Which best describes you: policy-maker, farmer or land manager, green "
        "finance, or research scientist?' among your follow-up questions. When the persona is fixed by the "
        "application, use it. Then adapt to the persona throughout: the follow-up questions "
        "you ask, the defaults and assumptions you record, the agent calls you choose, the "
        "framing and tone, and the persona section of the report "
        "(`persona_section_markdown` in write_report). The context facts below are for "
        "framing and naming relevant policies, schemes and standards; they are not data, and "
        "the rule that every number comes from an agent still applies.",
        "",
    ]
    for p in PERSONAS.values():
        out += [f"Persona `{p.id}`: {p.label}", f"Who: {p.who}",
                "Typical cues: " + ", ".join(p.recognise_by) + ".",
                "Decisions they take: " + "; ".join(p.decisions) + ".",
                "What they need from the twins: " + "; ".join(p.needs) + ".",
                "Follow-up questions worth asking (only when the condition holds; give the "
                "default):"]
        out += [f"  - {f.question} Default: {f.default}. Ask when: {f.when}."
                for f in p.follow_ups]
        out += ["How to write for them:"] + [f"  - {x}" for x in p.framing]
        out += [f"Persona section of the report, titled '{p.section_title}': {p.section_brief}",
                "Context (reviewed " + REVIEWED + "):"]
        out += [f"  - {fact} [{SOURCES[k].publisher}, {SOURCES[k].year}]"
                for fact, k in p.context]
        out.append("")
    return "\n".join(out)


def sources_markdown(persona_id: str) -> list[str]:
    """Reference list for the report of one persona."""
    p = get(persona_id)
    if p is None:
        return []
    return [f"{SOURCES[k].publisher} ({SOURCES[k].year}). {SOURCES[k].title}. {SOURCES[k].url}"
            for k in p.sources]
