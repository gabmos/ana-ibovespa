"""Análise do IBOVESPA com a previsão do início e do final do dia.

Só usa preço e retorno (sem medidas de volatilidade).

Uso:
    python analise_ibovespa.py              análise completa: gráfico, previsão do início e do
                                            final do dia e embasamento
    python analise_ibovespa.py amanha       somente as previsões para amanhã (início e final)
    python analise_ibovespa.py amanha 15h   somente a previsão para esse horário de amanhã
    python analise_ibovespa.py hoje 16h     somente a previsão para esse horário de hoje
                                            (erro se já passou)

Qualquer hora serve: 16h, 16h30, 16:30 ou 16. Com a bolsa fechada, vale o início do dia (antes
da abertura) ou o fechamento (depois dele).

Opções: [--periodo 2y] [--ticker ^BVSP] [--saida arquivo.png] [--sem-janela]
"""

import argparse
import re
import sys
import unicodedata
from datetime import date, datetime, time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

import previsao_ibovespa as pv
from previsao_ibovespa import br, pct


def baixar_dados(ticker: str, periodo: str) -> pd.DataFrame:
    df = yf.download(ticker, period=periodo, auto_adjust=True, progress=False)
    if df.empty:
        raise SystemExit(f"Nenhum dado retornado para {ticker}.")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Close"])


def calcular_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    c = df["Close"]
    df["MM50"] = c.rolling(50).mean()
    df["MM200"] = c.rolling(200).mean()

    # RSI de Wilder (14 períodos)
    delta = c.diff()
    ganho = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    perda = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["RSI"] = 100 - 100 / (1 + ganho / perda)

    df["Drawdown"] = c / c.cummax() - 1
    return df


def embasamento(df: pd.DataFrame) -> list[dict]:
    """Monta, para cada análise, o conceito, a fórmula, o valor atual e a leitura."""
    u = df.iloc[-1]
    preco, mm50, mm200 = u["Close"], u["MM50"], u["MM200"]
    anos = (df.index[-1] - df.index[0]).days / 365.25
    retorno_total = df["Close"].iloc[-1] / df["Close"].iloc[0] - 1
    cagr = (1 + retorno_total) ** (1 / anos) - 1 if anos > 0 else np.nan
    dd_max = df["Drawdown"].min()
    pos_dd_max = df["Drawdown"].values.argmin()
    data_dd_max = pd.Timestamp(df.index[pos_dd_max]).date()

    if preco > mm50 > mm200:
        tendencia = "alta (preço > MM50 > MM200)"
    elif preco < mm50 < mm200:
        tendencia = "baixa (preço < MM50 < MM200)"
    else:
        tendencia = "indefinida / em transição (médias não alinhadas)"
    cruzamento = "Golden cross (MM50 acima da MM200)" if mm50 > mm200 else "Death cross (MM50 abaixo da MM200)"

    rsi = u["RSI"]
    leitura_rsi = ("sobrecompra (> 70)" if rsi > 70
                   else "sobrevenda (< 30)" if rsi < 30
                   else "zona neutra (30–70)")

    return [
        {
            "analise": "Tendência por médias móveis",
            "conceito": "Médias móveis simples suavizam o ruído; a MM50 indica a tendência de "
                        "médio prazo e a MM200 a de longo prazo. O alinhamento entre preço e médias "
                        "define a direção predominante.",
            "formula": "MM_n = (1/n) · Σ Close_{t-i}, i = 0..n-1",
            "valor": f"Preço {br(preco, 0)} | MM50 {br(mm50, 0)} | MM200 {br(mm200, 0)} — {cruzamento}",
            "leitura": f"Tendência {tendencia}.",
        },
        {
            "analise": "RSI — Índice de Força Relativa (14)",
            "conceito": "Oscilador de momento de Wilder: compara a média dos ganhos com a média das "
                        "perdas recentes. Acima de 70 sugere sobrecompra; abaixo de 30, sobrevenda.",
            "formula": "RSI = 100 − 100 / (1 + MédiaGanhos₁₄ / MédiaPerdas₁₄)  (suavização de Wilder)",
            "valor": f"RSI atual = {br(rsi, 1)}",
            "leitura": f"Momento em {leitura_rsi}.",
        },
        {
            "analise": "Drawdown",
            "conceito": "Queda percentual em relação ao topo histórico do período. Mede a perda "
                        "máxima que um investidor teria sofrido comprando no pico.",
            "formula": "DD_t = Close_t / max(Close_0..t) − 1",
            "valor": f"Atual: {pct(u['Drawdown'], 1)} | Máximo: {pct(dd_max, 1)} (em {data_dd_max:%d/%m/%Y})",
            "leitura": ("Índice no topo do período." if u["Drawdown"] > -0.001
                        else f"Índice {pct(abs(u['Drawdown']), 1, sinal=False)} abaixo do topo do período."),
        },
        {
            "analise": "Retorno do período",
            "conceito": "Retorno acumulado e taxa composta anual (CAGR), em pontos do índice "
                        "(sem dividendos, sem ajuste por inflação ou câmbio).",
            "formula": "CAGR = (Close_final / Close_inicial)^(1/anos) − 1",
            "valor": f"Acumulado: {pct(retorno_total, 1)} | CAGR: {pct(cagr, 1)} a.a. em {br(anos, 1)} anos",
            "leitura": "Desempenho positivo no período." if retorno_total > 0
                       else "Desempenho negativo no período.",
        },
        {"analise": "Volatilidade", "aviso": "Recurso não analisado na previsão."},
    ]


