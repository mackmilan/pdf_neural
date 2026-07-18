from __future__ import annotations

import sys

from backend.app.ml import tables as _tables

sys.modules[__name__] = _tables
