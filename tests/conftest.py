from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "synthetic"
MAIN = "graphical/GENERIC_TAX_REPORTING_CUBE.calculationview"


@pytest.fixture
def fixture_bytes():
    def load(rel: str) -> bytes:
        return (FIXTURES / rel).read_bytes()

    return load


@pytest.fixture
def parse_fixture():
    from app.parsers.dispatch import parse_bytes

    def parse(rel: str):
        path = FIXTURES / rel
        return parse_bytes(path.read_bytes(), file_name=path.name)

    return parse
