"""Tests of the DT6 model package (``trees``): run with ``pytest dt6_agent``.

They check the science properties each module promises (the allometry and its inverse, the
size-age curve passes through the site index, the crown light-use model responds to
productivity, light and drought, the calibration recovers a known tree, height drops are
caught, carbon bookkeeping closes, ash dieback reduces carbon, change detection respects the
error threshold, attribution needs evidence, the Kalman filter moves productivity towards
the data), pin the inventory numbers of the pilots, check that rerunning the calibration
script reproduces the shipped file, and check that the package is server-safe.
"""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from trees import GROWTH_MODELS, make_model  # noqa: E402
from trees import allometry, assimilation, calibration, carbon, change  # noqa: E402
from trees import crown_lue, growth_curves, inventory, pilots, scenario, state  # noqa: E402

KEYS = list(pilots.PILOTS)


# --------------------------------------------------------------------------- #
# allometry
# --------------------------------------------------------------------------- #
def test_jucker_values_and_inverse():
    assert allometry.agb_kg(15, 10) == pytest.approx(425, rel=0.01)
    assert allometry.agb_kg(15, 10, 1.0) == pytest.approx(948, rel=0.01)
    # a mixture is the weighted mean of the two equations
    mix = allometry.agb_kg(15, 10, 0.3)
    assert mix == pytest.approx(0.7 * allometry.agb_kg(15, 10) + 0.3 * allometry.agb_kg(15, 10, 1))
    for h in (3.0, 12.0, 30.0):
        agb = allometry.agb_kg(h, 0.7 * h)
        assert allometry.height_for_agb(agb, 0.7) == pytest.approx(h, rel=1e-3)


def test_living_carbon_uses_root_shoot():
    agc, bgc = allometry.living_carbon_t(1000.0)
    assert agc == pytest.approx(0.5) and bgc == pytest.approx(0.5 * allometry.ROOT_SHOOT)


# --------------------------------------------------------------------------- #
# growth models
# --------------------------------------------------------------------------- #
def test_size_age_passes_through_site_index():
    m = growth_curves.SizeAgeModel()
    for si in (6.0, 15.0, 28.0):
        assert m.height(si, 50) == pytest.approx(si, rel=1e-9)
        assert m.height(si, 1000) == pytest.approx(growth_curves.HMAX_PER_SI * si, rel=1e-3)
    h = m.height(15, np.arange(0, 200))
    assert np.all(np.diff(h) >= 0)
    # projecting from the curve's own height gives the curve again
    assert m.project_height(15, m.height(15, 30), 10) == pytest.approx(m.height(15, 40))


def test_crown_lue_responds_to_productivity_and_light():
    clim = pilots.load_climate("breckland")
    m = crown_lue.CrownLUEModel(0.0, clim)
    t = m.height_table(np.array([20.0, 60.0]), 0.7)
    assert np.all(np.diff(t[:, 1]) > 0)                     # higher theta grows taller
    assert np.all(t[:, 1] > t[:, 0])                        # trees keep growing
    assert t[:, 0].min() >= crown_lue.H_START
    # half the radiation: less light, partly offset by less drought (lower evaporation)
    dark = replace(clim, solar_mj_m2_d=tuple(0.5 * x for x in clim.solar_mj_m2_d))
    assert crown_lue.effective_light(dark) < 0.85 * crown_lue.effective_light(clim)
    wet = pilots.load_climate("tyne_valley")
    wet_dark = replace(wet, solar_mj_m2_d=tuple(0.5 * x for x in wet.solar_mj_m2_d))
    assert crown_lue.effective_light(wet_dark) < 0.7 * crown_lue.effective_light(wet)


def test_crown_lue_drought_limits_light_use():
    clim = pilots.load_climate("breckland")
    dry = replace(clim, rain_mm=tuple(0.1 * x for x in clim.rain_mm))
    assert crown_lue.effective_light(dry) < crown_lue.effective_light(clim)


def test_crown_lue_needs_climate():
    with pytest.raises(ValueError):
        crown_lue.CrownLUEModel(0.0, None)


@pytest.mark.parametrize("name", GROWTH_MODELS)
def test_make_model(name):
    m = make_model(name, "cheshire")
    assert m.name == name and m.theta_grid.size > 10
    with pytest.raises(ValueError):
        make_model("3pg", "cheshire")


