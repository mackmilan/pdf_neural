from __future__ import annotations

import sys

from backend.app.db import mongo as _mongo

sys.modules[__name__] = _mongo
