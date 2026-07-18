from __future__ import annotations

import sys

from backend.app.services import formatting as _formatting

sys.modules[__name__] = _formatting
