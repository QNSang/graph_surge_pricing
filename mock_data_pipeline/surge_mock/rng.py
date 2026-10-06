import zlib

import numpy as np


def stream(seed, name):
    """Independent, reproducible RNG stream per component name."""
    return np.random.default_rng(np.random.SeedSequence([int(seed), zlib.crc32(name.encode())]))


def numba_seed(seed, name):
    return int((int(seed) * 1_000_003 + zlib.crc32(name.encode())) % (2**31 - 1))
