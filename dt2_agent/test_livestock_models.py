"""Tests for the DT2 model package (``livestock``): run with `pytest dt2_agent`.

They pin the package to its sources: the inventory factors (NID 2025 Annex A 5.1.3), the June
Survey 2020 head counts, the Farm Carbon Calculator's equations, the shipped data layers and
the shipped calibration against the NAEI map.
"""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from livestock import assimilation, calibration, factors, herd, maps, model  # noqa: E402
from livestock.grid import GRID  # noqa: E402

CFG = calibration.calibrated_config()
CHESHIRE = model.Area(lat=53.15, lon=-2.55, radius_km=15)
EDEN = model.Area(lat=54.6, lon=-2.5, radius_km=30)


# --------------------------------------------------------------------------- #
# emission factors: the inventory's, as the Farm Carbon Calculator uses them
# --------------------------------------------------------------------------- #
def test_inventory_factors_table_a518():
    c = factors.CATEGORIES
    assert (c["dairy_cows"].enteric, c["dairy_cows"].manure) == (123.28, 38.03)
    assert (c["beef_cows"].enteric, c["beef_cows"].manure) == (75.99, 10.72)
    assert (c["steers"].enteric, c["steers"].manure) == (49.91, 5.84)
    assert (c["ewes"].enteric, c["ewes"].manure) == (6.98, 0.18)
    assert (c["lambs"].enteric, c["lambs"].manure) == (3.05, 0.07)
    assert (c["goats"].enteric, c["goats"].manure) == (9.00, 0.39)
    assert factors.MCF["liquid"] == 17 and factors.MCF["pasture"] == 1.0
    for cat in c.values():
        assert sum(factors.default_shares(cat).values()) == pytest.approx(100.0)


def test_manure_decomposition_returns_inventory_ef():
    for cat in factors.CATEGORIES.values():
        assert cat.manure_ef() == pytest.approx(cat.manure, rel=1e-12)
    dairy = factors.CATEGORIES["dairy_cows"]
    assert dairy.mcf_weighted() == pytest.approx(0.61 * 17 + 0.09 * 0.1 + 0.08 * 17 + 0.20 * 1
                                                 + 0.02 * 3)
    # VS x Bo x 0.67 of a UK dairy cow: ~1,970 kg VS/yr x 0.24 m3/kg x 0.67 kg/m3 = 317 kg
    assert dairy.methane_potential == pytest.approx(316.9, abs=0.1)


def test_farm_methane_is_calculator_eq_1a():
    r = factors.farm_methane({"dairy_cows": 100, "ewes": 500})
    enteric = 100 * 123.28 + 500 * 6.98
    manure = 100 * 38.03 + 500 * 0.18
    assert r["enteric_kg"] == pytest.approx(enteric)
    assert r["t_co2e"] == pytest.approx((enteric + manure) * 28 / 1000)   # AR5, as the calculator
    assert factors.farm_methane({"dairy_cows": 1}, "AR6")["t_co2e"] == pytest.approx(
        161.31 * 27 / 1000)


def test_manure_scenarios_move_the_right_way():
    dairy = factors.CATEGORIES["dairy_cows"]
    more_grazing = dairy.manure_ef(factors.shares_with(dairy, pasture_pct=50))
    all_housed = dairy.manure_ef(factors.shares_with(dairy, pasture_pct=0))
    digested = dairy.manure_ef(factors.shares_with(dairy, ad_pct_of_housed=100))
    assert more_grazing < dairy.manure < all_housed
    assert digested < dairy.manure
    s = factors.shares_with(dairy, pasture_pct=50, ad_pct_of_housed=40)
    assert sum(s.values()) == pytest.approx(100.0) and s["pasture"] == 50


# --------------------------------------------------------------------------- #
# census and data layers
# --------------------------------------------------------------------------- #
def test_census_rows_add_up_to_june_survey_totals():
    tot = herd.group_totals()
    assert tot["dairy"] + tot["beef_other"] == pytest.approx(herd.TOTALS_2020["cattle"] * 1e3)
    assert tot["sheep"] == pytest.approx(herd.TOTALS_2020["sheep"] * 1e3, abs=1e3)  # rounding
    assert tot["goats"] == 90e3
    for g, s in herd.group_structure().items():
        assert sum(s.values()) == pytest.approx(1.0)


