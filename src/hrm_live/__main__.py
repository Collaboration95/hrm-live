"""Run HRM Live with ``python -m hrm_live``."""

import sys

# The py2app launcher executes this source from the signed application bundle.
# Avoid adding ``__pycache__`` files there after code signing.
sys.dont_write_bytecode = True

from hrm_live.app import main  # noqa: E402  # Must follow bytecode-write configuration.

if __name__ == "__main__":
    main()
