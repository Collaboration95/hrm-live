"""Pure motion-policy decisions for the dashboard UI (no AppKit).

Kept free of AppKit so the decision table is unit-testable headless.
"""

from __future__ import annotations


def should_pulse(connection_status: str, reduce_motion: bool) -> bool:
    """Return whether the hero gauge should show the subtle live pulse.

    Rules:
      * Reduce Motion is on  -> never animate.
      * Not connected        -> static (disconnected/connecting/reconnecting/error).
      * Connected            -> gentle breathing pulse.
    """
    if reduce_motion:
        return False
    return connection_status == "connected"
