#!/usr/bin/env python3
"""Reconstroi data/h1/*.csv a partir do cache .bi5 ja baixado."""
import sys, pathlib, collections
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pandas as pd
from the5ers.dukascopy import fetch_month

CACHE = ROOT / "data" / "raw" / "duka"
by = collections.defaultdict(list)
for f in sorted(CACHE.rglob("*.bi5")):
    y, m = f.stem.split("-")
    df = fetch_month(f.parent.name, int(y), int(m), CACHE)
    if df is not None and len(df):
        by[f.parent.name].append(df)

out = ROOT / "data" / "h1"; out.mkdir(parents=True, exist_ok=True)
for p, parts in sorted(by.items()):
    d = pd.concat(parts).sort_index(); d = d[~d.index.duplicated(keep="last")]
    d.to_csv(out / f"{p}.csv")
    meses = len({(i.year, i.month) for i in d.index})
    print(f"  {p:8} {len(d):6} barras  {meses:>2} meses  {d.index[0].date()} -> {d.index[-1].date()}")
