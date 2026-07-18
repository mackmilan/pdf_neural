from __future__ import annotations

import sys

from backend.app.services import converter as _converter

sys.modules[__name__] = _converter
