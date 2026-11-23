# Ana, deixa eu te explicar o nosso projeto do IBOVESPA

Escrevi este texto para te contar, com calma, como cada pedacinho
deste projeto funciona: de onde vêm os números, como o modelo pensa, como a gente testa, o que
fica salvo e até onde dá para confiar.

> **Antes de tudo:** Espero conseguir te ajudar :)

**O que você vai encontrar aqui**

- [Ana, deixa eu te explicar o nosso projeto do IBOVESPA](#ana-deixa-eu-te-explicar-o-nosso-projeto-do-ibovespa)
  - [1. A ideia](#1-a-ideia)
  - [2. Como rodar](#2-como-rodar)
  - [3. Como ler o que aparece na tela](#3-como-ler-o-que-aparece-na-tela)
    - [O gráfico, no navegador](#o-gráfico-no-navegador)
    - [O texto, no Terminal](#o-texto-no-terminal)
  - [4. De onde vêm os dados](#4-de-onde-vêm-os-dados)
    - [Três manias do Yahoo](#três-manias-do-yahoo)
    - [E se a internet cair?](#e-se-a-internet-cair)
  - [5. Como o modelo pensa](#5-como-o-modelo-pensa)
    - [Parte 1: a pergunta que ele faz](#parte-1-a-pergunta-que-ele-faz)
    - [Parte 2: a previsão das 10h, que é a mais interessante](#parte-2-a-previsão-das-10h-que-é-a-mais-interessante)
    - [Parte 3: nos outros horários, ele é humilde](#parte-3-nos-outros-horários-ele-é-humilde)
    - [Parte 4: a faixa e a chance de alta](#parte-4-a-faixa-e-a-chance-de-alta)
    - [E o resto?](#e-o-resto)
    - [O que a gente decidiu deixar de fora](#o-que-a-gente-decidiu-deixar-de-fora)
  - [6. O que fica salvo e como ele aprende](#6-o-que-fica-salvo-e-como-ele-aprende)
    - [O caderno: a pasta `data/`](#o-caderno-a-pasta-data)
    - [Como o caderno cresce](#como-o-caderno-cresce)
    - [Os resultados: a pasta `saida/`](#os-resultados-a-pasta-saida)
  - [7. Como a gente testa](#7-como-a-gente-testa)
    - [Teste 1: "ele acerta?"](#teste-1-ele-acerta)
    - [Teste 2: "o programa está funcionando direito?"](#teste-2-o-programa-está-funcionando-direito)
  - [8. Quanto dá para confiar](#8-quanto-dá-para-confiar)
  - [9. O outro programa: a análise rápida](#9-o-outro-programa-a-análise-rápida)
  - [10. O mapa da pasta](#10-o-mapa-da-pasta)
  - [11. Se você quiser mexer](#11-se-você-quiser-mexer)
  - [12. Dúvidas que você provavelmente vai ter](#12-dúvidas-que-você-provavelmente-vai-ter)
  - [13. Pequeno dicionário](#13-pequeno-dicionário)

---

## 1. A ideia 

O IBOVESPA é um número que resume como as principais ações do Brasil estão indo. Este projeto
tenta responder a uma pergunta: **em quantos pontos ele vai estar?**

Ele responde para três momentos:

- o **início do dia** (11h);
- o **final do dia** (o fechamento);
- o **início do dia de amanhã** (11h do próximo dia de bolsa).

E, se você pedir, também para **uma hora de hoje** que você escolher.

Para cada momento, ele te dá duas coisas:

- **um número**, que é o palpite central;
- **uma faixa**, do tipo "provavelmente entre 163.734 e 164.965".

Se for guardar só uma coisa daqui, guarde esta: **a faixa é mais importante do que o número.**
Ninguém acerta o número exato. A faixa mostra o tamanho da dúvida.

---

## 2. Como rodar

Abra o Terminal, entre na pasta do projeto e rode:

```bash
cd "Ana - IBOVESPA"
.venv/bin/python -m ibov
```

Ele mostra o resultado em texto e abre o gráfico no navegador. Como baixa dados da internet,
pode demorar um pouquinho.

| O que você quer | O que digitar |
|---|---|
| A previsão de hoje | `.venv/bin/python -m ibov` |
| Saber também como vai estar às 16h20 de hoje | `.venv/bin/python -m ibov --hora 16:20` |
| Ver um dia que já passou | `.venv/bin/python -m ibov --dia 2026-11-19` |
| Um dia que já passou, numa certa hora | `.venv/bin/python -m ibov --dia 2026-11-19 --hora 15h30` |
| Ver a previsão que foi **feita** às 13h | `.venv/bin/python -m ibov --feita-as 13h` |
| Ver a previsão feita na noite anterior | `.venv/bin/python -m ibov --feita-as vespera` |
| Usar o que já está salvo, sem baixar nada | `.venv/bin/python -m ibov --sem-download` |
| Rodar sem abrir o navegador | `.venv/bin/python -m ibov --nao-abrir` |

Cuidado com duas opções parecidas:

- **`--hora`** é o momento que você quer **adivinhar**. Exemplo: "como vai estar às 16h20?".
- **`--feita-as`** é o momento em que o palpite **foi dado**. Exemplo: "o que o modelo dizia às 13h?".

Pode escrever a hora como preferir: `13:30`, `13h30`, `13h` ou `13`.

**Se a pasta `.venv` sumir** (é onde ficam as ferramentas do Python), recrie assim:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

---

## 3. Como ler o que aparece na tela

### O gráfico, no navegador

No alto da página há um **cartão para cada momento**. Dentro dele você vê:

- a **previsão** (o número grande);
- quanto isso dá de **alta ou de queda**;
- a **faixa provável**;
- o **valor real**, quando aquele momento já passou, e de quanto foi o erro.

Embaixo dos cartões vem o gráfico:

| O que você vê | O que significa |
|---|---|
| Linha escura | O que o índice **realmente** fez |
| Bolinha azul | Uma previsão |
| Bolinha laranja | A previsão da hora que você pediu |
| Barra clara em volta da bolinha | A faixa provável. Quanto mais comprida, maior a dúvida |
| Pontilhado azul | O caminho do preço de agora até as previsões |
| Pontilhado cinza | Onde o índice fechou no dia anterior |

Duas regras simples explicam quais números aparecem:

- **Se o momento já passou**, você vê a previsão da manhã (10h) ao lado do valor real. Assim dá
  para conferir se ela foi boa.
- **Se o momento ainda vem**, você vê a previsão mais recente.

No fim da página há um **"Detalhes"** que você pode abrir. Ali ficam o histórico de acertos e
erros e os botões para trocar o dia e o horário da previsão.

### O texto, no Terminal

É a mesma informação, por escrito. Começa com uma frase direta, como esta, de 23/11/2026 às 15h34:

```
  164.372 pontos, com faixa de 80% entre 163.734 e 164.965
  (fechamento de 23/11; previsão feita às 15h)
```

Depois vêm os momentos do dia, como a previsão foi mudando de hora em hora, quanto o modelo
costuma errar e a explicação de onde saiu cada número. Quando o dia termina, aparece também a
parte **RESULTADO DO DIA**, comparando o previsto com o que aconteceu.

---

## 4. De onde vêm os dados

Tudo vem do **Yahoo Finance**, que é gratuito. Quem busca é o arquivo `ibov/dados.py`.

Ele pega os preços em três "tamanhos":

| Tamanho | Desde quando | Para que serve |
|---|---|---|
| Um preço por **dia** | 2010 | Saber onde cada dia fechou |
| Um preço por **hora** | dezembro de 2023 | Saber como o mundo estava em cada horário. **É daqui que o modelo aprende** |
| Um preço a cada **5 minutos** | cerca de 60 dias | Só para desenhar a linha do gráfico e conferir o valor real. Não entra no modelo |

E busca preços de várias coisas:

| O que é | Código no Yahoo |
|---|---|
| **O próprio IBOVESPA** | `^BVSP` |
| **Um fundo de ações brasileiras negociado em Nova York (EWZ)** | `EWZ` |
| **O dólar em reais** | `BRL=X` |
| **Vale, negociada em Nova York** | `VALE` |
| Petrobras e Itaú, negociados em Nova York | `PBR`, `ITUB` |
| Bolsa americana (o índice e o contrato futuro) | `^GSPC`, `ES=F` |
| Petróleo | `BZ=F` |
| Força do dólar no mundo | `DX-Y.NYB` |
| Juros americanos | `^TNX` |
| Bolsas do Japão, de Hong Kong e da Europa | `^N225`, `^HSI`, `^STOXX50E` |
| Fundo de países emergentes | `EEM` |

Ana, uma coisa que eu quero deixar clara: **o modelo de hoje usa só as linhas em negrito.** As
outras são baixadas e organizadas, mas não entram na conta. Ficam ali para a gente poder fazer
novos testes.

### Três manias do Yahoo

- **Ele atrasa uns 15 minutos.** Por isso a previsão das 13h só aparece depois das 13h16.
- **A "abertura" das 10h não serve.** Em 98 de cada 100 dias, o número que ele dá às 10h é o
  mesmo do fechamento anterior, porque as ações ainda não começaram a negociar. Prever isso seria
  repetir um número que já se sabe. Por isso o nosso "início do dia" é às **11h**.
- **Ele para às 17h.** A bolsa brasileira acompanha Nova York: fecha às 17h durante o horário de
  verão de lá e às 18h no resto do ano. Entre 17h e 18h, o Yahoo só nos dá o fechamento final.
  Nesse pedaço, a linha do gráfico é só uma reta.

### E se a internet cair?

Ele avisa com um `[aviso] ... usando cache` e continua com a última cópia que tem guardada.

---

## 5. Como o modelo pensa

O modelo mora em `ibov/modelo.py`. Vou te contar em quatro partes.

### Parte 1: a pergunta que ele faz

Ele não tenta adivinhar o número do nada. Parte do **último preço conhecido** e pergunta:
*"daqui até o fechamento, quanto ainda vai andar?"*

### Parte 2: a previsão das 10h, que é a mais interessante

Enquanto a bolsa daqui está fechada, o mundo continua girando. Quando chega a manhã, já existem
pistas. O modelo olha três:

1. quanto o **EWZ** andou desde o nosso último fechamento;
2. quanto o **dólar** andou;
3. quanto a **Vale** andou em Nova York.

Se elas caíram, é provável que o IBOVESPA comece o dia caindo também. O EWZ é, de longe, a pista
que mais pesa.

**Um exemplo de verdade, de 23/11/2026, às 10h:**

| Pista | O que tinha acontecido |
|---|---|
| EWZ | caiu cerca de 1,7% |
| Dólar | subiu cerca de 0,7% |
| Vale | caiu cerca de 0,9% |

Com isso, ele previu uma queda de 0,82% e um fechamento em **165.014** pontos.

E como ele sabe quanto pesa cada pista? Olhando o passado. Ele vê centenas de manhãs antigas,
compara as pistas com o que aconteceu depois e descobre o peso que dá menos erro. O método se
chama **Ridge**. Pense nele como uma receita em que cada ingrediente tem uma medida, e o método
desconfia de exageros: não deixa um dia maluco do passado mudar a receita inteira.

### Parte 3: nos outros horários, ele é humilde

Das 11h em diante, e também na noite anterior, o palpite é simplesmente **o último preço
conhecido**.

Parece preguiça, mas não é. Centenas de jeitos de prever foram testados, e nenhum errou menos
do que isso de forma consistente. Então, em vez de inventar, ele repete o preço. É por isso que
às vezes você vai ver **o mesmo número** para o final do dia e para amanhã.

Isso **não quer dizer "vai ficar parado"**. Quer dizer "não achei sinal nem de alta, nem de
queda". Nessas horas, olhe a faixa.

*(O código dessa busca por modelos não ficou guardado na pasta. O que existe aqui é o modelo que
sobrou dela e os testes dele.)*

### Parte 4: a faixa e a chance de alta

Para montar a faixa, o modelo olha os **últimos 120 erros** dele, medidos em dias que ele não
tinha visto. Aí joga fora os 10% piores de cada lado. O que sobra no meio é a faixa de 80%.

A **chance de alta** vem dos mesmos 120 erros: ele conta em quantos deles o dia terminaria acima
do fechamento anterior. Se aparecer "1%", não leia como certeza. Leia como "entre os casos
parecidos que conheço, quase nenhum virou".

### E o resto?

O arquivo `ibov/alvos.py` usa esse mesmo raciocínio para os outros momentos: em vez de perguntar
"onde fecha?", ele pergunta "onde vai estar às 11h?" ou "e às 11h de amanhã?".

Se você pede uma hora quebrada, como 16h20, ele fica entre a estimativa anterior e a seguinte.
Antes das 11h, usa a previsão das 11h.

### O que a gente decidiu deixar de fora

**Volatilidade: recurso não analisado na previsão.** Volatilidade é o quanto o mercado está
nervoso. Nada disso entra na conta. O preço dessa escolha é que, em época agitada, a faixa pode
ficar estreita demais.

Notícias, eleições e decisões sobre juros também não entram. O modelo só enxerga preços.

---

## 6. O que fica salvo e como ele aprende

Esta parte confunde muita gente, então vou devagar.

**O modelo não fica guardado pronto.** Toda vez que você roda, ele **aprende de novo**, do zero,
com os preços salvos. O que a gente guarda é o material de estudo, como se fosse o caderno dele.

### O caderno: a pasta `data/`

| Arquivo | O que tem dentro | O modelo aprende com ele? |
|---|---|---|
| `d_*.parquet` | Preços por dia, um arquivo para cada item | Sim |
| `h_*.parquet` | Preços por hora, um arquivo para cada item | Sim |
| `painel.parquet` | Tudo acima já arrumado em uma tabela só | Sim, é o caderno passado a limpo |
| `m5_ibov.parquet` | Preços de 5 em 5 minutos | Não, é só para o gráfico |

"Parquet" é um tipo de planilha compacta. Se quiser espiar uma, rode:

```bash
.venv/bin/python -c "import pandas as pd; print(pd.read_parquet('data/d_ibov.parquet').tail())"
```

No `painel.parquet`, **cada linha é uma fotografia**: um dia, em um horário, só com o que se
sabia naquele instante. Cada dia rende até oito fotografias: na noite anterior (20h), às 10h e
de hora em hora, das 11h às 16h. Em 23/11/2026 eram 5.759 fotografias de 723 dias.

### Como o caderno cresce

1. Você roda o programa.
2. Ele baixa os preços novos e **junta com os antigos**, sem apagar.
3. O preço de hoje, enquanto o dia não acabou, **não é guardado** como se fosse o fechamento.
   Ele espera 45 minutos depois do fim da bolsa para confiar no número.
4. O painel é remontado com os dias novos.
5. O modelo estuda tudo de novo.

Por isso vale a pena rodar sempre. O Yahoo só entrega cerca de dois anos de preços por hora, mas
o que a gente já guardou continua aqui. A exceção são os preços de 5 minutos, que ficam só com os
últimos 60 dias.

**Então não apague a pasta `data/`.** Dá para baixar de novo, mas os preços por hora mais antigos
do que dois anos se perderiam.

### Os resultados: a pasta `saida/`

| Arquivo | O que é |
|---|---|
| `resultado_AAAA-MM-DD.txt` | O texto de cada dia. Rodar de novo no mesmo dia atualiza o arquivo |
| `painel.html` | A página com o gráfico |
| `plotly.min.js` | A peça que desenha o gráfico, guardada para ele abrir sem internet |
| `ultimo_ano_previsto_x_real_10h.csv` | Previsto e real das 10h, dia a dia, no último ano. Abre no Excel |

Esses arquivos são **para a gente**, não para o modelo. Ele não lê os próprios resultados para
aprender. E o `.csv` é uma foto tirada em 23/11/2026: ele não se atualiza sozinho.

---

## 7. Como a gente testa

São dois tipos de teste, e eles respondem a perguntas diferentes.

### Teste 1: "ele acerta?"

Imagine dar uma prova para alguém que já viu o gabarito. A nota não vale nada. Com o modelo é a
mesma coisa: ele não pode ser avaliado em dias que já estudou.

Por isso a gente finge que está no passado:

1. ele estuda só os dias **anteriores** (no mínimo uns 250, cerca de um ano);
2. prevê os **5 dias seguintes**, sem ver a resposta;
3. a gente confere;
4. ele estuda esses 5 dias também, e repete tudo, até hoje.

Toda previsão de dia passado que você vê no painel foi feita assim.

Depois a gente compara com o **palpite mais simples possível**: "vai fechar onde está agora". Se o
modelo não erra menos que isso, ele não está ajudando em nada.

### Teste 2: "o programa está funcionando direito?"

São 25 conferências automáticas, que rodam sem internet e em poucos segundos:

```bash
.venv/bin/python -m pytest -q tests
```

Se aparecer `25 passed`, está tudo certo. Elas ficam em `tests/test_modelo.py` e conferem que:

| O que é conferido | Por que importa |
|---|---|
| **Ninguém espia o futuro.** A gente finge que é 12h30 e olha se algo das 13h apareceu. Também confere que previsões antigas não mudam quando chegam dados novos | Se espiasse, pareceria genial no teste e falharia na vida real |
| O preço incompleto de hoje nunca vira fechamento | Senão ele estudaria um número errado |
| As três previsões aparecem, e são quatro quando você pede uma hora | É o coração do gráfico |
| O que ainda não aconteceu não tem "valor real" | Evita mostrar um número inventado |
| A bolsa fecha às 17h ou às 18h, na época certa | Muda duas vezes por ano |
| Feriados são pulados ao procurar o próximo dia de bolsa | Senão "amanhã" poderia cair num feriado |
| As horas que você digita são entendidas, e as inválidas dão um erro claro | Para ninguém ficar perdido |
| O texto sai certo com a bolsa aberta e com ela fechada | São duas situações diferentes |
| Nenhuma medida de volatilidade entrou na conta | Foi uma decisão nossa |

Se algum teste falhar depois de uma mudança, **não confie nos números** até descobrir o motivo.

---

## 8. Quanto dá para confiar

Estes são os números do último ano: 252 dias, de 13/11/2025 a 19/11/2026.

| Previsão feita... | Erro médio | Erro do palpite simples | Acertou se subia ou caía | Real caiu dentro da faixa |
|---|---|---|---|---|
| na noite anterior | 0,97% | 0,97% | — | 74% |
| **às 10h** | **0,79%** | **0,97%** | **67%** | **75%** |
| às 11h | 0,59% | 0,59% | 79% | 71% |
| às 12h | 0,49% | 0,49% | 83% | 73% |
| às 13h | 0,39% | 0,39% | 88% | 75% |
| às 14h | 0,32% | 0,32% | 88% | 76% |
| às 15h | 0,26% | 0,26% | 92% | 74% |
| às 16h | 0,21% | 0,21% | 94% | 72% |

Para ter noção: com o índice perto de 165 mil pontos, errar 0,79% é errar uns 1.300 pontos.

**O que isso quer dizer, sem enfeite:**

- **Às 10h o modelo ajuda de verdade.** Erra cerca de 18% menos que o palpite simples. Parte
  disso veio de poucos dias muito fortes, como a queda de 13,9% em 26/10/2026. Sem os 5 dias mais
  extremos, o ganho cai para uns 12%.
- **Depois das 11h ele empata com o palpite simples**, porque ele *é* o palpite simples. O erro
  diminui só porque falta menos tempo para o dia acabar.
- **Os 94% de acerto das 16h enganam.** Se o dia já está em queda forte a uma hora ou duas do fim,
  acertar que vai fechar em queda é fácil.
- **A faixa promete 80% e entregou de 71% a 76%.** Trate como "acerta uns três em cada quatro dias".
- **O teste não foi totalmente às cegas.** Resultados que incluíam esse ano já tinham sido vistos
  durante o projeto, e isso pode deixar os números um pouco otimistas.

Na tela você vai ver números um pouco diferentes destes, como 0,73% às 10h. É que lá a conta usa
um período maior, de 472 dias.

---

## 9. O outro programa: a análise rápida

Existe um segundo programa na pasta, o `analise_ibovespa.py`, que trabalha junto com o
`previsao_ibovespa.py`.

| O que você quer | O que digitar |
|---|---|
| Análise completa, com gráfico e explicação | `.venv/bin/python analise_ibovespa.py` |
| Só amanhã (início e final) | `.venv/bin/python analise_ibovespa.py amanha` |
| Amanhã às 15h | `.venv/bin/python analise_ibovespa.py amanha 15h` |
| Hoje às 16h30 (precisa ser uma hora que ainda não passou) | `.venv/bin/python analise_ibovespa.py hoje 16h30` |

Aqui ele abre uma janela e salva uma imagem, a `ibovespa_analise.png`. Na análise completa, também
explica a tendência, se o índice subiu ou caiu demais e quanto está abaixo do topo.

**Atenção, Ana: é outro modelo.** Os dois podem dar números diferentes, e isso é normal:

| | `python -m ibov` | `analise_ibovespa.py` |
|---|---|---|
| Aprende com | quase 3 anos de preços por hora | uns 60 dias de preços de 5 em 5 minutos |
| Olha | EWZ, dólar e Vale, às 10h | só o próprio IBOVESPA |
| "Início do dia" é | 11h | 10:05 |
| Acerto da faixa medido em | 472 dias | pouco mais de 20 dias |
| Guarda os preços? | Sim | Não, baixa tudo de novo |

Na dúvida, fique com o `python -m ibov`, porque foi testado em muito mais dias.

---

## 10. O mapa da pasta

```
Ana - IBOVESPA/
├── ibov/                    ← o projeto principal
│   ├── dados.py             ← busca os preços e monta o caderno
│   ├── modelo.py            ← aprende, prevê e mede os acertos
│   ├── alvos.py             ← início do dia, final, amanhã e a hora que você pedir
│   ├── relatorio.py         ← escreve o texto
│   ├── visual.py            ← desenha o gráfico
│   └── __main__.py          ← o maestro: chama todos na ordem certa
├── data/                    ← o caderno: preços guardados
├── saida/                   ← os resultados para você ler
├── tests/test_modelo.py     ← as conferências automáticas
├── analise_ibovespa.py      ← a análise rápida (outro modelo)
├── previsao_ibovespa.py     ← as contas da análise rápida
├── requirements.txt         ← a lista de ferramentas que o Python precisa
└── README.md                ← este texto
```

Quando você roda `python -m ibov`, a história é esta:

```
Yahoo Finance
   ↓   dados.py busca os preços e guarda em data/
Tabela arrumada (painel.parquet)
   ↓   modelo.py estuda o passado e mede os próprios erros
   ↓   alvos.py calcula início, final, amanhã e a hora pedida
Previsões
   ├─→ relatorio.py escreve o texto   (tela e saida/resultado_<dia>.txt)
   └─→ visual.py desenha o gráfico    (saida/painel.html)
```

---

## 11. Se você quiser mexer

Pode abrir qualquer arquivo da pasta `ibov/`: eles têm comentários em português. Depois de mudar
alguma coisa, rode os testes.

| Quero... | Onde mexer |
|---|---|
| Trocar as pistas que o modelo olha às 10h | `ATRIBUTOS`, em `ibov/modelo.py` |
| Fazer a faixa ficar mais larga ou mais estreita | `Q_BAIXO` e `Q_ALTO`, em `ibov/modelo.py` (para 90%, use 0.05 e 0.95) |
| Mudar quantos erros a faixa considera | `JANELA_ERROS`, em `ibov/modelo.py` |
| Mudar de quantos em quantos dias ele estuda de novo nos testes | `RETREINO`, em `ibov/modelo.py` |
| Buscar mais um item por hora no Yahoo | `HORARIOS`, em `ibov/dados.py`. Para o modelo usar, inclua `on_<nome>` em `ATRIBUTOS` |
| Buscar mais um item por dia no Yahoo | `DIARIOS`, em `ibov/dados.py` |
| Mudar cores e tamanhos do gráfico | O trecho `<style>`, em `ibov/visual.py` |

Se mexer no `dados.py`, rode **sem** o `--sem-download`, para o caderno ser refeito.

Um conselho: se você trocar uma pista e o erro cair só um pouquinho, desconfie. Testando muitas
ideias, uma delas parece boa por sorte.

---

## 12. Dúvidas que você provavelmente vai ter

**Por que o final do dia e amanhã mostram o mesmo número?**
Porque, a partir das 11h, o palpite é o último preço conhecido. Olhe a faixa: a de amanhã é mais
larga, já que até lá pode acontecer mais coisa.

**Por que a previsão das 15h ainda não apareceu?**
Ou ainda não são 15h, ou o dado está a caminho. Ela aparece depois das 15h16.

**Quando sai o resultado do dia?**
45 minutos depois que a bolsa fecha: 17h45 ou 18h45, dependendo da época. Aí é só rodar de novo.

**Rodei duas vezes e o número de hoje mudou. Quebrou?**
Não. Com a bolsa aberta, chegam preços novos o tempo todo. Com os mesmos dados, ele sempre dá o
mesmo resultado, porque não há sorteio em nenhuma parte.

**Apareceu `[aviso] ... usando cache`. E agora?**
O Yahoo não respondeu e ele usou a cópia guardada. Tente de novo mais tarde.

**Por que o histórico por hora começa em dezembro de 2023?**
Porque o Yahoo só entrega cerca de dois anos para trás, e foi dali que a gente começou a guardar.

**Posso investir com base nisso?**
Não é para isso. É um projeto para aprender como uma previsão é construída e, principalmente, como
se mede se ela presta.

---

## 13. Pequeno dicionário

| Palavra | O que quer dizer |
|---|---|
| **Pregão** | Um dia de funcionamento da bolsa |
| **Fechamento** | O último preço do dia |
| **Véspera** | A noite anterior, às 20h |
| **Horário de corte** | O momento em que a previsão é feita. O que vem depois fica escondido do modelo |
| **Faixa de 80%** | O intervalo que deveria conter o resultado em 8 de cada 10 dias |
| **Palpite ingênuo** | "Vai fechar onde está agora". É o mínimo que o modelo precisa superar |
| **Fora da amostra** | Previsão de um dia que o modelo não estudou |
| **Walk-forward** | O teste de fingir que está no passado e ir andando para a frente |
| **Cache** | A cópia dos preços guardada no computador |
| **EWZ** | Um fundo com ações brasileiras, negociado em Nova York |

— Gabriel M 
