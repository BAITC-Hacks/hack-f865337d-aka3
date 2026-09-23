"""Input adapters live here; engine only sees a validated internal Dataset."""
from pathlib import Path
from .models import Dataset

DEMO_PATH = Path(__file__).resolve().parent.parent / 'demo' / 'dataset.json'


def load_dataset(path: str | Path = DEMO_PATH) -> Dataset:
    return Dataset.model_validate_json(Path(path).read_text(encoding='utf-8'))
