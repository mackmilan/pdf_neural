from __future__ import annotations

import sys

from backend.app.db import odm as _odm

sys.modules[__name__] = _odm
