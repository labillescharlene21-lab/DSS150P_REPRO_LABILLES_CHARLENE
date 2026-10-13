from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    raw: dict

    def path(self, key: str) -> Path:
        return ROOT / self.raw["paths"][key]

    @property
    def source_file(self) -> Path:
        return self.path("source_dir") / self.raw["source"]["filename"]

    @property
    def seed(self) -> int:
        return int(os.getenv("RANDOM_SEED", self.raw["modeling"]["random_seed"]))


def load_settings(path: Path | None = None) -> Settings:
    path = path or ROOT / "config" / "settings.yml"
    with open(path, "r", encoding="utf-8") as f:
        return Settings(yaml.safe_load(f))