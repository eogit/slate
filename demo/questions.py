"""Demonstration questions: one per persona, each needing several digital twins.

Every question is written so that no single twin can answer it. The orchestrator has to split
it into parts, send each part to the twin that covers it, line the outputs up on a common basis
(t CO2e per hectare or per landscape, the same GWP, the same horizon) and synthesise one answer
framed for the persona. ``twins`` lists the agents a good answer needs; the demo checks that at
least two of them were actually called.

The places are chosen where the twins' coverage overlaps: the Fens (DT8 drained peat, the DT6
Fens tile, DT2 everywhere in England) and Breckland (DT4 Thetford Forest, the DT6 Breckland
tile, DT2).
"""

QUESTIONS = {
    "policy": {
        "title": "Which land-use change buys the most abatement per hectare in East Anglia?",
        "question": (
            "For the Land Use Framework we need to compare the greenhouse-gas return per hectare "
            "of three land-use changes in East Anglia over the next 25 years: raising the water "
            "table on drained Fenland arable peat, planting new woodland on arable land in "
            "Breckland, and planting hedgerow and agroforestry trees on Fenland farms. How does "
            "each compare per hectare, and how big is livestock methane in the same area by "
            "comparison? Which should be prioritised, and how confident can we be?"),
        "twins": ["dt8", "dt4", "dt6", "dt2"],
        "why": ("Peat rewetting (DT8), afforestation (DT4) and trees outside woodland (DT6) are "
                "modelled by different twins with different units and horizons; livestock "
                "methane (DT2) is the benchmark. Only the orchestrator can put them on one "
                "per-hectare, per-year basis."),
    },
    "farmer": {
        "title": "Where are the emissions on a mixed Fenland farm, and what would help?",
        "question": (
            "I'm a tenant farmer near Ely on 180 ha: 60 ha of potatoes and 40 ha of winter wheat "
            "on deep peat, 80 ha of grass, 90 suckler cows with followers and 200 breeding ewes, "
            "and a few kilometres of hedges. Where do most of my farm's emissions come from, and "
            "what would raising the water table on the potato ground, a methane-reducing feed "
            "additive and planting hedgerow trees each do?"),
        "twins": ["dt8", "dt2", "dt6"],
        "why": ("The peat soils (DT8), the herd (DT2) and the farm's trees (DT6) are three "
                "different twins; the farmer wants one ranked list of sources and options."),
    },
    "finance": {
        "title": "Which nature-based carbon project type is most robust to model uncertainty?",
        "question": (
            "We are building a portfolio of UK nature-based carbon projects that we may later "
            "tokenise. For East Anglia, compare the expected abatement per hectare and its "
            "uncertainty for a Peatland Code rewetting project on Fenland cropland, a new "
            "Corsican pine woodland near Thetford of the kind registered under the Woodland "
            "Carbon Code, and hedgerow agroforestry on Fenland farms. How well validated is "
            "each model, and which project type is the most robust basis for credits?"),
        "twins": ["dt8", "dt4", "dt6"],
        "why": ("Each project type sits in a different twin, and each twin has its own "
                "validation evidence (inventory comparison, CCI hold-out, lidar hold-out). The "
                "credit question is really about comparing those uncertainties side by side."),
    },
    "research": {
        "title": "How well do the twins reproduce independent observations?",
        "question": (
            "Across the SLATE twins, how good is each model at reproducing independent "
            "observations, and where is the structural uncertainty largest? Compare the hold-out "
            "skill of the forest biomass models at Thetford, of the tree-height models for trees "
            "outside woodland in Breckland and the Fens against persistence, of the livestock "
            "methane map against the NAEI over Norfolk and Suffolk, and of the peatland model "
            "against the UK Peatland Inventory emission factors."),
        "twins": ["dt4", "dt6", "dt2", "dt8"],
        "why": ("Each twin validates against a different observing system (Biomass CCI, EA "
                "lidar, NAEI, the Peatland Inventory). A cross-twin skill comparison needs all "
                "four validation tools and a common reading of their metrics."),
    },
    "ngo": {
        "title": "What is at stake for trees and nature recovery in Breckland?",
        "question": (
            "We are a conservation charity working in Breckland. How much carbon is held in the "
            "hedgerow and field trees outside the forest, what would ash dieback do to it and how "
            "much would replanting recover? How has the biomass of Thetford Forest changed since "
            "2015, and how much grassland and grazing livestock is there in the same area for "
            "heathland and grassland restoration?"),
        "twins": ["dt6", "dt4", "dt2"],
        "why": ("Trees outside woodland (DT6), the forest (DT4) and the grazing landscape (DT2) "
                "are the three parts of the Breckland mosaic the charity cares about."),
    },
    "general": {
        "title": "Is a potato field, a hedge or a cow the bigger climate issue in the Fens?",
        "question": (
            "I live in the Fens. Which matters more for the climate here: the drained peat fields, "
            "the cattle and sheep, or the trees in hedges and around farms? What could change it?"),
        "twins": ["dt8", "dt2", "dt6"],
        "why": ("A plain question that spans three twins; the answer has to put soil, livestock "
                "and trees on one scale without jargon."),
    },
}
