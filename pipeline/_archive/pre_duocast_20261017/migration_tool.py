"""One-shot, hash-guarded staging/activation of the approved DuoCast refactor.

No data, existing runs/checkpoints, backend, UI or Git index are modified.
The prior source, configs and tests are archived byte-for-byte on activation.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import textwrap

PIPE = Path(__file__).resolve().parents[1]
OLD = PIPE / 'src' / 'surge_ml'
STAGE = PIPE / '.duocast-refactor'
ARCHIVE = PIPE / '_archive' / 'pre_duocast_20261017'
OUTPUTS: dict[str, str] = {}


def source(path: str) -> str:
    return (OLD / path).read_text(encoding='utf-8')


def definitions(path: str, *names: str) -> str:
    text = source(path)
    lines = text.splitlines(keepends=True)
    result = []
    tree = ast.parse(text)
    index = {node.name: node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in names:
        node = index[name]
        first = min([node.lineno, *(d.lineno for d in node.decorator_list)]) - 1
        result.append(''.join(lines[first:node.end_lineno]))
    return '\n\n'.join(result) + '\n'


def replace(text: str, old: str, new: str, count: int | None = 1) -> str:
    found = text.count(old)
    if not found or (count is not None and found != count):
        raise RuntimeError(f'Refactor anchor changed: {old[:100]!r}, count={found}, expected={count}')
    return text.replace(old, new)


def versions(text: str) -> str:
    for name in ('forecast', 'operational', 'response', 'candidates', 'decision', 'policy.test'):
        text = text.replace(f'ggso.{name}.v1', f'ggso.{name}.v2')
    text = text.replace('ggso.confirmed-bookings.eligible-idle.h5.test.v1', 'ggso.confirmed-bookings.eligible-idle.h5.test.v2')
    return text.replace('geomobinet_smg_ds_h5_v1', 'duocast_ds_h5_v1')


def put(path: str, text: str) -> None:
    if path in OUTPUTS:
        raise RuntimeError(f'Duplicate staged destination {path}')
    OUTPUTS[path] = textwrap.dedent(text).lstrip('\n').rstrip() + '\n'


def module(path: str, imports: str, body: str) -> None:
    put('src/surge_ml/' + path, imports.strip() + '\n\n' + body.strip())


def inventory() -> dict[str, str]:
    paths = [*(PIPE / 'src').rglob('*.py'), *(PIPE / 'tests').rglob('*.py'), *(PIPE / 'configs').rglob('*')]
    paths += [PIPE / 'pyproject.toml', PIPE / 'README.md']
    return {p.relative_to(PIPE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file() and '__pycache__' not in p.parts}


def build_contracts() -> None:
    put('src/surge_ml/__init__.py', '"""DuoCast forecasting and fail-closed GGSO decisions. No static geo encoder."""\n__version__ = "0.2.0"')
    put('src/surge_ml/_constant.py', '''
    """Versioned mathematical/data identities, not operational policy defaults."""
    CONTRACT_VERSION = "duocast_ds_h5_v1"
    SEMANTIC_PROFILE = "ggso.confirmed-bookings.eligible-idle.h5.test.v2"
    DEMAND_DEFINITION = "confirmed_valid_bookings_per_5min"
    SUPPLY_DEFINITION = "online_idle_dispatch_eligible_stock_at_target"
    METRIC_VERSION = "duocast_metrics_log1p_eps1_v1"
    ''')
    put('src/surge_ml/errors.py', source('ggso/errors.py'))
    raw = source('ggso/contracts.py')
    common = raw[:raw.index('\nclass Identity')]
    common += '\n' + definitions('ggso/contracts.py', 'Vector', 'Transform')
    put('src/surge_ml/contracts/common.py', common)
    forecast = definitions('ggso/contracts.py', 'Identity', 'ForecastRow', 'Forecast')
    forecast = replace(forecast, '    geo_version: Name\n', '')
    forecast = forecast.replace('Literal["TEST_ONLY_MOCK_VERIFIED"]', 'Literal["TEST_ONLY_MOCK_VERIFIED", "TEST_ONLY_CHECKPOINT_VERIFIED"]')
    module('contracts/forecast.py', '''
from __future__ import annotations
from datetime import timedelta
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, model_validator
from .common import Contract, TestOnly, Name, Nodes, NonNegative
''', versions(forecast))
    module('contracts/response.py', '''
from __future__ import annotations
import math
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, model_validator
from .common import (Contract, TestOnly, Name, Nodes, Count, Price, Number, Positive,
                     Probability, NonNegative, Transform)
''', versions(definitions('ggso/contracts.py', 'Scenario', 'Support', 'Calibration', 'ResponseCell', 'ResponseArtifact')))
    module('contracts/decision.py', '''
from __future__ import annotations
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, model_validator
from .common import (Contract, TestOnly, Name, Names, Price, Adjustment, Number,
                     Positive, Probability, NonNegative, Vector)
from .forecast import Identity
''', versions(definitions('ggso/contracts.py', 'CapacitySource', 'OperationalRow', 'Edge', 'OperationalSnapshot', 'Outcome',
                         'Candidate', 'RejectedCandidate', 'CandidateTable', 'SolverInfo', 'Metrics', 'Recommendation',
                         'ConstraintChecks', 'DecisionResult')))
    put('src/surge_ml/contracts/__init__.py', '''
    """Canonical interface types. No model training or inference side effects."""
    from .common import *
    from .forecast import Identity, Forecast, ForecastRow
    from .response import Scenario, Support, Calibration, ResponseCell, ResponseArtifact
    from .decision import (CapacitySource, OperationalRow, Edge, OperationalSnapshot, Outcome,
                           Candidate, RejectedCandidate, CandidateTable, SolverInfo, Metrics,
                           Recommendation, ConstraintChecks, DecisionResult)
    ''')
    module('_utils/io.py', '''
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
''', definitions('geomobinet/training.py', 'atomic_json') + '''

def digest_file(path: Path) -> str:
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def write_json(path: Path, value: dict) -> None:
    """Exclusive artifact creation. Never silently replace an experiment result."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write('\\n')
''')
    module('_utils/time.py', '''
from __future__ import annotations
import pandas as pd
STEP = pd.Timedelta(minutes=5)
''', definitions('geomobinet/data.py', 'timestamps'))


def build_config_and_model() -> None:
    put('src/surge_ml/train/duocast/_constant.py', '''
    """Forecast benchmark catalog identities. Spatial/Mobility include temporal GRU."""
    NEURAL_VARIANTS = {
        "gru": (False, False),
        "gru_spatial": (True, False),
        "gru_mobility": (False, True),
        "duocast": (True, True),
    }
    BASELINES = ("lgbm_local", "persistence")
    MAIN_VARIANTS = ("lgbm_local", "gru", "gru_spatial", "gru_mobility", "duocast")
    VARIANTS = (*MAIN_VARIANTS, "persistence")
    TARGETS = ("demand_5m", "idle_supply_t")
    MODEL_LABELS = {"lgbm_local": "LightGBM baseline", "gru": "GRU-only",
                    "gru_spatial": "Spatial GATv2", "gru_mobility": "Mobility GATv2",
                    "duocast": "DuoCast", "persistence": "Persistence (auxiliary)"}
    ''')
    config = definitions('geomobinet/config.py', 'StrictModel', 'DataConfig', 'ModelConfig', 'TrainConfig', 'EvalConfig', 'Config', 'load_config', 'config_hash')
    config = replace(config, '    geo: Path\n', '    mobility_snapshots: Path\n')
    start = config.index('    geo_features: list[str]')
    end = config.index('    mobility_features:', start)
    config = config[:start] + config[end:]
    config = config.replace('["flow_5m", "eta_min", "distance_km"]', '["flow_5m", "eta_min"]')
    config = config.replace('    log_geo: list[str] = Field(default_factory=list)\n', '')
    config = config.replace('    log_spatial: list[str] = Field(default_factory=list)\n', '')
    start = config.index('    signed_features:')
    end = config.index('    train_fraction:', start)
    config = config[:start] + '    signed_features: list[str] = Field(default_factory=lambda: ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "driver_net_flow_5m"])\n' + config[end:]
    config = config.replace('("dynamic_features", "geo_features", "spatial_features", "mobility_features")', '("dynamic_features", "mobility_features")')
    config = replace(config, 'if not self.geo_features or not self.mobility_features:\n            raise ValueError("geo_features and mobility_features cannot be empty")', 'if not self.mobility_features or "flow_5m" not in self.mobility_features:\n            raise ValueError("Observed mobility requires flow_5m and an explicit complete snapshot manifest")')
    config = config.replace('("dynamic", "geo", "spatial", "mobility")', '("dynamic", "mobility")')
    config = replace(config, '        names = self.dynamic_features + self.mobility_features\n', '''        static_geo = ("geo_", "cbd", "poi_", "road_", "distance_", "_distance", "east_offset", "north_offset", "latitude", "longitude", "landuse")
        names = self.dynamic_features + self.mobility_features
        if any(any(token in name.lower() for token in static_geo) for name in names):
            raise ValueError("DuoCast does not accept static geographic node/edge inputs")
