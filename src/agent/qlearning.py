# -*- coding: utf-8 -*-
"""Q-Learning tabular com tabela compartilhada por todos os ônibus."""
import json
import numpy as np


class AgenteQLearning:
    def __init__(self, cfg, n_acoes=None, seed=0):
        self.cfg = cfg
        self.n = n_acoes or len(cfg.LINHAS)
        self.q = {}
        self.epsilon = cfg.EPSILON_INICIAL
        self.rng = np.random.default_rng(seed)

    def _linha(self, estado):
        if estado not in self.q:
            self.q[estado] = np.full(self.n, float(self.cfg.Q_INICIAL))   # início "otimista": ações ainda não testadas parecem boas
        return self.q[estado]

    def escolher(self, estado, mask, treino=True):
        validas = [i for i, ok in enumerate(mask) if ok]
        if treino and self.rng.random() < self.epsilon:
            return int(self.rng.choice(validas))
        q = self._linha(estado)
        melhor = max(q[i] for i in validas)
        return int(self.rng.choice([i for i in validas if q[i] == melhor]))

    def atualizar(self, estado, acao, recompensa, dt, prox_estado, prox_mask, fim=False):
        cfg = self.cfg
        q = self._linha(estado)
        alvo = recompensa
        if not fim:
            qn = self._linha(prox_estado)
            alvo += (cfg.GAMA ** (dt / cfg.DT_REFERENCIA_S)) * max(qn[i] for i, ok in enumerate(prox_mask) if ok)
        q[acao] += cfg.ALFA * (alvo - q[acao])

    def fim_do_episodio(self):
        self.epsilon = max(self.cfg.EPSILON_FINAL, self.epsilon * self.cfg.EPSILON_DECAIMENTO)

    # -- persistência -------------------------------------------------------------------
    def salvar(self, caminho):
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"epsilon": self.epsilon, "q": {",".join(map(str, k)): v.tolist() for k, v in self.q.items()}}, f)

    def carregar(self, caminho):
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
        self.epsilon = d.get("epsilon", self.cfg.EPSILON_FINAL)
        self.q = {tuple(int(x) for x in k.split(",")): np.array(v) for k, v in d["q"].items()}
        return self
