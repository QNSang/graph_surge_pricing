from __future__ import annotations
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
import numpy as np
import pandas as pd
import torch
from pydantic import AwareDatetime, Field
from surge_ml._constant import CONTRACT_VERSION
from surge_ml._utils.io import digest_file
from surge_ml._utils.time import STEP
from surge_ml.datasets.duocast import load_panel, input_schema
from surge_ml.datasets.batching import Batcher
from surge_ml.train.duocast._types import Config, ModelConfig
from surge_ml.train.duocast.variants.neural import DuoCast, count_predictions
from surge_ml.contracts import Contract, Forecast, ForecastRow, Identity, Name, Nodes, NonNegative, TestOnly
from surge_ml.errors import require

def load_checkpoint_snapshot(path: Path) -> tuple[dict, str]:
    """Deserialize and identify exactly the same bytes, never two path revisions."""
    import hashlib
    import io
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Checkpoint does not exist: {path}")
    content = path.read_bytes()
    result = torch.load(io.BytesIO(content), map_location="cpu", weights_only=True)
    if not isinstance(result, dict) or result.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("Incompatible checkpoint: DuoCast no-geo demand/supply contract required; GeoMobiNet and legacy log-ratio checkpoints are rejected")
    return result, hashlib.sha256(content).hexdigest()


def load_checkpoint(path: Path) -> dict:
    return load_checkpoint_snapshot(path)[0]


def resolve_device(name: str) -> torch.device:
    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(name)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA was requested but is unavailable")
    return device


@torch.no_grad()
def predict(model, batcher: Batcher, cutoffs, batch_size: int):
    model.eval()
    outputs = []
    for start in range(0, len(cutoffs), batch_size):
        ks = cutoffs[start:start + batch_size]
        output = model(batcher.build(ks, targets=False))
        outputs.append(count_predictions(output).reshape(len(ks), batcher.panel.n_nodes, 2).cpu().numpy())
    if not outputs:
        raise ValueError("No inference cutoffs")
    return np.concatenate(outputs).astype(np.float64)


def predict_checkpoint(cfg: Config, panel, checkpoint_path: Path, cutoffs):
    checkpoint = load_checkpoint(checkpoint_path)
    return _predict_loaded_checkpoint(cfg, panel, checkpoint, cutoffs)


def _predict_loaded_checkpoint(cfg: Config, panel, checkpoint: dict, cutoffs):
    """Use a pinned artifact, shared by file inference and the decision provider."""
    if checkpoint.get("input_schema") != input_schema(cfg, panel):
        raise ValueError("Inference feature order, node order, target, history, or graph/schema version differs from checkpoint")
    device = resolve_device(cfg.train.device)
    torch.set_num_threads(cfg.train.num_threads)
    batcher = Batcher(panel, cfg.data, checkpoint["scalers"], device)
    model = DuoCast(**checkpoint["dimensions"], cfg=ModelConfig.model_validate(checkpoint["model_config"]),
                       variant=checkpoint["variant"]).to(device)
    model.load_state_dict(checkpoint["model_state"])
    return predict(model, batcher, cutoffs, cfg.train.eval_batch_size)


def prediction_frame(panel, cutoffs, pred):
    return pd.DataFrame({"cutoff_time": np.repeat(panel.timestamps[cutoffs].astype(str), panel.n_nodes),
                         "target_time": np.repeat((panel.timestamps[cutoffs] + STEP).astype(str), panel.n_nodes),
                         "hex_id": np.tile(panel.hex_ids, len(cutoffs)),
                         "pred_demand": pred[..., 0].reshape(-1),
                         "pred_idle_supply": pred[..., 1].reshape(-1),
                         "ds_proxy": (pred[..., 0] / (pred[..., 1] + 1.0)).reshape(-1)})


