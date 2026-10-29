#!/usr/bin/env python3
"""
Reconfirma as regras do programa contra a API da The5ers e compara com
config/the5ers_100k.yaml.

Nao roda sozinho: o acesso a API e via conector MCP autenticado, que vive
no cliente, nao aqui. Este script existe para documentar EXATAMENTE quais
chamadas produziram o YAML, para que de para refazer a conferencia.

    the5ers_account(operation="list", contract_version="1.0")
      -> pega o account_ref da conta (label "meta-trader-5 . ...6821")

    the5ers_program(operation="rules", contract_version="1.0", account_ref=...)
      -> profitTarget, maxDailyLoss, maxTotalLoss

    the5ers_program(operation="journey", contract_version="1.0", account_ref=...)
      -> etapa atual, fase, proxima etapa

    the5ers_consistency(operation="list", contract_version="1.0", account_ref=...)
      -> regras de consistencia e seus limiares

Valores lidos em 2026-10-29 e gravados no YAML:
    programa          $100K High Stakes 10%
    profitTarget      10000  currency
    maxDailyLoss          4  percent
    maxTotalLoss       8000  currency
    profitable-days       3  days   (currentValue 0 = AMBIGUO, nao e "zero")
    etapa             1 de 2 (evaluation); proxima: $100K High Stakes - 2 (5000)
    SEM regra de expiracao e SEM minimo de dias de negociacao configurados.
"""
import pathlib, sys

CFG = pathlib.Path(__file__).resolve().parents[1] / "config" / "the5ers_100k.yaml"

print(__doc__)
print(f"\nconfig atual em: {CFG}")
if CFG.exists():
    print("-" * 60)
    print(CFG.read_text())
else:
    print("!! config nao encontrado")
    sys.exit(1)