''')
    config = config.replace('SMG contract', 'DuoCast contract')
    config = config.replace('    geo_hidden: int = Field(32, ge=1)\n', '')
    config = config.replace('"geomobinet-smg-v1"', '"duocast-v1"').replace('"../runs/geomobinet-smg-v1"', '"../runs/duocast/study-v1"')
    config = config.replace('["persistence", "geomobinet_smg"]', 'list(MAIN_VARIANTS)')
    config = config.replace('("market", "geo", "spatial", "mobility", "metadata")', '("market", "spatial", "mobility", "mobility_snapshots", "metadata")')
    # Freeze the complete comparison plan; resume may change only the epoch budget.
    config = config.replace('exclude={"output_dir", "seeds", "variants"}', 'exclude={"output_dir"}')
    module('train/duocast/_types.py', '''
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from surge_ml._constant import CONTRACT_VERSION
from ._constant import MAIN_VARIANTS, NEURAL_VARIANTS, VARIANTS, TARGETS
''', versions(config))
    neural = definitions('geomobinet/model.py', 'GeoMobiNet', 'count_predictions', 'loss_parts')
    neural = replace(neural, 'class GeoMobiNet(nn.Module):', 'class DuoCast(nn.Module):')
    first = neural.index('    """Return log1p')
    last = neural.index('    def __init__', first)
    neural = neural[:first] + '    """Two log1p-count heads; optional spatial/mobility branches, never static geo."""\n\n' + neural[last:]
    a = neural.index('    def __init__')
    b = neural.index('        self.gate =', a)
    neural = neural[:a] + '''    def __init__(self, n_dynamic: int, n_mobility: int, cfg: ModelConfig,
                 variant: str = "duocast") -> None:
        super().__init__()
        if variant not in NEURAL_VARIANTS:
            raise ValueError(f"Unknown neural architecture: {variant}")
        spatial, mobility = NEURAL_VARIANTS[variant]
        self.variant = variant
        hidden = cfg.hidden
        self.temporal = nn.GRU(n_dynamic, hidden, batch_first=True)
        self.spatial_gat = (GATv2Conv(hidden, hidden // cfg.heads, heads=cfg.heads,
                            add_self_loops=False, bias=False, dropout=cfg.dropout) if spatial else None)
        self.mobility_gat = (GATv2Conv(hidden, hidden // cfg.heads, heads=cfg.heads,
                             edge_dim=n_mobility, add_self_loops=False, bias=False,
                             dropout=cfg.dropout) if mobility else None)
        branches = int(spatial) + int(mobility)
''' + neural[b:]
    neural = replace(neural, '            attributes = batch["spatial_attr"] if self.road else None\n            messages.append(self.graph_message(self.spatial_gat, hidden, batch["spatial_index"], attributes))', '            messages.append(self.graph_message(self.spatial_gat, hidden, batch["spatial_index"]))')
    neural = replace(neural, '        if self.geo_encoder is not None:\n            messages.append(self.geo_encoder(batch["x_geo"]))\n', '')
    module('train/duocast/variants/neural.py', '''
from __future__ import annotations
import torch
from torch import nn
from torch.nn import functional as F
from torch_geometric.nn import GATv2Conv
from .._types import ModelConfig, TrainConfig
from .._constant import NEURAL_VARIANTS
''', neural)
    put('src/surge_ml/train/duocast/catalog.py', '''
    """Single model registry; importing this file does not start any training."""
    from ._constant import MODEL_LABELS, MAIN_VARIANTS, NEURAL_VARIANTS, VARIANTS

    def build_neural(n_dynamic, n_mobility, config, variant="duocast"):
        from .variants.neural import DuoCast
        if variant not in NEURAL_VARIANTS:
            raise ValueError(f"Not a neural variant: {variant}")
        return DuoCast(n_dynamic, n_mobility, config, variant)
    ''')


def build_datasets() -> None:
    data = definitions('geomobinet/data.py', 'read_table', 'numeric', 'check_available', 'Panel', 'file_fingerprint', 'load_panel', 'make_splits', 'split_manifest')
    data = data.replace('four-table SMG schema, not legacy hex40 data', 'DuoCast market/spatial/mobility/coverage schema')
    data = replace(data, '    geo: np.ndarray\n', '')
    data = replace(data, '    spatial_attr: np.ndarray\n', '')
    data = replace(data, '        if column not in cfg.signed_features and (vector < 0).any():', '''        if column in (*TARGETS, "flow_5m") and not np.equal(vector, np.floor(vector)).all():
            raise ValueError(f"{name}.{column}: observed counts must be integers; forecasts may be real-valued")
        if column not in cfg.signed_features and (vector < 0).any():''')
    data = replace(data, '    if not meta.get("dataset_id"):\n        raise ValueError("meta.dataset_id is required")', '''    for key in ("dataset_id", "feature_definition_version", "node_mapping_version", "spatial_graph_version"):
        if not isinstance(meta.get(key), str) or not meta[key]:
            raise ValueError(f"meta.{key} is required")
    if meta.get("demand_definition") != DEMAND_DEFINITION or meta.get("supply_definition") != SUPPLY_DEFINITION:
        raise ValueError("Unverified demand/supply semantics: confirmed bookings and eligible idle stock are required")
    if meta.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("DuoCast no-geo data contract required")''')
    data = replace(data, '    frames = {key: read_table(getattr(cfg, key)) for key in ("market", "geo", "spatial", "mobility")}\n    market, geo, spatial, mobility = (frames[k].copy() for k in ("market", "geo", "spatial", "mobility"))', '''    frames = {key: read_table(getattr(cfg, key)) for key in ("market", "spatial", "mobility", "mobility_snapshots")}
    market, spatial, mobility, coverage = (frames[k].copy() for k in ("market", "spatial", "mobility", "mobility_snapshots"))''')
    data = replace(data, '                              ("geo", geo, ["hex_id"]),\n', '')
    data = replace(data, '    if set(geo["hex_id"]) != set(nodes):\n        raise ValueError("hex_geo must contain exactly the market node set")\n', '')
    data = replace(data, '    check_available(geo, "geo", cfg, meta, times[0])\n', '')
    data = replace(data, '    node_map = {h: i for i, h in enumerate(nodes)}', '''    if not {"timestamp", "available_at", "complete"} <= set(coverage):
        raise ValueError("mobility_snapshots requires timestamp, available_at and complete")
    coverage["timestamp"] = timestamps(coverage["timestamp"], cfg.timezone)
    if coverage["timestamp"].duplicated().any() or set(coverage["timestamp"]) != set(times):
        raise ValueError("Missing/duplicate mobility coverage: missing data is not an observed empty graph")
    if not coverage["complete"].eq(True).all():
        raise ValueError("Incomplete mobility snapshot")
    check_available(coverage, "mobility_snapshots", cfg, meta)
    node_map = {h: i for i, h in enumerate(nodes)}''')
    data = replace(data, '    geo = geo.set_index("hex_id").loc[nodes]\n    geo_values = numeric(geo, cfg.geo_features, "geo", cfg)\n', '')
    data = replace(data, 'cfg.spatial_features, "spatial"', '[], "spatial"')
    a = data.index('    for delta in ("od_cbd_distance_delta"')
    b = data.index('    od_times =', a)
    data = data[:a] + data[b:]
    data = replace(data, '    fingerprint = file_fingerprint([cfg.market, cfg.geo, cfg.spatial, cfg.mobility, cfg.metadata])\n    return Panel(times, nodes, dynamic, geo_values, sp_index, sp_attr, ptr, od_index, od_attr,\n                 target, meta, fingerprint)', '''    fingerprint = file_fingerprint([cfg.market, cfg.spatial, cfg.mobility, cfg.mobility_snapshots, cfg.metadata])
    return Panel(times, nodes, dynamic, sp_index, ptr, od_index, od_attr, target, meta, fingerprint)''')
    schema = definitions('geomobinet/training.py', 'input_schema')
    schema = replace(schema, '("dynamic_features", "geo_features", "spatial_features", "mobility_features",\n              "nullable_dynamic", "log_dynamic", "log_geo", "log_spatial", "log_mobility",', '("dynamic_features", "mobility_features",\n              "nullable_dynamic", "log_dynamic", "log_mobility",')
    schema = replace(schema, '"target": ["new eligible requests in (t,t+5min]", "idle online eligible drivers at t+5min"],', '"target": [DEMAND_DEFINITION, SUPPLY_DEFINITION],')
    schema = replace(schema, '"geo_version": panel.metadata.get("geo_version"),', '"node_mapping_version": panel.metadata["node_mapping_version"],\n            "spatial_graph_version": panel.metadata["spatial_graph_version"],')
    module('datasets/duocast.py', '''
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from surge_ml._constant import CONTRACT_VERSION, DEMAND_DEFINITION, SUPPLY_DEFINITION
from surge_ml._utils.time import STEP, timestamps
from surge_ml.train.duocast._types import DataConfig
from surge_ml.train.duocast._constant import TARGETS
''', data + '\n' + schema)
    batching = definitions('geomobinet/batch.py', 'Scaler', 'fit_scalers', 'Batcher')
    batching = replace(batching, '    arrays = {"dynamic": panel.dynamic[first:last + 1], "geo": panel.geo,\n              "spatial": panel.spatial_attr, "mobility": panel.mobility_attr[low:high]}', '    arrays = {"dynamic": panel.dynamic[first:last + 1], "mobility": panel.mobility_attr[low:high]}')
    batching = replace(batching, '        for name, raw in (("dynamic", panel.dynamic), ("geo", panel.geo),\n                          ("spatial", panel.spatial_attr), ("mobility", panel.mobility_attr)):', '        for name, raw in (("dynamic", panel.dynamic), ("mobility", panel.mobility_attr)):')
    batching = replace(batching, '        self.geo, self.spatial, self.mobility = scaled["geo"], scaled["spatial"], scaled["mobility"]', '        self.mobility = scaled["mobility"]')
    batching = replace(batching, '        arrays = {"x_dyn": window, "x_geo": np.tile(self.geo, (b, 1)),\n                  "spatial_index": sp_index, "spatial_attr": np.tile(self.spatial, (b, 1)),', '        arrays = {"x_dyn": window, "spatial_index": sp_index,')
    module('datasets/batching.py', '''
