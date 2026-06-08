from pathlib import Path

from ..utils.image import to_data_uri

TEMPLATES_PATH = Path(__file__).parent.parent / "templates"

__all__ = ["TEMPLATES_PATH", "to_data_uri"]