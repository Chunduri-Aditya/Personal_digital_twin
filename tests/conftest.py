"""Pytest configuration: make the project root importable and isolate the suite from shell env."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _no_twin_env(monkeypatch):
    """UI agents run with TWIN_NO_WARM=1 / TWIN_THEME set; tests must not see them."""
    monkeypatch.delenv("TWIN_NO_WARM", raising=False)
    monkeypatch.delenv("TWIN_THEME", raising=False)