from __future__ import annotations
import numpy as np
import torch
from surge_ml.train.duocast._types import DataConfig
from .duocast import Panel
''', batching)
    module('datasets/responses.py', '''
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
import numpy as np
from pydantic import AwareDatetime, model_validator
from surge_ml.contracts.common import Count, Name, NonNegative, Price, TestOnly, Transform, Vector
from surge_ml.errors import require
''', definitions('ggso/response/dataset.py', 'Observation', 'Arrays', 'fit_transform', 'to_arrays', 'chronological_split'))


def build_responses_and_optimizer() -> None:
    module('train/responses/_types.py', '''
from __future__ import annotations
from typing import Annotated
from pydantic import Field, model_validator
from surge_ml.contracts.common import TestOnly, Name, Positive, Number, Probability, Count
''', definitions('ggso/config.py', 'FitConfig'))
    module('train/responses/glm.py', '''
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.optimize import minimize
from scipy.special import digamma, expit, gammaln
from ._types import FitConfig
from surge_ml.errors import require
''', definitions('ggso/response/glm.py', 'counts', 'nb_nll', 'binomial_nll', '_matrix', 'DemandFit', 'fit_demand', 'FulfillmentFit', 'fit_fulfillment'))
    module('train/responses/bootstrap.py', '''
from __future__ import annotations
import hashlib
import math
import numpy as np
from ._types import FitConfig
from .glm import fit_demand, fit_fulfillment
from surge_ml.contracts.response import Scenario
from surge_ml.datasets.responses import Arrays
from surge_ml.errors import GGSOError, require
''', definitions('ggso/response/bootstrap.py', 'paired_scenarios'))
    fit = definitions('ggso/response/artifacts.py', 'fit_artifact', 'save_artifact', 'load_artifact')
    module('train/responses/train.py', '''
from __future__ import annotations
import hashlib
import json
from datetime import datetime
from pathlib import Path
import numpy as np
from scipy.special import expit
from surge_ml._constant import SEMANTIC_PROFILE
from surge_ml.contracts.response import Calibration, ResponseArtifact, ResponseCell, Support
from surge_ml.datasets.responses import Observation, chronological_split
from surge_ml.errors import require
from ._types import FitConfig
from .bootstrap import paired_scenarios
from .glm import binomial_nll, fit_demand, fit_fulfillment, nb_nll
''', versions(fit))
    prepared = definitions('ggso/integration/operational_context.py', 'PreparedNetwork', 'prepare_network')
    prepared = replace(prepared, '        # Both contexts must remain within the explicit training support rectangle.', '''        require(cell.support.surge_min <= row.current_surge <= cell.support.surge_max,
                "RESPONSE_INVALID", f"Reference surge is outside trained response support for {row.hex_id}")
        # Baseline may be outside policy bounds, but not outside response support.
        # Both contexts must remain within the explicit training support rectangle.''')
    module('inferences/schemas.py', '''
from __future__ import annotations
import math
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, model_validator
from surge_ml.contracts.common import (Adjustment, Count, Name, NonNegative, Number,
                                      Positive, Price, Probability, TestOnly, Contract)
from surge_ml.contracts.forecast import Forecast
from surge_ml.contracts.response import ResponseArtifact
from surge_ml.contracts.decision import OperationalSnapshot
from surge_ml.errors import require
''', versions(definitions('ggso/config.py', 'PolicyConfig') + '\n' + prepared))
    module('inferences/candidate_utility.py', '''
from __future__ import annotations
import hashlib
import json
import math
from decimal import Decimal
import numpy as np
from scipy.special import expit
from surge_ml.contracts.decision import (Candidate, CandidateTable, CapacitySource, Outcome, RejectedCandidate)
from surge_ml.errors import GGSOError, require
from .schemas import PreparedNetwork, prepare_network
GRID = tuple(Decimal(i) / Decimal(10) for i in range(-3, 4))
''', versions(definitions('ggso/simulation/capacity.py', 'capacity_value') + '\n' + definitions('ggso/simulation/candidates.py', 'canonical_decimal', 'rejection_reasons', 'outcome', 'evaluate_candidate', 'build_candidates')))
    module('inferences/network_optimizer.py', '''
from __future__ import annotations
from dataclasses import dataclass
import math
import time
import numpy as np
import scipy
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_matrix
from surge_ml.contracts.decision import CandidateTable, OperationalSnapshot, SolverInfo
from surge_ml.errors import require
from .schemas import PolicyConfig
''', definitions('ggso/optimization/milp.py', 'Problem', 'build_problem') + '\n' + definitions('ggso/optimization/highs.py', 'SolveAttempt', '_finite_optional', 'solve', 'decode_incumbent', 'accepted_info'))
    module('inferences/validator.py', '''
from __future__ import annotations
import math
from surge_ml.contracts.decision import Candidate, CandidateTable, ConstraintChecks, Metrics
from surge_ml.errors import require
from .schemas import PreparedNetwork, prepare_network
from .candidate_utility import build_candidates, outcome
''', definitions('ggso/optimization/validator.py', 'validate_selection'))
    service = definitions('ggso/integration/decision_runner.py', 'run_decision')
    service = replace(service, '        require(forecast.identity == parsed_identity and forecast.generated_at <= timestamp,', '''        if generated_at is None:
            timestamp = datetime.now(timezone.utc)
        require(forecast.identity == parsed_identity and forecast.generated_at <= timestamp,''')
    service = replace(service, '        return DecisionResult(usage="TEST_ONLY", schema_version="ggso.decision.v1", result_status="VALID",', '''        if generated_at is None:
            timestamp = datetime.now(timezone.utc)
        return DecisionResult(usage="TEST_ONLY", schema_version="ggso.decision.v1", result_status="VALID",''')
    module('inferences/service.py', '''
from __future__ import annotations
from collections.abc import Callable
from datetime import datetime, timezone
from surge_ml.contracts import DecisionResult, Forecast, Identity, OperationalSnapshot, Recommendation, ResponseArtifact
from surge_ml.errors import GGSOError, require
from .schemas import PolicyConfig, prepare_network
from .network_optimizer import accepted_info, decode_incumbent, solve, build_problem
from .validator import validate_selection
from .candidate_utility import build_candidates, canonical_decimal
''', versions(service))
    # Simulated operator receipts stay a separate integration concern, not a model.
    demo_prices = source('ggso/integration/demo_prices.py').replace('from ..contracts import', 'from surge_ml.contracts import').replace('from ..errors import', 'from surge_ml.errors import')
    put('src/surge_ml/integrations/demo_prices.py', demo_prices)


