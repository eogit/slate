"""The scenario engine: grow, manage, disturb and account for carbon, year by year.

:func:`simulate` runs one stand forward with either growth model (they share an interface:
``init``, ``step``, ``agb``, ``remove``, ``replant``) as an ensemble. Members differ in
their productivity (yield class or fertility rating, drawn from the calibrated site
distribution) and, if given, in their starting biomass, so the spread of the results is the
uncertainty that comes from what CCI could not pin down. Stochastic disturbances add a
second source of spread.

Order of operations each year: growth, then management, then disturbance, then carbon
accounting. Year 0 in the output is the starting state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import carbon as cb
from . import disturbance as dist
from . import management as mg
from .species import CARBON_FRACTION, CO2_PER_C

INITIAL_DEADWOOD_FRACTION = 0.08  # deadwood C as a share of AGB C at the start (a priori)
INITIAL_LITTER_FRACTION = 0.05


@dataclass
class Result:
    """Annual output, arrays shaped (years + 1, members). Stocks in t C/ha (AGB in t DM/ha)."""

    years: np.ndarray
    agb: np.ndarray
    agb_c: np.ndarray
    bgb_c: np.ndarray
    deadwood_c: np.ndarray
    litter_c: np.ndarray
    hwp_c: np.ndarray
    removals_dm: np.ndarray        # harvested and salvaged biomass leaving the site
    to_soil_c: np.ndarray          # carbon passed from litter and deadwood to soil (DT7)
    emissions_c: np.ndarray        # decay of dead wood, litter and products, plus combustion
    net_flux_co2: np.ndarray       # forest + products, t CO2/ha/yr, + = emission
    age: np.ndarray
    events: list = field(default_factory=list)

    @property
    def ecosystem_c(self) -> np.ndarray:
        return self.agb_c + self.bgb_c + self.deadwood_c + self.litter_c

    @property
    def total_c(self) -> np.ndarray:
        return self.ecosystem_c + self.hwp_c


def _members(value, sd, n, lo, hi, rng):
    if sd and sd > 0:
        return np.clip(rng.normal(value, sd, n), lo, hi)
    return np.full(n, float(value))


def simulate(model, *, start_year: int, years: int, age: float, theta: float,
             theta_sd: float = 0.0, agb0: float | None = None, agb0_sd: float = 0.0,
             regime: mg.Regime | str = "no_intervention", events=(),
             stochastic: bool = False, hazard_multiplier: float = 1.0,
             n_members: int = 50, seed: int = 0) -> Result:
    """Simulate ``years`` years from ``start_year`` for a stand of a given ``age``.

    ``theta`` is the model's productivity (yield class for ``yield_curve``, fertility rating
    for ``3pg``) and ``theta_sd`` its uncertainty. ``agb0`` optionally overrides the starting
    AGB (for example the CCI value of the area) instead of the model's value at ``age``.
    ``events`` are :class:`forest.disturbance.Event` objects applied in their year.
    """
    if isinstance(regime, str):
        regime = mg.get(regime)
    rng = np.random.default_rng(seed)
    sp = model.sp
    grid = model.theta_grid()
    n = int(n_members) if (theta_sd or agb0_sd or stochastic) else 1
    th = _members(theta, theta_sd, n, grid.min(), grid.max(), rng)
    a0 = None if agb0 is None else _members(agb0, agb0_sd, n, 0.0, 2000.0, rng)
    state = model.init(np.full(n, float(age)), th, a0)

    agb_now = model.agb(state)
    agb_c0, _ = cb.living_carbon(agb_now, sp.conifer)
    pools = cb.Pools(n, INITIAL_DEADWOOD_FRACTION * agb_c0, INITIAL_LITTER_FRACTION * agb_c0)

    first = regime.first_intervention_age or sp.first_thin_age
    rotation = regime.rotation_age or sp.rotation_age
    since_thin = np.full(n, float(regime.thin_interval))
    since_ccf = np.full(n, float(regime.ccf_interval))
    ccf_on = np.zeros(n, dtype=bool)
    rates = dist.hazard_rates(sp, hazard_multiplier)

    T = years + 1
    rec = {k: np.zeros((T, n)) for k in ("agb", "agb_c", "bgb_c", "deadwood_c", "litter_c",
                                          "hwp_c", "removals_dm", "to_soil_c", "emissions_c",
                                          "net_flux_co2", "age")}

    def record(t, extra=None):
        a = model.agb(state)
        ac, bc = cb.living_carbon(a, sp.conifer)
        rec["agb"][t], rec["agb_c"][t], rec["bgb_c"][t] = a, ac, bc
        rec["deadwood_c"][t], rec["litter_c"][t] = pools.deadwood, pools.litter
        rec["hwp_c"][t] = pools.hwp.sum(axis=0)
        rec["age"][t] = state["age"]
        if extra:
            for k, v in extra.items():
                rec[k][t] = v

    record(0)
    log = []
    for t in range(1, T):
        year = start_year + t
        diag = model.step(state, t)
        age_now = np.round(state["age"])
        since_thin += 1
        since_ccf += 1
        bgb_before = cb.living_carbon(model.agb(state), sp.conifer)[1] / CARBON_FRACTION

        removed = np.zeros(n)
        products = np.zeros((3, n))
        dead_in = diag["mortality"].copy()
        combusted = np.zeros(n)

        def harvest(mask_or_frac, kind, rejuvenate=False):
            nonlocal removed, products, dead_in
            r = model.remove(state, mask_or_frac, rejuvenate=rejuvenate)
            logs = (1 - mg.RESIDUE_FRACTION) * r
            dead_in = dead_in + mg.RESIDUE_FRACTION * r
            products = products + np.outer(mg.PRODUCT_SHARES[kind], logs)
            removed = removed + logs
            return r

        # ---- management
        fell = np.zeros(n, dtype=bool)
        if regime.clearfell:
            fell = age_now >= rotation
            if fell.any():
                harvest(fell.astype(float), "fell")
                model.replant(state, fell)
                log.append({"year": year, "event": "clearfell", "members": int(fell.sum())})
        if regime.thin:
            thin = (~fell) & (age_now >= first) & (age_now <= rotation - 3) & \
                (since_thin >= regime.thin_interval)
            if thin.any():
                harvest(np.where(thin, regime.thin_fraction, 0.0), "thinning")
                since_thin = np.where(thin, 0.0, since_thin)
                log.append({"year": year, "event": "thinning", "members": int(thin.sum())})
        if regime.ccf:
            # once a stand has reached the first-intervention age it stays under continuous
            # cover, even when harvests rejuvenate its effective age below that age
            ccf_on |= age_now >= first
            cut = ccf_on & (since_ccf >= regime.ccf_interval) & (model.agb(state) > 20.0)
            if cut.any():
                harvest(np.where(cut, regime.ccf_fraction, 0.0), "ccf", rejuvenate=True)
                since_ccf = np.where(cut, 0.0, since_ccf)
                log.append({"year": year, "event": "ccf_harvest", "members": int(cut.sum())})

        # ---- disturbance
        sev = {k: np.zeros(n) for k in dist.KINDS}
        for ev in events:
            if ev.year == year:
                sev[ev.kind] = np.maximum(sev[ev.kind], ev.severity)
                log.append({"year": year, "event": ev.kind, "severity": ev.severity,
                            "prescribed": True})
        if stochastic:
            drawn = dist.draw(rng, rates, n)
            for k in dist.KINDS:
                sev[k] = np.maximum(sev[k], drawn[k])
        for kind in dist.KINDS:
            s = sev[kind]
            if not (s > 0).any():
                continue
            killed = model.remove(state, s)
            salv = next((e.salvage for e in events if e.year == year and e.kind == kind),
                        dist.SALVAGE[kind])
            burnt = dist.COMBUSTED[kind] * killed
            logs = (1 - mg.RESIDUE_FRACTION) * salv * killed
            products = products + np.outer(mg.PRODUCT_SHARES["salvage"], logs)
            removed = removed + logs
            combusted = combusted + burnt
            dead_in = dead_in + killed - logs - burnt
            replace_ = s >= dist.STAND_REPLACING
            if replace_.any():
                rest = model.remove(state, replace_.astype(float))
                rl = (1 - mg.RESIDUE_FRACTION) * rest
                products = products + np.outer(mg.PRODUCT_SHARES["salvage"], rl)
                removed = removed + rl
                dead_in = dead_in + rest - rl
                model.replant(state, replace_)

        # roots of removed or killed trees become deadwood
        bgb_after = cb.living_carbon(model.agb(state), sp.conifer)[1] / CARBON_FRACTION
        dead_in = dead_in + np.maximum(bgb_before - bgb_after, 0.0)

        total_before = rec["agb_c"][t - 1] + rec["bgb_c"][t - 1] + rec["deadwood_c"][t - 1] + \
            rec["litter_c"][t - 1] + rec["hwp_c"][t - 1]
        fl = pools.step(dead_in, diag["litterfall"], products)
        record(t)
        total_after = rec["agb_c"][t] + rec["bgb_c"][t] + rec["deadwood_c"][t] + \
            rec["litter_c"][t] + rec["hwp_c"][t]
        emitted = fl["dead_to_air"] + fl["hwp_to_air"] + CARBON_FRACTION * combusted
        # atmosphere's view: carbon that left the air = stock change + carbon handed to soil
        net = -(total_after - total_before + fl["to_soil"]) * CO2_PER_C
        rec["removals_dm"][t] = removed
        rec["to_soil_c"][t] = fl["to_soil"]
        rec["emissions_c"][t] = emitted
        rec["net_flux_co2"][t] = net

    return Result(years=np.arange(start_year, start_year + T), events=log, **rec)


def summarise(values: np.ndarray) -> dict:
    """Mean and 90 % range across members for each year (rounded floats)."""
    v = np.asarray(values, float)
    return {"mean": np.round(v.mean(axis=1), 3).tolist(),
            "p05": np.round(np.percentile(v, 5, axis=1), 3).tolist(),
            "p95": np.round(np.percentile(v, 95, axis=1), 3).tolist()}
