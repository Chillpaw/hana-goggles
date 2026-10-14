"""Golden IR snapshots. A regression guard, not the primary check: the hand-written
assertions in test_graphical_*.py define correctness. Regenerate with
UPDATE_GOLDEN=1 pytest tests/test_golden_ir.py, then review the diff by hand."""
import os

import pytest
from conftest import FIXTURES

from app.parsers.dispatch import parse_bytes

CASES = sorted(FIXTURES.rglob("*.calculationview"))


def test_fixture_set_is_not_empty():
    assert len(CASES) >= 4


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_ir_matches_golden(path):
    actual = parse_bytes(path.read_bytes(), file_name=path.name).model_dump_json(indent=2) + "\n"
    golden = path.with_name(f"{path.stem}.ir.json")
    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden.write_bytes(actual.encode("utf-8"))
    assert golden.exists(), f"missing {golden.name}; run UPDATE_GOLDEN=1 pytest tests/test_golden_ir.py and review it"
    assert actual == golden.read_text(encoding="utf-8")
