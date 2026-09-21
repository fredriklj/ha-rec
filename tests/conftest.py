"""Test bootstrap.

``registers.py`` and ``modbus.py`` are deliberately free of Home Assistant
imports so they can be tested — and later packaged — on their own. Importing
them through ``custom_components.rec_temovex`` would run the integration's
``__init__.py`` and drag Home Assistant in, so the package is stitched together
here by hand instead.
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "rec_temovex"

_package = types.ModuleType("rec_temovex")
_package.__path__ = [str(COMPONENT)]
sys.modules.setdefault("rec_temovex", _package)

# Import eagerly so a syntax error surfaces at collection time.
importlib.import_module("rec_temovex.registers")
importlib.import_module("rec_temovex.const")
importlib.import_module("rec_temovex.modbus")
