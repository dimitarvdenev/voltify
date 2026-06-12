import json
import os

import pytest

from agent import config


@pytest.fixture(scope="session")
def arc():
    with open(os.path.join(config.ROOT, "scenarios", "arc_118.json")) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def tools():
    """Shared GridTools on the demo chronic for read-only tests."""
    from agent.tools import GridTools

    return GridTools()
