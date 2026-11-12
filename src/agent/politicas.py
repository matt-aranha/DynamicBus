# -*- coding: utf-8 -*-
"""Políticas de referência para comparar com o Q-Learning."""
import numpy as np


class PoliticaFixa:
    """Cada ônibus continua sempre na linha em que começou (nada de redistribuição)."""
    nome = "fixa"

    def escolher(self, dec):
        l = dec.onibus.linha
        return l if l in dec.opcoes else next(iter(dec.opcoes))


class PoliticaProporcional:
    """A regra que o enunciado descreve: a frota se distribui na proporção dos passageiros excedentes conhecidos.

    O ônibus escolhe a linha em que o 'déficit' é maior: (parcela da demanda) - (parcela da frota).
    """
    nome = "proporcional"

    def escolher(self, dec):
        exc, fr = dec.excedentes, dec.frota
        tot_e = sum(exc.values()) or 1
        tot_f = (sum(fr.values()) + 1)
        melhor, melhor_v = None, -1e9
        for l in dec.opcoes:
            v = exc[l] / tot_e - (fr.get(l, 0)) / tot_f
            if v > melhor_v:
                melhor, melhor_v = l, v
        return melhor


class PoliticaAleatoria:
    nome = "aleatoria"

    def __init__(self, seed=0):
        self.rng = np.random.default_rng(seed)

    def escolher(self, dec):
        return list(dec.opcoes)[int(self.rng.integers(len(dec.opcoes)))]


class PoliticaQ:
    """Usa a Q-table treinada de forma gulosa (sem exploração)."""
    nome = "qlearning"

    def __init__(self, agente, cfg):
        self.agente, self.cfg = agente, cfg

    def escolher(self, dec):
        i = self.agente.escolher(dec.estado, dec.mask, treino=False)
        return self.cfg.LINHAS[i]
