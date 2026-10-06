"""Config loading: YAML + profile (full/dev) + dotted-key overrides."""
import copy
import os

import yaml

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")


class Config(dict):
    """dict with attribute access (recursive)."""

    def __getattr__(self, k):
        try:
            v = self[k]
        except KeyError as e:
            raise AttributeError(k) from e
        return Config(v) if isinstance(v, dict) else v

    def deep(self):
        return copy.deepcopy(dict(self))


def _set_dotted(d, key, value):
    parts = key.split(".")
    for p in parts[:-1]:
        d = d[p]
    d[parts[-1]] = value


def load_config(path=None, profile="full", overrides=None):
    with open(path or DEFAULT_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    prof = raw["profiles"][profile]
    raw["profile"] = profile
    raw["n_days"] = prof["n_days"]
    raw["split"] = prof["split"]
    raw["rain"]["days"] = prof["rain_days"]
    raw["signals"]["s4"]["events"] = prof["venue_events"]
    for k, v in (overrides or {}).items():
        _set_dotted(raw, k, v)
    return Config(raw)


def parse_hhmm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def khung_bounds(key):
    a, b = key.split("-")
    return int(a), int(b)
