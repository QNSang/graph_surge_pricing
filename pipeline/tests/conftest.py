"""Keep fixture work local to pytest temporary directories; no production fixtures."""
import os
os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('MKL_NUM_THREADS','2')
