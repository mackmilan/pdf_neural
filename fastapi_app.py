from __future__ import annotations

import sys

from backend.app import main as _main

if __name__ == "__main__":
    _main.main()
else:
    # Compatibility alias for existing imports, tests, and patch targets.
    # The canonical FastAPI module is now backend.app.main.
    sys.modules[__name__] = _main
