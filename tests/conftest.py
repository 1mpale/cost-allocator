from pathlib import Path
import pytest

MOCK_DATA_DIR = Path(__file__).parent.parent / "mock_data"

@pytest.fixture
def mock_data_dir():
    return MOCK_DATA_DIR
