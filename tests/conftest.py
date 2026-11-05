import json
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


@pytest.fixture
def fixtures():
    return FIXTURES


@pytest.fixture
def profiles(tmp_path):
    """Copies of the two fixture profiles in a scratch dir (safe to write)."""
    paths = []
    for name in ("profile_a", "profile_b"):
        dst = tmp_path / name
        shutil.copytree(os.path.join(FIXTURES, name), dst)
        paths.append(str(dst))
    return paths


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
