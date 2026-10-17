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