def build_training_and_reports() -> None:
    # A single inference implementation is shared by training validation and serving.
    infer = definitions('geomobinet/training.py', 'load_checkpoint', 'resolve_device', 'predict', 'predict_checkpoint')
    infer = infer.replace('GeoMobiNet demand/idle-supply contract required; legacy log-ratio is rejected', 'DuoCast no-geo demand/supply contract required; GeoMobiNet and ratio checkpoints are rejected')
    infer = replace(infer, '    model = GeoMobiNet(**checkpoint["dimensions"], cfg=ModelConfig.model_validate(checkpoint["model_config"]),', '    model = DuoCast(**checkpoint["dimensions"], cfg=ModelConfig.model_validate(checkpoint["model_config"]),')
    infer = infer.replace('or geo version', 'or graph/schema version')
    adapter = definitions('ggso/integration/duocast_adapter.py', 'MockCheckpoint', 'RawForecastRow', 'check_mock_parity', 'adapt_rows', 'DuoCastMockAdapter')
    adapter = replace(adapter, '    geo_version: Name\n', '')
    adapter = replace(adapter, '"feature_version", "geo_version",', '"feature_version",')
    frame = definitions('geomobinet/runner.py', 'prediction_frame', 'forecast')
    module('inferences/duocast.py', '''
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
''', versions(infer + '\n' + frame + '\n' + adapter) + '''

class CheckpointForecastProvider:
    """One real, batched neural forward from a compatible synthetic-trained checkpoint.

    TEST_ONLY is enforced here until operational source/model eligibility is reviewed.
    Node, feature, target, history and artifact identities are never guessed from names.
    """
    def __init__(self, config: Config, checkpoint: Path, *, forecast_run_id: str):
        self.config, self.path = config, Path(checkpoint)
        self.forecast_run_id = forecast_run_id
        self.checkpoint = load_checkpoint(self.path)
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
        prediction = predict_checkpoint(self.config, panel, self.path, positions)[0]
        return Forecast(usage='TEST_ONLY', schema_version='ggso.forecast.v2', identity=identity,
            forecast_run_id=self.forecast_run_id, forecast_model_id='duocast', checkpoint_version=digest_file(self.path),
            checkpoint_contract=CONTRACT_VERSION, history_steps=self.config.data.history,
            demand_definition='confirmed_valid_bookings_per_5min',
            supply_definition='online_idle_dispatch_eligible_stock_at_target',
            parity_status='TEST_ONLY_CHECKPOINT_VERIFIED', parity_evidence=(f'checkpoint-sha256:{digest_file(self.path)}',),
            features_available_at=identity.cutoff_time, generated_at=datetime.now(timezone.utc),
            rows=tuple(ForecastRow(hex_id=node, forecast_demand=float(value[0]), forecast_supply=float(value[1]))
                       for node, value in zip(panel.hex_ids, prediction)))
''')
    metrics = definitions('geomobinet/metrics.py', 'point_metrics', 'evaluate')
    metrics = replace(metrics, '    out["loss_log_huber"] = float(losses.mean())', '''    out["loss_log_huber"] = float(losses.mean())
    signed_log_error = np.log1p(pred) - np.log1p(truth)
    log_ratio_error = signed_log_error[:, 0] - signed_log_error[:, 1]
    out['log_d_mae'] = float(np.abs(signed_log_error[:, 0]).mean())
    out['log_s_mae'] = float(np.abs(signed_log_error[:, 1]).mean())
    out['log_ds_mae'] = float(np.abs(log_ratio_error).mean())
    out['log_ds_rmse'] = float(np.sqrt(np.mean(log_ratio_error ** 2)))''')
    module('reports/metrics.py', '''
from __future__ import annotations
import numpy as np
from surge_ml.train.duocast._types import EvalConfig, TrainConfig
FORECAST_METRICS = ('demand_mae', 'supply_mae', 'log_d_mae', 'log_s_mae', 'log_ds_mae', 'log_ds_rmse')
''', metrics)
    lgb = definitions('geomobinet/baselines.py', 'fit_lightgbm', 'predict_lightgbm')
    lgb = lgb.replace('network = variant == "lgbm_network"', 'network = False')
    lgb = lgb.replace('variant == "lgbm_network"', 'False')
    lgb = lgb.replace('geomobinet optional dependencies', 'baselines extra: uv sync --project pipeline --extra baselines')
    module('train/duocast/variants/lightgbm.py', '''
from __future__ import annotations
from pathlib import Path
import numpy as np
from surge_ml.train.duocast._types import Config
from surge_ml.train.duocast._constant import TARGETS
from surge_ml.datasets.duocast import Panel

def tabular_features(panel, cutoffs, cfg, network=False):
    if network:
        raise ValueError('Only the local LightGBM baseline belongs to this benchmark')
    ks = np.asarray(cutoffs, dtype=np.int64)
    history, n = cfg.data.history, panel.n_nodes
    indices = ks[:, None] + np.arange(-history + 1, 1)
    matrix = panel.dynamic[indices].transpose(0, 2, 1, 3).reshape(len(ks) * n, -1)
    names = [f'lag{lag}_{name}' for lag in range(history - 1, -1, -1) for name in cfg.data.dynamic_features]
    return matrix, names
''', lgb)
    # Pure helpers used by both train and report, not a second workflow implementation.
    OUTPUTS['src/surge_ml/_utils/io.py'] += '\nfrom contextlib import contextmanager\n\n' + definitions('geomobinet/runner.py', 'trial_lock')
    OUTPUTS['src/surge_ml/_utils/io.py'] = OUTPUTS['src/surge_ml/_utils/io.py'].replace('GeoMobiNet trial', 'DuoCast trial')
    train = definitions('geomobinet/training.py', 'atomic_checkpoint', 'make_model', 'train_neural')
    a = train.index('    dimensions =')
    b = train.index('\n\n', a)
    train = train[:a] + '''    dimensions = {"n_dynamic": batcher.n_dynamic, "n_mobility": panel.mobility_attr.shape[1]}
    return DuoCast(**dimensions, cfg=cfg.model, variant=variant), dimensions''' + train[b:]
    workflow = definitions('geomobinet/runner.py', 'prepare', 'trial_folder', 'validate_result', 'run_trial', 'benchmark')
    workflow = workflow.replace('Static geo/road data validated as-of first snapshot; dynamic and OD fitted on train inputs only', 'Adjacency validated as-of first snapshot; dynamic and OD scalers fitted on train inputs only; no geo')
    workflow = workflow.replace('elif variant in ("persistence", "seasonal_naive"):', 'elif variant == "persistence":')
    workflow = replace(workflow, '            pred, info = naive_predictions(panel, splits["val"], variant, cfg.evaluation.seasonal_period)', '            pred, info = panel.target[splits["val"]].astype(np.float64), {"baseline": "current_observed_counts"}')
    module('train/duocast/train.py', '''
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from uuid import uuid4
import numpy as np
import pandas as pd
import torch
from surge_ml._constant import CONTRACT_VERSION
from surge_ml._utils.io import atomic_json, digest_file, trial_lock
from surge_ml.datasets.duocast import load_panel, make_splits, split_manifest, input_schema
from surge_ml.datasets.batching import Batcher, fit_scalers
from surge_ml.reports.metrics import point_metrics, evaluate
from surge_ml.inferences.duocast import load_checkpoint, resolve_device, predict
from ._types import Config, config_hash
from ._constant import BASELINES, NEURAL_VARIANTS, VARIANTS
from .variants.neural import DuoCast, loss_parts
from .variants.lightgbm import fit_lightgbm
''', train + '\n' + workflow)
    reports = definitions('geomobinet/runner.py', 'collect_results', 'validation_table', 'report', 'select', 'finalize')
    reports = replace(reports, '("loss_log_huber", "demand_mae", "supply_mae", "ds_proxy_mae")', '("loss_log_huber", *FORECAST_METRICS, "ds_proxy_mae")')
    reports = replace(reports, '    if "persistence" not in cfg.variants:\n        raise ValueError("Frozen comparison must include persistence")', '    if not {"lgbm_local", "persistence"}.intersection(cfg.variants):\n        raise ValueError("Frozen comparison must include a baseline")')
    reports = replace(reports, '                pred, _ = naive_predictions(panel, ks, variant, cfg.evaluation.seasonal_period)', '                pred = panel.target[ks].astype(np.float64)')
    module('reports/benchmark.py', '''
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from surge_ml._constant import CONTRACT_VERSION
from surge_ml._utils.io import atomic_json, digest_file, trial_lock
from surge_ml.train.duocast._types import config_hash
from surge_ml.train.duocast._constant import NEURAL_VARIANTS, MODEL_LABELS
from surge_ml.train.duocast.train import prepare, trial_folder, validate_result
from surge_ml.train.duocast.variants.lightgbm import predict_lightgbm
from surge_ml.inferences.duocast import predict_checkpoint, prediction_frame
from .metrics import FORECAST_METRICS, evaluate
''', reports)


