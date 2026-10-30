# Holy Grail (Raschke) — implementação e teste honesto

Implementação do setup **"Holy Grail"** de Linda Raschke e Larry Connors
(livro *Street Smarts*), testado em majors de forex para avaliar se serve a um
desafio de mesa proprietária The5ers 100K.

---

## 1. O setup, como publicado

| Passo | Regra |
|---|---|
| 1 | **ADX(14) acima de 30** — a tendência precisa estar *forte*, não apenas existir |
| 2 | **Direção pela DI** — `+DI > -DI` só compra; `-DI > +DI` só vende |
| 3 | **Espera o recuo** até a **EMA de 20** períodos (o "valor") |
| 4 | **Entrada no rompimento** da extremidade da barra de recuo (ordem parada) |
| 5 | **Stop** na outra ponta do recuo |
| 6 | **Alvo** no topo/fundo anterior — a última extremidade antes do recuo |

Não é sinal de uma barra: é uma **sequência** (tendência forte → recuo →
retomada). Por isso está implementado como máquina de estados (`setup.py`), não
como máscara booleana — uma máscara não expressa "arma aqui, dispara depois,
expira se não disparar".

O ADX é calculado pela **suavização de Wilder** (α = 1/n), não SMA nem EMA
comum. Usar a suavização errada muda o nível do indicador e o filtro de 30 passa
a significar outra coisa.

---

## 2. Resultado por tempo gráfico

Dados: **5 majors, 17 meses, H1 da Dukascopy** (bid real), reamostrado.
Custos: spread do par + 0,7 pip de comissão + 0,3 pip de slippage.

| TF | setups | acerto | avg R | aleatório | vantagem | t | p | soma R |
|---|---|---|---|---|---|---|---|---|
| H1 | 745 | 29,0% | **−0,210** | −0,192 | −0,018 | −3,38 | 0,0007 | −156,6 |
| **H4** | **186** | **30,1%** | **−0,044** | −0,171 | **+0,127** | −0,34 | 0,73 | −8,3 |
| D1 | 23 | 13,0% | −0,658 | −0,142 | −0,515 | −3,45 | 0,0006 | −15,1 |

Leitura:

- **H1 é hostil ao setup** — perde e perde *mais que entradas aleatórias*. Faz
  sentido: Raschke desenhou isto para gráfico diário em futuros, e H1 de forex é
  mais reversivo que tendencial.
- **H4 é o habitat** — quase empata e **bate o controle aleatório em +0,127 R**.
- **D1 não dá para julgar** — 17 meses rendem só 23 setups. Não é "ruim", é
  **insuficiente**.

### Por que o H4 quase fecha

| Saída | n | % | avg R |
|---|---|---|---|
| stop | 130 | 69,9% | −1,091 |
| alvo | 56 | 30,1% | +2,386 |

Acerto de equilíbrio = 1,091 / (2,386 + 1,091) = **31,4%**. Realizado: **30,1%**.
Falta **1,3 ponto**.

E repare na perda média: **−1,091 R**, não −1,0. Esses **0,09 R são o pedágio**
(spread + comissão + slippage). **No bruto o setup empata; o custo derruba.**

---

## 3. O ajuste em H4, com disciplina

27 combinações de `ADX mínimo` × `RR mínimo` × `alvo travado`, escolhidas
**só nos 60% iniciais**, teste olhado **uma vez**:

Escolhido no treino: **ADX > 30, RR mínimo 2,0, alvo travado em 2 R**.

| Fora da amostra | |
|---|---|
| setups | 53 |
| acerto | **41,5%** |
| avg R | **+0,1199** |
| aleatório | −0,1041 |
| vantagem | **+0,2240 R** |
| t | 0,59 — **p bruto 0,55** |
| **p após Bonferroni (27 testes)** | **1,0000** |

Positivo, mas **indistinguível de zero**. Em 53 trades, +0,12 R é ruído.

