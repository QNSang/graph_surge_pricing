"""Config huấn luyện YAML. Khoá lạ bị từ chối; đường dẫn tương đối tính từ thư mục chứa file config."""

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from surge_ml.errors import SurgeError
from surge_ml.features import HORIZON, MAX_HORIZON, SNAPSHOT_SECONDS, VARIANTS, WINDOW


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataConfig(_Base):
    # Give `current` (data/CURRENT.json, the release pointer, wins) or an explicit `source_root`.
    current: Path | None = None
    source_root: Path | None = None  # filled from `current` by load_config
    derived_root: Path
    dataset_id: str  # pinned: must equal CURRENT.json and the source manifest, so a new release is never silent
    # 1-based inclusive days per split, e.g. {train: [1, 63], val: [64, 76], test: [77, 90]};
    # null = the source manifest's suggested_split_days_inclusive.
    split_days: dict[str, tuple[int, int]] | None = None
    std_floor: float = 1e-6
    window_steps: int = WINDOW  # input snapshots per sample (4 = 20 min, 6 = 30 min)
    horizon_steps: int = HORIZON  # target y[k] = b[k + h]; 1, 2, 3 = 5, 10, 15 min

    @field_validator("window_steps")
    @classmethod
    def _window(cls, v: int) -> int:
        if v < 1:
            raise ValueError("window_steps must be >= 1")
        return v

    @field_validator("horizon_steps")
    @classmethod
    def _horizon(cls, v: int) -> int:
        if not 1 <= v <= MAX_HORIZON:
            raise ValueError(f"horizon_steps must be in 1..{MAX_HORIZON} (END_GAP covers 15 min)")
        return v

    @property
    def horizon_minutes(self) -> int:
        return self.horizon_steps * SNAPSHOT_SECONDS // 60

    @model_validator(mode="after")
    def _has_source(self) -> "DataConfig":
        # load_config fills source_root from `current`, so a loaded config legitimately has both.
        if self.current is None and self.source_root is None:
            raise ValueError("data: set `current` (CURRENT.json) or `source_root`")
        return self


class ModelConfig(_Base):
    gru_hidden: int = 64
    neighbor_hidden: int = 16
    gat_layers: int = 2
    gat_heads: int = 4
    head_hidden: int = 64
    dropout: float = 0.1


class LossConfig(_Base):
    smooth_l1_beta: float = 1.0
    lambda_local: float = 0.3

    @field_validator("lambda_local")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("lambda_local must be > 0 (report §8.2)")
        return v


class TrainConfig(_Base):
    device: str = "auto"
    batch_size: int = 32
    eval_batch_size: int = 128
    epochs: int = 30
    lr: float = 1e-3
    weight_decay: float = 1e-4
    grad_clip_norm: float = 1.0
    patience: int = 5
    scheduler: Literal["none", "cosine", "plateau"] = "cosine"
    tie_tolerance: float = 1e-6
    smoke_batches: int = 5
    limit_batches: int | None = None  # set by --smoke


class TrackingConfig(_Base):
    enabled: bool = True
    experiment: str = "graph_surge_pricing"  # prefix; the CLI appends _<YYYYmmdd-HHMMSS> per invocation


class ControllerConfig(_Base):
    """Chính sách demo/shadow sau dự báo; giá trị chỉ là ví dụ cho đến khi hiệu chuẩn."""

    execution_mode: Literal["demo", "shadow"] = "demo"
    policy_version: str = "w4_pressure_revision_demo_v1"
    reference_version: str = "smoothed_q_reference_demo_v1"
    calibrated: bool = False
    reference_q: float = 1.2
    q_min: float = 1e-6
    pressure_dead_zone: float = 0.10
    revision_dead_zone: float = 0.05
    pressure_gain: float = 0.60
    revision_gain: float = 0.40
    max_requested_delta: float = 0.40
    surge_min: float = 1.0
    surge_max: float = 3.0

    @model_validator(mode="after")
    def _valid_policy(self) -> "ControllerConfig":
        numeric = {
            "reference_q": self.reference_q,
            "q_min": self.q_min,
            "pressure_dead_zone": self.pressure_dead_zone,
            "revision_dead_zone": self.revision_dead_zone,
            "pressure_gain": self.pressure_gain,
            "revision_gain": self.revision_gain,
            "max_requested_delta": self.max_requested_delta,
            "surge_min": self.surge_min,
            "surge_max": self.surge_max,
        }
        bad = [name for name, value in numeric.items() if not math.isfinite(value)]
        if bad:
            raise ValueError(f"controller values must be finite: {bad}")
        if self.reference_q <= 0 or self.q_min <= 0:
            raise ValueError("controller reference_q and q_min must be > 0")
        if self.pressure_dead_zone < 0 or self.revision_dead_zone < 0:
            raise ValueError("controller dead zones must be >= 0")
        if self.pressure_gain < 0 or self.revision_gain < 0:
            raise ValueError("controller gains must be >= 0")
        if not 0 < self.max_requested_delta <= 0.40:
            raise ValueError("controller max_requested_delta must be in (0, 0.40]")
        if self.surge_min >= self.surge_max:
            raise ValueError("controller surge_min must be < surge_max")
        if self.calibrated:
            raise ValueError("production-calibrated controller is not supported by this research pipeline")
        return self


