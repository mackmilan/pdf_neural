from __future__ import annotations

import sys

from backend.app.services import pdf as _pdf

sys.modules[__name__] = _pdf
