from __future__ import annotations

import sys

from backend.app.auth import service as _service

sys.modules[__name__] = _service