def build_fixtures() -> None:
    body = definitions('ggso/fixtures.py', 'Fixture', 'make_fixture', 'fit_config', 'synthetic_observations', 'make_fitted_fixture')
    body = body.replace('feature_version=self.identity.feature_version, geo_version=self.identity.geo_version,', 'feature_version=self.identity.feature_version,')
    body = body.replace(', geo_version="test-geo-v1"', '')
    body = body.replace('geomobinet_smg.mock', 'duocast.mock')
    body = body.replace('from .integration.decision_runner import run_decision', 'from surge_ml.inferences.service import run_decision')
    body = body.replace('from .response.artifacts import fit_artifact', 'from surge_ml.train.responses.train import fit_artifact')
    module('datasets/fixtures.py', '''
"""Explicit synthetic fixtures. These are not a historical-data fallback."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import json
import numpy as np
import pandas as pd
import yaml
from scipy.special import expit
from surge_ml._constant import SEMANTIC_PROFILE, CONTRACT_VERSION, DEMAND_DEFINITION, SUPPLY_DEFINITION
from surge_ml.contracts import *
from surge_ml.train.responses._types import FitConfig
from surge_ml.inferences.schemas import PolicyConfig, prepare_network
from surge_ml.inferences.duocast import DuoCastMockAdapter, MockCheckpoint
from surge_ml.datasets.responses import Observation
FIXTURE_VERSION = 'ggso.synthetic-fixture.v2'
''', versions(body) + '''


def write_demo(folder: Path, *, steps: int = 160, nodes: int = 7, seed: int = 42) -> Path:
    """Small, deterministic no-geo fixture for every stage. Never overwrites data."""
    from surge_ml.train.duocast._constant import MAIN_VARIANTS
    if steps < 100 or nodes < 2:
        raise ValueError('Demo needs at least 100 snapshots and 2 nodes')
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(seed)
    hexes = [f'test-hex-{i:02d}' for i in range(nodes)]
    times = pd.date_range('2026-01-05', periods=steps, freq='5min', tz='Asia/Ho_Chi_Minh')
    spatial = [{'source_hex': hexes[a], 'target_hex': hexes[b], 'available_at': times[0]}
               for i in range(nodes - 1) for a, b in ((i, i + 1), (i + 1, i))]
    market, mobility = [], []
    demand, supply = np.full(nodes, 12.0), np.full(nodes, 10.0)
    for k, ts in enumerate(times):
        demand = np.maximum(0, np.rint(.8*demand + .2*(12+4*np.sin(k/12)) + rng.normal(0,1,nodes)))
        supply = np.maximum(0, np.rint(.85*supply + .15*(11+2*np.cos(k/16)) + rng.normal(0,1,nodes)))
        for i, node in enumerate(hexes):
            market.append(dict(timestamp=ts, hex_id=node, demand_5m=int(demand[i]), idle_supply_t=int(supply[i]),
                backlog_t=max(0, demand[i]-supply[i]), eta_sec_t=120+10*max(0,demand[i]-supply[i]),
                base_surge=1.2, available_at=ts, event_time=ts))
        if k % 11:
            for i in range(nodes-1):
                a,b = (i,i+1) if k%2 else (i+1,i)
                mobility.append(dict(timestamp=ts, origin_hex=hexes[a], dest_hex=hexes[b],
                    flow_5m=int(rng.integers(1,4)), eta_min=2.0, available_at=ts))
    pd.DataFrame(market).to_csv(folder/'market.csv', index=False)
    pd.DataFrame(spatial).to_csv(folder/'spatial_edges.csv', index=False)
    pd.DataFrame(mobility).to_csv(folder/'od.csv', index=False)
    pd.DataFrame({'timestamp':times, 'available_at':times, 'complete':True}).to_csv(folder/'mobility_snapshots.csv', index=False)
    meta = dict(dataset_id=f'duocast_fixture_{steps}_{nodes}_{seed}', contract_version=CONTRACT_VERSION,
        synthetic=True, node_order=hexes, feature_definition_version='duocast_minimal_v1',
        node_mapping_version='test-node-order-v1', spatial_graph_version='synthetic-ring-v1',
        demand_definition=DEMAND_DEFINITION, supply_definition=SUPPLY_DEFINITION,
        mobility_semantics='physical_driver_transitions', static_as_of=str(times[0]),
        warning='Synthetic software verification only; not evidence of forecast accuracy or business uplift')
    (folder/'meta.json').write_text(json.dumps(meta,indent=2), encoding='utf-8')
    config = dict(contract_version=CONTRACT_VERSION, study_id='duocast-synthetic', seeds=[seed],
        variants=list(MAIN_VARIANTS), output_dir='runs',
        data=dict(market='market.csv', spatial='spatial_edges.csv', mobility='od.csv',
            mobility_snapshots='mobility_snapshots.csv', metadata='meta.json', validate_h3=False),
        model=dict(hidden=16,heads=2,head_hidden=8),
        train=dict(epochs=2,batch_size=8,eval_batch_size=16,num_threads=2,lgbm_rounds=10))
    path = folder/'config.yaml'
    path.write_text(yaml.safe_dump(config,sort_keys=False),encoding='utf-8')
    return path
''')
    # Frozen replay belongs to the service; no actual network inference is invoked.
    replay = definitions('ggso/__main__.py', 'replay_payload')
    OUTPUTS['src/surge_ml/inferences/service.py'] += '\n\n' + replay
    put('configs/duocast.yaml', '''
    # No supplied marketplace data yet. Use `surge-ml demo` for an isolated synthetic run.
    contract_version: duocast_ds_h5_v1
    study_id: duocast-v1
    seeds: [42, 43, 44]
    variants: [lgbm_local, gru, gru_spatial, gru_mobility, duocast]
    output_dir: ../runs/duocast/study-v1
    data:
      market: ../../data/duocast/market.parquet
      spatial: ../../data/duocast/spatial_edges.parquet
      mobility: ../../data/duocast/od.parquet
      mobility_snapshots: ../../data/duocast/mobility_snapshots.parquet
      metadata: ../../data/duocast/meta.json
      history: 12
      horizon: 1
      validate_h3: true
      availability: strict
      split_mode: strict
      dynamic_features: [demand_5m, idle_supply_t, backlog_t, eta_sec_t, base_surge]
      mobility_features: [flow_5m, eta_min]
      train_fraction: 0.70
      val_fraction: 0.15
    model:
      hidden: 64
      heads: 2
      head_hidden: 32
      dropout: 0.1
    train:
      device: auto
      epochs: 50
      batch_size: 16
      eval_batch_size: 64
      lr: 0.001
      weight_decay: 0.0001
      grad_clip: 1.0
      patience: 8
      huber_delta: 1.0
      num_threads: 2
      lgbm_rounds: 500
    ''')
    put('configs/responses.yaml', '''
    # TEST_ONLY numerical profile. Replace paths/cohort metadata after data review.
    input: ../../data/responses/observations.json
    output: ../runs/responses/response-v1/artifact.json
    dataset_id: REQUIRED_DATASET_ID
    node_mapping_version: REQUIRED_NODE_MAPPING
    required_hex_ids: []
    artifact_version: response-v1
    split_time: null
    fit_as_of: null
    fit:
      usage: TEST_ONLY
      version: test-fit-config-v1
      epsilon: 0.000001
      max_iterations: 1000
      log_dispersion_min: -5.0
      log_dispersion_max: 10.0
      min_train_rows: 30
      min_validation_rows: 10
      min_positive_trial_rows: 20
      min_unique_surge: 3
      max_demand_mean_nll: 20.0
      max_fulfillment_mean_nll: 20.0
      max_fulfillment_calibration_error: 0.15
      bootstrap_replicates: 50
      bootstrap_block_size: 12
      seed: 42
    ''')
    put('configs/optimization.yaml', '''
    # Synthetic verification profile ONLY, not approved operating/pricing thresholds.
    usage: TEST_ONLY
    schema_version: ggso.policy.test.v2
    version: test-policy-v2
    currency: TEST_UNITS
    surge_min: '1.0'
    surge_max: '2.0'
    delta_max: '0.3'
    br_min: 0.1
    br_max: 0.9
    lambda_temporal: 5.0
    lambda_spatial: 2.0
    epsilon: 0.000001
    quantile: 0.05
    quantile_method: linear_equal_weight
    solver_time_limit_seconds: 10.0
    solver_mip_rel_gap: 0.0
    integrality_tolerance: 0.0000001
    feasibility_tolerance: 0.0000001
    money_tolerance: 0.000001
    monetary_scale: 100.0
    ''')


