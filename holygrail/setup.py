"""
O setup "Holy Grail" de Linda Raschke e Larry Connors (livro Street Smarts).

As regras, como publicadas:

  1. ADX(14) acima de 30 - a tendencia precisa estar FORTE, nao so existir.
  2. Direcao pela DI: +DI > -DI so compra; -DI > +DI so vende.
  3. Espera o preco RECUAR ate a EMA de 20 periodos (o "valor").
  4. Entrada no rompimento da extremidade da barra de recuo - compra acima
     da maxima, venda abaixo da minima. E ordem parada, nao a mercado.
  5. Stop na outra ponta do recuo (minima do pullback na compra).
  6. Alvo no topo/fundo anterior - a ultima extremidade antes do recuo.

Nao e um sinal de uma barra so: e uma SEQUENCIA (tendencia forte -> recuo
-> retomada). Por isso esta implementado como maquina de estados e nao
como mascara booleana. Uma mascara nao consegue expressar "arma aqui,
dispara depois, expira se nao disparar".

Cuidado com look-ahead: tudo que arma o setup usa dados ATE a barra i; o
disparo so pode ocorrer em i+1 ou depois, e no PRECO do gatilho.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = ["HGParams", "Setup", "find_setups"]


@dataclass(frozen=True)
class HGParams:
    adx_len: int = 14
    adx_min: float = 30.0
    ema_len: int = 20
    atr_len: int = 14
    max_wait: int = 5          # barras para o gatilho acontecer apos o recuo
    swing_lookback: int = 20   # janela para achar o topo/fundo anterior
    min_rr: float = 1.0        # descarta setup cujo alvo nem paga 1 R
    max_rr: float | None = None  # trava o alvo em N R, se quiser
    require_di: bool = True    # direcao pela DI; False usa preco vs EMA
    stop_buffer_atr: float = 0.10   # folga no stop, em ATR


@dataclass
class Setup:
    """Um setup disparado: ja virou trade."""
    i_entry: int
    side: int            # +1 compra, -1 venda
    entry: float         # preco do gatilho (ordem parada)
    stop: float
    target: float
    i_armed: int         # barra do recuo que armou

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def rr(self) -> float:
        r = self.risk
        return abs(self.target - self.entry) / r if r > 0 else 0.0


def find_setups(df: pd.DataFrame, p: HGParams | None = None) -> list[Setup]:
    """
    Varre as barras e devolve os setups que DISPARARAM.

    `df` precisa ter as colunas de indicators.add_indicators.
    """
    p = p or HGParams()
    hi = df["high"].values
    lo = df["low"].values
    adx = df["adx"].values
    pdi = df["plus_di"].values
    mdi = df["minus_di"].values
    ema = df["ema"].values
    atr = df["atr"].values
    n = len(df)

    out: list[Setup] = []
    armed: dict | None = None

    for i in range(max(p.adx_len, p.ema_len, p.swing_lookback) + 1, n):
        # ---- 1) o setup armado dispara? -------------------------------
        if armed is not None:
            if i - armed["i"] > p.max_wait:
                armed = None                      # expirou sem romper
            else:
                side = armed["side"]
                trig = armed["trigger"]
                hit = (hi[i] >= trig) if side > 0 else (lo[i] <= trig)
                if hit:
                    buf = p.stop_buffer_atr * atr[i]
                    stop = armed["pb_low"] - buf if side > 0 else armed["pb_high"] + buf
                    tgt = armed["swing"]
                    risk = abs(trig - stop)
                    if risk > 0:
                        rr = abs(tgt - trig) / risk
                        if p.max_rr is not None and rr > p.max_rr:
                            tgt = trig + side * p.max_rr * risk
                            rr = p.max_rr
                        if rr >= p.min_rr:
                            out.append(Setup(i_entry=i, side=side, entry=trig,
                                             stop=stop, target=tgt,
                                             i_armed=armed["i"]))
                    armed = None
                    continue
                # ainda armado: o recuo pode se aprofundar
                armed["pb_low"] = min(armed["pb_low"], lo[i])
                armed["pb_high"] = max(armed["pb_high"], hi[i])
                armed["trigger"] = max(armed["trigger"], hi[i]) if side > 0 \
                    else min(armed["trigger"], lo[i])

        # ---- 2) arma um setup novo ------------------------------------
        if not np.isfinite(adx[i]) or adx[i] <= p.adx_min:
            continue
        if p.require_di:
            if not (np.isfinite(pdi[i]) and np.isfinite(mdi[i])):
                continue
            side = 1 if pdi[i] > mdi[i] else -1
        else:
            side = 1 if df["close"].values[i] > ema[i] else -1

        # recuo: a barra TOCOU a EMA do lado contrario a tendencia
        touched = (lo[i] <= ema[i]) if side > 0 else (hi[i] >= ema[i])
        if not touched:
            continue

        # topo/fundo anterior = extremo da janela ANTES desta barra
        j0 = max(0, i - p.swing_lookback)
        swing = float(hi[j0:i].max()) if side > 0 else float(lo[j0:i].min())

        # o alvo tem de estar a frente do preco, senao o setup nao faz sentido
        if (side > 0 and swing <= hi[i]) or (side < 0 and swing >= lo[i]):
            continue

        armed = {"i": i, "side": side, "pb_low": float(lo[i]),
                 "pb_high": float(hi[i]), "swing": swing,
                 "trigger": float(hi[i]) if side > 0 else float(lo[i])}

    return out
