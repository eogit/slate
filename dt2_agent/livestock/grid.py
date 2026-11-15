"""The 1 km British National Grid (EPSG:27700) on which DT2 keeps its state.

Rows run north to south (row 0 is the northern edge), columns west to east, as in a GeoTIFF.
The extent covers England including the Isles of Scilly and Berwick-upon-Tweed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Grid:
    x0: float = 80_000.0      # western edge, metres easting
    y1: float = 660_000.0     # northern edge, metres northing
    nx: int = 580
    ny: int = 660
    res: float = 1_000.0
    crs: str = "EPSG:27700"

    @property
    def shape(self) -> tuple[int, int]:
        return (self.ny, self.nx)

    @property
    def transform(self):
        """Affine transform (rasterio convention)."""
        from affine import Affine
        return Affine(self.res, 0.0, self.x0, 0.0, -self.res, self.y1)

    def index(self, x: float, y: float) -> tuple[int, int]:
        """(row, col) of the cell containing easting x, northing y (may fall outside)."""
        return int((self.y1 - y) // self.res), int((x - self.x0) // self.res)

    def centre(self, row: int, col: int) -> tuple[float, float]:
        """Easting and northing of a cell centre."""
        return self.x0 + (col + 0.5) * self.res, self.y1 - (row + 0.5) * self.res

    def bounds(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y1 - self.ny * self.res, self.x0 + self.nx * self.res, self.y1)


GRID = Grid()
