"""Converte os itinerários (texto) em data/paradas_linhas.csv. Rode uma vez; depois edite o CSV à mão se precisar."""
import csv, re, sys, pathlib

ITIN = {
("090","ida"): """Terminal De Integração Campus
Av. Gov. Marcelo Deda Chagas 731
Av. Mal. Cândido Rondon 1515 | Progresso
Av. Mal. Cândido Rondon 890
Av. Prof. José Bonifácio Forte Neto | Hemocentro De Sergipe
Av. Prof. José Bonifácio Forte Neto, 105
Terminal De Integração Zona Oeste (Leonel Brizola)
Av. Pres. Tancredo Neves 5550
Av. Pres. Tancredo Neves, 5655
Av. Pres. Tancredo Neves, 6055
Av. Pres. Tancredo Neves, 4911
Av. Pres. Tancredo Neves, 8215
Av. Pres. Tancredo Neves 3803
Av. Pres. Tancredo Neves 3231
Av. Pres. Tancredo Neves | Ferreira Costa
Terminal De Integração D.I.A (Distrito Industrial De Aracaju)""",
("090","volta"): """Terminal De Integração D.I.A (Distrito Industrial De Aracaju)
Av. Pres. Tancredo Neves | Praça Anival Dantas
Av. Pres. Tancredo Neves, 3420
Av. Pres. Tancredo Neves, 3801
Av. Pres. Tancredo Neves, 3960
Av. Pres. Tancredo Neves, 5033
Av. Pres. Tancredo Neves, 6056
Av. Pres. Tancredo Neves, 5660
Av. Pres. Tancredo Neves 2012
Av. Pres. Tancredo Neves 2595
Av. Pres. Tancredo Neves, 2880
Terminal De Integração Zona Oeste (Leonel Brizola)
Av. Mal. Cândido Rondon 901
Av. Mal. Cândido Rondon 870
Av. Mal. Cândido Rondon 1346
Av. Gov. Marcelo Deda Chagas 730
Terminal De Integração Campus""",
("091","ida"): """Terminal De Integração Campus
Av. Gov. Marcelo Deda Chagas 208
Av. João Bebe Água, 736
Av. João Bebe Água 964
Av. João Bebe Água ,1100
Av. João Bebe Água 1808
Av. João Bebe Água 1881
Av. João Bebe Água, 1101
Av. João Bebe Água 985
Rua I 102
Rua Joaquim De Barros 223a
Rua Saneamento 94
Rua J 7
Rua Jasiel De Brito Côrtes 847
Rua Jasiel De Brito Côrtes 715
Rua Jasiel De Brito Côrtes, 80
Rua Jasiel De Brito Côrtes, 450
Rua Pedro Brito Dos Santos | Res. Vila Velha
Rua Pedro Brito Dos Santos | Bela Vista Residencial
Rua Projetada 16
Av. Escritor Graciliano Ramos 746
Av. Cel. Sizinio Da Rocha 103
Rua Hildete Falcão Batista 37
Av. Farmacêutica Cezartina Régis , 793
Av. Farmacêutica Cezartina Régis 357
Rua Moizete Leite Mendonça
Av. Pres. Tancredo Neves | Ferreira Costa
Terminal De Integração D.I.A (Distrito Industrial De Aracaju)""",
("091","volta"): """Terminal De Integração D.I.A (Distrito Industrial De Aracaju)
Av. Pres. Tancredo Neves | Praça Anival Dantas
Rua Major João Téles, 88
Av. Farmacêutica Cezartina Régis 438
Av. Farmacêutica Cezartina Régis 686
Av. Rio Poxim 11
Estrada Do Jabotiana, 605
Rua Jasiel De Brito Côrtes, 540
Rua Jasiel De Brito Côrtes, 79
Rua Jasiel De Brito Côrtes 655
Rua Jasiel De Brito Côrtes 847
Rua J 8
Rua Saneamento 439
Rua Saneamento 114
Rua I 59
Av. João Bebe Água 577
Av. Gov. Marcelo Deda Chagas 195
Terminal De Integração Campus""",
("050","ida"): """Terminal De Integração Campus
Av. Gov. Marcelo Deda Chagas 731
Av. Mal. Cândido Rondon 1515 | Progresso
Av. Mal. Cândido Rondon 890
Av. Prof. José Bonifácio Forte Neto | Hemocentro De Sergipe
Av. Prof. José Bonifácio Forte Neto, 105
Terminal De Integração Zona Oeste (Leonel Brizola)
Av. Pres. Tancredo Neves 4210
Av. Pres. Tancredo Neves 2717
Av. Alcides Fontes 110
Av. Gen. Euclides Figueiredo 243
Av. Gen. Euclides Figueiredo 584
Av. Gen. Euclides Figueiredo 908
Rua Serafim Bonfim 237
Rua Serafim Bonfim 71
Rua Gen. Prado 152
Terminal De Integração Maracaju
Av. Visconde De Maracaju 781
Av. Visconde De Maracaju 521
Av. Visconde De Maracaju 365
Av. Visconde De Maracaju 113
Av. Visconde De Maracaju | Paróquia Pio X
Av. Visconde De Maracaju 147
Av. Visconde De Maracaju 72
Rua Do Carmo 147
Rua Santa Maria, 2-92
Rua Cláudio Batista, 169
Rua Cláudio Batista, 334
Rua Cláudio Batista 454""",
("050","volta"): """Rua Cláudio Batista 454
Rua Santa Terezinha | E.E Clodoaldo De Alencar
Av. Sanatório 39
Rua Artur Fortes 80
Av. Visconde De Maracaju 388
Av. Visconde De Maracaju 604
Av. Visconde De Maracaju 850
Terminal De Integração Maracaju
Rua São Francisco De Assis 1149
Rua São Francisco De Assis 755
Rua São Francisco De Assis 535
Av. Gen. Euclides Figueiredo 905
Av. Gen. Euclides Figueiredo 457
Av. Gen. Euclides Figueiredo 275
Av. Alcides Fontes 218
Av. Pres. Tancredo Neves 2728
Av. Pres. Tancredo Neves 4201
Terminal De Integração Zona Oeste (Leonel Brizola)
Av. Mal. Cândido Rondon 901
Av. Mal. Cândido Rondon 870
Av. Mal. Cândido Rondon 1346
Av. Gov. Marcelo Deda Chagas 730
Terminal De Integração Campus""",
}
TERMINAIS = {"campus":"term_campus","d.i.a":"term_dia","zona oeste":"term_zona_oeste","maracaju":"term_maracaju"}