def imprimir_embasamento(itens: list[dict], df: pd.DataFrame, ticker: str) -> None:
    linha = "=" * 78
    print(f"\n{linha}\nEMBASAMENTO DAS ANÁLISES — {ticker}")
    print(f"Dados: Yahoo Finance | {df.index[0]:%d/%m/%Y} a {df.index[-1]:%d/%m/%Y} "
          f"| {len(df)} pregões\n{linha}")
    for i, it in enumerate(itens, 1):
        print(f"\n{i}. {it['analise']}")
        if "aviso" in it:                      # item só informativo, sem cálculo
            print(f"   • {it['aviso']}")
            continue
        print(f"   • Conceito: {it['conceito']}")
        print(f"   • Fórmula:  {it['formula']}")
        print(f"   • Valor:    {it['valor']}")
        print(f"   • Leitura:  {it['leitura']}")


def erro(msg: str) -> None:
    """Mostra o erro e encerra com código 1."""
    sys.exit(f"Erro: {msg}")


def ler_horario(txt: str) -> time:
    """'16h', '16h30', '16:30', '16', '16 horas' -> horário.

    De 1h a 6h é lido como tarde (2h = 14:00), porque o pregão é das 10h às 17h/18h.
    """
    m = re.fullmatch(r"(\d{1,2})\s*(?:horas?|hrs?|[h:](\d{2})?(?:min|m)?)?", txt.strip())
    if not m or int(m[1]) > 23 or int(m[2] or 0) > 59:
        erro(f"não entendi o horário {txt!r}. Use, por exemplo: 16h, 16h30 ou 16:30.")
    return time(int(m[1]) + (12 if 1 <= int(m[1]) <= 6 else 0), int(m[2] or 0))


