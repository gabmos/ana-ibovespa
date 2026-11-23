# Previsão do IBOVESPA

Aqui está como o projeto funciona: como rodar, de onde vêm os dados, como o modelo prevê, o
que fica salvo, como é testado e quanto dá para confiar. Espero conseguir te ajudar :)

- [Previsão do IBOVESPA](#previsão-do-ibovespa)
  - [1. O que ele prevê](#1-o-que-ele-prevê)
  - [2. Como rodar](#2-como-rodar)
  - [3. Como ler o resultado](#3-como-ler-o-resultado)
    - [Gráfico](#gráfico)
    - [Texto](#texto)
  - [4. De onde vêm os dados](#4-de-onde-vêm-os-dados)
  - [5. Como o modelo prevê](#5-como-o-modelo-prevê)
    - [Previsão das 10h](#previsão-das-10h)
    - [Véspera e das 11h em diante](#véspera-e-das-11h-em-diante)
    - [Faixa e chance de alta](#faixa-e-chance-de-alta)
    - [Outros momentos](#outros-momentos)
    - [O que não entra](#o-que-não-entra)
  - [6. O que fica salvo](#6-o-que-fica-salvo)
  - [7. Como é testado](#7-como-é-testado)
    - [Qualidade da previsão](#qualidade-da-previsão)
    - [Funcionamento do programa](#funcionamento-do-programa)
  - [8. Quanto dá para confiar](#8-quanto-dá-para-confiar)
  - [9. Análise rápida](#9-análise-rápida)
  - [10. Arquivos do projeto](#10-arquivos-do-projeto)
  - [11. Como modificar](#11-como-modificar)
  - [12. Dúvidas comuns](#12-dúvidas-comuns)

---

## 1. O que ele prevê

- **Início do dia** (11h)
- **Final do dia** (fechamento)
- **Início do dia de amanhã** (11h do próximo pregão)
- **Uma hora de hoje**, se você pedir

Cada previsão traz um número e uma faixa provável, por exemplo: "164.372 pontos, com faixa de 80%
entre 163.734 e 164.965". Dê mais atenção à faixa do que ao número.

---

## 2. Como rodar

Na pasta do projeto, no Terminal:

```bash
.venv/bin/python -m ibov
```

Ele mostra o resultado em texto e abre o gráfico no navegador.

| Para... | Comando |
|---|---|
| Ver a previsão de hoje | `.venv/bin/python -m ibov` |
| Incluir a previsão para as 16h20 de hoje | `.venv/bin/python -m ibov --hora 16:20` |
| Ver um pregão passado | `.venv/bin/python -m ibov --dia 2026-11-19` |
| Ver um pregão passado em certa hora | `.venv/bin/python -m ibov --dia 2026-11-19 --hora 15h30` |
| Ver a previsão feita às 13h | `.venv/bin/python -m ibov --feita-as 13h` |
| Ver a previsão feita na véspera, às 20h | `.venv/bin/python -m ibov --feita-as vespera` |
| Usar os dados já salvos, sem baixar | `.venv/bin/python -m ibov --sem-download` |
| Não abrir o navegador | `.venv/bin/python -m ibov --nao-abrir` |

- **`--hora`**: o momento que você quer prever.
- **`--feita-as`**: o momento em que a previsão foi feita.

A hora pode ser escrita como `13:30`, `13h30`, `13h` ou `13`.

**Primeira vez em um computador** (precisa do Python 3.12):

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt matplotlib
```

---

## 3. Como ler o resultado

### Gráfico

Há um cartão para cada momento, com a previsão, a variação, a faixa e, se o momento já passou, o
valor real. No gráfico:

| Elemento | Significado |
|---|---|
| Linha escura | Preço real |
| Ponto azul | Previsão |
| Ponto laranja | Previsão da hora que você pediu |
| Barra clara | Faixa provável |
| Pontilhado azul | Caminho do preço atual até as previsões |
| Pontilhado cinza | Fechamento anterior |

- **Momento que já passou:** mostra a previsão das 10h e o valor real.
- **Momento que ainda vem:** mostra a previsão mais recente.

Em **Detalhes**, no fim da página, ficam o histórico e a qualidade das previsões.

### Texto

Traz as mesmas previsões, a evolução ao longo do dia, o erro histórico e a origem de cada número.
Depois do fechamento, inclui também o resultado real.

---

## 4. De onde vêm os dados

Todos os preços vêm do **Yahoo Finance**, baixados pelo `ibov/dados.py`.

| Frequência | Período | Uso |
|---|---|---|
| Diária | Desde 2010 | Fechamentos |
| Horária | Desde dezembro de 2023 | Base de aprendizado do modelo |
| 5 minutos | Cerca de 60 dias | Só para o gráfico e para conferir o valor real |

| Ativo | Código | Usado no modelo? |
|---|---|---|
| IBOVESPA | `^BVSP` | Sim |
| EWZ | `EWZ` | Sim |
| Dólar/real | `BRL=X` | Sim |
| Vale (ADR) | `VALE` | Sim |
| Petrobras e Itaú (ADRs) | `PBR`, `ITUB` | Não |
| S&P 500 e futuro | `^GSPC`, `ES=F` | Não |
| Petróleo Brent | `BZ=F` | Não |
| Índice do dólar (DXY) | `DX-Y.NYB` | Não |
| Juros americanos de 10 anos | `^TNX` | Não |
| Japão, Hong Kong e Europa | `^N225`, `^HSI`, `^STOXX50E` | Não |
| Emergentes | `EEM` | Não |

Os ativos marcados com "Não" são baixados e ficam disponíveis para novos testes.

**Limitações do Yahoo:**

- **Atraso de cerca de 15 minutos.** A previsão das 13h só aparece depois das 13h16.
- **A abertura das 10h repete o fechamento anterior** em cerca de 98% dos dias. Por isso o início do
  dia é às 11h.
- **Os preços do IBOVESPA param às 17h.** Quando o pregão fecha às 18h (fora do horário de verão dos
  EUA), só há o fechamento oficial para esse último trecho.

---

## 5. Como o modelo prevê

O código está em `ibov/modelo.py`. A previsão parte do último preço conhecido e estima quanto o
índice ainda vai andar.

### Previsão das 10h

Usa três informações, medidas desde o último fechamento da B3:

1. variação do EWZ, que é a que mais pesa;
2. variação do dólar;
3. variação da Vale em Nova York.

Exemplo de 23/11/2026: o EWZ caiu cerca de 1,7%, o dólar subiu 0,7% e a Vale caiu 0,9%. O modelo
previu queda de 0,82% e fechamento em **165.014** pontos.

O peso de cada informação é calculado com os pregões anteriores, por uma **regressão Ridge**. Ela
procura os pesos que dão menos erro e evita que poucos dias atípicos distorçam o resultado.

### Véspera e das 11h em diante

A previsão é o **último preço conhecido**. Centenas de modelos foram testados e nenhum errou menos
de forma consistente. O código dessa busca não está nesta pasta.

Por isso o final do dia e amanhã podem mostrar o mesmo número. Isso significa "sem sinal de alta ou
de queda", e não "vai ficar parado".

### Faixa e chance de alta

As duas usam os **120 erros mais recentes** do modelo, em dias que ele não usou para aprender:

- **Faixa de 80%:** descarta os 10% de erros mais extremos de cada lado.
- **Chance de alta:** a proporção desses erros que deixaria o fechamento acima do anterior.

### Outros momentos

O `ibov/alvos.py` aplica o mesmo método às 11h, a amanhã e à hora pedida. Uma hora quebrada, como
16h20, é estimada entre os dois pontos vizinhos. Antes das 11h, vale a previsão das 11h.

### O que não entra

- **Volatilidade: recurso não analisado na previsão.** Em períodos agitados, a faixa pode ficar
  estreita demais.
- Notícias, eleições e decisões de juros.

---

## 6. O que fica salvo

O modelo treinado **não é salvo**. A cada execução, ele aprende de novo com os dados da pasta `data/`.

| Arquivo em `data/` | Conteúdo | Usado para aprender? |
|---|---|---|
| `d_*.parquet` | Preços diários | Sim |
| `h_*.parquet` | Preços por hora | Sim |
| `painel.parquet` | Tabela final, montada com os dois acima | Sim |
| `m5_ibov.parquet` | Preços de 5 minutos | Não |

No `painel.parquet`, cada linha é um pregão em um horário, só com o que se sabia naquele momento. São
até oito horários por dia: véspera às 20h, 10h e de hora em hora das 11h às 16h.

**A cada execução:**

1. Os preços novos são baixados e somados aos antigos.
2. O preço de hoje só entra como fechamento 45 minutos depois do fim do pregão.
3. O painel é remontado.
4. O modelo aprende de novo.

Os dados de 5 minutos são a exceção: guardam só os últimos 60 dias.

**Não apague a pasta `data/`.** O Yahoo só entrega cerca de dois anos de preços por hora, e o que for
mais antigo se perderia.

| Arquivo em `saida/` | Conteúdo |
|---|---|
| `resultado_AAAA-MM-DD.txt` | Resultado de cada dia em texto |
| `painel.html` | Gráfico |
| `plotly.min.js` | Biblioteca que desenha o gráfico, para funcionar sem internet |
| `ultimo_ano_previsto_x_real_10h.csv` | Previsto e real das 10h no último ano (de 23/11/2026, não se atualiza) |

O modelo não usa os arquivos de `saida/` para aprender.

Para ver um arquivo `.parquet`:

```bash
.venv/bin/python -c "import pandas as pd; print(pd.read_parquet('data/d_ibov.parquet').tail())"
```

---

## 7. Como é testado

### Qualidade da previsão

O teste simula o uso real:

1. O modelo aprende só com os pregões anteriores (cerca de 250, no mínimo).
2. Prevê os 5 seguintes, sem ver o resultado.
3. O previsto é comparado com o real.
4. Esses 5 dias entram no aprendizado, e o processo se repete até hoje.

O erro é comparado com o do **palpite simples**: "vai fechar no preço atual". O modelo só é útil se
errar menos que isso.

### Funcionamento do programa

```bash
.venv/bin/python -m pytest -q tests
```

São 25 testes, em `tests/test_modelo.py`. O resultado esperado é `25 passed`. Eles conferem que:

- nenhuma previsão usa dados do futuro;
- o preço parcial do dia nunca vira fechamento;
- as três previsões aparecem, e são quatro com `--hora`;
- o que ainda não aconteceu não tem valor real;
- o fechamento (17h ou 18h) e os feriados estão corretos;
- as horas digitadas são lidas corretamente, e as inválidas dão erro claro;
- o relatório sai certo com o pregão aberto e fechado;
- nenhuma medida de volatilidade é usada.

---

## 8. Quanto dá para confiar

Último ano: 252 pregões, de 13/11/2025 a 19/11/2026.

| Previsão feita | Erro médio | Erro do palpite simples | Acerto de direção | Real dentro da faixa |
|---|---|---|---|---|
| Véspera, 20h | 0,97% | 0,97% | — | 74% |
| **10h** | **0,79%** | **0,97%** | **67%** | **75%** |
| 11h | 0,59% | 0,59% | 79% | 71% |
| 12h | 0,49% | 0,49% | 83% | 73% |
| 13h | 0,39% | 0,39% | 88% | 75% |
| 14h | 0,32% | 0,32% | 88% | 76% |
| 15h | 0,26% | 0,26% | 92% | 74% |
| 16h | 0,21% | 0,21% | 94% | 72% |

- **Às 10h, o modelo erra cerca de 18% menos** que o palpite simples. Sem os 5 dias mais extremos, o
  ganho é de cerca de 12%.
- **Das 11h em diante, ele empata**, porque a previsão é o próprio preço atual. O erro cai porque
  falta menos tempo para o fechamento.
- **O acerto de direção da tarde é alto** porque o índice já andou no dia.
- **A faixa de 80% acertou de 71% a 76%** dos dias.
- **O teste não foi totalmente às cegas:** resultados que incluíam esse período já tinham sido vistos
  durante o projeto, o que pode deixar os números um pouco otimistas.

O programa mostra valores um pouco diferentes porque usa um período maior, de 472 pregões.

É um projeto de estudo, não uma recomendação de investimento.

---

## 9. Análise rápida

O `analise_ibovespa.py` é um programa separado. Ele abre o gráfico em uma janela e salva a imagem em
`ibovespa_analise.png`.

| Para... | Comando |
|---|---|
| Análise completa | `.venv/bin/python analise_ibovespa.py` |
| Amanhã (início e final) | `.venv/bin/python analise_ibovespa.py amanha` |
| Amanhã às 15h | `.venv/bin/python analise_ibovespa.py amanha 15h` |
| Hoje às 16h30 (se ainda não passou) | `.venv/bin/python analise_ibovespa.py hoje 16h30` |

**Ele usa outro modelo**, então os números podem ser diferentes:

| | `python -m ibov` | `analise_ibovespa.py` |
|---|---|---|
| Aprende com | Quase 3 anos de preços por hora | Cerca de 60 dias, de 5 em 5 minutos |
| Informações usadas | EWZ, dólar e Vale (às 10h) | Só o IBOVESPA |
| Início do dia | 11h | 10:05 |
| Faixa testada em | 472 pregões | Pouco mais de 20 pregões |
| Guarda os preços | Sim | Não |

Prefira o `python -m ibov`, que foi testado em muito mais dias.

---

## 10. Arquivos do projeto

```
├── ibov/                    projeto principal
│   ├── __main__.py          executa todas as etapas
│   ├── dados.py             baixa os preços e monta a tabela
│   ├── modelo.py            aprende, prevê e mede os erros
│   ├── alvos.py             início, final, amanhã e hora pedida
│   ├── relatorio.py         gera o texto
│   └── visual.py            gera o gráfico
├── data/                    preços salvos
├── saida/                   resultados
├── tests/test_modelo.py     testes
├── analise_ibovespa.py      análise rápida
├── previsao_ibovespa.py     cálculos da análise rápida
└── requirements.txt         bibliotecas necessárias
```

Ordem de execução:

```
Yahoo Finance → dados.py → modelo.py → alvos.py → relatorio.py (texto) e visual.py (gráfico)
```

---

## 11. Como modificar

| Para mudar... | Onde |
|---|---|
| Informações usadas às 10h | `ATRIBUTOS`, em `ibov/modelo.py` |
| Largura da faixa | `Q_BAIXO` e `Q_ALTO`, em `ibov/modelo.py` (para 90%: 0.05 e 0.95) |
| Quantidade de erros usados na faixa | `JANELA_ERROS`, em `ibov/modelo.py` |
| Intervalo entre os aprendizados no teste | `RETREINO`, em `ibov/modelo.py` |
| Ativos por hora | `HORARIOS`, em `ibov/dados.py` (para usar no modelo, inclua `on_<nome>` em `ATRIBUTOS`) |
| Ativos diários | `DIARIOS`, em `ibov/dados.py` |
| Aparência do gráfico | Bloco `<style>`, em `ibov/visual.py` |

Depois de mudar, rode os testes. Se mudou o `dados.py`, rode o programa sem `--sem-download`.

---

## 12. Dúvidas comuns

**A previsão das 15h não apareceu.** Ela só fica disponível depois das 15h16.

**Quando sai o resultado do dia?** 45 minutos depois do fechamento: 17h45 ou 18h45. Rode de novo.

**O número mudou ao rodar de novo.** Com o pregão aberto, chegam preços novos. Com os mesmos dados, o
resultado é sempre igual.

**Apareceu `[aviso] ... usando cache`.** O Yahoo não respondeu e o programa usou os dados salvos.

— Gabriel M
