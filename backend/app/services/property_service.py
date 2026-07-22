import json
from functools import lru_cache
from pathlib import Path

from app.models.schemas import Property


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "properties.json"


@lru_cache
def load_properties() -> list[Property]:
    with DATA_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return [Property.model_validate(item) for item in data]