def forecast(cfg, checkpoint_path: Path, *, cutoff: int | None = None, output: Path | None = None):
    panel = load_panel(cfg.data)
    cutoff = len(panel.timestamps) - 1 if cutoff is None else cutoff
    if not cfg.data.history - 1 <= cutoff < len(panel.timestamps):
        raise ValueError("Forecast cutoff is outside the available history")
    ks = np.array([cutoff], dtype=np.int64)
    pred = predict_checkpoint(cfg, panel, checkpoint_path, ks)
    frame = prediction_frame(panel, ks, pred)
    if output is not None:
        output = output.resolve()
        if output.exists():
            raise ValueError(f"Forecast output already exists; choose a new path: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output, index=False)
    return frame


class MockCheckpoint(TestOnly):
    contract_version: Literal["duocast_ds_h5_v1"]
    model_id: Name
    checkpoint_version: Name
    dataset_id: Name
    dataset_fingerprint: Name
    feature_version: Name
    node_mapping_version: Name
    required_hex_ids: Nodes
    history_steps: Annotated[int, Field(gt=0, strict=True)]
    demand_definition: Literal["confirmed_valid_bookings_per_5min"]
    supply_definition: Literal["online_idle_dispatch_eligible_stock_at_target"]
    parity_status: Literal["TEST_ONLY_MOCK_VERIFIED"]
    evidence_refs: Annotated[tuple[Name, ...], Field(min_length=1)]
    features_available_at: AwareDatetime


class RawForecastRow(Contract):
    cutoff_time: AwareDatetime
    target_time: AwareDatetime
    hex_id: Name
    pred_demand: NonNegative
    pred_idle_supply: NonNegative
    ds_proxy: NonNegative | None = None


def check_mock_parity(identity: Identity, checkpoint: MockCheckpoint) -> None:
    for field in ("dataset_id", "dataset_fingerprint", "feature_version",
                  "node_mapping_version", "required_hex_ids"):
        require(getattr(identity, field) == getattr(checkpoint, field),
                "SEMANTIC_MISMATCH", f"Mock checkpoint parity mismatch: {field}")
    require(checkpoint.features_available_at <= identity.cutoff_time,
            "FORECAST_INVALID", "Forecast features unavailable at cutoff")


def adapt_rows(rows: Iterable[Mapping], *, identity: Identity, checkpoint: MockCheckpoint,
               forecast_run_id: str, generated_at) -> Forecast:
    identity = Identity.model_validate(identity)
    checkpoint = MockCheckpoint.model_validate(checkpoint)
    check_mock_parity(identity, checkpoint)
    parsed = tuple(RawForecastRow.model_validate(row) for row in rows)
    require(tuple(row.hex_id for row in parsed) == identity.required_hex_ids,
            "FORECAST_INVALID", "Raw forecast rows do not preserve full checkpoint node order")
    require(all(row.cutoff_time == identity.cutoff_time and row.target_time == identity.target_time for row in parsed),
            "FORECAST_INVALID", "Raw forecast mixes cutoff or target timestamps")
    return Forecast(usage="TEST_ONLY", schema_version="ggso.forecast.v2", identity=identity,
                    forecast_run_id=forecast_run_id, forecast_model_id=checkpoint.model_id,
                    checkpoint_version=checkpoint.checkpoint_version,
                    checkpoint_contract=checkpoint.contract_version, history_steps=checkpoint.history_steps,
                    demand_definition=checkpoint.demand_definition, supply_definition=checkpoint.supply_definition,
                    parity_status=checkpoint.parity_status, parity_evidence=checkpoint.evidence_refs,
                    features_available_at=checkpoint.features_available_at, generated_at=generated_at,
                    rows=tuple(ForecastRow(hex_id=row.hex_id, forecast_demand=row.pred_demand,
                                          forecast_supply=row.pred_idle_supply) for row in parsed))


class DuoCastMockAdapter:
    def __init__(self, infer: Callable[[Identity], Iterable[Mapping]], *, checkpoint: MockCheckpoint,
                 forecast_run_id: str, generated_at):
        self._infer = infer
        self.checkpoint = MockCheckpoint.model_validate(checkpoint)
        self.forecast_run_id = forecast_run_id
        self.generated_at = generated_at

    def __call__(self, identity: Identity) -> Forecast:
        identity = Identity.model_validate(identity)
        check_mock_parity(identity, self.checkpoint)
        rows = self._infer(identity)  # Exactly one batched invocation, outside all candidate loops.
        return adapt_rows(rows, identity=identity, checkpoint=self.checkpoint,
                          forecast_run_id=self.forecast_run_id, generated_at=self.generated_at)



class CheckpointForecastProvider:
    """One real, batched neural forward from a compatible synthetic-trained checkpoint.

    TEST_ONLY is enforced here until operational source/model eligibility is reviewed.
    Node, feature, target, history and artifact identities are never guessed from names.
    """
    def __init__(self, config: Config, checkpoint: Path, *, forecast_run_id: str):
        # A provider is bound to this exact artifact revision. Construct a new
        # provider to switch checkpoints; an on-disk replacement cannot change it.
        self.config, self.path = config.model_copy(deep=True), Path(checkpoint)
        self.forecast_run_id = forecast_run_id
        self.checkpoint, self.checkpoint_sha256 = load_checkpoint_snapshot(self.path)
        require(self.checkpoint['variant'] == 'duocast', 'FORECAST_INVALID', 'DuoCast provider requires the dual-graph architecture')

    def __call__(self, identity: Identity) -> Forecast:
        identity = Identity.model_validate(identity)
        panel = load_panel(self.config.data)
        require(panel.metadata.get('synthetic') is True, 'SEMANTIC_MISMATCH', 'Official model eligibility is not established')
        require(tuple(panel.hex_ids) == identity.required_hex_ids and
                panel.metadata['dataset_id'] == identity.dataset_id and panel.fingerprint == identity.dataset_fingerprint and
                panel.metadata['node_mapping_version'] == identity.node_mapping_version and
                panel.metadata['feature_definition_version'] == identity.feature_version,
                'SEMANTIC_MISMATCH', 'Decision snapshot differs from checkpoint input source')
        positions = np.flatnonzero(panel.timestamps == pd.Timestamp(identity.cutoff_time))
        require(len(positions) == 1, 'FORECAST_INVALID', 'Cutoff is not in the supplied complete snapshot history')
        for split in ('train', 'val'):
            require(pd.Timestamp(self.checkpoint['splits'][split]['last_target']) <= pd.Timestamp(identity.cutoff_time),
                    'FORECAST_INVALID', 'Checkpoint used labels from after the decision cutoff')
        prediction = _predict_loaded_checkpoint(self.config, panel, self.checkpoint, positions)[0]
        return Forecast(usage='TEST_ONLY', schema_version='ggso.forecast.v2', identity=identity,
            forecast_run_id=self.forecast_run_id, forecast_model_id='duocast', checkpoint_version=self.checkpoint_sha256,
            checkpoint_contract=CONTRACT_VERSION, history_steps=self.config.data.history,
            demand_definition='confirmed_valid_bookings_per_5min',
            supply_definition='online_idle_dispatch_eligible_stock_at_target',
            parity_status='TEST_ONLY_CHECKPOINT_VERIFIED', parity_evidence=(f'checkpoint-sha256:{self.checkpoint_sha256}',),
            features_available_at=identity.cutoff_time, generated_at=datetime.now(timezone.utc),
            rows=tuple(ForecastRow(hex_id=node, forecast_demand=float(value[0]), forecast_supply=float(value[1]))
                       for node, value in zip(panel.hex_ids, prediction)))
