from __future__ import annotations

import sys

from backend.app.legacy import handler as _handler

sys.modules[__name__] = _handler
