# -*- coding: utf-8 -*-
# Configurações globais do projeto DynamicBus (distribuição dinâmica da frota de ônibus com Q-Learning).

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# ======================================================================================
# INTERRUPTOR DA GERAÇÃO DE PASSAGEIROS
# ======================================================================================
#   False -> geração ALEATÓRIA (padrão): passageiros sorteados com as regras da seção "Demanda aleatória".
#   True  -> geração CONTROLADA: os passageiros vêm do arquivo ARQUIVO_PASSAGEIROS_CONTROLADOS.
GERACAO_CONTROLADA = False
ARQUIVO_PASSAGEIROS_CONTROLADOS = RAIZ / "data" / "passageiros_controlados.csv"

# ======================================================================================
# Arquivos do cenário SUMO
# ======================================================================================
ARQ_REDE = RAIZ / "sumo" / "net" / "net_linhas_090_091_050.net.xml"
ARQ_PARADAS = RAIZ / "sumo" / "additional" / "busstops_linhas.add.xml"
ARQ_VTYPES = RAIZ / "sumo" / "routes" / "vtypes.rou.xml"
ARQ_ROTAS = RAIZ / "sumo" / "routes" / "bus_routes.rou.xml"
ARQ_RELATORIO_PARADAS = RAIZ / "data" / "relatorio_revisao.csv"   # usado só para ler a geração controlada pelo nº da parada

LINHAS = ("090", "091", "050")   # a ordem aqui define a ordem dos estados do Q-Learning

# ======================================================================================
# Frota
# ======================================================================================
NUM_ONIBUS = 15                  # frota fixa
CAPACIDADE_ONIBUS = 40           # definida nos vTypes (sumo/routes/vtypes.rou.xml: personCapacity)
DISTRIBUICAO_INICIAL = {"090": 5, "091": 5, "050": 5}   # soma = NUM_ONIBUS
INTERVALO_SAIDA_S = 150          # os ônibus de uma mesma linha saem do Campus com esse espaçamento
PARADA_DURACAO_S = 15            # tempo mínimo parado em cada parada (definido em bus_routes.rou.xml)

# ======================================================================================
# Simulação
# ======================================================================================
DURACAO_EPISODIO_S = 3 * 3600    # 3h simuladas por episódio
PASSO_S = 1.0                    # passo do SUMO em segundos
SEED = 42

# ======================================================================================
# Demanda aleatória (usada quando GERACAO_CONTROLADA = False)
# ======================================================================================
PASSAGEIROS_POR_HORA = 1500      # total, somando as três linhas
FASE_DEMANDA_S = 1800            # a cada 30 min a divisão da demanda entre as linhas é sorteada de novo
DIRICHLET_ALFA = 1.2             # menor = demanda mais desbalanceada entre as linhas (mais difícil, mais interessante)
PESOS_FIXOS_LINHAS = None        # ex.: {"090": 0.5, "091": 0.2, "050": 0.3} para travar a divisão (sem sorteio)
PESO_ORIGEM_TERMINAL = 5.0       # quanto mais provável é um passageiro surgir num terminal (1 = igual às demais paradas)
FIM_DA_DEMANDA_S = 20 * 60       # nos últimos 20 min não surgem passageiros novos (para dar tempo de atendê-los)

# ======================================================================================
# Q-Learning
# ======================================================================================
TIPO_ESTADO = "compacto"         # "detalhado": nível de excedentes + nível de frota de cada linha (3.456 estados possíveis)
                                 # "compacto":  nível total de excedentes + déficit de frota por linha (243 estados possíveis; aprende mais rápido)
NIVEIS_EXCEDENTE = (5, 20, 50)   # limites que viram os níveis 0, 1, 2 e 3 de passageiros excedentes por linha
NIVEIS_EXCEDENTE_TOTAL = (15, 60)  # (estado compacto) limites do nível do total de excedentes: 0, 1 ou 2
LIMITE_DEFICIT = 0.15            # (estado compacto) diferença entre a parcela da demanda e a da frota que conta como falta/sobra
NIVEIS_FROTA = (3, 6)            # limites que viram os níveis 0, 1 e 2 de ônibus por linha (sem contar o que decide)
ALFA = 0.10                      # taxa de aprendizado
GAMA = 0.80                      # desconto (por DT_REFERENCIA_S segundos)
Q_INICIAL = 6.0                  # valor inicial "otimista" da Q-table (força a experimentar todas as ações)
DT_REFERENCIA_S = 1200
EPSILON_INICIAL = 1.0
EPSILON_FINAL = 0.05
EPSILON_DECAIMENTO = 0.97        # multiplicado a cada episódio
# Recompensa de cada decisão (soma de dois termos; zere o peso de um deles para desligá-lo):
PESO_RECOMPENSA_LOCAL = 1.0      # + (passageiros que ESTE ônibus embarcou no percurso) / CAPACIDADE_ONIBUS
PESO_RECOMPENSA_EQUIPE = 0.0     # - (passageiros-minuto esperando em toda a rede) / ESCALA_RECOMPENSA  (ruidoso: veja docs)
ESCALA_RECOMPENSA = 1000.0

# ======================================================================================
# Saídas
# ======================================================================================
PASTA_RESULTADOS = RAIZ / "results"
ARQ_QTABLE = PASTA_RESULTADOS / "qtable.json"
