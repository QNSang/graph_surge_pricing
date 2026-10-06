"""End-to-end generation: exogenous world once, then one simulation per graph-signal strength g."""
import os
import shutil
import time

import yaml

from .calendar_gen import build_calendar
from .exogenous import Exogenous
from .geo import Geo
from .rng import stream
from .simulate import build_tables, run_simulation, shuffle_destinations
from .writers import RAW_TABLES, calendar_json, dump_json, write_dataset, write_partitioned


def dataset_name(g):
    return f"g{g:.1f}"


def generate(cfg, out_dir, strengths=None, shuffled=None, log=print):
    strengths = cfg.signals["graph_signal_strength"] if strengths is None else strengths
    shuffled = cfg.signals["shuffled_control"] if shuffled is None else shuffled
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    geo = Geo(cfg, stream(cfg.seed, "geo"))
    cal = build_calendar(cfg, geo, stream(cfg.seed, "calendar"))
    exo = Exogenous(cfg, geo, cal, stream(cfg.seed, "intents"))
    log(f"exogenous ready: {geo.n} hexes, {cal.n_days} days, {exo.intents.sum():,} intents ({time.time() - t0:.0f}s)")

    with open(os.path.join(out_dir, "config.yaml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg.deep(), fh, allow_unicode=True, sort_keys=False)
    geo.static_table().to_parquet(os.path.join(out_dir, "hexes.parquet"), index=False)
    dump_json(calendar_json(cal, geo, cfg), os.path.join(out_dir, "calendar.json"))

    flat = len(strengths) == 1 and not shuffled   # single dataset: tables go straight into out_dir
    names = []
    for g in strengths:
        name = dataset_name(g)
        log(f"[{name}] simulating")
        S = run_simulation(cfg, geo, exo, g, log=log)
        tables = build_tables(cfg, geo, exo, S)
        root = out_dir if flat else os.path.join(out_dir, name)
        if os.path.isdir(root) and not flat:
            shutil.rmtree(root)
        write_dataset(tables, root)
        log(f"[{name}] wrote {len(tables['orders']):,} orders, {len(tables['hex_snapshot_5min']):,} snapshot rows")
        names.append(name)
        if shuffled and g == 1.0:
            sname = name + "_shuffled"
            sroot = os.path.join(out_dir, sname)
            if os.path.isdir(sroot):
                shutil.rmtree(sroot)
            os.makedirs(sroot)
            for t in RAW_TABLES:
                if t != "orders":
                    shutil.copytree(os.path.join(root, t), os.path.join(sroot, t))
            shutil.copytree(os.path.join(root, "_debug"), os.path.join(sroot, "_debug"))
            write_partitioned(shuffle_destinations(tables["orders"], cfg.seed), sroot, "orders")
            names.append(sname)
            log(f"[{sname}] wrote")
    log(f"done in {time.time() - t0:.0f}s: {names}")
    return names
