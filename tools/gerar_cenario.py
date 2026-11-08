#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gerar_cenario.py - monta rotas (ida/volta) e paradas das linhas 090, 091 e 050 no SUMO.

Entradas (relativas à raiz do repositório):
  sumo/net/net_linhas_090_091_050.net.xml   rede gerada pelo netconvert
  sumo/additional/terminais.add.xml         terminais posicionados à mão (busStop)
  data/paradas_linhas.csv                   itinerários (linha, sentido, ordem, rua, numero, ...)
  data/aliases_ruas.json                    nomes do itinerário -> nomes no OSM (opcional)
  data/overrides_rotas.json                 ajustes manuais por rota (opcional)

Saídas:
  sumo/additional/busstops_linhas.add.xml   terminais + paradas intermediárias
  sumo/routes/bus_routes.rou.xml            6 rotas (090/091/050 x ida/volta) com as paradas
  sumo/additional/revisao_pois.add.xml      pontos para conferir no netedit (verde = parada, vermelho = geocodificado)
  data/relatorio_revisao.csv                uma linha por parada, com método e avisos

Como as posições são decididas (nesta ordem de confiança):
  1. terminais: posição que você definiu;
  2. geocodificação (Nominatim) com número de porta, se cair a <= --max-dist-geo m da rota;
  3. ordem do itinerário: as paradas de uma mesma rua são espaçadas ao longo do trecho da rota
     que passa por essa rua, respeitando a ordem da lista;
  4. interpolação entre vizinhas, quando o nome da rua não existe no OSM.
