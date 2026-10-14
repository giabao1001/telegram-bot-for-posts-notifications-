"""Make the ``diemrenluyen_v2`` package importable when pytest is run from the
repository root (e.g. ``python -m pytest v2/tests`` in CI).

Pytest imports ``conftest.py`` files top-down before collecting test modules,
so inserting this directory into ``sys.path`` here guarantees the package
resolves no matter which working directory the test run starts from.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