def build_cli() -> None:
    put('src/surge_ml/cli.py', '''
    """One entrypoint for forecast training, response fitting and GGSO decisions."""
    from __future__ import annotations
    import argparse
    import json
    import sys
    from pathlib import Path

    DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / 'configs' / 'duocast.yaml'

    def parser():
        from surge_ml.train.duocast._constant import VARIANTS
        root = argparse.ArgumentParser(prog='surge-ml', description='DuoCast no-geo + per-cell response GLMs + GGSO MILP')
        commands = root.add_subparsers(dest='command', required=True)
        demo = commands.add_parser('demo', help='Create explicit synthetic no-geo training input')
        demo.add_argument('--output-dir', type=Path, required=True)
        demo.add_argument('--steps', type=int, default=160)
        demo.add_argument('--nodes', type=int, default=7)
        demo.add_argument('--seed', type=int, default=42)
        for name in ('prepare','train','benchmark','report','select','finalize','predict'):
            cmd = commands.add_parser(name)
            cmd.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
            cmd.add_argument('--smoke', action='store_true')
            if name in ('train','benchmark'):
                cmd.add_argument('--epochs', type=int)
            if name == 'train':
                cmd.add_argument('--variant', choices=VARIANTS, default='duocast')
                cmd.add_argument('--seed', type=int)
                cmd.add_argument('--resume', action='store_true')
            if name == 'predict':
                cmd.add_argument('--checkpoint', type=Path, required=True)
                cmd.add_argument('--cutoff', type=int)
                cmd.add_argument('--output', type=Path, required=True)
        fit = commands.add_parser('fit-responses', help='Fit independent GLMs from explicitly matured observation JSON')
        fit.add_argument('--config', type=Path, required=True)
        dd = commands.add_parser('decision-demo', help='TEST_ONLY fitted/declared response and mock forecast workflow')
        dd.add_argument('--output-dir', type=Path, required=True)
        dd.add_argument('--cells', type=int, default=2)
        dd.add_argument('--fit-response', action='store_true')
        decide = commands.add_parser('decide', help='Run a real synthetic-trained DuoCast checkpoint and supplied GGSO inputs')
        decide.add_argument('--config', type=Path, required=True)
        decide.add_argument('--checkpoint', type=Path, required=True)
        decide.add_argument('--input', type=Path, required=True)
        decide.add_argument('--output-dir', type=Path, required=True)
        replay = commands.add_parser('replay', help='Replay frozen decision input without refitting models')
        replay.add_argument('--input', type=Path, required=True)
        replay.add_argument('--output', type=Path, required=True)
        schemas = commands.add_parser('schemas')
        schemas.add_argument('--output-dir', type=Path, required=True)
        return root

    def effective_config(args):
        from surge_ml.train.duocast._types import load_config, Config
        cfg = load_config(args.config)
        values = cfg.model_dump()
        if args.smoke:
            values['study_id'] += '-smoke'
            values['output_dir'] = cfg.output_dir.with_name(cfg.output_dir.name+'-smoke')
            values['train'].update(epochs=2, limit_batches=2, lgbm_rounds=5)
        if getattr(args,'epochs',None) is not None:
            values['train']['epochs'] = args.epochs
        return Config.model_validate(values)

    def save_decision(folder, result, payload, candidates=None):
        from surge_ml._utils.io import write_json, digest_file
        import platform
        import scipy
        folder.mkdir(parents=True, exist_ok=False)
        write_json(folder/'decision.json',result.model_dump(mode='json'))
        write_json(folder/'input.json',payload)
        if candidates is not None:
            write_json(folder/'candidates.json',candidates.model_dump(mode='json'))
        write_json(folder/'evidence.json',dict(scope='TEST_ONLY',production_eligible=False,
            python=platform.python_version(),scipy=scipy.__version__,result_status=result.result_status,
            artifact_sha256={p.name:digest_file(p) for p in sorted(folder.glob('*.json'))},
            solver=None if result.solver is None else result.solver.model_dump(mode='json')))

    def main(argv=None):
        actual = list(sys.argv[1:] if argv is None else argv)
        if actual[:1] in (['legacy'], ['legacy-ggso']):
            from surge_ml.legacy import run_legacy
            return run_legacy(actual)
        args = parser().parse_args(actual)
        try:
            from surge_ml._utils.io import write_json
            if args.command == 'demo':
                from surge_ml.datasets.fixtures import write_demo
                print(write_demo(args.output_dir,steps=args.steps,nodes=args.nodes,seed=args.seed))
                return 0
            if args.command == 'schemas':
                from surge_ml.contracts import Forecast, OperationalSnapshot, ResponseArtifact, CandidateTable, DecisionResult
                from surge_ml.inferences.schemas import PolicyConfig
                from surge_ml.train.responses._types import FitConfig
                args.output_dir.mkdir(parents=True,exist_ok=False)
                for model in (Forecast,OperationalSnapshot,ResponseArtifact,CandidateTable,DecisionResult,PolicyConfig,FitConfig):
                    write_json(args.output_dir/f'{model.__name__}.schema.json',model.model_json_schema())
                return 0
            if args.command == 'fit-responses':
                from surge_ml.train.responses.train import fit_from_config
                result = fit_from_config(args.config)
                print(json.dumps(result))
                return 0
            if args.command == 'decision-demo':
                from surge_ml.datasets.fixtures import make_fixture, make_fitted_fixture
                from surge_ml.inferences.candidate_utility import build_candidates
                fixture = (make_fitted_fixture if args.fit_response else make_fixture)(hex_count=args.cells)
                result = fixture.run()
                save_decision(args.output_dir,result,fixture.payload(),
                              build_candidates(fixture.network()) if result.result_status=='VALID' else None)
            elif args.command == 'replay':
                from surge_ml.inferences.service import replay_payload
                result = replay_payload(json.loads(args.input.read_text(encoding='utf-8')))
                write_json(args.output,result.model_dump(mode='json'))
            elif args.command == 'decide':
                from surge_ml.train.duocast._types import load_config
                from surge_ml.inferences.duocast import CheckpointForecastProvider
                from surge_ml.inferences.service import run_decision
                payload = json.loads(args.input.read_text(encoding='utf-8'))
                if set(payload) != {'identity','policy','operational','response'}:
                    raise ValueError('Decision input must contain identity, policy, operational, response')
                provider = CheckpointForecastProvider(load_config(args.config), args.checkpoint,
                                                     forecast_run_id=payload['identity']['decision_id']+':forecast')
                captured = {}
                def once(identity):
                    forecast = provider(identity)
                    captured['forecast'] = forecast.model_dump(mode='json')
                    return forecast
                result = run_decision(**payload,forecast_provider=once)
                save_decision(args.output_dir,result,{**payload,**captured})
            else:
                cfg = effective_config(args)
                from surge_ml.train.duocast import train as training
                from surge_ml.reports import benchmark as reporting
                if args.command=='prepare':
                    panel,splits,_,_ = training.prepare(cfg)
                    print(json.dumps(dict(nodes=panel.n_nodes,snapshots=len(panel.timestamps),samples={k:len(v) for k,v in splits.items()})))
                elif args.command=='train':
                    training.run_trial(cfg,args.variant,args.seed if args.seed is not None else cfg.seeds[0],resume=args.resume)
                elif args.command=='benchmark':
                    training.benchmark(cfg)
                    reporting.report(cfg)
                elif args.command=='report': reporting.report(cfg)
                elif args.command=='select': print(json.dumps(reporting.select(cfg)))
                elif args.command=='finalize': reporting.finalize(cfg)
                elif args.command=='predict':
                    from surge_ml.inferences.duocast import forecast
                    forecast(cfg,args.checkpoint,cutoff=args.cutoff,output=args.output)
                return 0
            print(json.dumps(dict(status=result.result_status,recommendations=len(result.recommendations),
                                  error_code=result.error_code,publication=result.publication)))
            return 0 if result.result_status=='VALID' else 2
        except (ValueError,OSError,RuntimeError,ImportError,KeyError,TypeError) as exc:
            print(f'DuoCast pipeline: {type(exc).__name__}: {exc}',file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            return 130

    if __name__ == '__main__':
        raise SystemExit(main())
    ''')
    put('src/surge_ml/legacy.py', '''
    """Explicit isolated compatibility route; never imports old models into new inference."""
    from __future__ import annotations
    import os
    from pathlib import Path
    import subprocess
    import sys

    def run_legacy(arguments):
        pipeline = Path(__file__).resolve().parents[2]
        archive = pipeline/'_archive'/'pre_duocast_20261017'
        if not (archive/'src'/'surge_ml'/'cli.py').is_file():
            raise ValueError('Archived compatibility source is unavailable')
        env = {**os.environ, 'PYTHONPATH': str(archive/'src')}
        if arguments[0]=='legacy-ggso':
            command = [sys.executable,'-m','surge_ml.ggso',*arguments[1:]]
        else:
            command = [sys.executable,'-m','surge_ml.cli',*arguments]
        return subprocess.run(command,env=env,check=False).returncode
    ''')
    OUTPUTS['src/surge_ml/train/responses/train.py'] += '''


def fit_from_config(path: Path) -> dict:
    """Offline fit of explicit TEST_ONLY cohorts; output is never production eligible."""
    import yaml
    from surge_ml._utils.io import write_json
    path = Path(path).resolve()
    job = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not job.get('required_hex_ids') or not job.get('split_time') or not job.get('fit_as_of'):
        raise ValueError('Supply node IDs, split_time and fit_as_of from the reviewed dataset; no defaults are fabricated')
    config = FitConfig.model_validate(job['fit'])
    input_path = (path.parent/job['input']).resolve()
    output_path = (path.parent/job['output']).resolve()
    if output_path.exists():
        raise FileExistsError(f'Refusing to overwrite {output_path}')
    raw = json.loads(input_path.read_text(encoding='utf-8'))
    if not isinstance(raw,list):
        raise ValueError('Response input must be an array of versioned Observation objects')
    artifact = fit_artifact(raw, required_hex_ids=tuple(job['required_hex_ids']),
        split_time=datetime.fromisoformat(str(job['split_time']).replace('Z','+00:00')),
        fit_as_of=datetime.fromisoformat(str(job['fit_as_of']).replace('Z','+00:00')),
        dataset_id=job['dataset_id'],node_mapping_version=job['node_mapping_version'],
        artifact_version=job['artifact_version'],config=config)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    save_artifact(artifact,output_path)
    return dict(path=str(output_path),cells=len(artifact.cells),production_eligible=False,
                eligible_cells=sum(c.calibration.status=='SYNTHETIC_PASS' for c in artifact.cells))
'''


