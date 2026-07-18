from __future__ import annotations

import sys

from backend.app.api import static as _static

sys.modules[__name__] = _static
