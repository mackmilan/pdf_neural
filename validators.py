from __future__ import annotations

import sys

from backend.app.utils import validation as _validation

sys.modules[__name__] = _validation
