"""Validated, vendor-independent configuration and journey contracts."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

Viewport = Literal["desktop", "mobile"]
Environment = Literal["preview", "prod"]
SAFETY_PREAMBLE = "Never submit payment, never send messages, never delete data."


def validate_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an HTTP(S) demo URL without credentials, query or fragment")
    return value.rstrip("/")


class Journey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    name: str
    entry_path: str
    goal: str
    success_criteria: list[str] = Field(min_length=1)
    owns: list[str] = Field(default_factory=list)
    critical_selectors: list[str] = Field(default_factory=list)
    viewports: list[Viewport] = Field(default_factory=lambda: ["desktop", "mobile"], min_length=1)
    max_steps: int = Field(default=25, ge=1, le=100)

    @field_validator("entry_path")
    @classmethod
    def local_path(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//") or "\\" in value:
            raise ValueError("entry_path must be a local absolute URL path")
        return value

    @property
    def safe_goal(self) -> str:
        return f"{SAFETY_PREAMBLE}\n{self.goal}"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    production_url: str = "http://localhost:3000"
    viewports: dict[Viewport, dict[str, int]] = Field(
        default_factory=lambda: {
            "desktop": {"width": 1440, "height": 900},
            "mobile": {"width": 390, "height": 844},
        }
    )
    concurrency: int = Field(default=2, ge=1, le=10)
    budget_usd_per_run: float = Field(default=3, gt=0, allow_inf_nan=False)
    fail_on: list[Literal["P0", "P1", "P2"]] = Field(default_factory=lambda: ["P0"])
    llm_provider: str = "openai"
    llm_model: str = "configured-in-M3"
    confirm_retries: int = Field(default=1, ge=0, le=1)
    include_fetch_precheck: bool = True
    include_search: bool = True
    max_duration_seconds: int = Field(default=300, ge=1, le=300)

    _url = field_validator("production_url")(validate_url)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    journeys: list[Journey] = Field(min_length=1)

    @field_validator("journeys")
    @classmethod
    def unique_ids(cls, values: list[Journey]) -> list[Journey]:
        if len({item.id for item in values}) != len(values):
            raise ValueError("Journey IDs must be unique")
        return values


def load_config(path: Path = Path(".ux-guardian") / "config.yaml") -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_journeys(path: Path = Path(".ux-guardian") / "journeys.yaml") -> list[Journey]:
    return Manifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).journeys