# --------------------------------------------------------------------------- #
# calibration on synthetic trees
# --------------------------------------------------------------------------- #
def _synthetic_inventory(model, theta, age, epochs=(2000.0, 2010.0, 2020.0), drop=None):
    """One lone tree per (theta, age), observed without error at three epochs."""
    theta, age = np.atleast_1d(theta).astype(float), np.atleast_1d(age).astype(float)
    n = theta.size
    ages = np.arange(0, 400.5, 0.5)
    table = model.height_table(ages, 0.7)
    t_ref = epochs[-1]

    def h_at(i, t):
        row = np.array([np.interp(theta[i], model.theta_grid, table[:, k])
                        for k in range(ages.size)])
        return float(np.interp(age[i] - (t_ref - t), ages, row))

    h_lz = np.array([[h_at(i, t) for t in epochs] for i in range(n)])
    if drop is not None:
        h_lz[:, 0] += drop                               # the tree was taller before a cut
    h_fz = h_lz[:, -1].copy()
    cd = 0.7 * h_fz
    return inventory.Inventory(
        key="synthetic", tow_id=np.array([str(i) for i in range(n)]), cls=np.zeros(n, int),
        area_m2=np.pi * (cd / 2) ** 2, n_trees=np.ones(n, int), crown_diam_m=cd,
        height_m=h_fz, h_fz=h_fz, fz_date=np.full(n, t_ref), lon=np.zeros(n), lat=np.zeros(n),
        x=np.zeros(n), y=np.zeros(n), epoch_year=np.array([int(e) for e in epochs]),
        h_lz=h_lz, date_lz=np.tile(np.array(epochs), (n, 1)), p_conifer=0.0)


@pytest.mark.parametrize("name", GROWTH_MODELS)
def test_calibration_recovers_synthetic_tree(name):
    m = make_model(name, "herefordshire")
    g = m.theta_grid
    truth = np.array([g[6], g[12], g[18]])
    inv = _synthetic_inventory(m, truth, np.array([25.0, 30.0, 20.0]))
    fit = calibration.fit_crowns(m, inv)
    # within two posterior SDs, and closer to the truth than the broad prior's centre
    assert np.all(np.abs(fit.theta - truth) < 2 * fit.theta_sd)
    mu, _ = calibration.theta_prior(m)
    far = np.abs(truth - mu) > 0.1 * (g[-1] - g[0])
    assert np.all(np.abs(fit.theta - truth)[far] < np.abs(mu - truth)[far])
    assert fit.theta[0] < fit.theta[1] < fit.theta[2]
    assert np.all(fit.n_obs == 4)
    assert not np.isfinite(fit.event_year).any()


def test_height_drop_is_an_event_and_old_heights_are_dropped():
    m = make_model("size_age", "herefordshire")
    inv = _synthetic_inventory(m, [15.0], [40.0], drop=8.0)
    t, h, s, ev, drop = calibration.observations(inv)
    # the 8 m cut, less the growth between 2000 and 2010, dated between the two flights
    assert ev[0] == pytest.approx(2005.0) and calibration.DROP_M < drop[0] < 8.0
    assert np.isnan(h[0, 1])                             # the 2000 epoch is gone
    assert np.isfinite(h[0, 2]) and np.isfinite(h[0, 3])


def test_same_night_first_and_last_return_is_not_a_drop():
    m = make_model("size_age", "herefordshire")
    inv = _synthetic_inventory(m, [15.0], [40.0])
    inv = replace(inv, h_fz=inv.h_fz + 5.0, height_m=inv.height_m + 5.0)
    *_, ev, _ = calibration.observations(inv)
    assert not np.isfinite(ev).any()


def test_empirical_prior_is_learned_from_multi_epoch_trees():
    m = make_model("size_age", "herefordshire")
    rng = np.random.default_rng(0)
    truth = rng.uniform(7, 9, 60)
    inv = _synthetic_inventory(m, truth, rng.uniform(15, 40, 60))
    prior = calibration.empirical_prior(m, inv)
    assert prior is not None and abs(prior[0] - 8.0) < 1.5


# --------------------------------------------------------------------------- #
# carbon and scenarios
# --------------------------------------------------------------------------- #
def test_pools_decay_and_firewood_is_burnt_fast():
    p = carbon.Pools(1)
    p.step(np.array([1.0]))
    fw0, dw0 = p.firewood[0], p.deadwood[0]
    assert fw0 == pytest.approx(0.5 * carbon.FIREWOOD_FRACTION)
    assert dw0 == pytest.approx(0.5 * (1 - carbon.FIREWOOD_FRACTION) + 0.5 * allometry.ROOT_SHOOT)
    for _ in range(5):
        p.step(np.array([0.0]))
    assert p.firewood[0] < 0.05 * fw0 and p.deadwood[0] > 0.8 * dw0


@pytest.fixture(scope="module")
def breckland_size_age():
    model, inv, fit, prior = state.crown_fit("breckland", "size_age")
    return state.height_bank("breckland", "size_age"), inv, fit


def test_height_bank_matches_model(breckland_size_age):
    bank, _, _ = breckland_size_age
    m = bank.model
    assert bank.height(12.0, 37.0, 1) == pytest.approx(float(m.height(12.0, 37.0)), rel=1e-3)


