# DynamicBus

Distribuição dinâmica da frota de ônibus de Aracaju-SE com **Q-Learning**, simulada no **Eclipse SUMO** e controlada em Python via **TraCI**.

Versão 1.0 do projeto da disciplina de Fundamentos de Inteligência Artificial (UFS, Departamento de Computação).

## Visão geral

Uma frota fixa de 15 ônibus (capacidade de 40 passageiros) atende três linhas urbanas. A demanda de cada linha muda ao longo do tempo, então uma divisão fixa da frota deixa passageiros esperando numa linha enquanto ônibus circulam quase vazios em outra. Os ônibus são os agentes: ao chegar a um terminal, cada um decide a linha do próximo percurso, com base nos passageiros excedentes que conhece.

| Linha | Trajeto | Cor do ônibus |
|---|---|---|
| 090 | Terminal D.I.A. ↔ Terminal Campus, via Av. Tancredo Neves | vermelho |
| 091 | Terminal D.I.A. ↔ Terminal Campus, via bairro Santa Lúcia | azul |
| 050 | Terminal Campus ↔ Hospital Universitário, passando pelo Terminal Maracaju | verde |

Os passageiros têm a cor escura da sua linha. As rotas (ida e volta), os 4 terminais (Campus, D.I.A., Maracaju e Zona Oeste) e as paradas intermediárias foram montados a partir do OpenStreetMap e conferidos à mão contra os itinerários reais.

## Resultados

Cinco episódios de 3 h simuladas, mesmas sementes para todas as políticas, demanda aleatória:

| Política | Espera média por passageiro |
|---|---|
| Fixa (cada ônibus fica na sua linha) | 13,15 min |
| Aleatória | 11,88 min |
| **Q-Learning** (60 episódios de treino) | **11,21 ± 1,17 min** |
| Proporcional (frota proporcional aos excedentes) | 10,94 min |

