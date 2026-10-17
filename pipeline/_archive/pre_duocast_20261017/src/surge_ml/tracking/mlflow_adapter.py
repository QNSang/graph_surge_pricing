"""Ghi log MLflow cho một trial; tracker tắt thì không làm gì."""

import os
from datetime import datetime
from pathlib import Path

DEFAULT_URI = "http://127.0.0.1:5000"


def stamped_experiment(prefix: str) -> str:
    """Tên experiment cho một lần train/benchmark, ví dụ graph_surge_pricing_20261009-123000."""
    return f"{prefix}_{datetime.now():%Y%m%d-%H%M%S}"


class Tracker:
    """Trial mới mở run mới trong `experiment`; trial chạy tiếp thì dùng lại run đã ghi."""

    def __init__(self, enabled: bool, experiment: str, trial_dir: Path, run_name: str, resume: bool = False):
        self.enabled, self.experiment, self.dir, self.run_name = enabled, experiment, trial_dir, run_name
        self.resume = resume
        self._mlflow = None

    def __enter__(self) -> "Tracker":
        if not self.enabled:
            return self
        import mlflow

        self._mlflow = mlflow
        mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", DEFAULT_URI))
        id_file = self.dir / "mlflow_run_id.txt"
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.resume and id_file.is_file():
            mlflow.start_run(run_id=id_file.read_text(encoding="utf-8").strip())
        else:
            mlflow.set_experiment(self.experiment)
            run = mlflow.start_run(run_name=self.run_name)
            id_file.write_text(run.info.run_id, encoding="utf-8")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._mlflow:
            self._mlflow.end_run(status="FINISHED" if exc_type is None else
                                 "KILLED" if exc_type is KeyboardInterrupt else "FAILED")

    def log_params(self, params: dict) -> None:
        if self._mlflow:
            existing = self._mlflow.active_run().data.params
            self._mlflow.log_params({k: str(v)[:6000] for k, v in params.items() if k not in existing})

    def log_metrics(self, metrics: dict, step: int | None = None) -> None:
        if self._mlflow:
            self._mlflow.log_metrics({k: float(v) for k, v in metrics.items() if v is not None}, step=step)

    def log_artifact(self, path: Path, artifact_path: str | None = None) -> None:
        if self._mlflow and path.is_file():
            self._mlflow.log_artifact(str(path), artifact_path)

    def log_figures(self, folder: Path, artifact_path: str) -> None:
        for png in sorted(folder.glob("*.png")):
            self.log_artifact(png, artifact_path)
