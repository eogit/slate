"""Tests of the DT4 model package (``forest``): run with ``pytest dt4_agent``.

They check the science properties each module promises (yield class = peak MAI, 3-PG
responds to fertility and water, carbon bookkeeping closes, disturbances replace stands,
change detection respects uncertainty, the Kalman filter learns a known productivity), pin
the CCI v7 numbers of the pilot landscapes, check that rerunning the calibration script
reproduces the shipped calibration, and check that the package is server-safe.
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from forest import assimilation, calibration, carbon, cci, change, disturbance  # noqa: E402
from forest import landscapes, management, scenario, species, state, threepg  # noqa: E402
from forest import yield_curves as yc  # noqa: E402
from forest import make_model  # noqa: E402

KIELDER = landscapes.KIELDER
THETFORD = landscapes.THETFORD


# --------------------------------------------------------------------------- #
# yield curves
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code", sorted(species.SPECIES))
def test_yield_class_is_peak_mai(code):
    s = species.get(code)
    ages = np.arange(1, 300, 0.25)
    for y in (s.yc_min, s.yc_default, s.yc_max):
        m = yc.mai(ages, y, code)
        assert m.max() == pytest.approx(y, rel=1e-4)
        assert ages[m.argmax()] == pytest.approx(s.culmination_age, abs=0.5)


def test_yield_curve_inverse_and_conversion():
    v = yc.volume(37.0, 14, "SS")
    assert yc.age_for_volume(v, 14, "SS") == pytest.approx(37.0, rel=1e-6)
    assert yc.to_volume(yc.to_agb(v, "SS"), "SS") == pytest.approx(v)
    assert yc.agb(40, 14, "SS") == pytest.approx(yc.volume(40, 14, "SS") * 0.33 * 1.30)


def test_yield_curve_thinning_keeps_most_increment():
    m = yc.YieldCurveModel("SS")
    full = m.init(30, 14)
    thinned = m.init(30, 14)
    m.remove(thinned, 0.3)
    v_full, v_thin = full["vol"].copy(), thinned["vol"].copy()
    m.step(full)
    m.step(thinned)
    inc_full, inc_thin = full["vol"] - v_full, thinned["vol"] - v_thin
    assert inc_thin / inc_full == pytest.approx(math.sqrt(0.7), rel=1e-6)


def test_ccf_harvest_rejuvenates():
    m = yc.YieldCurveModel("SS")
    st = m.init(60, 14)
    m.remove(st, 0.2, rejuvenate=True)
    assert st["age"][0] < 60
    assert yc.volume(st["age"], 14, "SS")[0] == pytest.approx(st["vol"][0], rel=1e-6)


# --------------------------------------------------------------------------- #
# 3-PG
# --------------------------------------------------------------------------- #
def test_3pg_responds_to_fertility():
    m = threepg.ThreePGModel("SS", KIELDER)
    table = m.agb_table([0.0, 0.25, 0.5, 0.75, 1.0], 80)
    assert np.all(np.diff(table[:, 40]) > 0)                 # more fertile, more biomass
    assert np.all(np.diff(table[2, :60]) >= -1e-9)           # unthinned growth is monotonic
    assert 100 < table[2, 40] < 400                          # plausible Sitka AGB at 40 years


def test_3pg_self_thinning_reduces_stems():
    m = threepg.ThreePGModel("SS", KIELDER)
    st = m.init(60, 0.8)
    assert st["N"][0] < species.get("SS").threepg["stems_planted"]
    avg_kg = st["WS"][0] * 1000 / st["N"][0]
    line = m.p["wSx1000"] * (1000 / st["N"][0]) ** m.p["thinPower"]
    assert avg_kg <= line * 1.001


def test_3pg_drought_limits_growth():
    wet = threepg.ThreePGModel("CP", THETFORD)
    dry = threepg.ThreePGModel("CP", THETFORD, rain_factor=0.5)
    assert dry.agb_table([0.5], 40)[0, 40] < wet.agb_table([0.5], 40)[0, 40]


def test_3pg_deciduous_and_init_scaling():
    m = threepg.ThreePGModel("OK", THETFORD)
    st = m.init(30, 0.6, agb0=80.0)
    assert m.agb(st)[0] == pytest.approx(80.0)
    m.step(st)
    assert m.agb(st)[0] > 80.0


def test_3pg_day_length():
    assert threepg.day_length_s(55.0, 5) / 3600 > 16      # June in Northumberland
    assert threepg.day_length_s(55.0, 11) / 3600 < 8.5    # December


# --------------------------------------------------------------------------- #
# management, disturbance and carbon
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model_name", ["yield_curve", "3pg"])
def test_clearfell_sends_logs_to_products(model_name):
    m = make_model(model_name, "SS", KIELDER)
    theta = 14 if model_name == "yield_curve" else 0.5
    r = scenario.simulate(m, start_year=2024, years=10, age=40, theta=theta,
                          regime=management.get("clearfell_no_thin").with_options(rotation_age=45))
    t = int(np.argmax(r.removals_dm[:, 0]))       # the felling year
    assert r.years[t] == 2029
    assert r.agb[t, 0] < 5.0 < r.agb[t - 1, 0]       # felled and replanted
    logs_c = species.CARBON_FRACTION * r.removals_dm[t, 0]
    hwp_in = r.hwp_c[t, 0] - r.hwp_c[t - 1, 0] * math.exp(-min(carbon.K_HWP))
    assert hwp_in == pytest.approx(logs_c, rel=0.05)
    assert r.deadwood_c[t, 0] > r.deadwood_c[t - 1, 0]   # brash and roots


def test_net_flux_is_stock_change_plus_soil_input():
    m = yc.YieldCurveModel("CP")
    r = scenario.simulate(m, start_year=2024, years=30, age=20, theta=12, regime="thin_and_fell")
    d_total = np.diff(r.total_c[:, 0])
    expected = -(d_total + r.to_soil_c[1:, 0]) * species.CO2_PER_C
    assert np.allclose(r.net_flux_co2[1:, 0], expected)
    assert r.removals_dm.sum() > 0


def test_unmanaged_young_forest_is_a_sink():
    r = scenario.simulate(yc.YieldCurveModel("SS"), start_year=2024, years=30, age=10, theta=14)
    assert np.all(r.net_flux_co2[1:, 0] < 0)


def test_stand_replacing_wind_replants():
    m = yc.YieldCurveModel("SS")
    ev = [disturbance.Event(2030, "wind", 0.9)]
    r = scenario.simulate(m, start_year=2024, years=10, age=30, theta=14, events=ev)
    t = list(r.years).index(2030)
    assert r.agb[t, 0] == pytest.approx(0.0, abs=1e-9)
    assert r.age[t, 0] == 0
    assert r.removals_dm[t, 0] > 0                 # salvage
    assert any(e["event"] == "wind" for e in r.events)


def test_fire_emits_directly():
    m = yc.YieldCurveModel("CP")
    calm = scenario.simulate(m, start_year=2024, years=3, age=40, theta=12)
    burn = scenario.simulate(m, start_year=2024, years=3, age=40, theta=12,
                             events=[disturbance.Event(2025, "fire", 0.5)])
    assert burn.emissions_c[1, 0] > calm.emissions_c[1, 0]
    assert burn.net_flux_co2[1, 0] > calm.net_flux_co2[1, 0]


def test_stochastic_disturbance_is_repeatable_and_spreads():
    m = yc.YieldCurveModel("SS")
    kw = dict(start_year=2024, years=40, age=20, theta=14, stochastic=True,
              hazard_multiplier=10, n_members=40, seed=3)
    a, b = scenario.simulate(m, **kw), scenario.simulate(m, **kw)
    assert np.array_equal(a.agb, b.agb)
    assert a.agb[-1].std() > 1.0


def test_root_shoot_ratio_mokany():
    assert species.root_shoot_ratio(100) * 100 == pytest.approx(0.489 * 100 ** 0.890)
    r = species.root_shoot_ratio(np.array([10.0, 50.0, 100.0, 200.0]))
    assert np.all(np.diff(r) < 0) and 0.25 < r[-1] < r[0] < 0.4


# --------------------------------------------------------------------------- #
# CCI v7 data
# --------------------------------------------------------------------------- #
PINNED = {  # landscape: (shape, woodland pixels, woodland ha, {year: (mean, sd)})
    "thetford": ((18, 158, 281), 23795, 14198.5,
                 {2005: (113.0848, 10.8308), 2020: (108.187, 11.227), 2024: (106.4233, 12.8453)}),
    "kielder": ((18, 191, 394), 33969, 18978.6,
                {2005: (91.3228, 12.934), 2020: (115.5523, 19.4168), 2024: (116.7961, 17.954)}),
}


@pytest.mark.parametrize("key", sorted(PINNED))
def test_cci_cube_pinned(key):
    shape, n, ha, years = PINNED[key]
    c = cci.load(key)
    assert c.agb.shape == shape
    assert c.years == cci.CCI_YEARS and 2013 not in c.years
    assert int(c.woodland.sum()) == n
    assert float(c.pixel_area_ha()[c.woodland].sum()) == pytest.approx(ha, abs=0.1)
    for y, (mean, sd) in years.items():
        s = cci.area_stats(c, y, c.woodland)
        assert s["agb_mean_mg_ha"] == pytest.approx(mean, abs=1e-3)
        assert s["agb_sd_mg_ha"] == pytest.approx(sd, abs=1e-3)


def test_cci_pixel_area_is_about_one_hectare():
    a = cci.load("kielder").pixel_area_ha()
    assert 0.55 < a.mean() < 0.65      # 0.000889 deg: 99 m x 57 m at 55 N


def test_area_sd_keeps_systematic_error():
    sd = np.full(10000, 40.0)
    assert cci.area_sd(sd[:1]) == 40.0
    assert cci.area_sd(sd) >= cci.SYSTEMATIC_FRACTION * 40.0
    assert cci.area_sd(sd) < 40.0


def test_select_point_bbox_and_errors():
    c = cci.load("thetford")
    one = cci.select(c, cci.Area(point=(0.70, 52.45)))
    assert one.sum() == 1
    disk = cci.select(c, cci.Area(point=(0.70, 52.45), radius_m=500))
    assert 20 < disk.sum() < 160
    box = cci.select(c, cci.Area(bbox=(0.6, 52.4, 0.7, 52.5)))
    assert box.sum() < c.woodland.sum()
    with pytest.raises(ValueError):
        cci.select(c, cci.Area(point=(-3.0, 50.0)))
    with pytest.raises(ValueError):
        c.year_index(2013)


def test_epoch_flag():
    assert cci.crosses_epoch(2010, 2016)
    assert not cci.crosses_epoch(2015, 2024)


# --------------------------------------------------------------------------- #
# change and attribution
# --------------------------------------------------------------------------- #
def test_change_significance_and_labels():
    c = cci.load("kielder")
    ch = change.area_change(c, 2015, 2024, c.woodland)
    assert ch["impact"] in (change.IMPACT_NONE, change.IMPACT_GAIN, change.IMPACT_LOSS)
    assert ch["significant_at_90pct"] == (abs(ch["delta_agb_mean_mg_ha"]) >
                                          cci.Z90 * ch["delta_agb_sd_mg_ha"])
    assert ch["loss_area_ha"] > 0 and ch["gain_area_ha"] > 0
    assert ch["conversion_candidate_area_ha"] <= ch["loss_area_ha"]
    assert not ch["crosses_sensor_epoch"]
    with pytest.raises(ValueError):
        change.area_change(c, 2020, 2015, c.woodland)


def test_attribution_needs_evidence():
    c = cci.load("kielder")
    ch = change.area_change(c, 2015, 2024, c.woodland)
    none = change.attribute(c, ch, [])
    assert none["unattributed_share"] == 1.0
    full = change.attribute(c, ch, [change.Evidence("harvest", 2016, 2024, bbox=KIELDER.bbox)])
    assert full["unattributed_share"] == pytest.approx(0.0)
    assert full["attributions"][0]["label"].endswith("(harvest)")
    late = change.attribute(c, ch, [change.Evidence("wind", 2025, 2026, bbox=KIELDER.bbox)])
    assert late["unattributed_share"] == 1.0       # evidence outside the change period


# --------------------------------------------------------------------------- #
# calibration and assimilation
# --------------------------------------------------------------------------- #
def test_calibration_recovers_synthetic_pixels():
    """Pixels generated from known (YC, age) are fitted back to them."""
    import dataclasses

    m = yc.YieldCurveModel("SS")
    rng = np.random.default_rng(0)
    rows, cols = 6, 6
    true_yc = rng.integers(8, 20, (rows, cols)).astype(float)
    true_age = rng.integers(10, 50, (rows, cols)).astype(float)
    years = cci.CCI_YEARS
    agb = np.stack([yc.agb(true_age + (y - years[0]), true_yc, "SS") for y in years])
    cube = cci.Cube(key="synthetic", agb=agb, sd=np.full_like(agb, 5.0), years=years,
                    transform=(0.000888, 0, 0, 0, -0.000888, 55), woodland=np.ones((rows, cols), bool))
    fit = calibration.fit_pixels(m, cube, cube.woodland, years, n_sample=None, prior_sd=1e6)
    assert np.allclose(fit["theta"], true_yc.ravel())
    assert np.allclose(fit["age_ref"], true_age.ravel())
    assert dataclasses.is_dataclass(cube)


def test_shipped_calibration_is_reproducible():
    sys.path.insert(0, str(HERE / "scripts"))
    import calibrate_pilots

    fresh = json.loads(json.dumps(calibrate_pilots.run()))
    shipped = json.loads(state.CALIBRATION_FILE.read_text())
    assert fresh == shipped


def test_shipped_calibration_summary():
    cal = state.calibration()
    for key in ("thetford", "kielder"):
        for m in ("yield_curve", "3pg"):
            c, v = cal[key][m]["calibration"], cal[key][m]["validation"]
            assert c["n_pixels"] == 2000
            assert c["fit"]["r2"] > 0.6
            assert v["holdout"]["rmse_mg_ha"] < 50
            assert v["holdout_years"] == [2018, 2019, 2020, 2021, 2022, 2023, 2024]
    # the numbers reported in the README
    assert cal["thetford"]["yield_curve"]["validation"]["holdout"]["rmse_mg_ha"] == pytest.approx(38.39, abs=0.01)
    assert cal["thetford"]["3pg"]["validation"]["holdout"]["rmse_mg_ha"] == pytest.approx(37.96, abs=0.01)
    assert cal["kielder"]["yield_curve"]["validation"]["holdout"]["rmse_mg_ha"] == pytest.approx(42.58, abs=0.01)
    assert cal["kielder"]["3pg"]["validation"]["holdout"]["rmse_mg_ha"] == pytest.approx(43.68, abs=0.01)


@pytest.mark.parametrize("model_name,truth,prior", [("yield_curve", 18.0, 9.0), ("3pg", 0.7, 0.3)])
def test_kalman_filter_learns_productivity(model_name, truth, prior):
    m = make_model(model_name, "SS", KIELDER)
    bank = assimilation.CurveBank(m)
    syn = assimilation.synthetic_observations(m, theta_true=truth, age_start=10,
                                              years=cci.CCI_YEARS, bank=bank)
    span = bank.grid[-1] - bank.grid[0]
    r = assimilation.enkf(m, syn["years"], syn["obs"], syn["sd"], prior_theta=prior,
                          prior_theta_sd=span / 4, start_year=2005, prior_age=10, bank=bank)
    assert abs(r["theta_mean"] - truth) < 0.25 * abs(prior - truth)
    assert r["theta_sd"] < span / 4
    assert len(r["years"]) == 2024 - 2005 + 1          # 2013 and 2014 forecast only
    assert "observed_agb" not in r["years"][2013 - 2005]


def test_parameter_store_persists(tmp_path):
    path = tmp_path / "state.json"
    s = state.ParameterStore(path)
    base = s.get("k1", "kielder", "3pg")
    s.set("k1", "kielder", "3pg", {**base, "theta": 0.9}, note="test")
    again = state.ParameterStore(path)
    assert again.get("k1", "kielder", "3pg")["theta"] == 0.9
    assert again.source("k1", "kielder", "3pg").startswith("learned")
    assert again.get("k1", "thetford", "3pg")["theta"] == state.baseline("thetford", "3pg")["theta"]
    again.reset("k1")
    assert state.ParameterStore(path).get("k1", "kielder", "3pg") == base


# --------------------------------------------------------------------------- #
# server safety
# --------------------------------------------------------------------------- #
def test_package_is_server_safe(tmp_path):
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from forest import make_model, scenario, cci, calibration, landscapes as L\n"
        "m = make_model('3pg', 'SS', L.KIELDER)\n"
        "scenario.simulate(m, start_year=2024, years=5, age=20, theta=0.5)\n"
        "c = cci.load('kielder')\n"
        "calibration.calibrate(make_model('yield_curve', 'SS', L.KIELDER), c, n_sample=50)\n"
        "assert not any(k.startswith(('matplotlib', 'pandas')) for k in sys.modules)\n"
    ) % str(HERE)
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True,
                         text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout == ""
    assert list(tmp_path.iterdir()) == []
