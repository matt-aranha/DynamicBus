# Passageiros, ambiente TraCI e Q-Learning

Rodar sempre da raiz do repositório (a pasta que contém `config/`, `src/`, `sumo/` e `data/`), com o ambiente virtual ativado.

```powershell
pip install numpy matplotlib sumolib traci pyproj
python -m src.train --episodios 100          # treina (≈ 15 s por episódio de 3 h simuladas)
python -m src.evaluate --episodios 10        # compara fixa x proporcional x aleatória x Q-Learning
python -m src.train --episodios 3 --gui      # assistir no sumo-gui (bem mais lento)
```

## Interruptor da geração de passageiros
Em `config/settings.py`:
```python
GERACAO_CONTROLADA = False   # False = aleatória (padrão) | True = lê data/passageiros_controlados.csv
```
Também dá para ligar sem editar o arquivo: `python -m src.train --controlada` e `python -m src.evaluate --controlada`.

**Aleatória.** Chegadas de Poisson, `PASSAGEIROS_POR_HORA` no total. A cada `FASE_DEMANDA_S` (30 min) a divisão da demanda entre
as linhas é sorteada (Dirichlet, `DIRICHLET_ALFA`): é isso que cria desequilíbrio entre as linhas e dá o que o agente aprender.
Cada passageiro recebe uma linha, um sentido, uma parada de origem (terminais têm peso `PESO_ORIGEM_TERMINAL`) e um destino
sempre à frente da origem, na mesma rota. Com `PESOS_FIXOS_LINHAS` a divisão fica travada.

**Controlada.** `data/passageiros_controlados.csv`, colunas `tempo_s, linha, sentido, origem, destino, quantidade`.
`origem`/`destino` aceitam o id da parada (`term_campus`, `bs_090i_05`) ou o número da parada no itinerário
(coluna `ordem` do `data/paradas_linhas.csv`). Erros no arquivo são explicados com o número da linha.

## Como a simulação funciona
- Cada passageiro nasce na parada de origem com a cor da sua linha (`pass090`, `pass091`, `pass050` em `vtypes.rou.xml`),
  espera o ônibus da **sua** linha e desce na parada de destino. O SUMO impõe a capacidade (40): quem não cabe continua esperando.
- Cada ônibus percorre ida e volta. **Ao entrar na última aresta de um percurso (um terminal), ele decide a linha do próximo percurso.**
  Campus: 090, 091 ou 050 (ida). D.I.A.: 090 ou 091 (volta). Hospital Universitário: só a 050, então é automático.
- **Excedentes:** toda vez que um ônibus sai de um terminal, a simulação conta quantos passageiros ficaram esperando ali, por linha.
  Esse valor fica guardado e é o que os ônibus "sabem" sobre a demanda (eles não enxergam as paradas intermediárias).

## Q-Learning
- Agentes: os ônibus (uma Q-table compartilhada). Ações: linha do próximo percurso (090, 091, 050), só as possíveis no terminal.
- Estado (`TIPO_ESTADO`): `detalhado` = (terminal, nível de excedentes de cada linha, nível da frota de cada linha, sem contar o ônibus que decide);
  `compacto` = (terminal, nível do total de excedentes, falta/sobra de frota em cada linha).
- Recompensa de cada decisão: **passageiros que o próprio ônibus embarcou no percurso / capacidade** (`PESO_RECOMPENSA_LOCAL`). Existe também um termo da rede toda
  (`PESO_RECOMPENSA_EQUIPE`, passageiros-minuto esperando), desligado por padrão: na 1ª versão, só com ele, o agente concentrou a frota numa linha e ficou pior que a frota fixa,
  porque o efeito da decisão de um ônibus se perde no ruído da rede inteira. Cada decisão é atualizada quando o mesmo ônibus decide de novo (Q-Learning SMDP).
- Comparações (`src.evaluate`), nas mesmas sementes: `fixa` (cada ônibus fica na sua linha), `proporcional` (a regra do enunciado:
  frota proporcional aos excedentes conhecidos), `aleatoria` e `qlearning`.

## Saídas (pasta `results/`)
`qtable.json`, `qtable_melhor.json`, `treino_log.csv`, `treino_curva.png`, `avaliacao.csv`.

## Resultado de referência (5 episódios, mesmas sementes, demanda aleatória)
Q-table treinada com 60 episódios, estado `compacto`, recompensa local:

| Política | Espera média por passageiro |
|---|---|
| Fixa | 13,15 min |
| Aleatória | 11,88 min |
| **Q-Learning** | **11,21 ± 1,17 min** |
| Proporcional | 10,94 min |

O Q-Learning reduz a espera em cerca de 15% sobre a frota fixa e fica a ~2,5% da regra proporcional (diferença dentro do ruído de 5 episódios).
Treinar mais episódios (200+) e avaliar com mais sementes (20+) é o próximo passo.
