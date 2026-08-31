"""RouteRegisterFastApi — re-export of platform_core.http.

Kept so `from src.interfaces.http.route_register_fast_api import RouteRegisterFastApi`
keeps working. platform_core's `execute()` adds optional `compress`/`file` params
(default off) — call sites that pass only 4 args are unchanged.
"""

from platform_core.http.route_register import RouteRegisterFastApi

__all__ = ["RouteRegisterFastApi"]
