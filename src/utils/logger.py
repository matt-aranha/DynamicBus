# -*- coding: utf-8 -*-
import csv
import os


class LogCSV:
    """Acrescenta uma linha por episódio em um CSV."""

    def __init__(self, caminho):
        self.caminho = str(caminho)
        os.makedirs(os.path.dirname(self.caminho) or ".", exist_ok=True)
        self._cab = False

    def escrever(self, linha: dict):
        novo = not os.path.exists(self.caminho) or not self._cab and os.path.getsize(self.caminho) == 0
        with open(self.caminho, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(linha.keys()))
            if novo:
                w.writeheader()
            w.writerow(linha)
        self._cab = True
