from __future__ import annotations

import sys

from backend.app.workers import jobs as _jobs

sys.modules[__name__] = _jobs
