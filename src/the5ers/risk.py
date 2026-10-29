"""
Camada de risco: dimensionamento de posicao e travas operacionais.

Separada de rules.py de proposito. rules.py diz onde a conta MORRE;
este modulo mantem distancia desse ponto. Os limites aqui sao sempre
mais apertados que os contratuais - a margem e o produto.

Regra de ouro do desafio: a maioria das contas nao quebra por estrategia
ruim, quebra por violacao de regra. Entao o governor tem poder de veto
sobre qualquer sinal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .rules import Breach, RuleEngine

__all__ = ["RiskLimits", "Decision", "RiskGovernor", "pip_size", "pip_value_usd", "size_position"]


# --------------------------------------------------------------- FX helpers

def pip_size(symbol: str) -> float:
    """Tamanho do pip. Pares com JPY usam 0.01, o resto 0.0001."""
    return 0.01 if "JPY" in symbol.upper() else 0.0001


def pip_value_usd(symbol: str, price: float, lots: float = 1.0) -> float:
    """
    Valor de 1 pip em USD para `lots` lotes padrao (100 000 unidades).

    XXX/USD  -> pip vale 10 USD por lote, independente do preco.
    USD/XXX  -> pip vale (pip / preco) * 100 000 por lote.
    Cruzados sem USD nao sao cobertos; o backtest so opera majors com USD.
    """
    sym = symbol.upper().replace("/", "").replace("=X", "")
    base, quote = sym[:3], sym[3:6]
    units = 100_000.0 * lots
    p = pip_size(symbol)
    if quote == "USD":
        return p * units
    if base == "USD":
        if price <= 0:
            raise ValueError(f"preco invalido para {symbol}: {price}")
        return (p / price) * units
    raise ValueError(f"par sem USD nao suportado: {symbol}")


def size_position(symbol: str, price: float, stop_distance: float, risk_usd: float,
                  min_lots: float = 0.01, max_lots: float = 50.0) -> float:
    """
    Lotes tais que, batendo o stop, a perda seja ~`risk_usd`.

    `stop_distance` em PRECO (nao em pips). Retorna 0.0 se o stop for
    tao apertado que nem o lote minimo cabe no risco - preferimos nao
    operar a operar grande demais.
    """
    if stop_distance <= 0 or risk_usd <= 0:
        return 0.0
    pips = stop_distance / pip_size(symbol)
    if pips <= 0:
        return 0.0
    value_per_pip_one_lot = pip_value_usd(symbol, price, 1.0)
    loss_one_lot = pips * value_per_pip_one_lot
    if loss_one_lot <= 0:
        return 0.0
    lots = risk_usd / loss_one_lot
    lots = round(lots, 2)
    if lots < min_lots:
        return 0.0
    return min(lots, max_lots)


# --------------------------------------------------------------- governor

@dataclass(frozen=True)
class RiskLimits:
    """
    Travas operacionais. Todas MAIS apertadas que as contratuais.

    O limite diario contratual e 4 %. Paramos de abrir em 1.5 % e
    zeramos tudo em 2.5 %, deixando 1.5 % de folga para gap/slippage
    - que e exatamente o cenario em que contas morrem no fim de semana.
    """

    risk_per_trade_pct: float = 0.35      # % da equity por trade
    daily_soft_stop_pct: float = 1.50     # para de ABRIR
    daily_hard_stop_pct: float = 2.50     # ZERA tudo
    max_concurrent: int = 2
    max_per_currency: int = 1             # nao dobra exposicao no mesmo CCY
    floor_buffer_pct: float = 1.00        # folga extra acima do piso de perda total
    max_trades_per_day: int = 6
    # Quanto o alvo pode encolher o risco: ao chegar perto do alvo,
    # reduzir risco preserva o que ja foi feito.
    derisk_at_target_pct: float = 80.0    # a partir de 80 % do alvo
    derisk_factor: float = 0.5


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    lots: float = 0.0

    def __bool__(self) -> bool:
        return self.allowed


@dataclass
class RiskGovernor:
    """Veta sinais. O backtest e o live devem consultar isto antes de qualquer ordem."""

    engine: RuleEngine
    limits: RiskLimits = field(default_factory=RiskLimits)
    trades_today: int = field(default=0, init=False)
    open_symbols: list[str] = field(default_factory=list, init=False)
    flattened_today: bool = field(default=False, init=False)

    # ------------------------------------------------------- dia

    def on_day_open(self) -> None:
        self.trades_today = 0
        self.flattened_today = False

    # ------------------------------------------------------- limiares do dia

    @property
    def daily_soft_floor(self) -> float:
        d = self.engine.day_start_balance
        return d - d * self.limits.daily_soft_stop_pct / 100.0

    @property
    def daily_hard_floor(self) -> float:
        d = self.engine.day_start_balance
        return d - d * self.limits.daily_hard_stop_pct / 100.0

    @property
    def guarded_total_floor(self) -> float:
        """Piso de perda total + folga. Nunca encostamos no piso real."""
        buf = self.engine.rules.initial_balance * self.limits.floor_buffer_pct / 100.0
        return self.engine.total_loss_floor + buf

    def must_flatten(self, equity: float) -> bool:
        """True = fechar tudo agora."""
        return equity <= self.daily_hard_floor or equity <= self.guarded_total_floor

    # ------------------------------------------------------- risco por trade

    def risk_usd(self, equity: float) -> float:
        r = equity * self.limits.risk_per_trade_pct / 100.0
        # perto do alvo, corta risco pela metade
        progress = (equity - self.engine.rules.initial_balance) / self.engine.rules.profit_target
        if progress * 100.0 >= self.limits.derisk_at_target_pct:
            r *= self.limits.derisk_factor
        # nunca arriscar mais do que a folga ate o piso do dia
        room_day = max(0.0, equity - self.daily_hard_floor)
        room_tot = max(0.0, equity - self.guarded_total_floor)
        return max(0.0, min(r, room_day, room_tot))

    # ------------------------------------------------------- veto

    def can_open(self, symbol: str, equity: float) -> Decision:
        if self.engine.breach:
            return Decision(False, f"conta ja violada ({self.engine.breach.value})")
        if self.engine.target_hit:
            return Decision(False, "alvo atingido - parar de arriscar")
        if self.flattened_today:
            return Decision(False, "hard stop diario ja acionado hoje")
        if equity <= self.daily_soft_floor:
            return Decision(False, "soft stop diario atingido")
        if equity <= self.guarded_total_floor:
            return Decision(False, "perto do piso de perda total")
        if self.trades_today >= self.limits.max_trades_per_day:
            return Decision(False, "limite de trades do dia")
        if len(self.open_symbols) >= self.limits.max_concurrent:
            return Decision(False, "limite de posicoes simultaneas")
        if symbol in self.open_symbols:
            return Decision(False, "ja posicionado neste par")
        if self._currency_clash(symbol):
            return Decision(False, "exposicao duplicada na mesma moeda")
        return Decision(True, "ok")

    def _currency_clash(self, symbol: str) -> bool:
        def ccys(s: str) -> set[str]:
            t = s.upper().replace("/", "").replace("=X", "")
            return {t[:3], t[3:6]}
        new = ccys(symbol)
        count = sum(1 for s in self.open_symbols if ccys(s) & new)
        return count >= self.limits.max_per_currency

    # ------------------------------------------------------- bookkeeping

    def register_open(self, symbol: str) -> None:
        self.open_symbols.append(symbol)
        self.trades_today += 1

    def register_close(self, symbol: str) -> None:
        if symbol in self.open_symbols:
            self.open_symbols.remove(symbol)
