"""python -m scripts.validate --out output_dev [--names g1.0 g0.0 ...]"""
import argparse
import sys
import os

from surge_mock.validate import evaluate, load_hexes, write_report


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output")
    ap.add_argument("--names", nargs="*", default=None)
    a = ap.parse_args()
    names = a.names or sorted(d for d in os.listdir(a.out)
                              if d.startswith("g") and os.path.isdir(os.path.join(a.out, d)))
    if not names and os.path.isdir(os.path.join(a.out, "orders")):
        names = ["."]   # flat layout: a single g1.0 dataset directly in --out
    res = write_report(a.out, names, load_hexes(a.out))
    for n, m in res.items():
        bad = [(label, v) for label, key, v, lo, hi, ok in evaluate(m) if not ok]
        print(f"{n}: {len(bad)} chỉ tiêu ngoài khoảng")
        for label, v in bad:
            print(f"   - {label}: {v:.3f}")


if __name__ == "__main__":
    main()
