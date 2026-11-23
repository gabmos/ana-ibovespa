"""
Pacote `ibov` — previsão do fechamento do IBOVESPA em vários horários do dia.

Módulos (na ordem em que são usados):
    dados.py      baixa cotações (Yahoo Finance) e monta o painel "as-of"
    modelo.py     treina um modelo por horário e gera previsões walk-forward
    relatorio.py  escreve o resultado do dia em texto claro (terminal + .txt)
    visual.py     gera o painel gráfico interativo (saida/painel.html)
    __main__.py   junta tudo:  python -m ibov  [--hora 13:30] [--dia AAAA-MM-DD]

Veja o README.md na raiz do projeto para a explicação completa.
"""
