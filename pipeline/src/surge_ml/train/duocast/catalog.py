"""Single model registry; importing this file does not start any training."""
from ._constant import MODEL_LABELS, MAIN_VARIANTS, NEURAL_VARIANTS, VARIANTS

def build_neural(n_dynamic, n_mobility, config, variant="duocast"):
    from .variants.neural import DuoCast
    if variant not in NEURAL_VARIANTS:
        raise ValueError(f"Not a neural variant: {variant}")
    return DuoCast(n_dynamic, n_mobility, config, variant)
