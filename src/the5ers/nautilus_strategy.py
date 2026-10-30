"""
Adaptador NautilusTrader.

Por que Nautilus e nao os outros sete repos da lista: e o unico
asset-class-agnostic com FX de verdade, backtest orientado a eventos em
nanossegundos e paridade de codigo entre backtest e live. Os outros sao
cripto-only (Freqtrade, Jesse, Hummingbot, CCXT, Eliza), acoes + LLM
(AI Hedge Fund) ou pesquisa em RL (FinRL).

ATENCAO - ESTE ADAPTADOR NAO ESTA VALIDADO. NAO USE OS NUMEROS DELE.

Duas tentativas de caminho de execucao, as duas erradas:

  1. bracket (sl_trigger_price/tp_price): o motor REJEITA as ordens
     reduce-only em varios casos e a posicao fica SEM protecao - uma
     ficou aberta 16 meses e "ganhou" 8 192 USD.
  2. saida gerida na barra com close_all_positions(): e ordem A MERCADO.
     Quando a barra toca o stop, a posicao nao fecha NO stop, fecha no
     preco da barra seguinte. Em mercado reversivo, tocar o stop e voltar
     vira VITORIA - a taxa de acerto sobe para 55-72% e todo par "bate"
     os +10 000 do alvo. E artefato da premissa, nao resultado.

O certo e ordens STOP_MARKET e LIMIT reduce-only, descansando na venue,
submetidas DEPOIS do preenchimento da entrada. Nao esta feito.

A conclusao do repo NAO depende disto: a bancada de pesquisa
(research.py) avalia sinais direto sobre OHLC, varrendo stop e alvo barra
a barra, sem motor, sem ordens e sem estado de posicao. E de la que vem o
resultado de "sem vantagem", e ele e independente dos dois backtests.

O contraste vale como licao: a MESMA estrategia da -5 715 USD com saida
pessimista (backtest.py) e +10 000 com saida ingenua (aqui). A diferenca
entre "funciona" e "nao funciona" estava inteira na premissa de saida.

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
        # Stop/alvo geridos AQUI, nao por bracket. Motivo: se uma ordem do
        # bracket e rejeitada, a posicao fica sem protecao e a estrategia
        # trava esperando um on_position_closed que nunca vem - foi
        # exatamente isso que aconteceu (posicao aberta por 16 meses).
        # Gerir na barra e mais simples e espelha src/the5ers/backtest.py.
        self._stop: float | None = None
        self._target: float | None = None
        self._side: int = 0
        # Entre submeter a ordem e a posicao aparecer no portfolio existe
        # uma barra em que `is_flat` ainda e True. Sem esta flag a
        # reconciliacao lia isso como "fechou", zerava o estado e abria de
        # novo - empilhando posicao em netting e inventando lucro.
        self._awaiting_fill: bool = False

    # ------------------------------------------------------------- ciclo

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"instrumento nao encontrado: {self.config.instrument_id}")
            self.stop()
            return
        # Sem request_bars: em backtest as barras chegam pelo stream, e em
        # live a propria janela `_bars` faz o aquecimento (config.warmup).
        # A assinatura de request_bars muda entre versoes do Nautilus e nao
        # vale acoplar a estrategia a ela por um aquecimento que ja existe.
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

        sym = self.config.instrument_id.symbol.value.replace("/", "")[:6]
        flat = self.portfolio.is_flat(self.config.instrument_id)

        # Estado do governor vem do PORTFOLIO, nunca de contabilidade
        # paralela: assim nao existe o estado "travado" que impedia
        # qualquer entrada nova depois de uma ordem rejeitada.
        if not flat:
            self._awaiting_fill = False
        if flat and not self._awaiting_fill and sym in self._gov.open_symbols:
            self._gov.register_close(sym)
            self._stop = self._target = None
            self._side = 0

        # saida gerida na barra: stop antes do alvo (pessimista)
        if not flat and self._stop is not None:
            hi, lo = float(bar.high), float(bar.low)
            hit_stop = (lo <= self._stop) if self._side > 0 else (hi >= self._stop)
            hit_tgt = (hi >= self._target) if self._side > 0 else (lo <= self._target)
            if hit_stop or hit_tgt:
                self.close_all_positions(self.config.instrument_id)
                self._stop = self._target = None
                self._side = 0
            return

        if not flat:
            return

        df = add_indicators(self._frame(), self._params)
        sig = generate_signals(df, self._params)
        side_i = int(sig.iloc[-1])
        if side_i == 0:
            return

        dec = self._gov.can_open(sym, equity)
        if not dec:
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
        self.submit_order(self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=side,
            quantity=qty,
        ))
        self._awaiting_fill = True
        self._side = side_i
        self._stop = px - side_i * stop_dist
        self._target = px + side_i * stop_dist * self._params.rr
        self._gov.register_open(sym)

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
        # Atalho util, mas NAO e a fonte de verdade: on_bar reconcilia
        # contra o portfolio a cada barra, entao perder este evento nao
        # trava mais a estrategia.
        sym = self.config.instrument_id.symbol.value.replace("/", "")[:6]
        self._gov.register_close(sym)
        self._stop = self._target = None
        self._side = 0
        self._awaiting_fill = False
        self._engine.balance = self._equity()
