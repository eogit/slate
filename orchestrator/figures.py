"""Figures for orchestrator reports: bar and line charts, and point maps of England.

Claude passes the numbers it got from the agents; this module only draws them. Figures are
saved as PNG (for the HTML report, embedded) and referenced from the Markdown report.

Colours follow a small colour-blind-safe categorical palette; maps draw England's outline
from DT2's Living England 1 km coverage when it is present in the checkout, in British National
Grid coordinates, so distances and areas are true.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

PALETTE = ["#1b6ca8", "#e08a1e", "#3a9a5b", "#c4473a", "#7b5ea7", "#8c6d46", "#5f9ea0"]
REPO = Path(__file__).resolve().parent.parent
LE_FILE = REPO / "dt2_agent" / "livestock" / "data" / "living_england_1km.npz"


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.dpi": 150})
    return plt


def bar(path: Path, title: str, categories: list[str], series: dict[str, list[float]],
        ylabel: str = "", note: str = "", errors: dict[str, list[float]] | None = None) -> Path:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7, 3.8))
    n = len(series)
    width = 0.8 / max(n, 1)
    x = np.arange(len(categories))
    for k, (name, vals) in enumerate(series.items()):
        err = (errors or {}).get(name)
        ax.bar(x + (k - (n - 1) / 2) * width, vals, width, label=name,
               color=PALETTE[k % len(PALETTE)], yerr=err, capsize=3 if err else 0)
    ax.set_xticks(x, categories, rotation=20 if max(map(len, categories)) > 10 else 0,
                  ha="right" if max(map(len, categories)) > 10 else "center")
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontweight="bold")
    ax.axhline(0, color="#444", lw=0.6)
    if n > 1:
        ax.legend(frameon=False)
    if note:
        fig.text(0.01, 0.01, note, fontsize=8, color="#555")
    fig.tight_layout(rect=(0, 0.04 if note else 0, 1, 1))
    fig.savefig(path)
    plt.close(fig)
    return path


def line(path: Path, title: str, x: list[float], series: dict[str, list[float]],
         xlabel: str = "", ylabel: str = "", note: str = "") -> Path:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7, 3.8))
    for k, (name, vals) in enumerate(series.items()):
        ax.plot(x, vals, label=name, color=PALETTE[k % len(PALETTE)], lw=1.8)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left", fontweight="bold")
    if len(series) > 1:
        ax.legend(frameon=False)
    if note:
        fig.text(0.01, 0.01, note, fontsize=8, color="#555")
    fig.tight_layout(rect=(0, 0.04 if note else 0, 1, 1))
    fig.savefig(path)
    plt.close(fig)
    return path


def _england_outline(ax) -> bool:
    if not LE_FILE.exists():
        return False
    le = np.load(LE_FILE)
    mask = le["ha"].sum(0) > 50
    # grid of DT2: 1 km cells, west edge 80 km, north edge 660 km (dt2_agent/livestock/grid.py)
    xs = 80_000 + (np.arange(mask.shape[1]) + 0.5) * 1000
    ys = 660_000 - (np.arange(mask.shape[0]) + 0.5) * 1000
    ax.contourf(xs, ys, mask.astype(float), levels=[0.5, 1.5], colors=["#eeeeea"])
    ax.contour(xs, ys, mask.astype(float), levels=[0.5], colors=["#9a9a90"], linewidths=0.5)
    return True


def point_map(path: Path, title: str, points: list[dict], value_label: str = "",
              note: str = "") -> Path:
    """Points with ``lat``, ``lon``, ``value`` and optional ``label`` on an England map."""
    from pyproj import Transformer
    plt = _plt()
    t = Transformer.from_crs(4326, 27700, always_xy=True)
    lon = [p["lon"] for p in points]
    lat = [p["lat"] for p in points]
    x, y = t.transform(lon, lat)
    v = np.array([float(p.get("value", 1.0)) for p in points])
    fig, ax = plt.subplots(figsize=(5.2, 6.2))
    outline = _england_outline(ax)
    size = 20 + 180 * (v - v.min()) / (np.ptp(v) or 1.0)
    sc = ax.scatter(x, y, s=size, c=v, cmap="viridis", edgecolor="k", linewidth=0.4, zorder=3)
    for xi, yi, p in zip(x, y, points):
        if p.get("label"):
            ax.annotate(p["label"], (xi, yi), xytext=(4, 4), textcoords="offset points",
                        fontsize=8, zorder=4)
    cb = fig.colorbar(sc, ax=ax, shrink=0.6)
    cb.set_label(value_label)
    ax.set_aspect("equal")
    if outline:
        ax.set_xlim(80_000, 660_000)
        ax.set_ylim(0, 660_000)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, loc="left", fontweight="bold")
    fig.text(0.01, 0.01, (note + "  " if note else "") + "British National Grid; outline: "
             "Living England coverage", fontsize=7, color="#555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path)
    plt.close(fig)
    return path