"""
import argparse
import csv
import heapq
import json
import math
import os
import re
import sys
import time
import unicodedata
import difflib
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict, OrderedDict
from xml.sax.saxutils import quoteattr

try:
    import pyproj  # noqa: F401  (o sumolib precisa dele para converter lat/lon <-> x/y)
except ImportError:
    sys.exit("Falta o pacote 'pyproj'. Rode:  pip install pyproj   e execute o script novamente.")
import sumolib
from sumolib.geomhelper import polygonOffsetAndDistanceToPoint, positionAtShapeOffset

# --------------------------------------------------------------------------------------
# Normalização de nomes de rua
# --------------------------------------------------------------------------------------
ABREV = {"av": "avenida", "gen": "general", "mal": "marechal", "cel": "coronel", "pres": "presidente",
         "prof": "professor", "gov": "governador", "dr": "doutor", "trav": "travessa", "est": "estrada",
         "sen": "senador", "eng": "engenheiro", "pca": "praca", "tv": "travessa"}
ARTIGOS = {"de", "da", "do", "dos", "das", "e"}
TIPOS = {"avenida", "rua", "travessa", "estrada", "praca", "alameda", "rodovia", "via", "acesso", "ciclovia",
         "largo", "beco", "viela"}


def sem_acento(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def tokens(s):
    s = sem_acento(s).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = s.replace("presidentetancredo", "presidente tancredo")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [ABREV.get(t, t) for t in s.split()]
    return [t for t in toks if t not in ARTIGOS]


def partes(nome):
    """Divide nomes compostos ('Rua G Avenida Visconde de Maracaju') em [(tipo, núcleo), ...]."""
    toks = tokens(nome)
    out, atual = [], []
    for t in toks:
        if t in TIPOS and len(atual) >= 2:
            out.append(atual)
            atual = [t]
        else:
            atual.append(t)
    if atual:
        out.append(atual)
    res = []
    for p in out:
        tipo = p[0] if p[0] in TIPOS else ""
        nucleo = tuple(p[1:] if tipo else p)
        if nucleo:
            res.append((tipo, nucleo))
    return res


def chave_rua(texto):
    p = partes(texto)
    return p[0] if p else ("", ())


# --------------------------------------------------------------------------------------
# Rede
# --------------------------------------------------------------------------------------
class Rede:
    def __init__(self, caminho):
        print(f"Lendo rede {caminho} ...", flush=True)
        self.net = sumolib.net.readNet(caminho, withInternal=False, withPedestrianConnections=False)
        self.edge_cores = {}
        self.idx_tc = defaultdict(set)     # (tipo, núcleo) -> nomes OSM
        self.idx_core = defaultdict(set)   # núcleo -> nomes OSM
        self.edges_por_nome = defaultdict(list)
        for e in self.net.getEdges():
            nome = e.getParam("name", "")
            cores = set()
            if nome:
                self.edges_por_nome[nome].append(e.getID())
                for tipo, nuc in partes(nome):
                    cores.add(nuc)
                    self.idx_tc[(tipo, nuc)].add(nome)
                    self.idx_core[nuc].add(nome)
            self.edge_cores[e.getID()] = cores
        self._conn_cache = {}
        self.alias_edges = {}
        print(f"  {len(self.net.getEdges())} arestas, {len(self.edges_por_nome)} nomes de rua distintos", flush=True)

    def aplicar_aliases(self, aliases):
        """Aliases com 'arestas': liga o nome do itinerário a ids de aresta escolhidos manualmente.
        Um id sem '#' vale para todas as partes '#k' (mesmo sinal); um id com '#' vale só para ele."""
        todos = {e.getID() for e in self.net.getEdges()}
        for chave, info in aliases.items():
            if not isinstance(info, dict) or "arestas" not in info:
                continue
            ids = []
            for spec in info["arestas"]:
                achados = [i for i in todos if i == spec or ("#" not in spec and i.startswith(spec + "#"))]
                if not achados:
                    print(f"AVISO: alias '{chave}': aresta '{spec}' não existe na rede")
                ids.extend(sorted(achados, key=lambda i: (len(i), i)))
            self.alias_edges[chave] = ids
            marca = ("@" + chave,)
            for i in ids:
                self.edge_cores[i].add(marca)

    def permite(self, e, b):
        k = (e.getID(), b.getID())
        if k not in self._conn_cache:
            ok = False
            for c in e.getConnections(b):
                if c.getFromLane().allows("bus") and c.getToLane().allows("bus"):
                    ok = True
                    break
            self._conn_cache[k] = ok
        return self._conn_cache[k]

    def dijkstra(self, origem, destino, permitidas, fator_fora, fator_sem_nome=1.6):
        """Caminho de menor custo de 'origem' a 'destino' (ids de aresta), penalizando ruas fora do itinerário."""
        net = self.net
        src, dst = net.getEdge(origem), net.getEdge(destino)
        if src.getID() == dst.getID():
            return [src], 0.0
        dist = {src.getID(): 0.0}
        prev = {}
        heap = [(0.0, src.getID())]
        while heap:
            d, eid = heapq.heappop(heap)
            if d > dist.get(eid, 1e18):
                continue
            if eid == dst.getID():
                break
            e = net.getEdge(eid)
            for s in e.getOutgoing():
                if not s.allows("bus") or not self.permite(e, s):
                    continue
                cores = self.edge_cores[s.getID()]
                if cores & permitidas:
                    f = 1.0
                elif not cores:
                    f = fator_sem_nome
                else:
                    f = fator_fora
                custo = s.getLength() / max(s.getSpeed(), 3.0) * f
                if s.getToNode() == e.getFromNode() and s.getFromNode() == e.getToNode():
                    custo += 300.0  # retorno (U-turn) só em último caso
                nd = d + custo
                if nd < dist.get(s.getID(), 1e18):
                    dist[s.getID()] = nd
                    prev[s.getID()] = eid
                    heapq.heappush(heap, (nd, s.getID()))
        if dst.getID() not in dist:
            return None, float("inf")
        path = [dst.getID()]
        while path[-1] != src.getID():
            path.append(prev[path[-1]])
        path.reverse()
        return [net.getEdge(i) for i in path], dist[dst.getID()]

    def custo_aresta(self, s, permitidas, fator_fora, fator_sem_nome=1.6):
        cores = self.edge_cores[s.getID()]
        f = 1.0 if (cores & permitidas) else (fator_sem_nome if not cores else fator_fora)
        return s.getLength() / max(s.getSpeed(), 3.0) * f

    def arvore(self, origem, permitidas, fator_fora, reverso=False):
        """Custo mínimo de/para 'origem' até todas as arestas (custo = soma das arestas percorridas, sem a de origem)."""
        net = self.net
        dist = {origem: 0.0}
        heap = [(0.0, origem)]
        while heap:
            d, eid = heapq.heappop(heap)
            if d > dist.get(eid, 1e18):
                continue
            e = net.getEdge(eid)
            if not reverso:
                for t in e.getOutgoing():
                    if not t.allows("bus") or not self.permite(e, t):
                        continue
                    nd = d + self.custo_aresta(t, permitidas, fator_fora)
                    if nd < dist.get(t.getID(), 1e18):
                        dist[t.getID()] = nd
                        heapq.heappush(heap, (nd, t.getID()))
            else:
                c_e = self.custo_aresta(e, permitidas, fator_fora)
                for p in e.getIncoming():
                    if not p.allows("bus") or not self.permite(p, e):
                        continue
                    nd = d + c_e
                    if nd < dist.get(p.getID(), 1e18):
                        dist[p.getID()] = nd
                        heapq.heappush(heap, (nd, p.getID()))
        return dist

    def completar_cadeia(self, cadeia, rid=""):
        """Sequência exata de arestas informada à mão; se duas consecutivas não se ligam diretamente, completa pelo menor caminho."""
        net = self.net
        try:
            cheia = [net.getEdge(cadeia[0])]
            for nxt in cadeia[1:]:
                cur, ne = cheia[-1], net.getEdge(nxt)
                if ne in cur.getOutgoing() and self.permite(cur, ne):
                    cheia.append(ne)
                    continue
                seg, _ = self.dijkstra(cur.getID(), nxt, set(), 1.0)
                if seg is None:
                    print(f"  ERRO: {rid}: sem ligação entre {cur.getID()} e {nxt} no trecho fixo")
                    return None
                print(f"  AVISO: {rid}: entre {cur.getID()} e {nxt} não há ligação direta; completei com {[e.getID() for e in seg[1:-1]]}")
                cheia.extend(seg[1:])
            return cheia
        except KeyError as ex:
            print(f"  ERRO: {rid}: aresta {ex} do trecho fixo não existe na rede")
            return None

    def rota_por_pontos(self, pontos, permitidas, fator_fora, rid=""):
        """pontos: ids de aresta (str) ou sequências fixas (list). Devolve (arestas, custo) ou (None, (a, b))."""
        net = self.net
        total, custo, atual = [], 0.0, None

        def anexar(seg):
            if total and seg and total[-1].getID() == seg[0].getID():
                total.extend(seg[1:])
            else:
                total.extend(seg)
        for item in pontos:
            if isinstance(item, str):
                if atual is None:
                    total.append(net.getEdge(item))
                else:
                    seg, c = self.dijkstra(atual, item, permitidas, fator_fora)
                    if seg is None:
                        return None, (atual, item)
                    custo += c
                    anexar(seg)
                atual = item
            else:
                cadeia = self.completar_cadeia(item, rid)
                if cadeia is None:
                    return None, (item[0], item[-1])
                if atual is None:
                    total.extend(cadeia)
                else:
                    seg, c = self.dijkstra(atual, cadeia[0].getID(), permitidas, fator_fora)
                    if seg is None:
                        return None, (atual, cadeia[0].getID())
                    custo += c
                    anexar(seg)
                    total.extend(cadeia[1:])
                atual = cadeia[-1].getID()
        return total, custo


def inserir_trechos_fixos(rede, pontos, trechos, permitidas, fator_fora, rid):
    """Coloca cada sequência fixa de arestas entre os dois pontos de passagem onde ela causa o menor desvio."""
    ids_cadeias = {e for tr in trechos for e in tr["arestas"]}
    pontos = [p for k, p in enumerate(pontos) if k in (0, len(pontos) - 1) or p not in ids_cadeias]
    k_min = 0
    for tr in trechos:
        cadeia = tr["arestas"]
        A, B = cadeia[0], cadeia[-1]
        melhor, melhor_k = None, None
        for k in range(k_min, len(pontos) - 1):
            u = pontos[k] if isinstance(pontos[k], str) else pontos[k][-1]
            v = pontos[k + 1] if isinstance(pontos[k + 1], str) else pontos[k + 1][0]
            try:
                _, d1 = rede.dijkstra(u, A, permitidas, fator_fora)
                _, d2 = rede.dijkstra(B, v, permitidas, fator_fora)
                _, d0 = rede.dijkstra(u, v, permitidas, fator_fora)
            except KeyError:
                print(f"  ERRO: {rid}: aresta do trecho fixo não existe na rede")
                return pontos
            if d1 == float("inf") or d2 == float("inf"):
                continue
            score = d1 + d2 - (d0 if d0 != float("inf") else 0.0)
            if melhor is None or score < melhor:
                melhor, melhor_k = score, k
        if melhor_k is None:
            print(f"  ERRO: {rid}: o trecho fixo {A} ... {B} não se encaixa em nenhum ponto da rota; NÃO aplicado.")
            continue
        pontos.insert(melhor_k + 1, cadeia)
        k_min = melhor_k + 1
        print(f"  trecho fixo {A} ... {B} inserido em {rid} (entre os pontos {melhor_k} e {melhor_k + 1} da rota)")
    return pontos


# --------------------------------------------------------------------------------------
# Geocodificação (Nominatim)
# --------------------------------------------------------------------------------------
class Geocodificador:
    URL = "https://nominatim.openstreetmap.org/search"

    def __init__(self, cache_path, online, viewbox, contato):
        self.cache_path = cache_path
        self.online = online
        self.viewbox = viewbox  # (lon_min, lat_min, lon_max, lat_max)
        self.contato = contato
        self.cache = {}
        self._ultimo = 0.0
        if os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                self.cache = json.load(f)

    def _salvar(self):
        os.makedirs(os.path.dirname(self.cache_path) or ".", exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=1)

    def buscar(self, consulta, geojson=False):
        chave = ("G|" if geojson else "") + consulta
        if chave in self.cache:
            return self.cache[chave]
        if not self.online:
            return None
        lon0, lat0, lon1, lat1 = self.viewbox
        params = {"q": consulta, "format": "jsonv2", "limit": "5", "addressdetails": "1",
                  "countrycodes": "br", "bounded": "1", "viewbox": f"{lon0},{lat1},{lon1},{lat0}",
                  "accept-language": "pt-BR"}
        if geojson:
            params["polygon_geojson"] = "1"
        espera = 1.2 - (time.time() - self._ultimo)
        if espera > 0:
            time.sleep(espera)
        req = urllib.request.Request(self.URL + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": f"DynamicBus-UFS/1.0 ({self.contato})"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                dados = json.loads(r.read().decode("utf-8"))
        except Exception as ex:  # rede fora, bloqueio, etc.
            print(f"  [geocode] falha em '{consulta}': {ex}", file=sys.stderr)
            return None
        self._ultimo = time.time()
        self.cache[chave] = dados
        self._salvar()
        return dados


def melhor_resultado(resultados, viewbox):
    """Escolhe o primeiro resultado dentro da caixa; classifica a precisão."""
    if not resultados:
        return None
    lon0, lat0, lon1, lat1 = viewbox
    for r in resultados:
        lat, lon = float(r["lat"]), float(r["lon"])
        if lat0 <= lat <= lat1 and lon0 <= lon <= lon1:
            end = r.get("address", {}) or {}
            preciso = bool(end.get("house_number")) or r.get("category") in ("building", "amenity", "shop", "office")
            return {"lat": lat, "lon": lon, "preciso": preciso, "nome": r.get("display_name", "")}
    return None


# --------------------------------------------------------------------------------------
# Leitura de entradas
# --------------------------------------------------------------------------------------
def ler_terminais(caminho):
    raiz = ET.parse(caminho).getroot()
    out = OrderedDict()
    for bs in raiz.iter("busStop"):
        out[bs.get("id")] = {"id": bs.get("id"), "name": bs.get("name", bs.get("id")), "lane": bs.get("lane"),
                             "start": float(bs.get("startPos")), "end": float(bs.get("endPos"))}
    return out


def ler_csv(caminho):
    with open(caminho, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def ler_json(caminho, padrao):
    if caminho and os.path.exists(caminho):
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    return padrao


# --------------------------------------------------------------------------------------
# Resolução do nome das ruas do itinerário -> nomes no OSM
# --------------------------------------------------------------------------------------
def resolver_rua(rede, texto, aliases):
    """Retorna dict(cores=set(núcleos), nomes=[nomes OSM], status=str)."""
    if not texto:
        return {"cores": set(), "nomes": [], "status": "sem_rua"}
    tipo, nuc = chave_rua(texto)
    chave_alias = " ".join(([tipo] if tipo else []) + list(nuc))
    if chave_alias in aliases and "arestas" in aliases[chave_alias]:
        info = aliases[chave_alias]
        return {"cores": {("@" + chave_alias,)}, "nomes": [], "edges": rede.alias_edges.get(chave_alias, []),
                "status": "manual", "ponto_unico": bool(info.get("ponto_unico"))}
    if chave_alias in aliases:
        info = aliases[chave_alias]
        nomes = info["osm"]
        cores = set()
        for n in nomes:
            for _, c in partes(n):
                cores.add(c)
        return {"cores": cores, "nomes": nomes, "status": "hipotese" if info.get("hipotese") else "alias"}
    if (tipo, nuc) in rede.idx_tc:
        return {"cores": {nuc}, "nomes": sorted(rede.idx_tc[(tipo, nuc)]), "status": "exato"}
    if nuc in rede.idx_core:
        return {"cores": {nuc}, "nomes": sorted(rede.idx_core[nuc]), "status": "tipo_diferente"}
    if len(" ".join(nuc)) >= 6:
        alvo = " ".join(nuc)
        pontuacao = []
        for c in rede.idx_core:
            s = " ".join(c)
            if len(s) >= 6:
                pontuacao.append((difflib.SequenceMatcher(None, alvo, s).ratio(), c))
        pontuacao.sort(reverse=True)
        if pontuacao and pontuacao[0][0] >= 0.88:
            melhor = pontuacao[0][0]
            cores = {c for r, c in pontuacao if r >= melhor - 0.03 and r >= 0.88}
            nomes = sorted({n for c in cores for n in rede.idx_core[c]})
            return {"cores": cores, "nomes": nomes, "status": "aproximado"}
    return {"cores": set(), "nomes": [], "status": "nao_encontrada"}


def arestas_da_rua(rede, info):
    if info.get("edges"):
        return list(info["edges"])
    return [i for nm in info.get("nomes", []) for i in rede.edges_por_nome[nm]]


# --------------------------------------------------------------------------------------
# Posicionamento das paradas ao longo de uma rota
# --------------------------------------------------------------------------------------
class Percurso:
    def __init__(self, rede, edges):
        self.rede = rede
        self.edges = edges
        self.ini = []
        acc = 0.0
        for e in edges:
            self.ini.append(acc)
            acc += e.getLength()
        self.total = acc
        self.idx_por_id = defaultdict(list)
        for i, e in enumerate(edges):
            self.idx_por_id[e.getID()].append(i)

    def s_para_aresta(self, s):
        lo, hi = 0, len(self.edges) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.ini[mid] <= s:
                lo = mid
            else:
                hi = mid - 1
        return lo, s - self.ini[lo]

    def projetar(self, x, y):
        """Ponto (x,y) -> (s ao longo do percurso, distância à rota)."""
        melhor = (None, 1e18)
        for i, e in enumerate(self.edges):
            shape = e.getLanes()[0].getShape()
            off, d = polygonOffsetAndDistanceToPoint((x, y), shape)
            if d < melhor[1]:
                melhor = (self.ini[i] + min(off, e.getLength()), d)
        return melhor


def grade(percurso, passo=8.0, margem=10.0, min_len=28.0):
    S, idx = [], []
    for i, e in enumerate(percurso.edges):
        L = e.getLength()
        if L < min_len:
            continue
        off = margem
        while off <= L - margem:
            S.append(percurso.ini[i] + off)
            idx.append(i)
            off += passo
    return S, idx


def intervalos_permitidos(S, idx, percurso, cores, salto=80.0):
    pontos = [s for s, i in zip(S, idx) if percurso.rede.edge_cores[percurso.edges[i].getID()] & cores]
    out = []
    for s in pontos:
        if out and s - out[-1][1] <= salto:
            out[-1][1] = s
        else:
            out.append([s, s])
    return out


def resolver_posicoes(percurso, paradas, gap=30.0, passo=8.0):
    """
    paradas: lista (na ordem) de dicts com chaves
        pin (s fixo ou None), cores (set ou None), geo_s (s do geocode ou None)
    Define 's' para cada uma: não decrescente, respeitando as ruas, o mais perto possível dos alvos.
    """
    S, idx = grade(percurso, passo)
    n = len(paradas)
    # inclui posições fixas na lista de amostras
    fixas = sorted({p["pin"] for p in paradas if p["pin"] is not None})
    todos = sorted(set(S) | set(fixas))
    pos_de = {s: k for k, s in enumerate(todos)}
    eh_grade = [False] * len(todos)
    aresta_de = [None] * len(todos)
    for s, i in zip(S, idx):
        eh_grade[pos_de[s]] = True
        aresta_de[pos_de[s]] = i
    for s in fixas:
        aresta_de[pos_de[s]] = percurso.s_para_aresta(s)[0]
    m = len(todos)
    nome_ok = lambda j, cores: cores is None or (percurso.rede.edge_cores[percurso.edges[aresta_de[j]].getID()] & cores)

    # alvos (prior)
    alvo = [None] * n
    peso = [1.0] * n
    cursor = -1e9
    i = 0
    while i < n:
        p = paradas[i]
        if p["pin"] is not None:
            alvo[i] = p["pin"]
            peso[i] = 1e3
            cursor = p["pin"]
            i += 1
            continue
        if p["cores"]:
            j = i
            while j + 1 < n and paradas[j + 1]["pin"] is None and paradas[j + 1]["cores"] == p["cores"]:
                j += 1
            k = j - i + 1
            ints = intervalos_permitidos(S, idx, percurso, p["cores"])
            escolhido = None
            for a, b in ints:
                if b > cursor + gap:
                    escolhido = (max(a, cursor + gap), b)
                    break
            if escolhido is None and ints:
                escolhido = tuple(ints[-1])
            if escolhido:
                a, b = escolhido
                for q in range(k):
                    alvo[i + q] = a + (q + 0.5) / k * max(b - a, 0.0)
                cursor = alvo[j]
            i = j + 1
            continue
        i += 1
    # preenche alvos faltantes por interpolação entre vizinhas
    conhecidos = [q for q in range(n) if alvo[q] is not None]
    if not conhecidos:
        for q in range(n):
            alvo[q] = percurso.total * (q + 0.5) / n
    else:
        for q in range(n):
            if alvo[q] is None:
                ant = max([c for c in conhecidos if c < q], default=None)
                pro = min([c for c in conhecidos if c > q], default=None)
                if ant is None:
                    alvo[q] = alvo[pro]
                elif pro is None:
                    alvo[q] = alvo[ant]
                else:
                    f = (q - ant) / (pro - ant)
                    alvo[q] = alvo[ant] + f * (alvo[pro] - alvo[ant])
    for q in range(n):
        if paradas[q]["geo_s"] is not None and paradas[q]["pin"] is None:
            alvo[q] = paradas[q]["geo_s"]
            peso[q] = 25.0

    def rodar():
        INF = float("inf")
        dp_prev = None
        voltar = []
        for q in range(n):
            p = paradas[q]
            custo = [INF] * m
            for j in range(m):
                if p["pin"] is not None:
                    if abs(todos[j] - p["pin"]) < 1e-6:
                        custo[j] = 0.0
                    continue
                if not eh_grade[j]:
                    continue
                if not nome_ok(j, p["cores"]):
                    continue
                custo[j] = peso[q] * ((todos[j] - alvo[q]) / 10.0) ** 2
            if q == 0:
                dp_cur = custo
                voltar.append([None] * m)
            else:
                if p["pin"] is not None and paradas[q - 1]["pin"] == p["pin"]:
                    g = 0.0
                elif p["pin"] is not None or paradas[q - 1]["pin"] is not None:
                    g = 20.0
                else:
                    g = gap
                dp_cur = [INF] * m
                bk = [None] * m
                ptr, melhor, melhor_k = 0, INF, None
                for j in range(m):
                    while ptr < m and todos[ptr] <= todos[j] - g:
                        if dp_prev[ptr] < melhor:
                            melhor, melhor_k = dp_prev[ptr], ptr
                        ptr += 1
                    if custo[j] < INF and melhor < INF:
                        dp_cur[j] = custo[j] + melhor
                        bk[j] = melhor_k
                voltar.append(bk)
            if min(dp_cur) == INF:
                return None, q
            dp_prev = dp_cur
        fim = min(range(m), key=lambda j: dp_prev[j])
        sol = [None] * n
        j = fim
        for q in range(n - 1, -1, -1):
            sol[q] = todos[j]
            j = voltar[q][j]
        return sol, None

    # 1) paradas cuja rua nem aparece na rota: relaxa só essas
    relaxadas = []
    for q in range(n):
        p = paradas[q]
        if p["pin"] is None and p["cores"] and not any(eh_grade[j] and nome_ok(j, p["cores"]) for j in range(m)):
            relaxadas.append(q)
            p["cores"] = None
    # 2) se a ordem das ruas for incompatível com o percurso, relaxa uma a uma onde falhar
    for _ in range(n + 1):
        sol, falha = rodar()
        if sol is not None:
            break
        q = falha
        alvo_q = [k for k in range(q, -1, -1) if paradas[k]["pin"] is None and paradas[k]["cores"]]
        if not alvo_q:
            return None, relaxadas, alvo
        relaxadas.append(alvo_q[0])
        paradas[alvo_q[0]]["cores"] = None
    else:
        return None, relaxadas, alvo
    return sol, relaxadas, alvo


# --------------------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------------------
CORES_LINHA = {"090": "1,0,0", "091": "0,0,1", "050": "0,0.7,0"}
ORDEM_ROTAS = [("090", "ida"), ("090", "volta"), ("050", "ida"), ("050", "volta"), ("091", "ida"), ("091", "volta")]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--net", default="sumo/net/net_linhas_090_091_050.net.xml")
    ap.add_argument("--csv", default="data/paradas_linhas.csv")
    ap.add_argument("--terminais", default="sumo/additional/terminais.add.xml")
    ap.add_argument("--aliases", default="data/aliases_ruas.json")
    ap.add_argument("--overrides", default="data/overrides_rotas.json")
    ap.add_argument("--cache", default="data/cache_geocode.json")
    ap.add_argument("--saida-paradas", default="sumo/additional/busstops_linhas.add.xml")
    ap.add_argument("--saida-rotas", default="sumo/routes/bus_routes.rou.xml")
    ap.add_argument("--saida-pois", default="sumo/additional/revisao_pois.add.xml")
    ap.add_argument("--relatorio", default="data/relatorio_revisao.csv")
    ap.add_argument("--geocodificar", action="store_true", help="consulta o Nominatim (precisa de internet; 1 consulta/s)")
    ap.add_argument("--diagnosticar-ruas", action="store_true", help="para ruas não encontradas, mostra nomes OSM vizinhos (usa Nominatim)")
    ap.add_argument("--contato", default="seu-email@exemplo.com", help="e-mail no User-Agent (política do Nominatim)")
    ap.add_argument("--caixa", default="-37.132828,-10.974419,-37.045374,-10.873508", help="lon_min,lat_min,lon_max,lat_max")
    ap.add_argument("--max-dist-geo", type=float, default=80.0)
    ap.add_argument("--fator-fora", type=float, default=5.0, help="penalidade para ruas que não constam no itinerário")
    ap.add_argument("--duracao-parada", type=int, default=15)
    ap.add_argument("--sem-paradas-na-rota", action="store_true")
    ap.add_argument("--ancoras-max-arestas", type=int, default=0,
                    help="(experimental) força a passagem por ruas do itinerário com até N arestas no OSM; 0 desliga (padrão). Pode gerar desvios/voltas")
    a = ap.parse_args()

    viewbox = tuple(float(v) for v in a.caixa.split(","))
    rede = Rede(a.net)
    net = rede.net
    terminais = ler_terminais(a.terminais)
    linhas_csv = ler_csv(a.csv)
    inativas = [r for r in linhas_csv if r.get("ativa", "sim").strip().lower() in ("nao", "não", "n", "0", "false")]
    linhas_csv = [r for r in linhas_csv if r not in inativas]
    aliases = ler_json(a.aliases, {})
    aliases = {k: v for k, v in aliases.items() if not k.startswith("_")}
    overrides = ler_json(a.overrides, {})
    rede.aplicar_aliases(aliases)
    geo = Geocodificador(a.cache, a.geocodificar or a.diagnosticar_ruas, viewbox, a.contato)

    # terminal -> aresta
    global TERMINAL_EDGES
    TERMINAL_EDGES = set()
    term_aresta = {}
    for tid, t in terminais.items():
        lane = net.getLane(t["lane"])
        term_aresta[tid] = lane.getEdge().getID()
        TERMINAL_EDGES.add(term_aresta[tid])
        if t["end"] > lane.getLength() + 1e-6:
            print(f"AVISO: terminal {tid}: endPos {t['end']} maior que a faixa ({lane.getLength():.1f} m)")

    # --- resolução das ruas -------------------------------------------------------------
    resolvidas = {}
    for r in linhas_csv:
        rua = r["rua"]
        if rua and rua not in resolvidas:
            resolvidas[rua] = resolver_rua(rede, rua, aliases)
    print("\nResolução dos nomes de rua (itinerário -> OSM):")
    for rua, info in sorted(resolvidas.items(), key=lambda kv: kv[1]["status"]):
        print(f"  [{info['status']:<15}] {rua}  ->  {', '.join(info['nomes'][:3]) or '-'}")
    if a.diagnosticar_ruas:
        print("\nDiagnóstico (geocodificando ruas não resolvidas ou hipóteses):")
        for rua, info in resolvidas.items():
            if info["status"] in ("nao_encontrada", "hipotese"):
                res = geo.buscar(rua + ", Sergipe", geojson=True)
                if not res:
                    print(f"  {rua}: sem resposta do Nominatim")
                    continue
                cont = defaultdict(int)
                for rr in res[:3]:
                    g = rr.get("geojson", {})
                    coords = g.get("coordinates", []) if g.get("type") == "LineString" else []
                    for lon, lat in coords[:: max(1, len(coords) // 12)]:
                        x, y = net.convertLonLat2XY(lon, lat)
                        for e, d in net.getNeighboringEdges(x, y, 40, includeJunctions=False):
                            if e.getParam("name", ""):
                                cont[e.getParam("name")] += 1
                top = sorted(cont.items(), key=lambda kv: -kv[1])[:5]
                print(f"  {rua}: ruas OSM sob o traçado -> {top or 'nada'}")

    # --- rotas --------------------------------------------------------------------------
    paradas_xml = OrderedDict()   # id -> dict
    reuso = {}                    # texto normalizado -> id da parada
    rotas_saida = []
    linhas_do_terminal = defaultdict(set)
    relatorio = []
    pois = []
    fim_da_ida = {}

    for linha, sentido in ORDEM_ROTAS:
        rid = f"{linha}_{sentido}"
        rows = [r for r in linhas_csv if r["linha"] == linha and r["sentido"] == sentido]
        rows.sort(key=lambda r: int(r["ordem"]))
        ov = overrides.get(rid, {})
        permitidas = set()
        for r in rows:
            if r["rua"]:
                permitidas |= resolvidas[r["rua"]]["cores"]
        for nome in ov.get("ruas_extras", []):
            permitidas |= {c for _, c in partes(nome)}

        # pontos de passagem: início, terminais, âncoras nas ruas do itinerário (na ordem) e fim
        for r in rows:
            if r["tipo"] == "terminal":
                linhas_do_terminal[r["terminal_id"]].add(linha)
        primeira, ultima = rows[0], rows[-1]
        term0 = term_aresta[primeira["terminal_id"]] if primeira["tipo"] == "terminal" else None
        termN = term_aresta[ultima["terminal_id"]] if ultima["tipo"] == "terminal" else None
        if term0 is None:
            ref = next(term_aresta[r["terminal_id"]] for r in rows if r["tipo"] == "terminal")
            term0 = ov.get("inicio")
            if not term0 and (linha, "ida") in fim_da_ida:
                term0 = fim_da_ida[(linha, "ida")]   # a volta parte do mesmo ponto em que a ida termina
            if not term0:
                term0 = escolher_ponta(rede, primeira, resolvidas, ref, permitidas, a.fator_fora, "inicio")
        if termN is None:
            ref = next(term_aresta[r["terminal_id"]] for r in reversed(rows) if r["tipo"] == "terminal")
            termN = ov.get("fim") or escolher_ponta(rede, ultima, resolvidas, ref, permitidas, a.fator_fora, "fim")
        fixas = {str(k): v for k, v in ov.get("paradas_fixas", {}).items()}
        pontos, ancoras = montar_pontos(rede, rows, resolvidas, term_aresta, term0, termN, permitidas,
                                        a.fator_fora, fixas, limite_ancora=a.ancoras_max_arestas)
        if ov.get("trechos_fixos"):
            pontos = inserir_trechos_fixos(rede, pontos, ov["trechos_fixos"], permitidas, a.fator_fora, rid)
        edges, custo = rede.rota_por_pontos(pontos, permitidas, a.fator_fora, rid)
        if edges is None:
            print(f"\nERRO: rota {rid}: sem caminho entre {custo}. Verifique os terminais/overrides.")
            continue
        # remove retornos (U-turn) inúteis nas pontas, comuns em ruas sem saída
        def oposta_de(i):
            return i[1:] if i.startswith("-") else "-" + i
        while len(edges) > 2 and edges[-1].getID() == oposta_de(edges[-2].getID()) and not termN_fixo(termN, edges[-1]):
            edges = edges[:-1]
        while len(edges) > 2 and edges[0].getID() == oposta_de(edges[1].getID()) and not termN_fixo(term0, edges[0]):
            edges = edges[1:]
        per = Percurso(rede, edges)
        ids = [e.getID() for e in edges]
        if sentido == "ida":
            fim_da_ida[(linha, "ida")] = ids[-1]
        repetidas = len(ids) - len(set(ids))

        # estatísticas da rota
        no_itin = sum(e.getLength() for e in edges if rede.edge_cores[e.getID()] & permitidas)
        fora = defaultdict(float)
        for e in edges:
            if not (rede.edge_cores[e.getID()] & permitidas):
                fora[e.getParam("name", "") or "(sem nome)"] += e.getLength()
        topo_fora = sorted(fora.items(), key=lambda kv: -kv[1])[:6]
        print(f"\nRota {rid}: {per.total/1000:.2f} km, {len(edges)} arestas, {100*no_itin/per.total:.0f}% em ruas do itinerário"
              f"{', ARESTAS REPETIDAS: %d' % repetidas if repetidas else ''}")
        print("   fora do itinerário:", ", ".join(f"{n} ({int(l)} m)" for n, l in topo_fora) or "-")
        seq = []
        for e in edges:
            nm = (e.getParam("name", "") or "(sem nome)")
            nm = nm.split(" Avenida ")[0].split(" Rua ")[0]
            if seq and seq[-1][0] == nm:
                seq[-1][1] += e.getLength()
            else:
                seq.append([nm, e.getLength()])
        print("   percurso:", " > ".join(f"{n.replace('Avenida ', 'Av. ').replace('Rua ', 'R. ')} {int(l)}" for n, l in seq if l >= 150 or n != "(sem nome)")[:1400])

        # geocodificação -> s
        itens = []
        for r in rows:
            item = {"row": r, "pin": None, "cores": None, "geo_s": None, "geo": None, "reuso": None}
            if r["tipo"] == "terminal":
                t = terminais[r["terminal_id"]]
                eid = term_aresta[r["terminal_id"]]
                k = per.idx_por_id.get(eid)
                if not k:
                    print(f"  AVISO: terminal {r['terminal_id']} não está na rota {rid}")
                else:
                    item["pin"] = per.ini[k[0]] + (t["start"] + t["end"]) / 2
            else:
                info = resolvidas.get(r["rua"], {"cores": set()})
                item["cores"] = info["cores"] or None
                if info.get("ponto_unico") and info.get("edges"):
                    cand = [eid for eid in info["edges"] if eid in per.idx_por_id]
                    if cand:
                        k0 = per.idx_por_id[cand[0]][0]
                        item["pin"] = per.ini[k0] + per.edges[k0].getLength() / 2
                        item["fixa"] = True
                if r["ordem"] in fixas:
                    k = per.idx_por_id.get(fixas[r["ordem"]]["edge"])
                    if k:
                        item["pin"] = per.ini[k[0]] + float(fixas[r["ordem"]].get("pos", 20.0))
                        item["fixa"] = True
                chave = sem_acento(r["texto_original"]).lower().strip()
                if chave in reuso:
                    p0 = paradas_xml[reuso[chave]]
                    k = per.idx_por_id.get(p0["edge"])
                    if k:
                        item["pin"] = per.ini[k[0]] + p0["pos"]
                        item["reuso"] = reuso[chave]
                if item["pin"] is None and not item.get("fixa") and (geo.online or geo.cache):
                    if r["numero"]:
                        res = melhor_resultado(geo.buscar(consulta_stop(r)), viewbox)
                        if res:
                            x, y = net.convertLonLat2XY(res["lon"], res["lat"])
                            s_proj, d = per.projetar(x, y)
                            item["geo"] = (res, x, y, d)
                            if res["preciso"] and d <= a.max_dist_geo:
                                item["geo_s"] = s_proj
            itens.append(item)

        # último elemento sem terminal (ponta do HU): fixa no fim do percurso
        if ultima["tipo"] != "terminal":
            if itens[-1]["pin"] is None:
                itens[-1]["pin"] = per.ini[-1] + edges[-1].getLength() / 2
            itens[-1]["cores"] = None
        if primeira["tipo"] != "terminal":
            if itens[0]["pin"] is None:
                itens[0]["pin"] = per.ini[0] + edges[0].getLength() / 2
            itens[0]["cores"] = None

        cores_orig = [it["cores"] for it in itens]
        sol, relaxadas, alvos = resolver_posicoes(per, itens)
        if sol is None:
            print(f"  ERRO: não foi possível ordenar as paradas da rota {rid}")
            continue
        relaxadas = set(relaxadas)
        if relaxadas:
            print(f"  AVISO: {len(relaxadas)} parada(s) cuja rua não aparece na rota foram posicionadas só por ordem: "
                  + ", ".join(itens[q]["row"]["ordem"] for q in sorted(relaxadas)))

        paradas_da_rota = []
        for q, (it, s) in enumerate(zip(itens, sol)):
            r = it["row"]
            aviso = []
            if r["tipo"] == "terminal":
                sid = r["terminal_id"]
                metodo = "terminal"
                edge_id = term_aresta[sid]
                pos = (terminais[sid]["start"] + terminais[sid]["end"]) / 2
                paradas_da_rota.append(sid)
            else:
                idx, off = per.s_para_aresta(s)
                e = edges[idx]
                if it["reuso"]:
                    sid, metodo = it["reuso"], "reaproveitada"
                    p0 = paradas_xml[sid]
                    p0["linhas"].add(linha)
                    edge_id, pos = p0["edge"], p0["pos"]
                else:
                    lane = next((l for l in e.getLanes() if l.allows("bus")), e.getLanes()[0])
                    L = lane.getLength()
                    centro = min(max(off, 8.0), L - 8.0)
                    vizinha = next((pid for pid, pp in paradas_xml.items()
                                    if pp["lane"] == lane.getID() and abs(pp["pos"] - centro) < 12.0), None)
                    if vizinha:
                        sid = vizinha
                        paradas_xml[sid]["linhas"].add(linha)
                        centro = paradas_xml[sid]["pos"]
                    else:
                        sid = f"bs_{linha}{sentido[0]}_{int(r['ordem']):02d}"
                        paradas_xml[sid] = {"id": sid, "name": r["texto_original"], "lane": lane.getID(), "edge": e.getID(),
                                             "pos": centro, "start": max(0.0, centro - 7.5), "end": min(L, centro + 7.5),
                                             "linhas": {linha}}
                    edge_id, pos = e.getID(), centro
                    reuso[sem_acento(r["texto_original"]).lower().strip()] = sid
                    if vizinha:
                        metodo = "mesclada_com_" + vizinha
                    elif it["geo_s"] is not None:
                        metodo = "geocode"
                    elif q in relaxadas or not resolvidas.get(r["rua"], {}).get("cores"):
                        metodo = "so_por_ordem"
                    elif resolvidas.get(r["rua"], {}).get("cores"):
                        metodo = "ordem_na_rua"
                    else:
                        metodo = "so_por_ordem"
                paradas_da_rota.append(sid)
                if q in relaxadas and r["tipo"] == "parada" and cores_orig[q]:
                    aviso.append("rua_fora_da_rota")
                nome_aresta = e.getParam("name", "") if not it["reuso"] else ""
            geo_info = it["geo"]
            dist_geo = ""
            if geo_info:
                res, gx, gy, dproj = geo_info
                lane = net.getLane(paradas_xml[sid]["lane"]) if sid in paradas_xml else net.getEdge(edge_id).getLanes()[0]
                px, py = positionAtShapeOffset(lane.getShape(), pos)
                dist_geo = round(math.hypot(px - gx, py - gy), 1)
                pois.append(("geo_" + sid, gx, gy, "geocode", "1,0,0"))
                if not res["preciso"]:
                    aviso.append("geocode_so_da_rua(nao_usado)")
                elif dproj > a.max_dist_geo:
                    aviso.append(f"geocode_longe_da_rota({int(dproj)}m)")
            if r["tipo"] == "parada" and resolvidas.get(r["rua"], {}).get("status") in ("hipotese", "nao_encontrada"):
                aviso.append("rua_" + resolvidas[r["rua"]]["status"])
            lane_id = terminais[sid]["lane"] if r["tipo"] == "terminal" else paradas_xml[sid]["lane"]
            lane_obj = net.getLane(lane_id)
            px, py = positionAtShapeOffset(lane_obj.getShape(), min(pos, lane_obj.getLength()))
            pois.append(("bs_" + rid + "_" + r["ordem"], px, py, "parada", "0,0.6,0"))
            lon, lat = net.convertXY2LonLat(px, py)
            relatorio.append({"rota": rid, "ordem": r["ordem"], "texto": r["texto_original"],
                              "rua_osm": ("arestas manuais" if resolvidas.get(r["rua"], {}).get("status") == "manual"
                                         else "; ".join(resolvidas.get(r["rua"], {}).get("nomes", [])[:2])),
                              "status_rua": resolvidas.get(r["rua"], {}).get("status", ""),
                              "metodo": metodo, "busStop": sid, "lane": lane_id, "pos": round(pos, 1),
                              "lat": round(lat, 6), "lon": round(lon, 6),
                              "dist_geocode_m": dist_geo, "avisos": " ".join(aviso)})
        unicas = [x for k, x in enumerate(paradas_da_rota) if k == 0 or x != paradas_da_rota[k - 1]]
        rotas_saida.append({"id": f"r{rid}", "linha": linha, "sentido": sentido, "edges": ids,
                            "paradas": unicas})

    # --- terminais com as linhas que passam por eles ---------------------------------------
    for tid, t in terminais.items():
        t["linhas"] = linhas_do_terminal.get(tid, set())

    for r in inativas:
        relatorio.append({"rota": f"{r['linha']}_{r['sentido']}", "ordem": r["ordem"], "texto": r["texto_original"],
                          "rua_osm": "", "status_rua": "", "metodo": "desativada", "busStop": "", "lane": "", "pos": "",
                          "lat": "", "lon": "", "dist_geocode_m": "", "avisos": "nao_existe_na_rota_real"})
    ordem_rota = {f"{l}_{sd}": k for k, (l, sd) in enumerate(ORDEM_ROTAS)}
    relatorio.sort(key=lambda x: (ordem_rota.get(x["rota"], 99), int(x["ordem"])))
    escrever_saidas(a, terminais, paradas_xml, rotas_saida, relatorio, pois)
    saida_ruas = os.path.join(os.path.dirname(a.relatorio) or ".", "arestas_por_rua.csv")
    with open(saida_ruas, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rua_no_itinerario", "status", "nomes_no_osm", "n_arestas", "extensao_m", "ids_das_arestas"])
        for rua, info in sorted(resolvidas.items()):
            ids_r = arestas_da_rua(rede, info)
            ext = sum(net.getEdge(i).getLength() for i in ids_r)
            nomes = " | ".join(info["nomes"]) if info["nomes"] else "(arestas indicadas manualmente)"
            w.writerow([rua, info["status"], nomes, len(ids_r), round(ext), " ".join(ids_r)])
    print(f"  {saida_ruas}")
    metodos = defaultdict(int)
    for r in relatorio:
        metodos[r["metodo"]] += 1
    print("\nMétodo de posicionamento (todas as rotas):", dict(metodos))
    print(f"busStops gerados: {len(paradas_xml)} intermediárias + {len(terminais)} terminais")


def montar_pontos(rede, rows, resolvidas, term_aresta, inicio, fim, permitidas, fator_fora, fixas, limite_ancora=20):
    """Sequência de arestas pelas quais a rota é obrigada a passar (inicio, ..., fim)."""
    pontos = [inicio]
    ancoras = {}
    tem_manual = any(resolvidas.get(r["rua"], {}).get("status") == "manual" for r in rows if r["rua"])
    dr = rede.arvore(fim, permitidas, fator_fora, reverso=True) if (limite_ancora or tem_manual) else {}
    i = 1
    n = len(rows) - 1  # a última linha é o fim
    while i < n:
        r = rows[i]
        if r["tipo"] == "terminal":
            pontos.append(term_aresta[r["terminal_id"]])
            i += 1
            continue
        if r["ordem"] in fixas:
            pontos.append(fixas[r["ordem"]]["edge"])
            ancoras[r["ordem"]] = fixas[r["ordem"]]["edge"]
            i += 1
            continue
        cores = resolvidas.get(r["rua"], {}).get("cores")
        j = i
        while j + 1 < n and rows[j + 1]["tipo"] == "parada" and rows[j + 1]["ordem"] not in fixas \
                and resolvidas.get(rows[j + 1]["rua"], {}).get("cores") == cores:
            j += 1
        info_rua = resolvidas.get(r["rua"], {})
        ids_rua = arestas_da_rua(rede, info_rua)
        n_arestas = len(ids_rua)
        manual = info_rua.get("status") == "manual"
        if cores and (manual or (limite_ancora and info_rua.get("status") in ("exato", "tipo_diferente", "aproximado", "alias")
                                 and 0 < n_arestas <= limite_ancora)):
            df = rede.arvore(pontos[-1], permitidas, fator_fora)
            melhor, melhor_c = None, float("inf")
            for eid in ids_rua:
                e = rede.net.getEdge(eid)
                if eid == pontos[-1] or (e.getLength() < 20 and not manual) or not e.allows("bus"):
                    continue
                if eid in df and eid in dr and df[eid] + dr[eid] < melhor_c:
                    melhor, melhor_c = eid, df[eid] + dr[eid]
            if melhor:
                pontos.append(melhor)
                ancoras[r["ordem"]] = melhor
            elif manual:
                print(f"  AVISO: nenhuma aresta manual de '{r['rua']}' é alcançável nesta rota (parada {r['ordem']})")
        i = j + 1
    pontos.append(fim)
    # remove repetições consecutivas
    limpo = [pontos[0]]
    for p in pontos[1:]:
        if p != limpo[-1]:
            limpo.append(p)
    return limpo, ancoras


def termN_fixo(ponto, edge):
    return ponto == edge.getID() and ponto in TERMINAL_EDGES


def consulta_stop(r):
    rua_cheia = " ".join(w.capitalize() if w not in ("de", "da", "do") else w for w in tokens_leg(r["rua"]))
    return f"{rua_cheia}, {r['numero']}"


def tokens_leg(texto):
    """Nome legível para consulta ao Nominatim (expande abreviações)."""
    exp = {"av": "avenida", "gen": "general", "mal": "marechal", "cel": "coronel", "pres": "presidente",
           "prof": "professor", "gov": "governador", "dr": "doutor", "trav": "travessa", "est": "estrada"}
    t = re.sub(r"[.,]", " ", texto).split()
    return [exp.get(w.lower(), w.lower()) for w in t]


def escolher_ponta(rede, row, resolvidas, ref_edge, permitidas, fator_fora, qual):
    """Fim de linha que não é terminal (ex.: Hospital Universitário): ponta da rua mais distante do terminal vizinho."""
    info = resolvidas.get(row["rua"])
    if not info or not (info["nomes"] or info.get("edges")):
        raise SystemExit(f"Não achei a rua '{row['rua']}' para a ponta da linha; use 'inicio'/'fim' em overrides_rotas.json")
    candidatas = [rede.net.getEdge(i) for i in arestas_da_rua(rede, info)
                  if rede.net.getEdge(i).getLength() >= (10 if info.get("edges") else 25) and rede.net.getEdge(i).allows("bus")]
    melhor, melhor_c = None, -1.0
    for e in candidatas:
        if qual == "fim":
            seg, c = rede.dijkstra(ref_edge, e.getID(), permitidas, fator_fora)
        else:
            seg, c = rede.dijkstra(e.getID(), ref_edge, permitidas, fator_fora)
        if seg is not None and c > melhor_c:
            melhor, melhor_c = e.getID(), c
    if melhor is None:
        raise SystemExit(f"Sem caminho entre o terminal e a rua '{row['rua']}'")
    return melhor


def esc(v):
    return quoteattr(str(v))


def escrever_saidas(a, terminais, paradas_xml, rotas, relatorio, pois):
    for p in (a.saida_paradas, a.saida_rotas, a.saida_pois, a.relatorio):
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    cor_linha = lambda linhas: CORES_LINHA[next(iter(linhas))] if len(linhas) == 1 else "0.5,0.5,0.5"
    with open(a.saida_paradas, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n')
        f.write("    <!-- Terminais (posições definidas manualmente) -->\n")
        for t in terminais.values():
            lns = " ".join(sorted(t["linhas"]))
            f.write(f'    <busStop id={esc(t["id"])} name={esc(t["name"])} lane={esc(t["lane"])} '
                    f'startPos="{t["start"]:.2f}" endPos="{t["end"]:.2f}" friendlyPos="true" '
                    f'lines={esc(lns)} color="0,0,0"/>\n')
        f.write("    <!-- Paradas intermediárias geradas por tools/gerar_cenario.py -->\n")
        for p in paradas_xml.values():
            f.write(f'    <busStop id={esc(p["id"])} name={esc(p["name"])} lane={esc(p["lane"])} '
                    f'startPos="{p["start"]:.2f}" endPos="{p["end"]:.2f}" friendlyPos="true" '
                    f'lines={esc(" ".join(sorted(p["linhas"])))} color="{cor_linha(p["linhas"])}"/>\n')
        f.write("</additional>\n")
    with open(a.saida_rotas, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<routes>\n')
        for r in rotas:
            f.write(f'    <route id="{r["id"]}" color="{CORES_LINHA[r["linha"]]}" edges="{" ".join(r["edges"])}"')
            if a.sem_paradas_na_rota:
                f.write("/>\n")
            else:
                f.write(">\n")
                for sid in r["paradas"]:
                    f.write(f'        <stop busStop="{sid}" duration="{a.duracao_parada}"/>\n')
                f.write("    </route>\n")
        f.write("</routes>\n")
    with open(a.saida_pois, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<additional>\n')
        for pid, x, y, tipo, cor in pois:
            f.write(f'    <poi id="{pid}" type="{tipo}" color="{cor}" x="{x:.2f}" y="{y:.2f}" layer="20"/>\n')
        f.write("</additional>\n")
    if relatorio:
        with open(a.relatorio, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(relatorio[0].keys()))
            w.writeheader()
            w.writerows(relatorio)
    print(f"\nGerados:\n  {a.saida_paradas}\n  {a.saida_rotas}\n  {a.saida_pois}\n  {a.relatorio}")


if __name__ == "__main__":
    main()