O Q-Learning reduz a espera em cerca de 15% em relação à frota fixa e fica a cerca de 2,5% da regra proporcional. Essa diferença está dentro do ruído de 5 episódios, então **ainda não está demonstrado que ele supera a regra proporcional**. Mais episódios de treino e mais sementes de avaliação estão previstos (veja o [Roteiro](#roteiro)).

No cenário controlado de pico da linha 050 (`data/passageiros_controlados.csv`), a frota fixa deixa 23,2 min de espera por passageiro contra 8,5 min com redistribuição.

## Como funciona

- **Simulação:** o SUMO simula ônibus e passageiros. Cada passageiro nasce numa parada, espera apenas o ônibus da sua linha e desce numa parada à frente na mesma rota. A capacidade de 40 é aplicada: quem não cabe continua esperando.
- **Decisão:** o ônibus decide ao entrar na última aresta de um percurso, que é um terminal. No Campus escolhe entre 090, 091 e 050 (ida). No D.I.A. escolhe entre 090 e 091 (volta). No Hospital Universitário só existe a 050, então a decisão é automática.
- **Excedentes:** toda vez que um ônibus sai de um terminal, conta-se quantos passageiros ficaram esperando ali, por linha. Os ônibus só conhecem esse valor, não enxergam as paradas intermediárias.
- **Estado** (`TIPO_ESTADO = "compacto"`): terminal, nível total de excedentes e falta ou sobra de frota em cada linha (243 estados possíveis). Existe também o estado `detalhado`.
- **Ação:** a linha do próximo percurso (090, 091 ou 050), entre as possíveis naquele terminal.
- **Recompensa:** passageiros que o próprio ônibus embarcou no percurso, divididos pela capacidade. Uma recompensa compartilhada por toda a frota foi testada primeiro e piorou o resultado (o agente concentrou a frota numa linha), pois o efeito da decisão de um ônibus se perde no ruído da rede inteira.
- **Aprendizado:** Q-Learning tabular com uma Q-table compartilhada por todos os ônibus.

Detalhes e parâmetros em [`docs/PASSAGEIROS_E_QLEARNING.md`](docs/PASSAGEIROS_E_QLEARNING.md).

## Requisitos

- Python 3.10 ou mais novo
- [Eclipse SUMO](https://sumo.dlr.de/docs/Downloads.php) 1.28 (a versão em que o projeto foi desenvolvido), com a variável de ambiente `SUMO_HOME` apontando para a instalação
- Pacotes Python: `numpy`, `matplotlib`, `pyproj`, `sumolib`, `traci`

## Instalação

```powershell
git clone <URL-DO-REPOSITORIO> DynamicBus
cd DynamicBus
python -m venv .venv
.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt     # ou: pip install numpy matplotlib pyproj sumolib traci
```

Confira a instalação:

```powershell
sumo --version
python -c "import traci, sumolib, pyproj, numpy; print('ambiente ok')"
```

## Uso

Rode sempre da raiz do repositório.

```powershell
python -m src.evaluate --episodios 5      # compara fixa, aleatória, proporcional e Q-Learning (usa results/qtable.json)
python -m src.train --episodios 100       # treina uma nova Q-table (~15 s por episódio de 3 h simuladas)
python -m src.train --episodios 100 --continuar   # continua a partir de results/qtable.json
python -m src.train --controlada --episodios 3    # passageiros do CSV em vez de aleatórios
python -m src.train --episodios 2 --gui   # assiste no sumo-gui (bem mais lento)
```

Para ver apenas o cenário, com um ônibus por rota:

```powershell
sumo-gui -c sumo/teste_rotas.sumocfg
```

Os resultados ficam em `results/`: `qtable.json`, `treino_log.csv`, `treino_curva.png` e `avaliacao.csv`.

### Geração de passageiros: aleatória ou controlada

Um interruptor global em [`config/settings.py`](config/settings.py) escolhe o modo:

```python
GERACAO_CONTROLADA = False   # False = aleatória (padrão) | True = lê data/passageiros_controlados.csv
```

- **Aleatória:** chegadas de Poisson (`PASSAGEIROS_POR_HORA`). A cada 30 min a divisão da demanda entre as linhas é sorteada, o que cria o desequilíbrio que o agente precisa aprender a atender.
- **Controlada:** o CSV tem as colunas `tempo_s, linha, sentido, origem, destino, quantidade`. `origem` e `destino` aceitam o id da parada (`term_campus`, `bs_090i_05`) ou o número da parada no itinerário. Erros no arquivo são explicados com o número da linha.

Tamanho da frota, capacidade, duração do episódio e parâmetros do Q-Learning também ficam em `config/settings.py`.

## Estrutura do repositório

```
DynamicBus/
├── config/settings.py          # todos os parâmetros e o interruptor de geração
├── data/
│   ├── paradas_linhas.csv      # itinerários (linha, sentido, ordem, rua, número)
│   ├── aliases_ruas.json       # nome da rua no itinerário -> arestas/nomes no OSM
│   ├── overrides_rotas.json    # ajustes manuais de rotas e paradas
│   ├── passageiros_controlados.csv
│   ├── relatorio_revisao.csv   # método de posicionamento de cada parada
│   └── arestas_por_rua.csv
├── docs/PASSAGEIROS_E_QLEARNING.md
├── results/                    # Q-table, logs, gráficos
├── src/
│   ├── agent/                  # qlearning.py, politicas.py
│   ├── env/                    # network_data.py, passenger_gen.py, fleet.py, sumo_env.py
│   ├── utils/logger.py
│   ├── train.py
│   └── evaluate.py
├── sumo/
│   ├── osm/aracaju.osm
│   ├── net/net_linhas_090_091_050.net.xml
│   ├── additional/             # terminais.add.xml, busstops_linhas.add.xml, revisao_pois.add.xml
│   ├── routes/                 # vtypes.rou.xml, bus_routes.rou.xml, teste_visual.rou.xml
│   └── teste_rotas.sumocfg
├── tools/                      # gerar_cenario.py, gerar_csv_itinerarios.py, LEIA-ME.md
└── tests/
```

## Regenerar o cenário SUMO

A rede (`.net.xml`) é gerada a partir do `.osm` recortado na região das linhas. Este comando foi o usado, na raiz do repositório:

```powershell
netconvert --osm-files sumo/osm/aracaju.osm -o sumo/net/net_linhas_090_091_050.net.xml `
  --keep-edges.in-geo-boundary -37.132828,-10.974419,-37.045374,-10.873508 `
  --remove-edges.isolated true --osm.all-attributes true `
  --tls.guess-signals true --tls.discard-simple true `
  --geometry.remove true --roundabouts.guess true --junctions.join true
```

Depois, as rotas e as paradas são geradas a partir dos itinerários:

```powershell
python tools/gerar_cenario.py
```

Isso reescreve `busstops_linhas.add.xml`, `bus_routes.rou.xml`, `revisao_pois.add.xml` e `data/relatorio_revisao.csv`. Ajustes dos terminais devem ser feitos em `sumo/additional/terminais.add.xml`, e correções de rota ou de parada em `data/overrides_rotas.json` e `data/aliases_ruas.json`. Veja [`tools/LEIA-ME.md`](tools/LEIA-ME.md).

O arquivo `net_linhas_090_091_050.net.xml` tem cerca de 63 MB. O GitHub avisa acima de 50 MB e bloqueia acima de 100 MB, então considere o Git LFS se o tamanho crescer.

## Limitações

- O Q-Learning foi avaliado com apenas 5 episódios e 60 de treino, então a comparação com a regra proporcional ainda não é conclusiva.
- A demanda aleatória é sintética (1500 passageiros por hora, divisão sorteada entre as linhas) e não foi calibrada com dados reais.
- A posição das paradas intermediárias vem do itinerário publicado e de uma regra de ordenação, e não de coordenadas medidas. A coluna `metodo` de `data/relatorio_revisao.csv` indica como cada uma foi posicionada.
- O ônibus decide só nos terminais, cerca de 100 decisões por episódio de 3 h.

## Roteiro

- Treinar 200 ou mais episódios e avaliar com 20 ou mais sementes, com intervalo de confiança.
- Ajustar os níveis do estado e a taxa de aprendizado e comparar os resultados.
- Comparar com o estado `detalhado` e, depois, com Deep Q-Learning.
- Testar decisões em outros pontos da rota e um custo para a troca de linha.
- Calibrar a demanda com dados reais de horários de pico.

## Autores

Desenvolvido por: Mateus Aranha, Natália Andrade, Iago, Daniel, Luan e Lucas Celestino.

## Licença

Veja o arquivo [`LICENSE`](LICENSE).