#!/usr/bin/env python3
"""
Baixa candles H1 (Dukascopy) dos majors para data/h1/.

O link ate a Dukascopy neste ambiente derruba ~70% das conexoes
(reset/timeout no relay), e isso NAO melhora com pausas maiores - medido.
A resposta e falhar rapido e repetir em paralelo, nao esperar mais.

    python scripts/fetch_data.py [meses] [pares...]
"""
from __future__ import annotations

import sys, time, pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
from the5ers.dukascopy import PAIRS, fetch_month

WORKERS = 8
PASSES = 12
CACHE = ROOT / "data" / "raw" / "duka"

args = [a for a in sys.argv[1:] if not a.startswith("-")]
MONTHS = int(args[0]) if args and args[0].isdigit() else 18
pairs = args[1:] if len(args) > 1 else PAIRS[:5]


def months_back(n: int) -> list[tuple[int, int]]:
    now = datetime.now(timezone.utc)
    y, m, out = now.year, now.month, []
    for _ in range(n):
        out.append((y, m)); m -= 1
        if m == 0: y, m = y - 1, 12
    return out


targets = [(p, y, m) for p in pairs for (y, m) in months_back(MONTHS)]
print(f"{len(targets)} arquivos ({len(pairs)} pares x {MONTHS} meses), {WORKERS} workers", flush=True)

got: dict[tuple, pd.DataFrame] = {}
for ap in range(PASSES):
    todo = [t for t in targets if t not in got]
    if not todo:
        break
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_month, p, y, m, CACHE): (p, y, m) for (p, y, m) in todo}
        for f in as_completed(futs):
            key = futs[f]
            try:
                df = f.result()
            except Exception:
                df = None
            if df is not None and len(df):
                got[key] = df
    print(f"  passada {ap+1}: {len(got)}/{len(targets)}", flush=True)
    if len(got) < len(targets) and ap < PASSES - 1:
        time.sleep(3)

outdir = ROOT / "data" / "h1"; outdir.mkdir(parents=True, exist_ok=True)
print()
for p in pairs:
    parts = [df for (pp, _, _), df in got.items() if pp == p]
    if not parts:
        print(f"  ! {p}: nada"); continue
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.to_csv(outdir / f"{p}.csv")
    print(f"  {p:8} {len(df):6} barras  {df.index[0].date()} -> {df.index[-1].date()}", flush=True)
print(f"\n{len(got)}/{len(targets)} arquivos; CSVs em {outdir}")