def build_tests() -> None:
    mapping = {
        'surge_ml.ggso.integration.operational_context': 'surge_ml.inferences.schemas',
        'surge_ml.ggso.integration.decision_runner': 'surge_ml.inferences.service',
        'surge_ml.ggso.integration.duocast_adapter': 'surge_ml.inferences.duocast',
        'surge_ml.ggso.integration.demo_prices': 'surge_ml.integrations.demo_prices',
        'surge_ml.ggso.optimization.highs': 'surge_ml.inferences.network_optimizer',
        'surge_ml.ggso.optimization.milp': 'surge_ml.inferences.network_optimizer',
        'surge_ml.ggso.optimization.validator': 'surge_ml.inferences.validator',
        'surge_ml.ggso.simulation.capacity': 'surge_ml.inferences.candidate_utility',
        'surge_ml.ggso.simulation.candidates': 'surge_ml.inferences.candidate_utility',
        'surge_ml.ggso.response.dataset': 'surge_ml.datasets.responses',
        'surge_ml.ggso.response.artifacts': 'surge_ml.train.responses.train',
        'surge_ml.ggso.response.glm': 'surge_ml.train.responses.glm',
        'surge_ml.ggso.response': 'surge_ml.train.responses',
        'surge_ml.ggso.contracts': 'surge_ml.contracts',
        'surge_ml.ggso.config': 'surge_ml.inferences.schemas',
        'surge_ml.ggso.errors': 'surge_ml.errors',
        'surge_ml.ggso.fixtures': 'surge_ml.datasets.fixtures',
        'surge_ml.ggso.__main__': 'surge_ml.cli',
    }
    for name in ('test_core.py','test_response.py','test_workflow.py','test_demo_prices.py'):
        text = (PIPE/'tests'/'ggso'/name).read_text(encoding='utf-8')
        for old,new in mapping.items():
            text = text.replace(old,new)
        text = versions(text)
        if name=='test_workflow.py':
            text = text.replace('main(["demo",', 'main(["decision-demo",')
        dest = 'responses' if name=='test_response.py' else 'inferences'
        put(f'tests/{dest}/{name}',text)
    imports = {
        'surge_ml.geomobinet.batch':'surge_ml.datasets.batching',
        'surge_ml.geomobinet.config':'surge_ml.train.duocast._types',
        'surge_ml.geomobinet.data':'surge_ml.datasets.duocast',
        'surge_ml.geomobinet.demo':'surge_ml.datasets.fixtures',
        'surge_ml.geomobinet.metrics':'surge_ml.reports.metrics',
        'surge_ml.geomobinet.model':'surge_ml.train.duocast.variants.neural',
        'surge_ml.geomobinet.training':'surge_ml.inferences.duocast',
    }
    text = (PIPE/'tests'/'test_geomobinet.py').read_text(encoding='utf-8')
    for old,new in imports.items(): text = text.replace(old,new)
    text = text.replace('GeoMobiNet','DuoCast')
    text = replace(text, 'model = DuoCast(batcher.n_dynamic, panel.geo.shape[1], panel.spatial_attr.shape[1],\n                       panel.mobility_attr.shape[1], cfg.model, variant)', 'model = DuoCast(batcher.n_dynamic, panel.mobility_attr.shape[1], cfg.model, variant)')
    text = replace(text, '    if model.geo_encoder is not None:\n        assert model.geo_encoder[0].weight.grad is not None', '    assert not hasattr(model, "geo_encoder")\n    for branch in (model.spatial_gat, model.mobility_gat):\n        if branch is not None:\n            assert any(p.grad is not None for p in branch.parameters())')
    text = text.replace('DuoCast(batcher.n_dynamic, 4, 2, 3, cfg.model)', 'DuoCast(batcher.n_dynamic, 2, cfg.model)')
    text = text.replace('docs/model/model.md (not the legacy ratio model)', 'the DuoCast forecasting contract')
    put('tests/duocast/test_models.py',text)
    text = (PIPE/'tests'/'test_geomobinet_workflow.py').read_text(encoding='utf-8')
    for old,new in imports.items(): text = text.replace(old,new)
    start=text.index('from surge_ml.geomobinet.runner import')
    end=text.index('from surge_ml.inferences.duocast import',start)
    text=text[:start]+'''from surge_ml.train.duocast.train import benchmark, prepare, run_trial, trial_folder
from surge_ml.reports.benchmark import collect_results, finalize, report, select
from surge_ml.inferences.duocast import forecast
'''+text[end:]
    text=text.replace('    cfg.model.geo_hidden = 4\n','    cfg.variants = ["persistence", "duocast"]\n')
    text=text.replace('geomobinet_smg','duocast')
    text=text.replace('["lgbm_local", "lgbm_network"]','["lgbm_local"]')
    text=text.replace('== 1\n    assert "CONFIG"','== 2\n    assert "CONFIG"')
    put('tests/duocast/test_training.py',text)
    put('tests/duocast/test_refactor.py', '''
    """New architecture/data boundaries and checkpoint-to-MILP integration regressions."""
    from __future__ import annotations
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    import ast
    import json
    import numpy as np
    import pandas as pd
    import pytest
    import torch
    import yaml
    from surge_ml.datasets.fixtures import write_demo, make_fixture, make_fitted_fixture, synthetic_observations, fit_config
    from surge_ml.datasets.duocast import load_panel, input_schema
    from surge_ml.train.duocast._types import load_config, DataConfig
    from surge_ml.train.duocast._constant import MAIN_VARIANTS
    from surge_ml.train.duocast.train import run_trial, prepare, benchmark
    from surge_ml.inferences.duocast import CheckpointForecastProvider, load_checkpoint
    from surge_ml.inferences.service import run_decision
    from surge_ml.reports.metrics import point_metrics, FORECAST_METRICS
    from surge_ml.reports.benchmark import select, finalize, report
    from surge_ml.train.responses.train import fit_from_config

    def change(model, **updates):
        return type(model).model_validate({**model.model_dump(),**updates})

    @pytest.fixture
    def cfg(tmp_path):
        config = load_config(write_demo(tmp_path/'forecast',steps=120,nodes=3))
        config.model.hidden=8
        config.model.head_hidden=4
        config.train.epochs=1
        config.train.lgbm_rounds=3
        config.train.device='cpu'
        return config

    @pytest.mark.parametrize('field,value', [('geo','x.csv'),('geo_features',['distance_to_cbd_km']),
        ('mobility_features',['flow_5m','distance_km']),('dynamic_features',['demand_5m','idle_supply_t','road_density'])])
    def test_static_geo_is_rejected(cfg,field,value):
        with pytest.raises(ValueError):
            change(cfg.data,**{field:value})

    @pytest.mark.parametrize('column',['demand_5m','idle_supply_t'])
    def test_fractional_observation_not_a_count(cfg,column):
        frame=pd.read_csv(cfg.data.market)
        frame[column]=frame[column].astype(float)
        frame.loc[0,column]=1.5
        frame.to_csv(cfg.data.market,index=False)
        with pytest.raises(ValueError,match='integers'):
            load_panel(cfg.data)

    @pytest.mark.parametrize('fault',['missing','incomplete','future'])
    def test_missing_mobility_is_not_observed_empty(cfg,fault):
        frame=pd.read_csv(cfg.data.mobility_snapshots)
        if fault=='missing': frame=frame.iloc[1:]
        elif fault=='incomplete': frame.loc[0,'complete']=False
        else: frame.loc[0,'available_at']='2030-01-01T00:00:00+07:00'
        frame.to_csv(cfg.data.mobility_snapshots,index=False)
        with pytest.raises(ValueError): load_panel(cfg.data)

    def test_count_and_schema_no_geo(cfg):
        panel=load_panel(cfg.data)
        assert not hasattr(panel,'geo')
        assert not any('geo' in name for name in input_schema(cfg,panel))
        assert set(MAIN_VARIANTS)=={'lgbm_local','gru','gru_spatial','gru_mobility','duocast'}
        meta=json.loads(cfg.data.metadata.read_text())
        meta['demand_definition']='quotes'
        cfg.data.metadata.write_text(json.dumps(meta))
        with pytest.raises(ValueError,match='semantics'): load_panel(cfg.data)

    def test_six_metrics_use_log1p_counts_and_log_ratio(cfg):
        truth=np.array([[3.,1.],[0.,2.]])
        pred=np.array([[7.,1.],[0.,0.]])
        result=point_metrics(pred,truth,cfg.evaluation,cfg.train)
        delta=np.log1p(pred)-np.log1p(truth)
        ratio_delta=delta[:,0]-delta[:,1]
        assert result['demand_mae']==pytest.approx(2.)
        assert result['supply_mae']==pytest.approx(1.)
        assert result['log_d_mae']==pytest.approx(np.abs(delta[:,0]).mean())
        assert result['log_s_mae']==pytest.approx(np.abs(delta[:,1]).mean())
        assert result['log_ds_mae']==pytest.approx(np.abs(ratio_delta).mean())
        assert result['log_ds_rmse']==pytest.approx(np.sqrt(np.mean(ratio_delta**2)))
        assert set(FORECAST_METRICS)<=set(result)

    def test_no_old_checkpoint_can_be_relabeled(tmp_path):
        path=tmp_path/'old.pt'
        torch.save({'contract_version':'geomobinet_smg_ds_h5_v1'},path)
        with pytest.raises(ValueError,match='checkpoints are rejected'): load_checkpoint(path)

    def test_actual_duocast_checkpoint_to_response_to_milp(cfg):
        run_trial(cfg,'duocast',42)
        panel=load_panel(cfg.data)
        fixture=make_fitted_fixture(hex_count=panel.n_nodes)
        cutoff=panel.timestamps[-1].to_pydatetime()
        identity=change(fixture.identity,dataset_id=panel.metadata['dataset_id'],dataset_fingerprint=panel.fingerprint,
            cutoff_time=cutoff,target_time=cutoff+timedelta(minutes=5),feature_version=panel.metadata['feature_definition_version'])
        rows=tuple(change(row,available_at=cutoff,quote_available_at=cutoff,quote_window_start=cutoff,
            quote_window_end=identity.target_time,capacity=change(row.capacity,available_at=cutoff)) for row in fixture.operational.rows)
        ops=change(fixture.operational,identity=identity,rows=rows,pricing_graph_available_at=cutoff)
        provider=CheckpointForecastProvider(cfg,cfg.output_dir/'duocast'/'seed_42'/'best.pt',forecast_run_id='actual-forward')
        calls=[]
        def recorded(i):
            forecast=provider(i)
            calls.append(forecast)
            return forecast
        result=run_decision(identity=identity,operational=ops,response=fixture.response,
            policy=change(fixture.policy,br_min=0.),forecast_provider=recorded)
        assert result.result_status=='VALID',result.diagnostics
        assert len(calls)==1
        assert calls[0].forecast_model_id=='duocast'
        assert calls[0].parity_status=='TEST_ONLY_CHECKPOINT_VERIFIED'
        assert result.production_effective is False
        assert len(result.recommendations)==panel.n_nodes

    def test_five_model_table_and_test_freeze(cfg):
        pytest.importorskip('lightgbm')
        assert tuple(cfg.variants)==MAIN_VARIANTS
        results=benchmark(cfg)
        assert len(results)==5
        table=report(cfg)
        assert {r['variant'] for r in table}==set(MAIN_VARIANTS)
        assert all(set(FORECAST_METRICS)<=set(r) for r in table)
        selected=select(cfg)
        assert selected['selected_variant'] in MAIN_VARIANTS
        result=finalize(cfg)
        assert len(result['trials'])==5
        with pytest.raises(ValueError,match='already evaluated'): finalize(cfg)

    def test_network_optimizer_imports_no_training_or_torch():
        import surge_ml.inferences.network_optimizer as optimizer
        tree=ast.parse(Path(optimizer.__file__).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                assert not any(x in (node.module or '') for x in ('torch','train','duocast'))

    def test_reference_outside_response_support_is_invalid():
        fixture=make_fixture(hex_count=1)
        cell=fixture.response.cells[0]
        response=change(fixture.response,cells=(change(cell,support=change(cell.support,surge_min='1.3')),))
        result=fixture.run(response=response)
        assert result.result_status=='INVALID'
        assert not result.recommendations

    def test_forecast_generation_after_service_start_is_valid():
        fixture=make_fixture()
        def generate(identity):
            return change(fixture.forecast,generated_at=datetime.now(timezone.utc))
        result=run_decision(identity=fixture.identity,operational=fixture.operational,
            response=fixture.response,policy=fixture.policy,forecast_provider=generate)
        assert result.result_status=='VALID',result.diagnostics

    def test_response_fit_from_file(cfg,tmp_path):
        rows=synthetic_observations(n=120)
        source=tmp_path/'observations.json'
        source.write_text(json.dumps([r.model_dump(mode='json') for r in rows]))
        job=dict(input='observations.json',output='fitted/artifact.json',dataset_id='synthetic-cohorts',
            node_mapping_version='test-nodes',required_hex_ids=['test-hex-00'],artifact_version='fit-test-v1',
            split_time=rows[90].decision_time.isoformat(),fit_as_of=rows[-1].outcome_matured_at.isoformat(),
            fit=fit_config(replicas=1).model_dump(mode='json'))
        path=tmp_path/'response.yaml'
        path.write_text(yaml.safe_dump(job))
        report=fit_from_config(path)
        assert report['cells']==1 and report['production_eligible'] is False
        with pytest.raises(FileExistsError): fit_from_config(path)
    ''')
    put('tests/conftest.py','''
    """Keep fixture work local to pytest temporary directories; no production fixtures."""
    import os
    os.environ.setdefault('OMP_NUM_THREADS','2')
    os.environ.setdefault('MKL_NUM_THREADS','2')
    ''')


