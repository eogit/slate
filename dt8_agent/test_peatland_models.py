"""Tests for the server-safe peatland model copy: run with `pytest dt8_agent`.

The expected numbers are the outputs printed in the executed ``peatland_digital_twin.ipynb``
on the digital_twin ``peatland-ghg-twin`` branch, so these tests pin the copy to the notebook.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from peatland import ch4, co2, inventory, n2o, soil_temp  # noqa: E402
from peatland.state import ParameterStore, baseline  # noqa: E402

NOTEBOOK_NEE = {"WW": 9.0, "Beet": 5.0, "Maize": 6.7, "Potato": 8.1, "Grass": 3.9,
                "Lettuce": 7.8, "Celery": 7.3, "Leek": 7.0, "Cabbage": 5.3, "Linseed": 11.7}


@pytest.fixture(scope="module")
def base():
    return baseline()


def test_co2_matches_notebook():
    for crop, expected in NOTEBOOK_NEE.items():
        assert co2.annual_budget(co2.simulate(crop))["NEE"] == pytest.approx(expected, abs=0.05)


def test_ch4_calibration_matches_notebook(base):
    assert base["ch4"]["k_prod"] == pytest.approx(204, abs=0.5)
    assert ch4.annual_ch4(0.7, base["ch4"]) == pytest.approx(-1.1, abs=0.05)
    assert ch4.annual_ch4(0.1, base["ch4"]) == pytest.approx(132.8, abs=0.05)


def test_n2o_calibration_matches_notebook(base):
    assert base["n2o"]["ef_peat"] == pytest.approx(0.016, abs=0.0005)
    crops = [c for c in co2.CROPS if c != "Grass"]
    vals = [n2o.annual_n2o(c, base["n2o"]) for c in crops]
    assert np.mean(vals) == pytest.approx(16.28, abs=0.01)
    assert min(vals) == pytest.approx(8.5, abs=0.05)
    assert max(vals) == pytest.approx(23.7, abs=0.05)
    assert n2o.annual_n2o("Grass", base["n2o"]) == pytest.approx(7.9, abs=0.05)


def test_inventory_validation_matches_notebook(base):
    v = inventory.validate(base["ch4"], base["n2o"])
    assert v["co2_slope_model"] == pytest.approx(0.419, abs=0.001)
    assert v["cropland_co2_model_t"] == pytest.approx(27.7, abs=0.05)
    assert v["ch4_rewetted_model_kg"] == pytest.approx(109, abs=0.5)
    assert v["ch4_cropland_model_kg"] == pytest.approx(-1.0, abs=0.05)
    assert v["n2o_rewetted_model_kg_n"] == pytest.approx(2.0, abs=0.05)


def test_ch4_gradients_match_finite_differences(base):
    rng = np.random.default_rng(0)
    Ts, W, L = rng.uniform(2, 18, 6), rng.uniform(0.05, 1.2, 6), rng.uniform(0.2, 4, 6)
    _, info = ch4.ch4_flux(base["ch4"], Ts, W, L)
    for key in ch4.LEARNABLE:
        eps = 1e-6 * base["ch4"][key]
        up = ch4.ch4_flux(dict(base["ch4"], **{key: base["ch4"][key] + eps}), Ts, W, L)[0]
        dn = ch4.ch4_flux(dict(base["ch4"], **{key: base["ch4"][key] - eps}), Ts, W, L)[0]
        np.testing.assert_allclose(info["grad"][key], (up - dn) / (2 * eps), rtol=1e-5)


def test_n2o_is_diagnostic(base):
    assert n2o.decouple_check(base["ch4"]) == (True, True)


def test_calibration_does_not_mutate_module_state():
    before = (dict(ch4.TRUE_CH4), dict(n2o.PARN))
    baseline()
    assert (ch4.TRUE_CH4, n2o.PARN) == before


def test_self_learning_moves_towards_truth(base):
    truth = base["ch4"]
    prior = dict(truth, k_prod=2 * truth["k_prod"], Q10_CH4=2.0)
    learned, hist = ch4.self_learn_ch4(ch4.make_synthetic(truth), prior, epochs=3,
                                       scale_k=truth["k_prod"])
    assert len(hist["k_prod"]) == 4      # prior + one entry per epoch
    assert abs(learned["k_prod"] - truth["k_prod"]) < abs(prior["k_prod"] - truth["k_prod"])
    assert abs(learned["Q10_CH4"] - truth["Q10_CH4"]) < abs(prior["Q10_CH4"] - truth["Q10_CH4"])


def test_parameter_store_persists(tmp_path):
    path = tmp_path / "state" / "dt8.json"
    s = ParameterStore(path)
    s.set("ch4", dict(s.get("ch4"), k_prod=123.0), site="fen1", note="test")
    reloaded = ParameterStore(path)
    assert reloaded.get("ch4", "fen1")["k_prod"] == 123.0
    assert reloaded.get("ch4")["k_prod"] == pytest.approx(204, abs=0.5)   # other sites untouched
    assert reloaded.sites() == ["fen1"]
    reloaded.reset("fen1")
    assert json.loads(path.read_text()) == {"sites": {}}


def test_import_is_side_effect_free(tmp_path):
    """Importing and running the models must not load matplotlib, print or write files."""
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from peatland import co2, ch4, n2o, inventory, state\n"
            "b = state.baseline(); inventory.validate(b['ch4'], b['n2o'])\n"
            "assert 'matplotlib' not in sys.modules\n") % str(HERE)
    out = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True,
                         text=True, env={**os.environ, "MPLBACKEND": "Agg"})
    assert out.returncode == 0, out.stderr
    assert out.stdout == ""
    assert list(tmp_path.iterdir()) == []


def test_full_self_learning_reproduces_notebooks():
    """CH4: Section 10 of the CH4 notebook (2.2x prior, 20 epochs). N2O: coupled notebook."""
    import dt8_server

    c = dt8_server.self_learn_synthetic("ch4", 20)
    assert c.learned["k_prod"] == pytest.approx(198.152, abs=0.01)
    assert c.learned["Q10_CH4"] == pytest.approx(3.537, abs=0.001)
    n = dt8_server.self_learn_synthetic("n2o", 20)
    assert n.learned["ef_peat"] == pytest.approx(0.016, abs=0.0005)
    assert n.learned["Q10_n2o"] == pytest.approx(2.48, abs=0.01)


# --------------------------------------------------------------------------- #
# Section 14 CH4 notebook (peatland_ch4_model_with_litter_extension.ipynb)
# --------------------------------------------------------------------------- #
def test_ch4_inventory_skill_matches_section7(base):
    v = ch4.inventory_validation(base["ch4"])
    assert v["eq3_5_70cm"]["nse"] == pytest.approx(0.88, abs=0.005)
    assert v["eq3_20_70cm"]["rmse"] == pytest.approx(3.56, abs=0.005)
    assert v["tier2_classes"]["rmse"] == pytest.approx(22.0, abs=0.005)
    models = [round(t["model"], 2) for t in v["tier2_table"]]
    assert models == [171.74, 109.28, 5.78, 2.83, -0.98]


def test_ch4_crop_classes_match_section12(base):
    expected = {"Upland_grass": 78.38, "Grass_grazed": 117.38, "Grass_ungrazed": 142.97,
                "Winter_cereal": 135.37, "Maize": 73.17}
    for veg, kg in expected.items():
        assert ch4.annual_ch4(0.115, base["ch4"], veg) == pytest.approx(kg, abs=0.005)


def test_litter_pool_only_for_flood_intolerant_vegetation(base):
    reed = ch4.annual_ch4_components(0.0, base["ch4"], "reed", years_since_rewetting=0)
    assert reed["litter"] == 0.0 and not reed["flood_intolerant"]
    drained = ch4.annual_ch4_components(0.6, base["ch4"], "Winter_cereal")
    assert drained["litter"] == 0.0            # no standing water, no flood kill
    assert ch4.is_flood_intolerant("Phalaris arundinacea cv. Bamse (+ Poa spp.)")
    assert not ch4.is_flood_intolerant("Phragmites australis")


def test_litter_pool_mass_balance(base):
    """Pool change equals input minus decomposition, and emission follows decomposition."""
    n = 365
    Ts = np.full(n, 10.0)
    WTD = np.full(n, -0.10)                      # 10 cm standing water: maximum mortality
    LAI = np.full(n, 2.0)
    pl = ch4.LITTER
    E, L = ch4.litter_ch4(base["ch4"], pl, Ts, WTD, LAI, 0.0)
    kill = pl["m_max"] * pl["cB"] * 2.0 * n
    decomposed = kill - L
    f_plant = base["ch4"]["p_aer"] * 2.0 / (2.0 + base["ch4"]["k_lai"])
    # standing water: f_ox = 0, so escape fraction = f_plant + (1 - f_plant) = 1
    assert E.sum() == pytest.approx(pl["Y_ch4"] * decomposed * 16 / 12 * 1000, rel=1e-9)
    assert 0 < f_plant < 1


def test_air_to_soil_temperature_matches_section3b():
    tair3 = np.tile(ch4.air_temperature(), 3)
    sod = soil_temp.air_to_soil_temperature(tair3, soil_temp.TSOIL_PARAMS["open_sod_10cm"])[-365:]
    forest = soil_temp.air_to_soil_temperature(
        tair3, soil_temp.TSOIL_PARAMS["temperate_forest_10cm"])[-365:]
    assert sod.mean() == pytest.approx(11.79, abs=0.005)
    assert forest.max() == pytest.approx(15.14, abs=0.005)


def test_peat_capped_sensitivity_matches_section9b(base):
    WTD = ch4.water_table(0.115)
    capd, _ = ch4.ch4_flux_peat_capped(base["ch4"], ch4.soil_temperature(), WTD,
                                       ch4.veg_lai("reed"), 0.15)
    assert capd.mean() * ch4.MGD_TO_KGHAYR == pytest.approx(55.7, abs=0.05)
