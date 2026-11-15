"""England's cattle, sheep and goat numbers, mapped onto the inventory categories.

Source: Defra, *Farming statistics: final land use, livestock populations and agricultural
workforce at 1 June 2020, England* (published 22 December 2020), Table 7 (cattle, from the
Cattle Tracing System), Table 9 (sheep and lambs) and Table 11 (goats), thousand head.
June 2020 matches the reference year of the Malek et al. livestock maps (about 2020).

Each census row is assigned to the closest inventory category of Table A 5.1.8 (see
``factors.py``). The assignment is DT2's and is listed in the README:

* Female dairy cattle aged 2+ that are not yet in the herd are "dairy heifers"; those aged 1-2
  "dairy replacements >1 year".
* Beef females aged 2+ outside the herd are "heifers for breeding"; beef females aged 1-2
  "beef females for slaughter".
* Male cattle aged 2+ are "bulls for breeding", aged 1-2 "steers". Most are dairy-bred, but the
  inventory factors for them do not depend on the breed of the dam.
* All cattle under one year use the inventory's dairy-calf factor (the inventory gives none for
  beef calves).
* "Other sheep 1 year and over" use the ewe factor.

Groups: the dairy herd and its followers are reported as ``dairy``; beef cows, their followers
and all male and young cattle as ``beef_other``; sheep and goats separately.
"""

from __future__ import annotations

CENSUS_SOURCE = ("Defra June Survey of Agriculture, England, 1 June 2020 (final, 22 Dec 2020): "
                 "Tables 7, 9 and 11; cattle from the Cattle Tracing System")

# thousand head, England, 1 June 2020: (census row, inventory category, group)
ENGLAND_2020 = [
    ("Dairy herd (cows in milk and in calf)", 1112, "dairy_cows", "dairy"),
    ("Other female dairy cattle, 2 years and over", 152, "dairy_heifers", "dairy"),
    ("Female dairy cattle, 1-2 years", 304, "dairy_replacements", "dairy"),
    ("Female dairy cattle, under 1 year", 321, "calves", "dairy"),
    ("Beef herd (suckler cows)", 688, "beef_cows", "beef_other"),
    ("Other female beef cattle, 2 years and over", 189, "heifers_breeding", "beef_other"),
    ("Female beef cattle, 1-2 years", 475, "beef_females_slaughter", "beef_other"),
    ("Female beef cattle, under 1 year", 534, "calves", "beef_other"),
    ("Male cattle, 2 years and over", 176, "bulls_breeding", "beef_other"),
    ("Male cattle, 1-2 years", 538, "steers", "beef_other"),
    ("Male cattle, under 1 year", 679, "calves", "beef_other"),
    ("Female breeding flock", 6977, "ewes", "sheep"),
    ("Lambs under 1 year", 7678, "lambs", "sheep"),
    ("Rams", 184, "rams", "sheep"),
    ("Other sheep 1 year and over", 187, "ewes", "sheep"),
    ("Goats", 90, "goats", "goats"),
]
TOTALS_2020 = {"cattle": 5168, "sheep": 15027, "goats": 90}   # thousand head, census totals
GROUPS = ("dairy", "beef_other", "sheep", "goats")
SPECIES_OF_GROUP = {"dairy": "cattle", "beef_other": "cattle", "sheep": "sheep",
                    "goats": "goats"}

# Livestock units per head, Eurostat coefficients (used only for stocking rates).
LSU = {"dairy_cows": 1.0, "dairy_heifers": 0.8, "dairy_replacements": 0.7, "calves": 0.4,
       "beef_cows": 0.8, "heifers_breeding": 0.8, "beef_females_slaughter": 0.7,
       "bulls_breeding": 1.0, "steers": 0.7, "ewes": 0.1, "rams": 0.1, "lambs": 0.1,
       "goats": 0.1}


def england_heads() -> dict[str, dict[str, float]]:
    """Heads per inventory category within each group (England, June 2020)."""
    out: dict[str, dict[str, float]] = {g: {} for g in GROUPS}
    for _, k, cat, grp in ENGLAND_2020:
        out[grp][cat] = out[grp].get(cat, 0.0) + k * 1000.0
    return out


def group_structure() -> dict[str, dict[str, float]]:
    """Fraction of each group's heads in each category (sums to 1 per group)."""
    h = england_heads()
    return {g: {c: n / sum(cats.values()) for c, n in cats.items()} for g, cats in h.items()}


def group_totals() -> dict[str, float]:
    return {g: sum(c.values()) for g, c in england_heads().items()}