def test_baseline_projection_is_a_sink_and_repeatable(breckland_size_age):
    bank, inv, fit = breckland_size_age
    a = scenario.simulate(bank, inv, fit, years=20, n_members=10, seed=3)
    b = scenario.simulate(bank, inv, fit, years=20, n_members=10, seed=3)
    assert a["living_c_t"] == b["living_c_t"]
    assert a["living_c_t"]["mean"][-1] > a["living_c_t"]["mean"][0]
    assert np.mean(a["net_flux_t_co2_yr"]["mean"][1:]) < 0
    assert all(lo <= m <= hi for lo, m, hi in zip(a["living_c_t"]["p05"], a["living_c_t"]["mean"],
                                                  a["living_c_t"]["p95"]))


def test_net_flux_closes_the_carbon_budget(breckland_size_age):
    bank, inv, fit = breckland_size_age
    r = scenario.simulate(bank, inv, fit, years=10, n_members=1, seed=0, ash={})
    tot = np.array(r["living_c_t"]["mean"]) + np.array(r["deadwood_c_t"]["mean"]) + \
        np.array(r["firewood_c_t"]["mean"])
    soil = np.array(r["to_soil_t_c_yr"]["mean"])
    flux_c = np.array(r["net_flux_t_co2_yr"]["mean"]) / allometry.CO2_PER_C
    assert flux_c[1:] == pytest.approx(-(np.diff(tot)) - soil[1:], rel=1e-9, abs=1e-9)


def test_ash_dieback_lowers_living_carbon_and_replanting_helps(breckland_size_age):
    bank, inv, fit = breckland_size_age
    kw = dict(years=30, n_members=10, seed=1)
    base = scenario.simulate(bank, inv, fit, **kw)
    ash = scenario.simulate(bank, inv, fit, ash={"ash_share": 0.5}, **kw)
    rep = scenario.simulate(bank, inv, fit, ash={"ash_share": 0.5}, replant_share=1.0, **kw)
    assert ash["living_c_t"]["mean"][-1] < base["living_c_t"]["mean"][-1]
    assert ash["firewood_c_t"]["mean"][5] > base["firewood_c_t"]["mean"][5]
    assert rep["living_c_t"]["mean"][-1] > ash["living_c_t"]["mean"][-1]
    assert ash["trees_alive"]["mean"][-1] < base["trees_alive"]["mean"][-1]


def test_planting_grows_and_survival_matters(breckland_size_age):
    bank, *_ = breckland_size_age
    hedge = scenario.planting(bank, 9.0, 1.0, 1000, "hedgerow")
    urban = scenario.planting(bank, 9.0, 1.0, 1000, "urban")
    assert hedge["living_c_t"]["mean"][0] < hedge["living_c_t"]["mean"][-1]
    assert urban["trees_alive"]["mean"][-1] < hedge["trees_alive"]["mean"][-1]
    assert hedge["cumulative_net_t_co2"]["mean"][-1] < 0
    with pytest.raises(ValueError):
        scenario.planting(bank, 9.0, 1.0, 10, "orchard")


# --------------------------------------------------------------------------- #
# change and attribution
# --------------------------------------------------------------------------- #
def test_change_threshold_and_labels():
    m = make_model("size_age", "herefordshire")
    inv = _synthetic_inventory(m, [15.0, 15.0, 15.0], [40.0, 40.0, 40.0])
    h = inv.h_lz.copy()
    h[1, 2] = h[1, 1] - 2.0                              # small reduction: below threshold
    h[2, 2] = 1.0                                        # cut down: removal candidate
    inv = replace(inv, h_lz=h)
    ch = change.height_change(inv, 2010, 2020)
    assert ch["significant_reductions"] == 1 and ch["removal_candidates"] == 1
    assert ch["agb_lost_t"] > 0
    assert ch["impact"] == change.IMPACT_LOSS
    with pytest.raises(ValueError):
        change.height_change(inv, 2020, 2010)


def test_attribution_needs_evidence():
    m = make_model("size_age", "herefordshire")
    inv = _synthetic_inventory(m, [15.0], [40.0])
    h = inv.h_lz.copy()
    h[0, 2] = 1.0
    inv = replace(inv, h_lz=h)
    ch = change.height_change(inv, 2010, 2020)
    none = change.attribute(inv, ch, [])
    assert none["unattributed_objects"] == 1
    late = change.attribute(inv, ch, [change.Evidence("felling", 2022, 2023, point=(0, 0))])
    assert late["unattributed_objects"] == 1
    hit = change.attribute(inv, ch, [change.Evidence("felling", 2012, 2015, point=(0, 0),
                                                     radius_m=50)])
    assert hit["unattributed_objects"] == 0 and hit["attributions"][0]["label"].endswith("(felling)")
    with pytest.raises(ValueError):
        change.Evidence("aliens", 2010, 2011, point=(0, 0))


