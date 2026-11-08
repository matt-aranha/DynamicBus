# Gerador de rotas e paradas (linhas 090, 091 e 050)

Rodar sempre da raiz do repositório (a pasta que contém `sumo/`, `data/` e `tools/`).

## Uso

```powershell
pip install sumolib pyproj
python tools/gerar_cenario.py                          # offline: posiciona as paradas pela ordem do itinerário
python tools/gerar_cenario.py --diagnosticar-ruas      # (internet) confere ruas não encontradas / hipóteses no Nominatim
python tools/gerar_cenario.py --geocodificar --contato seu-email@dominio.com   # (internet) usa o endereço de cada parada
```

O Nominatim limita a 1 consulta por segundo; as respostas ficam em `data/cache_geocode.json`,
então a segunda execução é instantânea e funciona offline.

## O que conferir no netedit
1. `File > Open Network...` e abra `sumo/net/net_linhas_090_091_050.net.xml`.
2. `File > Additional Elements > Load` e abra `sumo/additional/busstops_linhas.add.xml` e `sumo/additional/revisao_pois.add.xml`
   (pontos verdes = paradas geradas; pontos vermelhos = posição devolvida pela geocodificação).
3. Modo Demand: `File > Demand Elements > Load` com `sumo/routes/vtypes.rou.xml` e `sumo/routes/bus_routes.rou.xml`.
4. Use `data/relatorio_revisao.csv` (coluna `avisos`/`metodo`) para decidir quais paradas revisar primeiro.

## Paradas que não existem na rota real (`data/paradas_linhas.csv`)
A coluna `ativa` (`sim`/`nao`) liga e desliga uma parada. As desativadas continuam no CSV e aparecem no relatório como `desativada`.
Para reativar, troque `nao` por `sim` e rode o gerador de novo.

## Trechos de rota informados à mão (`trechos_fixos` em `data/overrides_rotas.json`)
```json
"050_ida": {"trechos_fixos": [{"arestas": ["ID_A", "ID_B", "ID_C"]}]}
```
A rota é obrigada a percorrer exatamente essa sequência, na ordem. O gerador acha sozinho em que ponto da rota ela se encaixa
(onde causa o menor desvio). Se duas arestas consecutivas não tiverem ligação direta no net, ele completa pelo menor caminho
e avisa no terminal (`AVISO: ... não há ligação direta; completei com [...]`).

## Terminais
A fonte dos terminais é `sumo/additional/terminais.add.xml`. O `busstops_linhas.add.xml` é regenerado a cada execução,
então qualquer ajuste de terminal deve ser feito em `terminais.add.xml`.

## Outros ajustes (`data/overrides_rotas.json`)
```json
{
  "050_ida":   {"paradas_fixas": {"26": {"edge": "ID_DA_ARESTA", "pos": 30}}},
  "050_volta": {"inicio": "ID_DA_ARESTA", "ruas_extras": ["Avenida João Ribeiro"]}
}
```
- `paradas_fixas`: número da parada na rota -> aresta e posição (m) exatas; a rota é obrigada a passar por ali.
- `inicio` / `fim`: aresta de partida/chegada quando a linha não começa/termina em terminal (caso do Hospital Universitário).
- `ruas_extras`: ruas que a rota pode usar sem penalidade além das do itinerário.

## Nomes de rua e arestas (`data/aliases_ruas.json`)
A chave é o nome da rua do itinerário já normalizado (minúsculas, sem acento, sem "de/da/do", abreviações expandidas:
"Av. Gen. Euclides Figueiredo" vira `avenida general euclides figueiredo`; "Rua Do Carmo" vira `rua carmo`).

Dois formatos:
```json
"rua carmo": {"arestas": ["216463968"]}
"avenida marechal candido rondon": {"osm": ["Avenida Marechal Cândido Mariano da Silva Rondon"]}
```
- `arestas`: ids que você escolheu no netedit. Um id **sem** `#` vale para todas as partes `#0, #1, ...` (mesmo sinal);
  um id **com** `#` vale só para ele; o sinal `-` é respeitado. A rota é obrigada a passar por essas arestas.
- `ponto_unico: true`: todas as paradas dessa rua na rota viram uma só parada, no meio da aresta.
- `osm`: nomes exatos de rua no OSM (só ajuda o roteamento e a escolha da posição da parada).