def test_layers_cover_england():
    L = maps.layers()
    assert L["england"].sum() == pytest.approx(130_524, abs=10)          # km2 of England
    assert L["le_total"].sum() / 1e6 == pytest.approx(13.05, abs=0.01)  # Mha, all segments
    assert L["le_total"][L["england"]].sum() / 1e6 == pytest.approx(12.99, abs=0.01)
    le = maps.le_classes()
    assert le["Improved Grassland"] / 1e3 == pytest.approx(2010, abs=5)          # kha
    assert le["Acid, Calcareous, Neutral Grassland"] / 1e3 == pytest.approx(3330, abs=5)
    assert L["naei_ch4_t"][L["england"]].sum() / 1e3 == pytest.approx(547.3, abs=0.5)  # kt
    # 5 LSU/ha cap; a 1 km cell catches 100 +/- a few rotated 100 m pixels of the LAEA grid
    assert L["cattle_other"].max() <= 105 * 5.0
    assert L["cattle_other_raw"].max() > 10_000            # the artefact the cap removes


def test_refine_keeps_block_totals():
    rng = np.random.default_rng(0)
    w, g = rng.random(GRID.shape), rng.random(GRID.shape)
    out = maps.refine(w, g, 10)
    assert maps._blocks(out, 10) == pytest.approx(maps._blocks(w, 10))
    assert np.array_equal(maps.refine(w, g, 0), w)


def test_allocation_conserves_heads():
    h = maps.allocate(CFG)
    for g, n in herd.group_totals().items():
        assert h[g].sum() == pytest.approx(n, rel=1e-9)
        assert (h[g][~maps.layers()["england"]] == 0).all()


# --------------------------------------------------------------------------- #
# England totals and scenarios
# --------------------------------------------------------------------------- #
def test_england_methane():
    r = model.run(model.Area(), CFG)
    assert r["cells_km2"] == maps.layers()["england"].sum()
    assert r["total_t_ch4"] / 1e3 == pytest.approx(491.7, abs=0.5)     # kt CH4, England 2020
    assert r["enteric_t_ch4"] / r["total_t_ch4"] == pytest.approx(0.861, abs=0.002)
    g = r["groups"]
    assert g["dairy"]["total_t_ch4"] / 1e3 == pytest.approx(220.3, abs=0.2)
    assert g["sheep"]["total_t_ch4"] / 1e3 == pytest.approx(76.8, abs=0.2)
    assert r["t_co2e_ar5"] == pytest.approx(28 * r["total_t_ch4"])
    # NAEI SNAP 10 (with pigs, poultry, horses, deer) is 547 kt: DT2 ~10 % below
    assert 0.85 < r["total_t_ch4"] / 547_273 < 0.95


def test_scenarios():
    base = model.run(CHESHIRE, CFG)
    less = model.run(CHESHIRE, CFG, sc=model.Scenario(herd_change_pct={"dairy": -50}))
    assert less["groups"]["dairy"]["total_t_ch4"] == pytest.approx(
        0.5 * base["groups"]["dairy"]["total_t_ch4"])
    assert less["groups"]["sheep"] == base["groups"]["sheep"]
    ad = model.run(CHESHIRE, CFG, sc=model.Scenario(ad_pct_of_housed=50))
    assert ad["manure_t_ch4"] < base["manure_t_ch4"] and ad["enteric_t_ch4"] == pytest.approx(
        base["enteric_t_ch4"])
    feed = model.run(CHESHIRE, CFG, sc=model.Scenario(enteric_reduction_pct={"dairy": 30}))
    assert feed["groups"]["dairy"]["enteric_t_ch4"] == pytest.approx(
        0.7 * base["groups"]["dairy"]["enteric_t_ch4"])
    loss = model.run(CHESHIRE, CFG, sc=model.Scenario(grassland_loss_pct=20))
    assert loss["groups"]["dairy"]["heads"] == pytest.approx(
        0.8 * base["groups"]["dairy"]["heads"], rel=0.02)
    cap = model.run(CHESHIRE, CFG, sc=model.Scenario(max_stocking_lsu_ha=1.0))
    assert cap["total_t_ch4"] < base["total_t_ch4"]
    assert model.run(CHESHIRE, CFG, sc=model.Scenario(max_stocking_lsu_ha=50))[
        "total_t_ch4"] == pytest.approx(base["total_t_ch4"])


