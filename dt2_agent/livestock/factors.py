"""Methane emission factors for cattle, sheep and goats, as the Farm Carbon Calculator uses them.

Why these factors
-----------------
The Farm Carbon Toolkit's *Farm Carbon Calculator* (methodology v3.6, April 2026, Section 11.6,
and the June 2025 livestock update) computes livestock methane at its default "Tier 2" with

    enteric CH4 (t CO2e) = default enteric EF (kg CH4/head/yr) x head x 28 / 1000      (Eq. 1a)

where the default EF is "the UK GHG inventories value", and manure methane with

    manure CH4 (t CO2e) = kg manure x (Bo x 0.67) x (MCF / 100) x 28 / 1000            (Eq. 4)

with the methane-producing capacity Bo and the storage system's methane conversion factor MCF.
It uses the IPCC AR5 GWP100 of 28 for methane. DT2 uses the same inventory factors so that a
field, a farm and a landscape give the same answer whichever tool computes them.

Source of the numbers
---------------------
UK Greenhouse Gas Inventory 1990 to 2023, National Inventory Document (NID 2025, Issue 1,
Ricardo for DESNZ), Annex A 5.1.3:

* Table A 5.1.8  Methane emission factors for livestock emissions for 2023 (enteric and manure,
  kg CH4/head/year);
* Table A 5.1.9  Methane conversion factors for manure management systems in the UK (%);
* Table A 5.1.11 Distribution of animal waste management systems (%), 2023.

The calculator's June 2025 livestock update cites the previous edition (1990-2022 annexes); the
inventory revises these factors every year, so DT2 takes the latest edition and records it.

The manure factor is split into a methane potential and a weighted MCF
------------------------------------------------------------------------
The inventory gives one manure EF per head, which already folds in the UK mix of storage
systems. To let scenarios change that mix (longer grazing, anaerobic digestion) DT2 writes it
in the form of the calculator's Eq. 4,

    EF_manure = P x sum_s share_s x MCF_s / 100,      P = VS x Bo x 0.67  (kg CH4/head/yr)

and back-calculates the methane potential P of each category from the inventory EF and the
inventory's 2023 system shares. With the inventory shares DT2 therefore returns exactly the
inventory EF; with other shares it returns what the calculator's Eq. 4 would give.
"""

from __future__ import annotations

from dataclasses import dataclass

GWP100 = {"AR5": 28.0, "AR6": 27.0}   # CH4 (AR6: non-fossil). AR5 is the calculator's choice.

FACTOR_SOURCE = ("UK GHG Inventory 1990-2023 (NID 2025, Ricardo/DESNZ), Annex Tables A 5.1.8, "
                 "A 5.1.9 and A 5.1.11; the UK-inventory default 'Tier 2' factors of the Farm "
                 "Carbon Calculator (methodology v3.6, April 2026, Eqs 1a and 4)")

# Table A 5.1.9: methane conversion factor (%) per manure management system.
MCF = {
    "liquid": 17.0,          # slurry; crusted and uncrusted not distinguished
    "daily_spread": 0.1,
    "solid_cattle": 17.0,    # deep bedding / farmyard manure, cattle and pigs
    "solid_sheep": 2.0,      # farmyard manure, sheep (DT2 also uses it for goats, see README)
    "pasture": 1.0,          # pasture, range and paddock (excreta deposited while grazing)
    "anaerobic_digestion": 3.0,   # cattle
}
SYSTEMS = ("liquid", "daily_spread", "solid", "pasture", "anaerobic_digestion")

# Table A 5.1.11: share (%) of excreta by system, 2023. Order as SYSTEMS.
AWMS = {
    "dairy_cows": (61, 9, 8, 20, 2),
    "other_cattle": (18, 14, 17, 49, 1),
    "ewes": (0, 0, 8, 92, 0),
    "rams": (0, 0, 1, 99, 0),
    "lambs": (0, 0, 1, 99, 0),
    "goats": (0, 0, 8, 92, 0),
}


@dataclass(frozen=True)
class Category:
    """One inventory livestock category with its 2023 UK factors."""
    code: str
    name: str
    species: str            # cattle, sheep or goats
    enteric: float          # kg CH4/head/yr, Table A 5.1.8
    manure: float           # kg CH4/head/yr, Table A 5.1.8
    awms: str               # key into AWMS

    @property
    def solid_mcf(self) -> float:
        return MCF["solid_cattle"] if self.species == "cattle" else MCF["solid_sheep"]

    def mcf_weighted(self, shares: dict[str, float] | None = None) -> float:
        """Share-weighted MCF (%) for this category; ``shares`` in % summing to 100."""
        s = shares or default_shares(self)
        mcf = dict(MCF, solid=self.solid_mcf)
        return sum(s[k] / 100.0 * mcf[k] for k in SYSTEMS)

    @property
    def methane_potential(self) -> float:
        """P = VS x Bo x 0.67 (kg CH4/head/yr), back-calculated from the inventory EF."""
        return self.manure / (self.mcf_weighted() / 100.0)

    def manure_ef(self, shares: dict[str, float] | None = None) -> float:
        """Manure CH4 (kg/head/yr) for a mix of systems (calculator Eq. 4 form)."""
        return self.methane_potential * self.mcf_weighted(shares) / 100.0


