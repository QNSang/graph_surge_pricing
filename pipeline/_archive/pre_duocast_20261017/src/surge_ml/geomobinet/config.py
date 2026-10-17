"""Strict configuration for the demand/idle-supply forecasting contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import CONTRACT_VERSION

NEURAL_VARIANTS = {
    "gru": (False, False, False, False),
    "gru_spatial": (True, False, False, False),
    "gru_mobility": (False, True, False, False),
    "gru_dual_graph": (True, True, False, False),
    "geomobinet_smg": (True, True, True, False),
    "geomobinet_smg_road": (True, True, True, True),
}
BASELINES = ("persistence", "seasonal_naive", "lgbm_local", "lgbm_network")
VARIANTS = (*BASELINES, *NEURAL_VARIANTS)
TARGETS = ("demand_5m", "idle_supply_t")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DataConfig(StrictModel):
    market: Path
    geo: Path
    spatial: Path
    mobility: Path
    metadata: Path
    timezone: str = "Asia/Ho_Chi_Minh"
    history: int = Field(12, ge=1)
    horizon: Literal[1] = 1
    validate_h3: bool = True
    availability: Literal["strict", "snapshot_contract"] = "strict"
    dynamic_features: list[str] = Field(default_factory=lambda: [
        "demand_5m", "idle_supply_t", "backlog_t", "eta_sec_t", "base_surge"])
    geo_features: list[str] = Field(default_factory=lambda: [
        "distance_to_cbd_km", "east_offset_km", "north_offset_km", "road_neighbor_count"])
    spatial_features: list[str] = Field(default_factory=list)
    mobility_features: list[str] = Field(default_factory=lambda: ["flow_5m", "eta_min", "distance_km"])
    nullable_dynamic: list[str] = Field(default_factory=list)
    log_dynamic: list[str] = Field(default_factory=lambda: ["demand_5m", "idle_supply_t", "backlog_t", "eta_sec_t"])
    log_geo: list[str] = Field(default_factory=list)
    log_spatial: list[str] = Field(default_factory=list)
    log_mobility: list[str] = Field(default_factory=lambda: ["flow_5m", "eta_min", "distance_km"])
    signed_features: list[str] = Field(default_factory=lambda: [
        "east_offset_km", "north_offset_km", "hour_sin", "hour_cos", "dow_sin", "dow_cos",
        "od_cbd_distance_delta", "od_cbd_distance_delta_km", "driver_net_flow_5m"])
    train_fraction: float = Field(0.70, gt=0, lt=1)
    val_fraction: float = Field(0.15, gt=0, lt=1)
    # Strict evaluation keeps each split's whole lookback inside its partition.
    split_mode: Literal["strict", "rolling"] = "strict"
    embargo_steps: int = Field(0, ge=0)

    @model_validator(mode="after")
    def validate_contract(self):
        if self.train_fraction + self.val_fraction >= 1:
            raise ValueError("train_fraction + val_fraction must be < 1")
        if not set(TARGETS) <= set(self.dynamic_features):
            raise ValueError("dynamic_features must include demand_5m and idle_supply_t")
        for name in ("dynamic_features", "geo_features", "spatial_features", "mobility_features"):
            names = getattr(self, name)
            if len(names) != len(set(names)) or any(not x for x in names):
                raise ValueError(f"{name} must contain unique nonempty names")
        if not self.geo_features or not self.mobility_features:
            raise ValueError("geo_features and mobility_features cannot be empty")
        if not set(self.nullable_dynamic) <= set(self.dynamic_features) or set(TARGETS) & set(self.nullable_dynamic):
            raise ValueError("nullable_dynamic must be input columns, never targets")
        for kind in ("dynamic", "geo", "spatial", "mobility"):
            if not set(getattr(self, f"log_{kind}")) <= set(getattr(self, f"{kind}_features")):
                raise ValueError(f"log_{kind} contains unknown feature names")
            if set(getattr(self, f"log_{kind}")) & set(self.signed_features):
                raise ValueError("signed features cannot be log1p transformed")
        forbidden = ("effective_supply", "arriving_trip", "predicted_", "propensity", "transition_prob",
                     "incoming_drivers", "od_requests", "od_arrivals", "future_")
        names = self.dynamic_features + self.mobility_features
        if any(any(token in name for token in forbidden) for name in names):
            raise ValueError("prediction-derived/future/passenger-OD features are outside the SMG contract")
        return self


class ModelConfig(StrictModel):
    hidden: int = Field(64, ge=2)
    geo_hidden: int = Field(32, ge=1)
    heads: int = Field(2, ge=1)
    head_hidden: int = Field(32, ge=1)
    dropout: float = Field(0.1, ge=0, lt=1)

    @model_validator(mode="after")
    def dimensions(self):
        if self.hidden % self.heads:
            raise ValueError("hidden must be divisible by heads")
        return self


class TrainConfig(StrictModel):
    device: str = "auto"
    epochs: int = Field(50, ge=1)
    batch_size: int = Field(16, ge=1)
    eval_batch_size: int = Field(64, ge=1)
    lr: float = Field(1e-3, gt=0)
    weight_decay: float = Field(1e-4, ge=0)
    grad_clip: float = Field(1.0, gt=0)
    patience: int = Field(8, ge=1)
    min_delta: float = Field(1e-6, ge=0)
    huber_delta: float = Field(1.0, gt=0)
    num_threads: int = Field(2, ge=1)
    limit_batches: int | None = Field(None, ge=1)
    lgbm_rounds: int = Field(500, ge=1)


class EvalConfig(StrictModel):
    shortage_threshold: float = Field(1.0, ge=0)
    low_supply_threshold: float = Field(2.0, ge=0)
    high_demand_quantile: float = Field(0.90, gt=0, lt=1)
    seasonal_period: int = Field(288, ge=1)


class Config(StrictModel):
    contract_version: Literal["geomobinet_smg_ds_h5_v1"] = CONTRACT_VERSION
    study_id: str = "geomobinet-smg-v1"
    seeds: list[int] = Field(default_factory=lambda: [42, 43, 44])
    variants: list[str] = Field(default_factory=lambda: ["persistence", "geomobinet_smg"])
    output_dir: Path = Path("../runs/geomobinet-smg-v1")
    data: DataConfig
    model: ModelConfig = Field(default_factory=ModelConfig)
    train: TrainConfig = Field(default_factory=TrainConfig)
    evaluation: EvalConfig = Field(default_factory=EvalConfig)

    @model_validator(mode="after")
    def study(self):
        if not self.seeds or len(self.seeds) != len(set(self.seeds)):
            raise ValueError("seeds must be nonempty and unique")
        if not self.variants or len(self.variants) != len(set(self.variants)) or set(self.variants) - set(VARIANTS):
            raise ValueError(f"variants must be unique members of {VARIANTS}")
        return self


def load_config(path: str | Path) -> Config:
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"[CONFIG] Config not found: {path}")
    cfg = Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    for field in ("market", "geo", "spatial", "mobility", "metadata"):
        setattr(cfg.data, field, (path.parent / getattr(cfg.data, field)).resolve())
    cfg.output_dir = (path.parent / cfg.output_dir).resolve()
    return cfg


def config_hash(cfg: Config) -> str:
    # Epoch budget may increase when resuming, but data/model/loss semantics may not.
    value = cfg.model_dump(mode="json", exclude={"output_dir", "seeds", "variants"})
    value["train"].pop("epochs")
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
