# -*- coding: utf-8 -*-
"""Treino do Q-Learning.

    python -m src.train --episodios 100            # treino sem janela (rápido)
    python -m src.train --episodios 5 --gui        # assistir no sumo-gui
    python -m src.train --controlada --episodios 30   # usa o CSV de passageiros controlados
"""
import argparse
import time

import numpy as np

from config import settings as cfg
from src.agent.qlearning import AgenteQLearning
from src.env.sumo_env import SumoBusEnv
from src.utils.logger import LogCSV


def rodar_episodio(env, agente, seed, treino=True):
    """Roda um episódio inteiro com o agente (treino=True atualiza a Q-table)."""
    env.reset(seed)
    while True:
        dec = env.proxima_decisao()
        if dec is None:
            break
        if treino and dec.anterior is not None:
            s0, a0, r, dt = dec.anterior
            agente.atualizar(s0, a0, r, dt, dec.estado, dec.mask)
        a = agente.escolher(dec.estado, dec.mask, treino=treino)
        env.aplicar(dec, cfg.LINHAS[a])
    finais, metricas = env.encerrar()
    if treino:
        for s0, a0, r, dt in finais:
            agente.atualizar(s0, a0, r, dt, None, None, fim=True)
        agente.fim_do_episodio()
    return metricas


def main():
    ap = argparse.ArgumentParser(description="Treina o Q-Learning da distribuição dinâmica da frota")
    ap.add_argument("--episodios", type=int, default=100)
    ap.add_argument("--gui", action="store_true", help="abre o sumo-gui (bem mais lento)")
    ap.add_argument("--controlada", action="store_true", help="liga GERACAO_CONTROLADA (lê data/passageiros_controlados.csv)")
    ap.add_argument("--continuar", action="store_true", help="continua a partir de results/qtable.json")
    ap.add_argument("--estado", choices=["detalhado", "compacto"], help="sobrescreve TIPO_ESTADO de config/settings.py")
    ap.add_argument("--pasta-resultados", help="pasta de saída (padrão: results/)")
    ap.add_argument("--seed", type=int, default=cfg.SEED)
    a = ap.parse_args()
    if a.controlada:
        cfg.GERACAO_CONTROLADA = True
    if a.estado:
        cfg.TIPO_ESTADO = a.estado
    if a.pasta_resultados:
        from pathlib import Path
        cfg.PASTA_RESULTADOS = Path(a.pasta_resultados)
        cfg.ARQ_QTABLE = cfg.PASTA_RESULTADOS / "qtable.json"
    print(f"Geração de passageiros: {'CONTROLADA (CSV)' if cfg.GERACAO_CONTROLADA else 'ALEATÓRIA'}")

    env = SumoBusEnv(cfg, gui=a.gui)
    agente = AgenteQLearning(cfg, seed=a.seed)
    if a.continuar and cfg.ARQ_QTABLE.exists():
        agente.carregar(cfg.ARQ_QTABLE)
        print(f"Q-table carregada ({len(agente.q)} estados), epsilon={agente.epsilon:.2f}")
    log = LogCSV(cfg.PASTA_RESULTADOS / "treino_log.csv")
    melhor = -1e18
    janela = []
    try:
        for ep in range(1, a.episodios + 1):
            t0 = time.time()
            eps = agente.epsilon
            m = rodar_episodio(env, agente, seed=a.seed + ep, treino=True)
            janela.append(-m["espera_por_passageiro_min"])
            media = float(np.mean(janela[-10:]))
            log.escrever({"episodio": ep, "epsilon": round(eps, 3), "estados_na_qtable": len(agente.q),
                          **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()},
                          "segundos": round(time.time() - t0, 1)})
            print(f"ep {ep:>3}/{a.episodios} | eps {eps:.2f} | "
                  f"espera/passageiro {m['espera_por_passageiro_min']:5.1f} min (média 10: {-media:5.1f}) | concluídos {m['passageiros_concluidos']}/{m['passageiros_gerados']} | "
                  f"decisões {m['decisoes_aprendidas']} | estados {len(agente.q)} | {time.time() - t0:4.0f}s")
            agente.salvar(cfg.ARQ_QTABLE)
            if media > melhor and ep >= 10:
                melhor = media
                agente.salvar(cfg.PASTA_RESULTADOS / "qtable_melhor.json")
    except KeyboardInterrupt:
        print("\nTreino interrompido; a Q-table até aqui está salva.")
    finally:
        env.encerrar_sumo()
    print(f"\nQ-table salva em {cfg.ARQ_QTABLE}")
    print(f"Log por episódio em {cfg.PASTA_RESULTADOS / 'treino_log.csv'}")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import csv
        with open(cfg.PASTA_RESULTADOS / "treino_log.csv", encoding="utf-8-sig") as f:
            linhas = list(csv.DictReader(f))
        x = [int(r["episodio"]) for r in linhas]
        fig, ax = plt.subplots(1, 2, figsize=(11, 4))
        ax[0].plot(x, [-float(r["espera_por_passageiro_min"]) for r in linhas], alpha=.4, label="por episódio")
        k = min(10, len(x))
        if k > 1:
            mm = np.convolve([-float(r["espera_por_passageiro_min"]) for r in linhas], np.ones(k) / k, mode="valid")
            ax[0].plot(x[k - 1:], mm, label=f"média móvel ({k})")
        ax[0].set_xlabel("episódio"); ax[0].set_ylabel("- espera por passageiro (min)"); ax[0].legend(); ax[0].set_title("Desempenho (maior = melhor)")
        ax[1].plot(x, [float(r["espera_por_passageiro_min"]) for r in linhas])
        ax[1].set_xlabel("episódio"); ax[1].set_ylabel("espera por passageiro (min)"); ax[1].set_title("Espera média")
        fig.tight_layout(); fig.savefig(cfg.PASTA_RESULTADOS / "treino_curva.png", dpi=120)
        print(f"Gráfico em {cfg.PASTA_RESULTADOS / 'treino_curva.png'}")
    except Exception as ex:
        print("(gráfico não gerado:", ex, ")")


if __name__ == "__main__":
    main()