# --------------------------------------------------------------------------- #
# assimilation and parameter store
# --------------------------------------------------------------------------- #
def test_kalman_filter_moves_productivity_towards_taller_trees(breckland_size_age):
    bank, inv, fit = breckland_size_age
    idx = np.flatnonzero(np.isfinite(fit.theta))[:30]
    obs = [{"tow_id": str(inv.tow_id[i]), "year": 2026.0,
            "height_m": float(inv.h_fz[i]) + 3.0, "sd_m": 0.5} for i in idx]
    r = assimilation.assimilate(bank, inv, fit, obs)
    assert r["n_matched"] == 30 and r["theta_shift"] > 0
    o = r["objects"][0]
    assert abs(o["analysis_height_m"] - o["observed_height_m"]) < abs(
        o["forecast_height_m"] - o["observed_height_m"])
    miss = assimilation.assimilate(bank, inv, fit, [{"lon": 0.0, "lat": 0.0, "year": 2026,
                                                     "height_m": 10}])
    assert miss["n_matched"] == 0


def test_parameter_store_persists(tmp_path):
    path = tmp_path / "s.json"
    s = state.ParameterStore(path)
    s.set("farm", "breckland", "size_age", 1.5, note="test")
    s2 = state.ParameterStore(path)
    assert s2.theta_shift("farm", "breckland", "size_age") == 1.5
    assert s2.theta_shift("farm", "fens", "size_age") == 0.0          # tied to its pilot
    p = s2.get("farm", "breckland", "size_age")
    assert p["learned"] and p["theta"] == pytest.approx(state.baseline("breckland", "size_age")["theta"] + 1.5)
    s2.reset("farm")
    assert state.ParameterStore(path).sites() == []


# --------------------------------------------------------------------------- #
# pilots, inventory and the shipped calibration
# --------------------------------------------------------------------------- #
def test_pilots_and_climate():
    assert len(KEYS) == 10
    assert len({p.region for p in pilots.PILOTS.values()}) == 8   # every English region but London
    for p in pilots.PILOTS.values():
        x0, y0 = p.origin
        assert x0 % 5000 == 0 and y0 % 5000 == 0
        c = p.climate
        assert 450 < c.annual_rain_mm < 1500 and 7 < c.mean_temp_c < 12
        assert len(c.solar_mj_m2_d) == 12


@pytest.mark.parametrize("key", KEYS)
def test_inventory_loads(key):
    inv = inventory.load(key)
    assert inv.n > 500          # the Fens tile is only partly covered by the NLP
    assert set(np.unique(inv.cls)) <= {0, 1, 2}
    assert np.all(inv.h_fz >= 3) and np.all(inv.n_trees >= 1)
    assert inv.epoch_year.size >= 2 and inv.epoch_year[0] < 2010
    s = inventory.summary(inv)
    assert s["agb_t"] > 0 and sum(r["objects"] for r in s["by_class"]) == s["objects"]


def test_shipped_calibration_summary():
    cal = state.calibration()
    assert set(cal["pilots"]) == set(KEYS)
    better = 0
    for key, entry in cal["pilots"].items():
        for name in GROWTH_MODELS:
            r = entry["models"][name]
            c, v = r["calibration"], r["validation"]
            m = make_model(name, key)
            assert m.theta_grid[0] <= c["theta_median"] <= m.theta_grid[-1]
            assert v["n"] > 100
            better += v["model"]["rmse_m"] < v["persistence"]["rmse_m"]
    # the models must beat the no-growth baseline in most pilot x model cases
    assert better >= 12


def test_shipped_calibration_is_reproducible():
    out = subprocess.run([sys.executable, "-c",
                          "import sys, json; sys.path.insert(0, %r); sys.path.insert(0, %r)\n"
                          "import calibrate_pilots as c\n"
                          "print(json.dumps(c.run(['breckland'])))" % (str(HERE), str(HERE / "scripts"))],
                         capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stderr
    fresh = json.loads(out.stdout.strip().splitlines()[-1])
    assert fresh["pilots"]["breckland"] == state.calibration()["pilots"]["breckland"]


def test_package_is_server_safe(tmp_path):
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from trees import state, scenario\n"
        "m, inv, fit, prior = state.crown_fit('fens', 'crown_lue')\n"
        "scenario.simulate(state.height_bank('fens', 'crown_lue'), inv, fit, years=3, n_members=5)\n"
        "assert not any(k.startswith(('matplotlib', 'pandas')) for k in sys.modules)\n"
    ) % str(HERE)
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True,
                         text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    assert out.stdout == ""
    assert list(tmp_path.iterdir()) == []
