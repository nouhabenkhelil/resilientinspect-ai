"""Chemins locaux et limites du MVP."""

from dataclasses import dataclass
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
API_VERSION = "0.1.0"


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT
    max_file_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 20_000_000

    @property
    def manifest(self) -> Path:
        return self.project_root / "data/manifests/manifest.csv"