class Config(_Base):
    study_id: str
    seeds: list[int]
    variants: list[str]
    data: DataConfig
    model: ModelConfig = ModelConfig()
    loss: LossConfig = LossConfig()
    train: TrainConfig = TrainConfig()
    tracking: TrackingConfig = TrackingConfig()
    controller: ControllerConfig = ControllerConfig()
    runs_root: Path
    # Per-variant tuning: {variant: {section: {key: value}}}, merged over the shared sections above.
    overrides: dict[str, dict[str, dict]] = {}

    @field_validator("variants")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        unknown = [x for x in v if x not in VARIANTS]
        if unknown:
            raise ValueError(f"unknown variants {unknown}; known: {list(VARIANTS)}")
        return v

    @model_validator(mode="after")
    def _valid_overrides(self) -> "Config":
        for name, patch in self.overrides.items():
            if name not in VARIANTS:
                raise ValueError(f"overrides: unknown variant {name!r}")
            bad = set(patch) - set(OVERRIDABLE)
            if bad:
                raise ValueError(f"overrides.{name}: sections {sorted(bad)} cannot be overridden; use {OVERRIDABLE}")
            try:
                self.for_variant(name)
            except ValidationError as exc:
                raise ValueError(f"overrides.{name}: {exc}") from exc
        return self

    def for_variant(self, name: str) -> "Config":
        """Bản config này với overrides[name] đã gộp vào các mục; kết quả không còn overrides."""
        d = self.model_dump()
        patch = d.pop("overrides").get(name, {})
        for section, values in patch.items():
            d[section] = {**d[section], **values}
        return Config.model_validate(d)


OVERRIDABLE = ("model", "loss", "train")


def _source_from_current(current: Path, dataset_id: str) -> Path:
    """Thư mục dataset do data/CURRENT.json chỉ; `path` tính từ gốc repo."""
    if not current.is_file():
        raise SurgeError("CONFIG", f"data.current not found: {current}")
    pointer = json.loads(current.read_text(encoding="utf-8"))
    if pointer.get("dataset_id") != dataset_id:
        raise SurgeError("CONFIG", f"{current} points to {pointer.get('dataset_id')!r} but data.dataset_id is "
                                   f"{dataset_id!r}; update data.dataset_id (and study_id) to train on it")
    return (current.parent.parent / pointer["path"]).resolve()


def load_config(path: str | Path) -> Config:
    path = Path(path).resolve()
    if not path.is_file():
        raise SurgeError("CONFIG", f"config not found: {path}")
    try:
        cfg = Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValidationError as exc:
        raise SurgeError("CONFIG", str(exc)) from exc
    base = path.parent
    if cfg.data.current is not None:
        cfg.data.current = (base / cfg.data.current).resolve()
        cfg.data.source_root = _source_from_current(cfg.data.current, cfg.data.dataset_id)
    else:
        cfg.data.source_root = (base / cfg.data.source_root).resolve()
    cfg.data.derived_root = (base / cfg.data.derived_root).resolve()
    cfg.runs_root = (base / cfg.runs_root).resolve()
    return cfg


def apply_overrides(cfg: Config, *, smoke: bool = False, epochs: int | None = None,
                    no_tracking: bool = False) -> Config:
    cfg = cfg.model_copy(deep=True)
    if smoke:
        cfg.study_id += "-smoke"
        cfg.train.epochs = 2
        cfg.train.limit_batches = cfg.train.smoke_batches
    if epochs is not None:
        cfg.train.epochs = epochs
    if no_tracking:
        cfg.tracking.enabled = False
    return cfg


# Sections each model family depends on. A trial's hash covers only these, so tuning one family (or one
# variant via overrides) leaves the other trials valid.
_EVAL = {"data": True, "loss": {"smooth_l1_beta"}, "train": {"eval_batch_size", "limit_batches"}}
HASHED = {
    "gru": {"data": True, "model": True, "loss": True, "train": True},
    "persistence": _EVAL,
    "seasonal": _EVAL,
}


def config_sha256(cfg: Config, variant: str | None = None) -> str:
    """Định danh thiết lập huấn luyện của trial; số epoch và tracking không ảnh hưởng nên có thể resume với --epochs lớn hơn. Có `variant` thì băm config đã gộp của variant, chỉ các mục họ model dùng."""
    if variant is None:
        d = cfg.model_dump(mode="json", exclude={"tracking": True, "controller": True, "train": {"epochs"},
                                                 "seeds": True, "variants": True, "runs_root": True,
                                                 "overrides": True})
    else:
        d = cfg.for_variant(variant).model_dump(mode="json", include=HASHED[VARIANTS[variant].family],
                                                exclude={"train": {"epochs"}})
    # Defaults of keys added later are left out so studies made before these keys existed keep their hash.
    for key, default in (("window_steps", WINDOW), ("horizon_steps", HORIZON)):
        if d["data"].get(key) == default:
            d["data"].pop(key)
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def flat_params(cfg: Config) -> dict[str, str]:
    out: dict[str, str] = {"data.horizon_minutes": str(cfg.data.horizon_minutes)}
    for section, values in cfg.model_dump(mode="json").items():
        if isinstance(values, dict):
            out.update({f"{section}.{k}": str(v) for k, v in values.items()})
        else:
            out[section] = str(values)
    return out