def ler_pedido(palavras: list[str], agora: datetime) -> tuple[str | None, date | None, time | None]:
    """(dia pedido, pregão correspondente, horário). Tudo None = análise completa.

    Aceita 'amanha', 'amanha 15h', 'amanhã às 15:30', 'hoje 16h'...
    """
    # tira acentos (o macOS pode mandar 'a' + til separado) e o 'as' de 'amanhã às 15h'
    txt = unicodedata.normalize("NFD", " ".join(palavras).lower())
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    quando, *resto = txt.split() or [""]
    resto = [r for r in resto if r not in ("as", "a")]
    if not quando:
        return None, None, None
    if quando not in ("hoje", "amanha"):
        erro(f"não entendi {' '.join(palavras)!r}. Use: (nada), amanha, amanha 15h ou hoje 16h.")
    horario = ler_horario(" ".join(resto)) if resto else None
    hoje = agora.date()
    if quando == "amanha":
        return quando, pv.proximo_pregao(hoje), horario

    if horario is None:
        erro("informe o horário. Exemplo: hoje 16h.")
    if not pv.eh_pregao(hoje):
        erro(f"hoje ({hoje:%d/%m}) não tem pregão na B3.")
    if datetime.combine(hoje, horario, pv.TZ) <= agora:
        erro(f"o horário {horario:%H:%M} de hoje já passou (agora são {agora:%H:%M}).")
    if agora >= pv.fechamento_b3(hoje):
        erro(f"o pregão de hoje já fechou (às {pv.fechamento_b3(hoje):%H:%M}). Tente: amanha {horario:%H:%M}.")
    return quando, hoje, horario


def aviso_fora_do_pregao(d: date, h: time) -> str:
    """Explica quando a hora pedida cai com a bolsa fechada (senão, texto vazio)."""
    fim = pv.fechamento_b3(d).time()
    if h < time(10):
        return f"Às {h:%H:%M} a bolsa ainda está fechada: vale a previsão do início do dia."
    if h > fim:
        return f"Às {h:%H:%M} a bolsa já fechou: vale a previsão do fechamento ({fim:%H:%M})."
    if time(17) < h < fim:
        return f"Entre 17:00 e {fim:%H:%M} o Yahoo não tem preços: valor estimado entre esses dois horários."
    return ""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("quando", nargs="*", metavar="amanha [HORA] | hoje HORA",
                   help="vazio = análise completa; 'amanha'; 'amanha 15h'; 'hoje 16h'")
    p.add_argument("--ticker", default="^BVSP")
    p.add_argument("--periodo", default="2y", help="ex.: 1y, 2y, 5y, max")
    p.add_argument("--saida", default="ibovespa_analise.png")
    p.add_argument("--sem-janela", action="store_true", help="não abrir a janela do gráfico")
    args = p.parse_args()

    # 1) entende o pedido antes de baixar qualquer dado
    agora = datetime.now(pv.TZ)
    quando, dia, horario = ler_pedido(args.quando, agora)

    # 2) dados e previsões
    intra, diario = pv.baixar(args.ticker)
    g = pv.montar_grade(intra, diario, agora)
    real_inicio = None
    if horario:
        previsoes = [pv.previsao_as(g, dia, horario, agora)]
    elif quando:
        previsoes = list(pv.previsoes_de_amanha(g, agora))
    else:
        inicio, final, real_inicio = pv.previsoes_do_dia(g, agora)
        previsoes = [inicio, final]

    # 3) gráfico (da última previsão da lista) e texto
    pv.plotar(g, diario, previsoes[-1], Path(args.saida))
    print(f"Gráfico salvo em: {args.saida}")
    if quando:
        titulo = f"PREVISÃO PARA {'HOJE' if quando == 'hoje' else 'AMANHÃ'} — IBOVESPA"
        if (dia - agora.date()).days > 1:
            titulo = f"PREVISÃO PARA O PRÓXIMO PREGÃO ({dia:%d/%m}) — IBOVESPA\nAmanhã não há pregão na B3."
        if horario and (aviso := aviso_fora_do_pregao(dia, horario)):
            titulo += f"\n{aviso}"
        pv.imprimir_previsao(titulo, previsoes)
    else:
        pv.imprimir_previsoes_do_dia(inicio, final, real_inicio)
        df = calcular_indicadores(baixar_dados(args.ticker, args.periodo))
        imprimir_embasamento(embasamento(df), df, args.ticker)
    if not args.sem_janela:
        plt.show()


if __name__ == "__main__":
    main()
