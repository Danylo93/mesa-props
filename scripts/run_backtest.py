#!/usr/bin/env python3
"""
Roda o backtest, a varredura de parametros, o walk-forward e o Monte Carlo.

    python scripts/run_backtest.py            # tudo
    python scripts/run_backtest.py --quick    # so o backtest padrao

O numero que decide nao e o lucro do backtest, e o P(aprovado) do Monte
Carlo. Um backtest que passa uma vez num periodo pode ser sorte; a
distribuicao diz quanto.
"""
from __future__ import annotations

import json
import sys
import pathlib
from itertools import product

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from the5ers.backtest import BacktestConfig, run_backtest
from the5ers.montecarlo import MCConfig, simulate
from the5ers.risk import RiskLimits
from the5ers.rules import ProgramRules
from the5ers.strategy import StratParams

DATA = ROOT / "data" / "h1"
REPORTS = ROOT / "reports"


def load() -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(DATA.glob("*.csv")):
        df = pd.read_csv(f, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index, utc=True)
        if len(df) > 400:
            out[f.stem] = df
    return out


def show(title: str, st: dict) -> None:
    print(f"\n--- {title} ---")
    for k in ("status", "breach", "profit", "equity", "trades", "win_rate",
              "profit_factor", "avg_R", "expectancy_usd", "max_drawdown_usd",
              "profitable_days", "min_equity_seen", "days_traded"):
        if k in st:
            print(f"  {k:20} {st[k]}")
    if st.get("exits"):
        print("  saidas:")
        for r_, e in sorted(st["exits"].items(), key=lambda x: -x[1]["n"]):
            print(f"    {r_:18} n={e['n']:>3}  pnl={e['pnl']:>9.2f}  medio={e['avg']:>8.2f}")


def slice_data(data, start=None, end=None):
    out = {}
    for s, df in data.items():
        d = df
        if start is not None:
            d = d[d.index >= start]
        if end is not None:
            d = d[d.index < end]
        if len(d) > 400:
            out[s] = d
    return out


