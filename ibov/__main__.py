"""
ibov/__main__.py — PONTO DE ENTRADA: junta todas as etapas num só comando.

Exemplos de uso (rodar na pasta do projeto):
    .venv/bin/python -m ibov                    # visão diária (previsão das 10h) — padrão
    .venv/bin/python -m ibov --hora 13:30       # mostra também a previsão PARA as 13h30 de hoje
    .venv/bin/python -m ibov --feita-as 13h     # usa a previsão FEITA às 13h (ou 'vespera', 'diario')
    .venv/bin/python -m ibov --dia 2026-11-19   # resultado de um pregão passado
    .venv/bin/python -m ibov --sem-download     # usa só os dados já salvos em data/
    .venv/bin/python -m ibov --nao-abrir        # não abre o painel no navegador

O fluxo é:
    1. baixar dados            (ibov/dados.py   → baixar)
    2. montar painel as-of     (ibov/dados.py   → painel)
    3. prever em walk-forward  (ibov/modelo.py  → walk_forward, metricas)
    3b. momentos do dia        (ibov/alvos.py   → montar: início, fim, próximo pregão, --hora)
    4. resultado do dia        (ibov/relatorio.py → texto no terminal + saida/resultado_<dia>.txt)
    5. painel gráfico          (ibov/visual.py  → saida/painel.html, aberto no navegador)
"""
from __future__ import annotations
import argparse
import webbrowser
import pandas as pd

from .alvos import ler_hora, montar
from .dados import CACHE, TZ, baixar, baixar_5min, painel
from .modelo import corte_para_hora, metricas, walk_forward
from .relatorio import caminho, gerar_relatorio
from .visual import gerar_html


def main() -> None:
    # --- 0. Lê as opções da linha de comando ---
    ap = argparse.ArgumentParser(description="Previsão do fechamento do IBOVESPA")
    ap.add_argument("--hora", help="mostra também a previsão PARA essa hora do dia: '13:30', '13h30', '13h'…")
    ap.add_argument("--feita-as", help="horário em que a previsão é FEITA: 'diario' (padrão), 'vespera', '13h'…")
    ap.add_argument("--dia", help="pregão a analisar (AAAA-MM-DD); padrão: o mais recente")
    ap.add_argument("--sem-download", action="store_true", help="não baixa dados novos")
    ap.add_argument("--nao-abrir", action="store_true", help="não abre o navegador")
    a = ap.parse_args()

    # 'vespera' e 'diario' nunca foram horas do relógio: continuam aceitos em --hora
    if a.hora and a.hora.lower() in ("vespera", "véspera", "diario", "diária", "diaria", "d"):
        a.feita_as, a.hora = a.feita_as or a.hora.lower().replace("é", "e"), None
    hora = ler_hora(a.hora, a.dia) if a.hora else None    # minutos desde 0h (None = sem hora pedida)
    corte = corte_para_hora(a.feita_as)        # ex.: '13:30' -> '13h'; nada -> 'abertura'
    agora = pd.Timestamp.now(tz=TZ)            # relógio usado para saber o que já aconteceu

    # --- 1 e 2. Dados e painel as-of ---
    print("Carregando dados…")
    dd, hh = baixar(atualizar=not a.sem_download)
    arq = CACHE / "painel.parquet"
    if a.sem_download and arq.exists():
        p = pd.read_parquet(arq)               # reaproveita o painel já montado
    else:
        p = painel(dd, hh)                     # remonta com os dados novos (leva alguns segundos)
        p.to_parquet(arq)

    # linha criada antes da abertura e que ficou sem fechamento num dia já encerrado: descarta
    p = p[p["fech"].notna() | (p["dia"].dt.tz_localize(TZ) + pd.Timedelta(hours=18, minutes=45) > agora)]

    # --- 3. Previsões fora da amostra e métricas de qualidade ---
    print("Treinando e prevendo (walk-forward)…\n")
    r = walk_forward(p, agora)
    met = metricas(r)

    # --- 3b. Previsões por momento (gráfico principal) ---
    dia = a.dia or r["dia"].max().strftime("%Y-%m-%d")
    m5 = baixar_5min(atualizar=not a.sem_download)
    mom = montar(p, r, dd, hh, m5, dia, agora, hora, corte if a.feita_as else None)

    # Para o gráfico intradiário só entram barras horárias já encerradas
    # (a barra que começa às 14h só "existe" às 15h).
    h = hh["ibov"]
    h = h[h.index + pd.Timedelta(hours=1) <= agora]

    # --- 4. Resultado do dia em texto (terminal + arquivo) ---
    print(gerar_relatorio(r, met, dia, corte, agora, momentos=mom))
    print(f"Resultado salvo em: {caminho(dia)}")

    # --- 5. Painel gráfico (pop-up no navegador) ---
    saida = gerar_html(r, h, met, corte, dia, grafico=mom)
    print(f"Painel gráfico:     {saida}")
    if not a.nao_abrir:
        webbrowser.open(saida.as_uri())


if __name__ == "__main__":
    main()
