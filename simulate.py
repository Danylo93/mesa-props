#!/usr/bin/env python3
"""
Teste pratico: o Holy Grail aprovaria a conta The5ers 100K, e em quanto tempo?

Backtest de CARTEIRA - 5 pares, uma conta so, risco compartilhado, as
regras reais no circuito. Diferente dos testes anteriores, que mediam a
qualidade do sinal trade a trade; aqui mede-se o que acontece com a conta.

Premissas conservadoras:
  * enquanto uma posicao esta aberta, a equity considerada para os pisos
    desconta a perda MAXIMA dela (como se todas batessem o stop juntas);
  * o dia vira as 21:00 UTC (fechamento de NY), nao a meia-noite;
  * o governor veta antes dos limites contratuais (1.5% / 2.5% vs 4%).

    python simulate.py [--tuned]   # --tuned usa ADX>30, RR>=2, alvo 2R
"""
from __future__ import annotations

import sys, pathlib
from datetime import timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from holygrail.indicators import add_indicators
from holygrail.setup import HGParams, find_setups
from holygrail.evaluate import CostModel, run_setups
from holygrail.resample import resample
from holygrail.the5ers import Account, Limits, Rules, Status, size_lots

PARES = ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY")
CM = CostModel(max_bars=48)


def broker_day(ts: pd.Timestamp):
    return (ts + timedelta(hours=3)).date()     # vira as 21:00 UTC


def build_trades(p: HGParams, tf: str = "H4") -> list[dict]:
    """Todos os setups dos 5 pares, com entrada, saida e R, em ordem de tempo."""
    trades = []
    for par in PARES:
        d = pd.read_csv(f"data/h1/{par}.csv", index_col=0, parse_dates=True)
        d.index = pd.to_datetime(d.index, utc=True)
        d = add_indicators(resample(d, tf))
        for s, o in zip(find_setups(d, p), run_setups(d, find_setups(d, p), par, CM)):
            trades.append({
                "pair": par,
                "t_in": d.index[o.i_entry], "t_out": d.index[o.i_exit],
                "r": o.r, "stop_dist": o.risk_price,
                "px": o.entry_px, "reason": o.reason,
            })
    trades.sort(key=lambda x: x["t_in"])
    return trades


def simulate(trades: list[dict], limits: Limits, rules: Rules | None = None,
             verbose: bool = False) -> dict:
    acc = Account(rules or Rules(), limits)
    openp: list[dict] = []
    if not trades:
        return {"status": "sem trades"}
    acc.open_day(broker_day(trades[0]["t_in"]))
    taken = skipped = 0
    travou = None
    equity_curve = []

    def worst_equity() -> float:
        return acc.balance - sum(t["risk_usd"] for t in openp)

    def settle(until: pd.Timestamp) -> None:
        nonlocal openp
        for t in sorted([x for x in openp if x["t_out"] <= until],
                        key=lambda x: x["t_out"]):
            d = broker_day(t["t_out"])
            while acc.day is not None and d > acc.day:
                acc.close_day()
                acc.open_day(acc.day + timedelta(days=1))
            acc.balance += t["r"] * t["risk_usd"]
            openp.remove(t)
            acc.mark(worst_equity())
            equity_curve.append((t["t_out"], acc.balance))

    for tr in trades:
        settle(tr["t_in"])
        if acc.breach or acc.status is Status.PASSED:
            break
        d = broker_day(tr["t_in"])
        while acc.day is not None and d > acc.day:
            acc.close_day()
            acc.open_day(acc.day + timedelta(days=1))
        acc.mark(worst_equity())
        if acc.breach:
            break
        if acc.balance <= acc.guarded_floor and travou is None:
            # A conta nao estourou, mas o piso que ARRASTA + a folga do
            # governor a deixaram sem espaco para arriscar. Na pratica
            # acabou: nao viola, mas tambem nao recupera mais.
            travou = tr["t_in"]
        if not acc.can_open(len(openp)):
            skipped += 1
            continue
        risk = acc.risk_usd()
        lots = size_lots(tr["pair"], tr["px"], tr["stop_dist"], risk)
        if lots <= 0:
            skipped += 1
            continue
        openp.append({**tr, "risk_usd": risk})
        taken += 1

    settle(pd.Timestamp("2100-01-01", tz="UTC"))
    if not acc.breach:
        acc.close_day()

    dias_corridos = (trades[-1]["t_in"] - trades[0]["t_in"]).days
    return {
        "status": acc.status.value,
        "saldo": round(acc.balance, 2),
        "lucro": round(acc.balance - acc.rules.initial, 2),
        "trades_feitos": taken, "trades_vetados": skipped,
        "dias_de_pregao": acc.days,
        "dias_corridos": dias_corridos,
        "dias_lucrativos": acc.profit_days,
        "equity_minima": round(acc.min_equity, 2),
        "travou_em": travou,
        "piso_total_final": round(acc.total_floor, 2),
        "curva": equity_curve,
    }


if __name__ == "__main__":
    tuned = "--tuned" in sys.argv
    p = HGParams(adx_min=30.0, min_rr=2.0, max_rr=2.0) if tuned else HGParams()
    print(__doc__)
    print(f"  config: {'AJUSTADA (ADX>30, RR>=2, alvo 2R)' if tuned else 'DO LIVRO'}\n")
    trades = build_trades(p)
    print(f"  {len(trades)} setups nos 5 pares, "
          f"{trades[0]['t_in'].date()} -> {trades[-1]['t_in'].date()}\n")

    print(f"  {'risco/trade':>12} {'status':>9} {'lucro':>10} {'feitos':>7} "
          f"{'vetados':>8} {'dias lucr':>10} {'eq.minima':>11}  travou em")
    print("  " + "-" * 88)
    for rp in (0.25, 0.35, 0.50, 0.75, 1.00):
        r = simulate(trades, Limits(risk_pct=rp))
        tv = r["travou_em"].date() if r["travou_em"] is not None else "-"
        print(f"  {rp:>11.2f}% {r['status']:>9} {r['lucro']:>+10.2f} "
              f"{r['trades_feitos']:>7} {r['trades_vetados']:>8} "
              f"{r['dias_lucrativos']:>10} {r['equity_minima']:>11.2f}  {tv}")

    base = simulate(trades, Limits(risk_pct=0.35))
    print(f"\n  periodo coberto: {base['dias_corridos']} dias corridos "
          f"(~{base['dias_corridos']/365:.1f} anos), {base['dias_de_pregao']} dias de pregao")
