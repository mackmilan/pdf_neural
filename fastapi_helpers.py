from __future__ import annotations

import sys

from backend.app.api import helpers as _helpers

sys.modules[__name__] = _helpers
