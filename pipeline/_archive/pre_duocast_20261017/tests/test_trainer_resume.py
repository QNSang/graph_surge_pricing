import pytest
import torch

from surge_ml.config import apply_overrides, config_sha256
from surge_ml.errors import SurgeError
from surge_ml.features import VARIANTS
from surge_ml.models.dual_gru_gatv2 import build_model
from surge_ml.orchestration.runner import set_seed
from surge_ml.training.trainer import Trainer


def _fit(cfg, data, out, epochs, resume=False):
    cfg = apply_overrides(cfg, epochs=epochs)
    set_seed(7)
    model = build_model(VARIANTS["gru_gatv2_40"], cfg.model)
    summary = Trainer(model, data, VARIANTS["gru_gatv2_40"], cfg, out, config_sha256(cfg), 7).fit(resume=resume)
    return model, summary


def test_resume_matches_continuous_run(cfg, data, tmp_path):
    model_a, sum_a = _fit(cfg, data, tmp_path / "a", epochs=3)
    _fit(cfg, data, tmp_path / "b", epochs=2)
    model_b, sum_b = _fit(cfg, data, tmp_path / "b", epochs=3, resume=True)
    assert sum_a["history"] == sum_b["history"]
    for pa, pb in zip(model_a.state_dict().values(), model_b.state_dict().values()):
        assert torch.equal(pa, pb)
    assert (tmp_path / "a" / "best.pt").is_file()


def test_resume_rejects_changed_config(cfg, data, tmp_path):
    _fit(cfg, data, tmp_path / "c", epochs=1)
    cfg.train.lr = 0.5
    with pytest.raises(SurgeError, match="config_sha256"):
        _fit(cfg, data, tmp_path / "c", epochs=2, resume=True)
