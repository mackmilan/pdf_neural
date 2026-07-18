"""HTTP helper compatibility facade.

New code should import HTTP-specific helpers from this module while the legacy
root module is migrated incrementally.
"""

from fastapi_helpers import *  # noqa: F401,F403
