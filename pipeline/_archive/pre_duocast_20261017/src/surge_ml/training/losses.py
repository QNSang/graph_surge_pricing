"""SmoothL1 có mask: phần tử bị mask bị loại trước khi tính loss (mean trên Z = số phần tử hợp lệ)."""

import torch
import torch.nn.functional as F


def target_mask(y: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    return torch.isfinite(y) & torch.isfinite(b)


def masked_smooth_l1(pred: torch.Tensor, y: torch.Tensor, mask: torch.Tensor, beta: float) -> torch.Tensor:
    return F.smooth_l1_loss(pred[mask], y[mask], beta=beta)


def dual_loss(out: dict, y: torch.Tensor, mask: torch.Tensor, beta: float, lambda_local: float):
    """V1.2: L_total = L_G + lambda_local * L_L (lambda_local = 0.3); chỉ có head local thì L_total = L_L.
    Trả (total, parts), hoặc None nếu batch không có target hợp lệ."""
    if not bool(mask.any()):
        return None
    parts = {"local": masked_smooth_l1(out["local"], y, mask, beta)}
    total = parts["local"]
    if "graph" in out:
        parts["graph"] = masked_smooth_l1(out["graph"], y, mask, beta)
        total = parts["graph"] + lambda_local * parts["local"]
    return total, parts
