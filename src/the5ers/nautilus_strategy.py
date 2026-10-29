"""
Adaptador NautilusTrader.

Por que Nautilus e nao os outros sete repos da lista: e o unico
asset-class-agnostic com FX de verdade, backtest orientado a eventos em
nanossegundos e paridade de codigo entre backtest e live. Os outros sao
cripto-only (Freqtrade, Jesse, Hummingbot, CCXT, Eliza), acoes + LLM
(AI Hedge Fund) ou pesquisa em RL (FinRL).

O que Nautilus NAO faz: falar com MetaTrader 5. Nao existe adaptador MT5.
Entao o desenho e:

    Nautilus  ->  pesquisa, backtest, validacao independente
    MT5       ->  execucao real na conta The5ers (ver live_mt5.py)

Os indicadores aqui sao calculados pelo MESMO codigo do backtest proprio
(strategy.py), de proposito: se eu usasse os indicadores nativos do
Nautilus, uma divergencia de resultado nao diria se o problema e a
estrategia ou a diferenca de implementacao.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

import pandas as pd

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Quantity
from nautilus_trader.trading.strategy import Strategy

from .risk import RiskGovernor, RiskLimits, size_position
from .rules import ProgramRules, RuleEngine
from .strategy import StratParams, add_indicators, generate_signals

__all__ = ["The5ersConfig", "The5ersStrategy"]


class The5ersConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId
    bar_type: BarType
    # Programa e limites viajam como primitivos: StrategyConfig e serializavel.
    initial_balance: float = 100_000.0
    profit_target: float = 10_000.0
    max_daily_loss_pct: float = 4.0
    max_total_loss: float = 8_000.0
    risk_per_trade_pct: float = 0.35
    atr_mult_stop: float = 1.5
    rr: float = 2.0
    warmup: int = 250


class The5ersStrategy(Strategy):
    """
    Pullback a favor da tendencia, com o motor de regras The5ers no caminho
    de CADA ordem. Nenhuma ordem e enviada sem passar pelo governor.
    """

    def __init__(self, config: The5ersConfig) -> None:
        super().__init__(config)
        self.instrument = None
        self._bars: deque[Bar] = deque(maxlen=max(600, config.warmup + 300))
        self._params = StratParams(atr_mult_stop=config.atr_mult_stop, rr=config.rr)
        self._engine = RuleEngine(ProgramRules(
            initial_balance=config.initial_balance,
            profit_target=config.profit_target,
            max_daily_loss_pct=config.max_daily_loss_pct,
            max_total_loss=config.max_total_loss,
        ))
        self._gov = RiskGovernor(self._engine, RiskLimits(
            risk_per_trade_pct=config.risk_per_trade_pct))
        self._day = None

    # ------------------------------------------------------------- ciclo

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"instrumento nao encontrado: {self.config.instrument_id}")
            self.stop()
            return
        self.request_bars(self.config.bar_type)
        self.subscribe_bars(self.config.bar_type)
        self._engine.open_day(self._today())
        self._gov.on_day_open()

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        self.close_all_positions(self.config.instrument_id)

    # ------------------------------------------------------------- dados

    def _today(self):
        return pd.Timestamp(self.clock.timestamp_ns(), unit="ns", tz="UTC").date()

    def _frame(self) -> pd.DataFrame:
        idx = [pd.Timestamp(b.ts_event, unit="ns", tz="UTC") for b in self._bars]
        return pd.DataFrame(
            {
                "open": [float(b.open) for b in self._bars],
                "high": [float(b.high) for b in self._bars],
                "low": [float(b.low) for b in self._bars],
                "close": [float(b.close) for b in self._bars],
            },
            index=pd.DatetimeIndex(idx),
        )

    def on_bar(self, bar: Bar) -> None:
        self._bars.append(bar)
        if len(self._bars) < self.config.warmup:
            return

        # virada de dia -> fecha o dia no motor de regras
        today = self._today()
        if self._day is None:
            self._day = today
        elif today != self._day:
            self._engine.close_day(self._equity())
            self._day = today
            self._engine.open_day(today, self._equity())
            self._gov.on_day_open()

        equity = self._equity()
        if self._engine.mark(equity):
            self.log.error(f"VIOLACAO {self._engine.breach.value} - parando")
            self.close_all_positions(self.config.instrument_id)
            self.stop()
            return

        if self._gov.must_flatten(equity):
            self.log.warning("trava dura do governor - zerando posicoes")
            self.close_all_positions(self.config.instrument_id)
            self._gov.flattened_today = True
            return

        if self.portfolio.is_net_long(self.config.instrument_id) or \
           self.portfolio.is_net_short(self.config.instrument_id):
            return  # ja posicionado: a saida e pela bracket

        df = add_indicators(self._frame(), self._params)
        sig = generate_signals(df, self._params)
        side_i = int(sig.iloc[-1])
        if side_i == 0:
            return

        sym = self.config.instrument_id.symbol.value.replace("/", "")[:6]
        dec = self._gov.can_open(sym, equity)
        if not dec:
            self.log.info(f"sinal vetado: {dec.reason}")
            return

        atr = float(df["atr"].iloc[-1])
        px = float(bar.close)
        if atr <= 0:
            return
        stop_dist = self._params.atr_mult_stop * atr
        lots = size_position(sym, px, stop_dist, self._gov.risk_usd(equity))
        if lots <= 0:
            return

        side = OrderSide.BUY if side_i > 0 else OrderSide.SELL
        qty = self.instrument.make_qty(Decimal(str(round(lots * 100_000))))
        entry = self.instrument.make_price(px)
        sl = self.instrument.make_price(px - side_i * stop_dist)
        tp = self.instrument.make_price(px + side_i * stop_dist * self._params.rr)

        order = self.order_factory.bracket(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=qty,
            sl_trigger_price=sl,
            tp_price=tp,
        )
        self.submit_order_list(order)
        self._gov.register_open(sym)
        self.log.info(f"{side.name} {lots} lotes @ {entry} SL={sl} TP={tp}")

    # ------------------------------------------------------------- estado

    def _equity(self) -> float:
        try:
            acct = self.portfolio.account(self.config.instrument_id.venue)
            if acct is not None:
                bal = acct.balance_total()
                if bal is not None:
                    return float(bal.as_double())
        except Exception:
            pass
        return self._engine.balance

    def on_position_closed(self, event) -> None:
        sym = self.config.instrument_id.symbol.value.replace("/", "")[:6]
        self._gov.register_close(sym)
        self._engine.balance = self._equity()
