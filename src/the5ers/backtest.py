"""
Backtest orientado a eventos, com as regras The5ers no circuito.

Premissas deliberadamente PESSIMISTAS. Um backtest de desafio de prop
firm que erra para o otimista nao vale nada - a conta e real.

  * Sinal da barra t executa na ABERTURA de t+1. Nunca no fechamento
    da propria barra que gerou o sinal.
  * Se stop E alvo cabem na mesma barra, assume-se STOP. Dados H1 nao
    dizem a ordem dentro da barra.
  * Spread cobrado meio a meio na entrada e na saida, mais slippage,
    mais comissao por lote.
  * A equity que vai ao motor de regras e a PIOR da barra (extremo
    contra a posicao), nao o fechamento. E assim que a corretora mede.
  * Virada do dia no horario do servidor MT5, nao em UTC 00:00.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from .data import SPREADS_PIPS
from .risk import RiskGovernor, RiskLimits, pip_size, pip_value_usd, size_position
from .rules import Breach, ProgramRules, RuleEngine, Status
from .strategy import StratParams, add_indicators, generate_signals, stop_distance

__all__ = ["BacktestConfig", "Trade", "Result", "run_backtest"]


@dataclass(frozen=True)
class BacktestConfig:
    commission_per_lot: float = 7.0      # USD, ida e volta, por lote padrao
    slippage_pips: float = 0.2
    # MT5 da maioria das prop firms vira o dia a 00:00 do servidor (GMT+2/+3).
    # 21:00 UTC e a aproximacao usada aqui; mude se o seu servidor diferir.
    day_rollover_utc_hour: int = 21
    warmup_bars: int = 250               # deixa as EMAs assentarem
    # Lacuna (em horas) que invalida os indicadores. Fim de semana normal
    # em FX e ~49h; acima disso e mes faltando, nao fim de semana.
    gap_hours: float = 72.0


@dataclass
class Trade:
    symbol: str
    side: int                 # +1 long, -1 short
    entry_time: pd.Timestamp
    entry_price: float
    stop: float
    target: float
    lots: float
    risk_usd: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    reason: str = ""
    bars_held: int = 0
    be_moved: bool = False

    @property
    def is_open(self) -> bool:
        return self.exit_time is None

    @property
    def r_multiple(self) -> float:
        return self.pnl / self.risk_usd if self.risk_usd else 0.0


@dataclass
class Result:
    engine: RuleEngine
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[pd.Timestamp, float]] = field(default_factory=list)

    @property
    def closed(self) -> list[Trade]:
        return [t for t in self.trades if not t.is_open]

    def stats(self) -> dict:
        cl = self.closed
        wins = [t for t in cl if t.pnl > 0]
        losses = [t for t in cl if t.pnl <= 0]
        gross_w = sum(t.pnl for t in wins)
        gross_l = -sum(t.pnl for t in losses)
        eq = [e for _, e in self.equity_curve] or [self.engine.rules.initial_balance]
        peak, mdd = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            mdd = max(mdd, peak - v)
        return {
            **self.engine.snapshot(),
            "trades": len(cl),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(100.0 * len(wins) / len(cl), 1) if cl else 0.0,
            "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else None,
            "avg_R": round(sum(t.r_multiple for t in cl) / len(cl), 3) if cl else 0.0,
            "expectancy_usd": round(sum(t.pnl for t in cl) / len(cl), 2) if cl else 0.0,
            "max_drawdown_usd": round(mdd, 2),
            "exits": self.exit_breakdown(),
        }

    def exit_breakdown(self) -> dict:
        """Por que os trades morreram. Diz mais sobre o sistema que o lucro."""
        out: dict[str, dict] = {}
        for t in self.closed:
            k = t.reason.split(":")[0]
            e = out.setdefault(k, {"n": 0, "pnl": 0.0})
            e["n"] += 1
            e["pnl"] += t.pnl
        for k, e in out.items():
            e["pnl"] = round(e["pnl"], 2)
            e["avg"] = round(e["pnl"] / e["n"], 2)
        return out


# ------------------------------------------------------------------ helpers

def _broker_day(ts: pd.Timestamp, rollover_hour: int) -> date:
    """Dia de negociacao do servidor. Depois do rollover ja e o dia seguinte."""
    shifted = ts + timedelta(hours=24 - rollover_hour)
    return shifted.date()


def _pnl_usd(symbol: str, side: int, entry: float, exit_px: float, lots: float,
             cfg: BacktestConfig) -> float:
    pips = (exit_px - entry) / pip_size(symbol) * side
    gross = pips * pip_value_usd(symbol, exit_px, lots)
    return gross - cfg.commission_per_lot * lots


def _half_spread(symbol: str) -> float:
    return SPREADS_PIPS.get(symbol, 1.5) / 2.0 * pip_size(symbol)


def _slip(symbol: str, cfg: BacktestConfig) -> float:
    return cfg.slippage_pips * pip_size(symbol)


# ------------------------------------------------------------------ engine

def run_backtest(
    data: dict[str, pd.DataFrame],
    params: StratParams | None = None,
    limits: RiskLimits | None = None,
    rules: ProgramRules | None = None,
    cfg: BacktestConfig | None = None,
) -> Result:
    params = params or StratParams()
    limits = limits or RiskLimits()
    rules = rules or ProgramRules()
    cfg = cfg or BacktestConfig()

    engine = RuleEngine(rules)
    gov = RiskGovernor(engine, limits)
    res = Result(engine=engine)

    prepared: dict[str, pd.DataFrame] = {}
    for sym, df in data.items():
        d = add_indicators(df, params)
        d["signal"] = generate_signals(d, params)
        d = d.iloc[cfg.warmup_bars:]
        # Barras logo depois de uma lacuna carregam EMA/ATR calculados
        # atravessando o buraco - sinal contaminado. Descarta a janela de
        # aquecimento apos cada lacuna maior que `gap_hours`.
        if cfg.gap_hours > 0 and len(d) > 1:
            gap = d.index.to_series().diff() > pd.Timedelta(hours=cfg.gap_hours)
            blocked = gap.rolling(cfg.warmup_bars, min_periods=1).max().fillna(0) > 0
            d = d[~blocked.values.astype(bool)]
        prepared[sym] = d

    # linha do tempo unificada
    all_ts = sorted({ts for d in prepared.values() for ts in d.index})
    if not all_ts:
        return res

    open_pos: dict[str, Trade] = {}
    pending: dict[str, int] = {}     # sinal da barra anterior, aguardando abertura
    cur_day = _broker_day(all_ts[0], cfg.day_rollover_utc_hour)
    engine.open_day(cur_day)
    gov.on_day_open()

    def close_trade(t: Trade, ts: pd.Timestamp, px: float, reason: str) -> None:
        t.exit_time, t.exit_price, t.reason = ts, px, reason
        t.pnl = _pnl_usd(t.symbol, t.side, t.entry_price, px, t.lots, cfg)
        engine.balance += t.pnl
        gov.register_close(t.symbol)
        open_pos.pop(t.symbol, None)

    for ts in all_ts:
        day = _broker_day(ts, cfg.day_rollover_utc_hour)
        if day != cur_day:
            engine.close_day()
            cur_day = day
            engine.open_day(cur_day)
            gov.on_day_open()

        rows = {s: d.loc[ts] for s, d in prepared.items() if ts in d.index}

        # 1) posicoes abertas: stop -> alvo -> tempo (nesta ordem, pessimista)
        for sym, t in list(open_pos.items()):
            r = rows.get(sym)
            if r is None:
                continue
            t.bars_held += 1
            hs, sl = _half_spread(sym), _slip(sym, cfg)
            # preco efetivo de saida visto pela corretora
            lo = r["low"] - hs if t.side > 0 else r["low"] + hs
            hi = r["high"] - hs if t.side > 0 else r["high"] + hs

            hit_stop = (lo <= t.stop) if t.side > 0 else (hi >= t.stop)
            hit_tgt = (hi >= t.target) if t.side > 0 else (lo <= t.target)

            if hit_stop:
                close_trade(t, ts, t.stop - sl * t.side, "stop")
            elif hit_tgt:
                close_trade(t, ts, t.target - sl * t.side, "alvo")
            elif t.bars_held >= params.max_bars:
                px = r["close"] - (hs + sl) * t.side
                close_trade(t, ts, px, "tempo")
            else:
                # breakeven so vale da PROXIMA barra em diante
                if not t.be_moved:
                    rdist = abs(t.entry_price - t.stop)
                    trig = t.entry_price + t.side * params.be_at_r * rdist
                    reached = (hi >= trig) if t.side > 0 else (lo <= trig)
                    if reached:
                        t.stop = t.entry_price
                        t.be_moved = True

        # 2) equity no PIOR ponto da barra -> motor de regras
        worst = engine.balance
        for sym, t in open_pos.items():
            r = rows.get(sym)
            if r is None:
                continue
            hs = _half_spread(sym)
            adverse = (r["low"] - hs) if t.side > 0 else (r["high"] + hs)
            worst += _pnl_usd(sym, t.side, t.entry_price, adverse, t.lots, cfg)
        breach = engine.mark(worst)
        res.equity_curve.append((ts, worst))
        if breach:
            for sym, t in list(open_pos.items()):
                r = rows.get(sym)
                if r is not None:
                    close_trade(t, ts, r["close"], f"violacao:{breach.value}")
            break

        # 3) trava dura do governor
        if gov.must_flatten(worst):
            for sym, t in list(open_pos.items()):
                r = rows.get(sym)
                if r is not None:
                    hs, sl = _half_spread(sym), _slip(sym, cfg)
                    close_trade(t, ts, r["close"] - (hs + sl) * t.side, "hard_stop_diario")
            gov.flattened_today = True

        # 4) abre o que ficou pendente da barra anterior
        for sym, side in list(pending.items()):
            r = rows.get(sym)
            pending.pop(sym, None)
            if r is None or side == 0:
                continue
            dec = gov.can_open(sym, worst)
            if not dec:
                continue
            hs, sl = _half_spread(sym), _slip(sym, cfg)
            entry = r["open"] + (hs + sl) * side          # paga o spread na entrada
            d = prepared[sym]
            try:
                i = d.index.get_loc(ts)
            except KeyError:
                continue
            stop_dist = stop_distance(d, int(i), side, params)
            if stop_dist <= 0:
                continue
            risk = gov.risk_usd(worst)
            lots = size_position(sym, entry, stop_dist, risk)
            if lots <= 0:
                continue
            t = Trade(
                symbol=sym, side=side, entry_time=ts, entry_price=entry,
                stop=entry - side * stop_dist,
                target=entry + side * stop_dist * params.rr,
                lots=lots, risk_usd=risk,
            )
            open_pos[sym] = t
            res.trades.append(t)
            gov.register_open(sym)

        # 5) sinais desta barra ficam pendentes para a proxima
        for sym, r in rows.items():
            s = int(r["signal"])
            if s != 0 and sym not in open_pos:
                pending[sym] = s

    if engine.status is not Status.FAILED:
        engine.close_day()
    return res
