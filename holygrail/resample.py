"""
Reamostragem H1 -> H4 / D1.

O Holy Grail foi publicado para grafico DIARIO em futuros. Testar so em H1
de forex e testa-lo fora do habitat. Aqui o mesmo dado vira H4 e D1 para
que o setup seja julgado no tempo grafico em que foi desenhado.

O dia de forex fecha as 21:00 UTC (fechamento de NY), nao a meia-noite -
usar 'D' puro corta o dia no meio da sessao asiatica e inventa barras.
"""

from __future__ import annotations

import pandas as pd

__all__ = ["resample"]

_AGG = {"open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"}


def resample(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    if tf.upper() in ("H1", "1H"):
        return df.copy()
    if tf.upper() in ("H4", "4H"):
        out = df.resample("4h").agg(_AGG)
    elif tf.upper() in ("D1", "1D", "D"):
        # offset de 21h: a barra diaria vai de 21:00 a 21:00 UTC
        out = df.resample("24h", offset="21h").agg(_AGG)
    else:
        raise ValueError(f"timeframe desconhecido: {tf}")
    return out.dropna(subset=["open", "high", "low", "close"])