# --------------------------------------------------------------------------- #
# calibration against NAEI
# --------------------------------------------------------------------------- #
def test_shipped_calibration_reproduces():
    shipped = calibration.load()
    assert shipped["chosen"] == {"alpha_other": 0.0, "block_km": 10, "acn_weight": 0.5}
    eng = maps.layers()["england"]
    val = eng & ~calibration.checkerboard()
    s = calibration.skill(calibration.total_ch4(CFG), val)
    assert s["r_1km"] == pytest.approx(shipped["holdout"]["r_1km"], abs=1e-9)
    assert s["r_1km"] == pytest.approx(0.653, abs=0.001)
    assert s["r_10km"] == pytest.approx(0.934, abs=0.001)


def test_living_england_improves_on_malek_alone():
    """The grassland map is worth having: better 1 km pattern on hold-out squares."""
    ref = calibration.load()["reference_holdout"]
    hold = calibration.load()["holdout"]
    assert hold["r_1km"] > ref["malek_grazing_layers_no_living_england"]["r_1km"] + 0.08
    assert hold["r_1km"] > ref["malek_all_layers_no_living_england"]["r_1km"] + 0.1


# --------------------------------------------------------------------------- #
# learning
# --------------------------------------------------------------------------- #
PRIOR = {"cattle": 1.0, "sheep": 1.0, "cattle_sd": 0.3, "sheep_sd": 0.3}


def test_assimilation_recovers_synthetic_truth():
    m = EDEN.mask()      # cattle in the valley, sheep on the fells: both factors identifiable
    grid = model.emissions_grid(CFG, m, {})
    truth = model.emissions_grid(CFG, m, {"cattle": 1.4, "sheep": 0.6})
    obs = sum(d["enteric"] + d["manure"] for d in truth.values())
    post, _ = assimilation.from_cells(PRIOR, grid, m, obs, other_fraction=0.0, rel_sd=0.05)
    assert post["cattle"] == pytest.approx(1.4, abs=0.02)
    assert post["sheep"] == pytest.approx(0.6, abs=0.02)
    total = float(obs.sum())
    post_t, d = assimilation.from_total(PRIOR, grid, total, 0.01 * total)
    assert d["predicted_after_t_ch4"] == pytest.approx(total, rel=0.02)


def test_naei_learning_improves_unseen_cells():
    """Learn from half of Cheshire's cells, predict the other half better."""
    m = CHESHIRE.mask()
    grid = model.emissions_grid(CFG, m, {})
    naei = maps.layers()["naei_ch4_t"]
    r, c = np.indices(GRID.shape)
    train, test = m & ((r + c) % 2 == 0), m & ((r + c) % 2 == 1)
    post, _ = assimilation.from_cells(PRIOR, grid, m, naei, sample=train & (naei > 0))
    tot = lambda s: sum((d["enteric"] + d["manure"]) for d in  # noqa: E731
                        model.emissions_grid(CFG, test, s).values()).sum()
    target = 0.95 * naei[test].sum()
    before = abs(tot({}) - target)
    after = abs(tot({"cattle": post["cattle"], "sheep": post["sheep"]}) - target)
    assert post["cattle"] > 1.1           # a dairy county has more cattle methane than average
    assert after < 0.5 * before


# --------------------------------------------------------------------------- #
# server safety
# --------------------------------------------------------------------------- #
def test_package_is_server_safe(tmp_path):
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from livestock import model, calibration\n"
            "model.run(model.Area(lat=52.0, lon=-1.0, radius_km=5), calibration.calibrated_config())\n"
            "print(sorted(m for m in sys.modules if m.split('.')[0] in "
            "('matplotlib', 'pandas', 'rasterio')))" % str(HERE))
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == "[]"          # no plotting, pandas or GDAL at run time
    assert list(tmp_path.iterdir()) == []      # no files written