def default_shares(cat: Category) -> dict[str, float]:
    """Inventory system shares (%) of a category, rescaled to sum to exactly 100.

    The published row for "all other cattle" sums to 99 because of rounding.
    """
    row = AWMS[cat.awms]
    return {k: 100.0 * v / sum(row) for k, v in zip(SYSTEMS, row)}


# Table A 5.1.8 (2023). The inventory has no separate beef-calf factor; DT2 uses the dairy-calf
# factor for all calves under one year (an assumption recorded in the README).
CATEGORIES: dict[str, Category] = {c.code: c for c in (
    Category("dairy_cows", "Dairy cows", "cattle", 123.28, 38.03, "dairy_cows"),
    Category("dairy_heifers", "Dairy heifers", "cattle", 53.72, 5.96, "other_cattle"),
    Category("dairy_replacements", "Dairy replacements >1 year", "cattle", 50.18, 5.78,
             "other_cattle"),
    Category("calves", "Calves <1 year (dairy-calf factor)", "cattle", 42.53, 3.67,
             "other_cattle"),
    Category("beef_cows", "Beef cows", "cattle", 75.99, 10.72, "other_cattle"),
    Category("beef_females_slaughter", "Beef females for slaughter", "cattle", 48.73, 5.70,
             "other_cattle"),
    Category("bulls_breeding", "Bulls for breeding", "cattle", 59.13, 8.28, "other_cattle"),
    Category("heifers_breeding", "Heifers for breeding", "cattle", 48.23, 6.25, "other_cattle"),
    Category("steers", "Steers", "cattle", 49.91, 5.84, "other_cattle"),
    Category("ewes", "Ewes", "sheep", 6.98, 0.18, "ewes"),
    Category("rams", "Rams", "sheep", 8.25, 0.23, "rams"),
    Category("lambs", "Lambs", "sheep", 3.05, 0.07, "lambs"),
    Category("goats", "Goats", "goats", 9.00, 0.39, "goats"),
)}


def shares_with(cat: Category, *, pasture_pct: float | None = None,
                ad_pct_of_housed: float | None = None) -> dict[str, float]:
    """Change a category's system mix.

    ``pasture_pct``: share of excreta deposited at pasture (%). The housed remainder keeps the
    inventory's proportions between the housed systems.
    ``ad_pct_of_housed``: share of the housed liquid and solid manure that goes to anaerobic
    digestion (%), taken from the liquid and solid stores in proportion. Daily spread stays.
    """
    s = default_shares(cat)
    if pasture_pct is not None:
        housed = {k: v for k, v in s.items() if k != "pasture"}
        tot = sum(housed.values())
        rest = 100.0 - pasture_pct
        s = {k: (v / tot * rest if tot > 0 else (rest if k == "solid" else 0.0))
             for k, v in housed.items()}
        s["pasture"] = float(pasture_pct)
    if ad_pct_of_housed is not None:
        store = s["liquid"] + s["solid"] + s["anaerobic_digestion"]
        target = store * ad_pct_of_housed / 100.0
        move = max(0.0, target - s["anaerobic_digestion"])
        ls = s["liquid"] + s["solid"]
        if ls > 0 and move > 0:
            s["liquid"] -= move * s["liquid"] / ls
            s["solid"] -= move * s["solid"] / ls
            s["anaerobic_digestion"] += move
    return s


def farm_methane(heads: dict[str, float], gwp: str = "AR5", *,
                 pasture_pct: dict[str, float] | None = None,
                 enteric_reduction_pct: dict[str, float] | None = None) -> dict:
    """Annual methane of a herd given head counts per category: the calculator's Tier 2.

    Returns kg CH4 by category and gas source plus the total in t CO2e.
    """
    out, ent_tot, man_tot = {}, 0.0, 0.0
    for code, n in heads.items():
        cat = CATEGORIES[code]
        shares = None
        if pasture_pct and code in pasture_pct:
            shares = shares_with(cat, pasture_pct=pasture_pct[code])
        e = n * cat.enteric * (1 - (enteric_reduction_pct or {}).get(code, 0.0) / 100.0)
        m = n * cat.manure_ef(shares)
        out[code] = {"heads": n, "enteric_kg": e, "manure_kg": m}
        ent_tot += e
        man_tot += m
    return {"by_category": out, "enteric_kg": ent_tot, "manure_kg": man_tot,
            "total_kg": ent_tot + man_tot,
            "t_co2e": (ent_tot + man_tot) * GWP100[gwp] / 1000.0, "gwp": gwp}
