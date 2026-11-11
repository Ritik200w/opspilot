import copy
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent


def load(name: str) -> dict[str, Any]:
    """Load a JSON fixture. Returns a fresh copy each call so tests can mutate it."""
    return copy.deepcopy(json.loads((FIXTURES / name).read_text()))
