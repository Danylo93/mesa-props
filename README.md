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

## 5. Teste prático: aprovaria? em quanto tempo?

Backtest de **carteira** — 5 pares, uma conta só, risco compartilhado, as regras
reais da The5ers no circuito (alvo 10 000, perda diária 4%, perda total 8 000
**arrastando** pelo fechamento, 3 dias lucrativos).

### O que aconteceu nos 17 meses de dado real

| Config | risco | status | lucro | trades | dias lucr. | travou em |
|---|---|---|---|---|---|---|
| Livro | 0,35% | não aprovou | **−6 276** | 45 | 7 | 2025-11-17 |
| Livro | 1,00% | não aprovou | −4 954 | 20 | 5 | 2025-07-08 |
| Ajustada | 0,35% | não aprovou | **−1 037** | 102 | 26 | — |
| Ajustada | 1,00% | não aprovou | +701 | 32 | 9 | 2025-11-21 |

Nenhuma chega perto de +10 000. E surgiu um terceiro desfecho que eu não
esperava: **"travou"**. A conta não viola regra nenhuma — o piso que arrasta,
somado à folga do governor, simplesmente a deixa **sem espaço para arriscar**.
Ela não quebra; ela para de poder operar. Na config do livro isso acontece entre
o 2º e o 7º mês.

### Em quanto tempo? (Monte Carlo, 8 000 caminhos, horizonte de 5 anos)

Um backtest dá **um** caminho. "Quanto tempo leva" é pergunta de distribuição.

**Config ajustada** (a mais favorável):

| risco | aprovou | **travou** | quebrou | mediana | p25–p75 |
|---|---|---|---|---|---|
| 0,25% | 8,9% | 66,3% | **0,0%** | 38,6 meses | 27–48 |
| 0,35% | 16,2% | 80,4% | **0,0%** | 25,6 meses | 18–36 |
| 0,50% | 19,9% | 80,1% | **0,0%** | 13,6 meses | 9–20 |
| 1,00% | 22,8% | 77,2% | **0,0%** | **3,8 meses** | 2–6 |

Três coisas saltam:

**1. `quebrou` é 0,0% em toda linha.** A camada de risco nunca deixa violar
regra. Isso é o sistema funcionando: você não perde a conta por infração, você
perde por travamento.

**2. Mais risco não melhora as chances — muda a velocidade.** De 0,25% para
1,00%, a aprovação vai de 8,9% para 22,8% enquanto o tempo cai de 38 para 4
meses. É exatamente o que se espera de vantagem ≈ zero: o resultado é quase
cara-ou-coroa, e o risco só define quão rápido a moeda cai.

**3. O desfecho dominante é travar (66–80%), não aprovar.**

### A régua que calibra tudo

E se a vantagem existisse? Mesma frequência, mesma variância, risco 0,5%:

| avg R | aprovou | mediana |
|---|---|---|
| **0,00** (cara-ou-coroa) | **25,1%** | 13,8 meses |
| +0,05 | 38,7% | 13,4 meses |
| +0,10 | 54,8% | 13,3 meses |
| +0,20 | 81,5% | 11,5 meses |
| +0,30 | 95,4% | 9,2 meses |

Duas leituras que mudam como se olha para qualquer estratégia de mesa:

> **Vantagem não te faz chegar mais rápido — te faz chegar.** A mediana mal se
> move (13,8 → 9,2 meses), mas a probabilidade salta de 25% para 95%. O tempo é
> ditado pela frequência e pelo risco; a vantagem decide *se* você chega.

> **25% é o piso da sorte.** Mesmo sem vantagem nenhuma, 1 em cada 4 caminhos
> aprova — a variância sozinha carrega a conta até +10% antes do piso alcançá-la.
> Logo, **qualquer coisa abaixo de ~25% de aprovação é pior que jogar moeda.**
> O Holy Grail mediu 8,9% a 22,8%. Está no piso da sorte ou abaixo dele.

### Resposta direta

**Não aprova de forma confiável.** No melhor cenário medido (config ajustada,
1% de risco — risco alto), são **22,8% de chance em ~4 meses**, contra 77% de
travar. Nos 17 meses de dado real, nenhuma configuração passou de +701 USD.

E a pergunta "em quanto tempo" é, em si, mal formulada aqui: o desfecho
dominante não é *aprovar mais tarde*, é **não aprovar**.

---

## 6. O que isso significa para a conta de 100K

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

## 7. Estrutura

```
holygrail/
  indicators.py    ADX/DI por Wilder, EMA, ATR
  setup.py         maquina de estados do Holy Grail
  evaluate.py      R-multiplos com custo + controle aleatorio
  resample.py      H1 -> H4 / D1 (dia de forex fecha 21:00 UTC)
  the5ers.py       regras da conta 100K + dimensionamento
run.py             roda o setup nos majors
compare_tf.py      compara H1 / H4 / D1
tune_h4.py         ajuste com treino/teste e Bonferroni
power.py           quanta amostra faltou
simulate.py        backtest de CARTEIRA com as regras da mesa
tempo_aprovacao.py Monte Carlo: aprova? em quanto tempo?
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

## 8. Uso

```bash
pip install -r requirements.txt
python run.py            # Holy Grail em H1, por par
python compare_tf.py     # H1 vs H4 vs D1
python tune_h4.py        # ajuste com disciplina treino/teste
python power.py          # analise de poder
python simulate.py       # carteira com as regras da mesa
python simulate.py --tuned
python tempo_aprovacao.py   # aprova? em quanto tempo?
python -m pytest tests/ -q
```

Os dados (`data/h1/*.csv`, candles H1 da Dukascopy) não estão versionados.

---

## 9. Se for levar adiante

A ordem que faz sentido, do mais barato ao mais caro:

1. **Conseguir 5–10 anos de H4** dos majors. Sem isso, nenhum teste decide, e
   todo resultado daqui é provisório.
2. **Atacar o pedágio.** A vantagem, se existe, é da ordem do custo. Stop mais
   largo dilui o custo em R; par com spread menor idem.
3. **Só então** pensar em risco e dimensionamento para a mesa — antes disso é
   dimensionar algo que não se sabe se tem vantagem.