def main() -> None:
    quick = "--quick" in sys.argv
    data = load()
    if not data:
        print(f"sem dados em {DATA}. Rode: python scripts/fetch_data.py")
        sys.exit(1)
    bars = sum(len(d) for d in data.values())
    span = (min(d.index[0] for d in data.values()).date(),
            max(d.index[-1] for d in data.values()).date())
    print(f"{len(data)} pares, {bars} barras H1, {span[0]} -> {span[1]}")
    print(f"pares: {', '.join(sorted(data))}")

    rules, cfg = ProgramRules(), BacktestConfig()
    base_p, base_l = StratParams(), RiskLimits()

    res = run_backtest(data, base_p, base_l, rules, cfg)
    st = res.stats()
    show("backtest padrao (parametros nao otimizados)", st)
    if quick:
        return

    # ---------------------------------------------------------- varredura
    # Risco fica fixo: ele escala o resultado, nao cria vantagem. O que a
    # varredura procura e avg_R > 0, que e escala-invariante.
    print("\n--- varredura de parametros ---")
    grid = [
        {"rr": rr, "stop_mode": sm, "slope_bars": sl, "shallow_pullback": sp}
        for rr in (1.0, 1.5, 2.0)
        for sm in ("atr", "swing")
        for sl in (0, 12)
        for sp in (False, True)
    ]

    def mk(g: dict) -> StratParams:
        return base_p.with_(**g)

    rows = []
    for g in grid:
        s = run_backtest(data, mk(g), base_l, rules, cfg).stats()
        rows.append({**g, "status": s["status"], "profit": s["profit"],
                     "trades": s["trades"], "win_rate": s["win_rate"],
                     "avg_R": s["avg_R"], "max_dd": s["max_drawdown_usd"]})
        print(f"  rr={g['rr']} stop={g['stop_mode']:5} slope={g['slope_bars']:>2} "
              f"raso={str(g['shallow_pullback'])[:1]}  ->  {s['status']:7} "
              f"lucro={s['profit']:>9.2f} trades={s['trades']:>4} "
              f"win={s['win_rate']:>5.1f}% avgR={s['avg_R']:>6.3f}")
    sweep = pd.DataFrame(rows).sort_values("avg_R", ascending=False)

    # Escolhe por avg_R com amostra minima. Lucro premia sorte; avg_R com
    # n>=40 ao menos exige que a vantagem apareca varias vezes.
    elegivel = sweep[sweep["trades"] >= 40]
    if elegivel.empty:
        print("\n  nenhuma config com >=40 trades. Amostra insuficiente.")
        elegivel = sweep
    best = elegivel.iloc[0]
    print(f"\nmelhor por avg_R (n>=40): rr={best.rr} stop={best.stop_mode} "
          f"slope={best.slope_bars} raso={best.shallow_pullback} -> avgR={best.avg_R}")
    if best.avg_R <= 0:
        print("  !! NENHUMA configuracao tem vantagem positiva neste periodo.")
        print("     Nao opere isto com dinheiro. Ver secao 6 do README.")
    bp = mk({"rr": float(best.rr), "stop_mode": str(best.stop_mode),
             "slope_bars": int(best.slope_bars),
             "shallow_pullback": bool(best.shallow_pullback)})
    bl = base_l

    # ---------------------------------------------------------- walk-forward
    print("\n--- walk-forward (3 janelas out-of-sample) ---")
    all_ts = sorted({t for d in data.values() for t in d.index})
    n = len(all_ts)
    edges = [all_ts[min(int(n * f), n - 1)] for f in (0.0, 0.4, 0.6, 0.8, 1.0)]
    wf = []
    for i in range(1, 4):
        tr = slice_data(data, edges[0], edges[i])
        te = slice_data(data, edges[i], edges[i + 1])
        if not tr or not te:
            continue
        # otimiza no treino
        bestR, bestcfg = -9e9, (bp, bl)
        for g in grid:
            p = mk(g)
            s = run_backtest(tr, p, base_l, rules, cfg).stats()
            if s["trades"] >= 20 and s["avg_R"] > bestR:
                bestR, bestcfg = s["avg_R"], (p, base_l)
        s_te = run_backtest(te, *bestcfg, rules, cfg).stats()
        wf.append({"fold": i, "train_avgR": round(bestR, 3),
                   "test_avgR": s_te["avg_R"], "test_profit": s_te["profit"],
                   "test_trades": s_te["trades"], "test_status": s_te["status"]})
        print(f"  janela {i}: treino avgR={bestR:>6.3f} | teste avgR={s_te['avg_R']:>6.3f} "
              f"lucro={s_te['profit']:>9.2f} trades={s_te['trades']:>3} {s_te['status']}")

    # ---------------------------------------------------------- monte carlo
    print("\n--- Monte Carlo (20 000 caminhos) ---")
    rb = run_backtest(data, bp, bl, rules, cfg)
    closed = rb.closed
    if len(closed) < 30:
        print(f"  so {len(closed)} trades fechados - amostra pequena demais. Pulando.")
        mc = None
    else:
        rs = np.array([t.r_multiple for t in closed])
        per_day = pd.Series([t.entry_time.date() for t in closed]).value_counts().values
        mc = simulate(rs, per_day, rules, bl, MCConfig(paths=20_000))
        for k, v in mc.as_dict().items():
            print(f"  {k:28} {v}")

    REPORTS.mkdir(exist_ok=True)
    sweep.to_csv(REPORTS / "sweep.csv", index=False)
    payload = {
        "dados": {"pares": sorted(data), "barras": bars,
                  "inicio": str(span[0]), "fim": str(span[1])},
        "backtest_padrao": st,
        "melhor_config": {"rr": float(best.rr), "stop_mode": str(best.stop_mode),
                          "slope_bars": int(best.slope_bars),
                          "shallow_pullback": bool(best.shallow_pullback),
                          "risk_per_trade_pct": base_l.risk_per_trade_pct},
        "backtest_melhor": rb.stats(),
        "walk_forward": wf,
        "monte_carlo": mc.as_dict() if mc else None,
    }
    (REPORTS / "resultado.json").write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nrelatorio -> {REPORTS/'resultado.json'}  e  {REPORTS/'sweep.csv'}")


if __name__ == "__main__":
    main()