# BUILDERS_CONTINUE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    if args.activate:
        state = json.loads((STAGE / 'state.json').read_text())
        if inventory() != state['original_sha256']:
            raise RuntimeError('Original files changed while staging; stop and reconcile, never overwrite concurrent edits')
        if ARCHIVE.exists():
            raise RuntimeError('Archive already exists; activation is intentionally one-shot')
        import xml.etree.ElementTree as ET
        report = STAGE / 'stage-tests.xml'
        if not report.is_file():
            raise RuntimeError('Run staging pytest with the documented JUnit destination before activation')
        root = ET.parse(report).getroot()
        suites = [root] if root.tag == 'testsuite' else list(root.iter('testsuite'))
        if not suites or sum(int(s.get('tests', '0')) for s in suites) == 0:
            raise RuntimeError('No executed staging tests')
        if any(int(s.get(key, '0')) for s in suites for key in ('failures', 'errors', 'skipped')):
            raise RuntimeError('Staging suite is not fully passing; activation refused')
        staged_files = [*(STAGE/'src').rglob('*.py'), *(STAGE/'tests').rglob('*.py')]
        if any(p.stat().st_mtime > report.stat().st_mtime for p in staged_files):
            raise RuntimeError('Source/tests changed since verification; rerun the complete staging suite')
        state['staged_sha256'] = {p.relative_to(STAGE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in staged_files}
        state['test_report_sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
        for file in (STAGE / 'src').rglob('*.py'):
            compile(file.read_text(encoding='utf-8'), str(file), 'exec')
        ARCHIVE.mkdir(parents=True)
        (ARCHIVE / 'src').mkdir()
        moved = []
        try:
            for old, backup, staged in ((PIPE/'src'/'surge_ml', ARCHIVE/'src'/'surge_ml', STAGE/'src'/'surge_ml'),
                                       (PIPE/'tests', ARCHIVE/'tests', STAGE/'tests'),
                                       (PIPE/'configs', ARCHIVE/'configs', STAGE/'configs')):
                old.rename(backup)
                moved.append((old, backup, staged))
                staged.rename(old)
        except Exception:
            for old, backup, staged in reversed(moved):
                if old.exists():
                    old.rename(staged)
                if backup.exists():
                    backup.rename(old)
            raise
        (ARCHIVE/'manifest.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
        for name in ('pyproject.toml', 'README.md'):
            path = PIPE / name
            if path.exists():
                shutil.copy2(path, ARCHIVE / name)
        print(f'ACTIVATED: {PIPE / "src" / "surge_ml"}; byte-preserved prior checkout: {ARCHIVE}')
        return
    if STAGE.exists():
        raise RuntimeError(f'Staging already exists: {STAGE}. Review it; no implicit overwrite.')
    before = inventory()
    build_contracts()
    build_config_and_model()
    build_datasets()
    build_responses_and_optimizer()
    build_training_and_reports()
    build_fixtures()
    build_cli()
    build_tests()
    for filename, text in list(OUTPUTS.items()):
        if filename.startswith('src/surge_ml/'):
            parent = Path(filename).parent
            while parent.as_posix() != 'src':
                OUTPUTS.setdefault((parent / '__init__.py').as_posix(), '"""Pipeline package; no import-time work."""\n')
                parent = parent.parent
    for filename, text in OUTPUTS.items():
        if filename.endswith('.py'):
            compile(text, filename, 'exec')
    if inventory() != before:
        raise RuntimeError('Source changed during stage generation')
    STAGE.mkdir()
    for filename, text in OUTPUTS.items():
        dest = STAGE / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding='utf-8', newline='\n')
    (STAGE/'state.json').write_text(json.dumps({'original_sha256': before, 'new_files': sorted(OUTPUTS)}, indent=2), encoding='utf-8')
    (STAGE/'pytest.ini').write_text('[pytest]\npythonpath = src\ntestpaths = tests\n', encoding='utf-8')
    print(f'STAGED {len(OUTPUTS)} files. Active source unchanged. Test with -c {STAGE / "pytest.ini"}.')


if __name__ == '__main__':
    main()
