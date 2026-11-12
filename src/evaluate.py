# -*- coding: utf-8 -*-
"""Compara o Q-Learning com as políticas de referência nos MESMOS cenários de passageiros.

    python -m src.evaluate --episodios 10
    python -m src.evaluate --episodios 3 --politicas fixa proporcional --gui
"""
import argparse
import csv

import numpy as np

from config import settings as cfg
from src.agent.politicas import PoliticaAleatoria, PoliticaFixa, PoliticaProporcional, PoliticaQ
from src.agent.qlearning import AgenteQLearning
from src.env.sumo_env import SumoBusEnv


def rodar_politica(env, politica, seed):
    env.reset(seed)
    while True:
        dec = env.proxima_decisao()
        if dec is None:
            break
        env.aplicar(dec, politica.escolher(dec))
    _, m = env.encerrar()
    return m


def main():
    ap = argparse.ArgumentParser(description="Avalia as políticas de distribuição da frota")
    ap.add_argument("--episodios", type=int, default=10)
    ap.add_argument("--politicas", nargs="+", default=["fixa", "proporcional", "aleatoria", "qlearning"],
                    choices=["fixa", "proporcional", "aleatoria", "qlearning"])
    ap.add_argument("--qtable", default=None, help="padrão: <pasta de resultados>/qtable.json")
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--controlada", action="store_true")
    ap.add_argument("--estado", choices=["detalhado", "compacto"], help="sobrescreve TIPO_ESTADO de config/settings.py")
    ap.add_argument("--pasta-resultados", help="pasta de saída (padrão: results/)")
    ap.add_argument("--seed", type=int, default=cfg.SEED + 10_000, help="sementes de avaliação (diferentes das do treino)")
    a = ap.parse_args()
    if a.controlada:
        cfg.GERACAO_CONTROLADA = True
    if a.estado:
        cfg.TIPO_ESTADO = a.estado
    if a.pasta_resultados:
        from pathlib import Path
        cfg.PASTA_RESULTADOS = Path(a.pasta_resultados)
        cfg.ARQ_QTABLE = cfg.PASTA_RESULTADOS / "qtable.json"
    env = SumoBusEnv(cfg, gui=a.gui)
    pols = []
    for nome in a.politicas:
        if nome == "fixa": pols.append(PoliticaFixa())
        elif nome == "proporcional": pols.append(PoliticaProporcional())
        elif nome == "aleatoria": pols.append(PoliticaAleatoria(a.seed))
        elif nome == "qlearning":
            try:
                pols.append(PoliticaQ(AgenteQLearning(cfg).carregar(a.qtable or cfg.ARQ_QTABLE), cfg))
            except FileNotFoundError:
                print(f"(sem Q-table em {a.qtable or cfg.ARQ_QTABLE}; rode primeiro python -m src.train)")
    chaves = ["espera_por_passageiro_min", "espera_media_concluidos_min", "espera_p95_concluidos_min",
              "passageiros_concluidos", "esperando_no_fim", "espera_total_pass_min", "lotacao_maxima"]
    linhas, resumo = [], {}
    print(f"Geração: {'CONTROLADA' if cfg.GERACAO_CONTROLADA else 'ALEATÓRIA'} | {a.episodios} episódio(s) por política, mesmas sementes\n")
    try:
        for pol in pols:
            ms = []
            for k in range(a.episodios):
                m = rodar_politica(env, pol, seed=a.seed + k)
                ms.append(m)
                linhas.append({"politica": pol.nome, "episodio": k + 1, **{c: round(m[c], 3) for c in chaves},
                               "passageiros_gerados": m["passageiros_gerados"]})
            resumo[pol.nome] = {c: (float(np.nanmean([m[c] for m in ms])), float(np.nanstd([m[c] for m in ms]))) for c in chaves}
            print(f"{pol.nome:<13} espera/passageiro {resumo[pol.nome]['espera_por_passageiro_min'][0]:6.2f} min | "
                  f"concluídos {resumo[pol.nome]['passageiros_concluidos'][0]:7.0f} | esperando no fim {resumo[pol.nome]['esperando_no_fim'][0]:6.0f}")
    finally:
        env.encerrar_sumo()
    cfg.PASTA_RESULTADOS.mkdir(exist_ok=True)
    caminho = cfg.PASTA_RESULTADOS / "avaliacao.csv"
    with open(caminho, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader(); w.writerows(linhas)
    print("\nResumo (média ± desvio-padrão):")
    print(f"{'política':<13}" + "".join(f"{c[:26]:>28}" for c in chaves[:4]))
    for nome, r in resumo.items():
        print(f"{nome:<13}" + "".join(f"{r[c][0]:>18.2f} ± {r[c][1]:<6.2f}" for c in chaves[:4]))
    print(f"\nDetalhe por episódio em {caminho}")


if __name__ == "__main__":
    main()