---

## 4. O achado que importa de verdade

Se o teste não decide, a pergunta certa é: **quanta amostra decidiria?**

Com a frequência real do setup (**78 trades/ano** nos 5 pares, H4) e o desvio
medido dos R-múltiplos (**1,437**):

| Para detectar vantagem de | trades necessários | anos de dado |
|---|---|---|
| +0,05 R | 6 473 | **83,3** |
| +0,10 R | 1 618 | **20,8** |
| **+0,12 R** | **1 126** | **14,5** |
| +0,20 R | 405 | 5,2 |
| +0,30 R | 180 | 2,3 |

**Tenho 17 meses. Para decidir sobre +0,12 R faltam ~13 anos de dado.**

Isso reenquadra tudo. A conclusão não é "o Holy Grail não funciona". É:

> **Este setup opera raro demais, com variância alta demais, para ser validado
> ou refutado em 17 meses. Qualquer backtest de 1–2 anos deste setup — positivo
> ou negativo — está mostrando ruído.**

Inclusive o vídeo. Inclusive este repositório.

---

## 5. O que isso significa para a conta de 100K

Três fatos que não dependem de opinião:

1. **Você não consegue validar este setup antes de arriscar a conta.** Precisaria
   de ~15 anos de dado; no H4 ele dá ~78 trades por ano nos 5 pares juntos.
2. **No melhor caso medido, ele empata no bruto.** A vantagem, se existe, é
   menor que o pedágio. Em conta com spread pior que o modelado, piora.
3. **O "11.000 vezes" do título não tem fonte primária** — procurei e não achei.
   E um retorno desse tamanho exige alavancagem incompatível com perder no
   máximo 4% num dia e 8% no total. O setup pode ser bom; o número é marketing.

O que eu **não** posso dizer: que ele vai reprovar. O teste não tem poder para
isso. Essa é a resposta honesta, e ela é diferente de "não funciona".

---

## 6. Estrutura

```
holygrail/
  indicators.py    ADX/DI por Wilder, EMA, ATR
  setup.py         maquina de estados do Holy Grail
  evaluate.py      R-multiplos com custo + controle aleatorio
  resample.py      H1 -> H4 / D1 (dia de forex fecha 21:00 UTC)
run.py             roda o setup nos majors
compare_tf.py      compara H1 / H4 / D1
tune_h4.py         ajuste com treino/teste e Bonferroni
power.py           quanta amostra faltou
tests/             19 testes
```

### Premissas, todas contra o resultado

- entrada no preço do gatilho **mais slippage** (ordem parada escorrega, nunca
  a favor);
- dentro da barra, **stop ganha do alvo** — H1/H4 não dizem a ordem dos eventos;
- spread na entrada **e** na saída, mais comissão;
- o controle aleatório usa **o mesmo lado e as mesmas distâncias**, sorteando só
  a barra de entrada — então ele isola a capacidade *preditiva*, não a estrutura
  do trade.

---

## 7. Uso

```bash
pip install -r requirements.txt
python run.py            # Holy Grail em H1, por par
python compare_tf.py     # H1 vs H4 vs D1
python tune_h4.py        # ajuste com disciplina treino/teste
python power.py          # analise de poder
python -m pytest tests/ -q
```

Os dados (`data/h1/*.csv`, candles H1 da Dukascopy) não estão versionados.

---

## 8. Se for levar adiante

A ordem que faz sentido, do mais barato ao mais caro:

1. **Conseguir 5–10 anos de H4** dos majors. Sem isso, nenhum teste decide, e
   todo resultado daqui é provisório.
2. **Atacar o pedágio.** A vantagem, se existe, é da ordem do custo. Stop mais
   largo dilui o custo em R; par com spread menor idem.
3. **Só então** pensar em risco e dimensionamento para a mesa — antes disso é
   dimensionar algo que não se sabe se tem vantagem.
