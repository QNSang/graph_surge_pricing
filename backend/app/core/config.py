"""Runtime settings (env) and surge policy (config/policy.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://surge:surge@localhost:5433/surge"
    demo_tokens: str = "demo-operator-token:operator_01:OPERATOR,demo-viewer-token:viewer_01:VIEWER"
    cors_origins: str = "http://localhost:5173"
    repo_root: str = ".."
    policy_file: str = "config/policy.yaml"
    timezone: str = "Asia/Ho_Chi_Minh"

    @property
    def repo_path(self) -> Path:
        path = Path(self.repo_root)
        return path if path.is_absolute() else (BACKEND_ROOT / path).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@dataclass(frozen=True)
class SurgeLimits:
    min: Decimal
    max: Decimal
    max_deviation: Decimal
    step: Decimal
    precision: int


@dataclass(frozen=True)
class Policy:
    policy_version: str
    execution_mode: str
    replay_mode: str
    region_id: str
    region_label: str
    limits: SurgeLimits
    override_requires_reason: bool
    allow_hold_override: bool
    batch_plan_ttl_minutes: int
    mock_controller: dict

    def as_public_dict(self) -> dict:
        return {
            "policy_version": self.policy_version,
            "execution_mode": self.execution_mode,
            "replay_mode": self.replay_mode,
            "surge_limits": {
                "min": str(self.limits.min),
                "max": str(self.limits.max),
                "max_deviation": str(self.limits.max_deviation),
                "step": str(self.limits.step),
                "precision": self.limits.precision,
            },
            "override_requires_reason": self.override_requires_reason,
            "allow_hold_override": self.allow_hold_override,
            "batch_plan_ttl_minutes": self.batch_plan_ttl_minutes,
        }


def load_policy(path: Path) -> Policy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    lim = raw["surge_limits"]
    return Policy(
        policy_version=str(raw["policy_version"]),
        execution_mode=str(raw.get("execution_mode", "DEMO")),
        replay_mode=str(raw.get("replay_mode", "DEMO_REPLAY")),
        region_id=str(raw["region_id"]),
        region_label=str(raw.get("region_label", raw["region_id"])),
        limits=SurgeLimits(
            min=Decimal(str(lim["min"])),
            max=Decimal(str(lim["max"])),
            max_deviation=Decimal(str(lim["max_deviation"])),
            step=Decimal(str(lim["step"])),
            precision=int(lim["precision"]),
        ),
        override_requires_reason=bool(raw.get("override_requires_reason", True)),
        allow_hold_override=bool(raw.get("allow_hold_override", True)),
        batch_plan_ttl_minutes=int(raw.get("batch_plan_ttl_minutes", 5)),
        mock_controller=dict(raw.get("mock_controller", {})),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_policy() -> Policy:
    settings = get_settings()
    path = Path(settings.policy_file)
    return load_policy(path if path.is_absolute() else BACKEND_ROOT / path)
