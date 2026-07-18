from __future__ import annotations

import sys

from backend.app.core import config as _config

sys.modules[__name__] = _config
