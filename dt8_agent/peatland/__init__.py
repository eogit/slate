"""Server-safe copy of the three-gas drained-peatland digital twin (CO2, CH4, N2O).

Sources:

* CO2 and N2O: eogit/digital_twin, ``peatland_pignn.py`` (main) and
  ``peatland_crop_validation.py`` / ``peatland_n2o.py`` (``peatland-ghg-twin`` branch), in the
  configuration of ``peatland_digital_twin.ipynb``.
* CH4: the standalone CH4 notebook ``peatland_ch4_model_with_litter_extension.ipynb``, Sections
  1-10 plus the Section 14 extension (methane from vegetation killed by flooding). The
  plant-functional-type extension (Section 15) and the model intercomparison (Section 11) are
  not included.

The physics is unchanged. What differs from the originals, so the code can run inside a
long-lived MCP server:

* no plotting library or pandas is imported and nothing is written to the working directory;
* nothing is printed: every function returns its result;
* calibrations return parameter sets instead of mutating module globals;
* imports are package-relative, so the modules work wherever the package is installed;
* learned parameters live in :mod:`peatland.state`, which can persist them to JSON.
"""

from . import ch4, co2, inventory, n2o, soil_temp
from .state import ParameterStore

__all__ = ["co2", "ch4", "n2o", "inventory", "soil_temp", "ParameterStore"]