def parse(txt):
    txt = txt.strip()
    ref = ""
    if "|" in txt:
        txt, ref = [p.strip() for p in txt.split("|", 1)]
    m = re.match(r"^(.*?)[\s,]+(\d+[A-Za-z]?(?:-\d+)?)$", txt)
    if m:
        rua, num = m.group(1).strip(" ,"), m.group(2)
    else:
        rua, num = txt.strip(" ,"), ""
    return rua, num, ref

rows = []
for (linha, sentido), bloco in ITIN.items():
    for i, ln in enumerate(l for l in bloco.splitlines() if l.strip()):
        low = ln.lower()
        term = ""
        if low.startswith("terminal de integração"):
            for k, v in TERMINAIS.items():
                if k in low: term = v
            rua, num, ref = "", "", ""
        else:
            rua, num, ref = parse(ln)
        rows.append(dict(linha=linha, sentido=sentido, ordem=i+1, tipo="terminal" if term else "parada",
                         terminal_id=term, rua=rua, numero=num, referencia=ref, texto_original=ln.strip()))
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "data/paradas_linhas.csv")
out.parent.mkdir(parents=True, exist_ok=True)
with out.open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
from collections import Counter
print(len(rows), "linhas ->", out); print(Counter((r["linha"], r["sentido"]) for r in rows))
