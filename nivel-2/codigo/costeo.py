#!/usr/bin/env python3
"""Costo de ingredientes por porción al 31/10/2026 - El Término Medio (nivel 2).

Uso:
    python3 costeo.py --datos <carpeta nivel-2 descomprimida> --salida costos.csv

Entradas (dentro de --datos):
    recetas.json, catalogo.csv, rendimientos.csv, facturas/*.pdf, notas/*.pdf

Toda la aritmética se hace con fracciones exactas; solo se redondea al final
(2 decimales, mitad hacia arriba).
"""
import argparse
import csv
import json
import re
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path

import pdfplumber

FECHA_COSTEO = date(2026, 10, 31)
COLUMNAS = ["Cant.", "Unidad", "P. unitario", "Bonif.%", "Neto"]
COLUMNAS_RE = re.compile(r"Cant\.|Unidad|P\. unitario|Bonif\.%|Neto")


def num(s):
    """'5000,00' -> Fraction(5000). Formato argentino: coma decimal."""
    s = s.strip().replace("$", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return Fraction(s)


def fecha(s):
    a, m, d = (int(x) for x in s.split("-"))
    return date(a, m, d)


def texto_pdf(ruta):
    with pdfplumber.open(ruta) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


# ---------------------------------------------------------------- catálogo
def cargar_catalogo(ruta):
    """(producto, presentación) -> cantidad base; producto -> unidad base."""
    equiv, unidad_base = {}, {}
    with open(ruta, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            equiv[(r["producto"], r["presentacion"])] = Fraction(r["cantidad_base"])
            ub = unidad_base.setdefault(r["producto"], r["unidad_base"])
            if ub != r["unidad_base"]:
                raise ValueError(f"unidad base inconsistente para {r['producto']}")
    return equiv, unidad_base


def cargar_rendimientos(ruta):
    rend = {}
    with open(ruta, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rend[r["producto"]] = (Fraction(r["limpio_sobre_bruto"]),
                                   Fraction(r["cocido_sobre_limpio"]))
    return rend


# ---------------------------------------------------------------- facturas
def parsear_factura(ruta):
    txt = texto_pdf(ruta)
    fid = re.search(r"Factura\s+(F-\d+)", txt).group(1)
    f = fecha(re.search(r"Fecha:\s*(\d{4}-\d{2}-\d{2})", txt).group(1))
    lineas = txt.splitlines()
    i_enc = next(i for i, l in enumerate(lineas) if l.startswith("R ") and "Código" in l)
    orden = COLUMNAS_RE.findall(lineas[i_enc])  # el orden de columnas varía por factura
    if sorted(orden) != sorted(COLUMNAS):
        raise ValueError(f"{fid}: encabezado inesperado {orden}")
    renglones, total = [], None
    for l in lineas[i_enc + 1:]:
        if l.startswith("TOTAL"):
            total = num(l.split("$")[1])
            break
        tok = l.split()
        if not tok or not tok[0].isdigit():
            continue
        valores = dict(zip(orden, tok[-5:]))
        renglones.append({
            "factura": fid, "fecha": f, "renglon": int(tok[0]),
            "producto": tok[1], "descripcion": " ".join(tok[2:-5]),
            "unidad": valores["Unidad"], "cantidad": num(valores["Cant."]),
            "precio": num(valores["P. unitario"]), "bonif": num(valores["Bonif.%"]),
            "neto": num(valores["Neto"]),
        })
    # Controles aritméticos: neto = cant * precio * (1 - bonif) y total = suma de netos.
    for r in renglones:
        calc = r["cantidad"] * r["precio"] * (1 - r["bonif"] / 100)
        if abs(calc - r["neto"]) > Fraction(1, 100):
            print(f"AVISO {fid} r{r['renglon']}: neto {float(r['neto'])} != {float(calc):.2f}",
                  file=sys.stderr)
    if total is not None and abs(sum(r["neto"] for r in renglones) - total) > Fraction(1, 100):
        print(f"AVISO {fid}: total no coincide con la suma de netos", file=sys.stderr)
    return renglones


def parsear_nota(ruta):
    txt = texto_pdf(ruta)
    campo = lambda k: re.search(rf"{k}:\s*(.+)", txt).group(1).strip()
    cant_txt = campo("Cantidad devuelta").split()
    return {
        "nota": re.search(r"(NC-\d+)", txt).group(1),
        "fecha": fecha(campo("Fecha")),
        "factura": campo("Factura asociada"),
        "renglon": int(campo("Renglón")),
        "producto": campo("Producto").split()[0],
        "concepto": campo("Concepto"),
        "cantidad": num(cant_txt[0]), "unidad": cant_txt[1],
        "importe": num(campo("Importe acreditado")),
    }


def precios_efectivos(datos, equiv, unidad_base, log):
    renglones = []
    for p in sorted((datos / "facturas").glob("*.pdf")):
        renglones += parsear_factura(p)
    notas = [parsear_nota(p) for p in sorted((datos / "notas").glob("*.pdf"))]

    # Cantidad equivalente en unidad base, según la presentación DE ESE producto.
    for r in renglones:
        r["cant_base"] = r["cantidad"] * equiv[(r["producto"], r["unidad"])]
        r["neto_aj"] = r["neto"]
        r["notas"] = []

    # Las notas ajustan su factura y renglón de origen (no son compras nuevas).
    idx = {(r["factura"], r["renglon"]): r for r in renglones}
    for n in notas:
        if n["fecha"] > FECHA_COSTEO:
            continue
        r = idx[(n["factura"], n["renglon"])]
        if r["producto"] != n["producto"]:
            raise ValueError(f"{n['nota']}: producto no coincide con el renglón")
        r["neto_aj"] -= n["importe"]                     # bonificación y devolución restan importe
        if n["cantidad"]:                                 # solo la devolución resta unidades
            r["cant_base"] -= n["cantidad"] * equiv[(n["producto"], n["unidad"])]
        r["notas"].append(n["nota"])

    # Última factura <= fecha de costeo; empate de fecha -> id alfanumérico mayor.
    precio = {}
    for prod in sorted(unidad_base):
        cand = [r for r in renglones if r["producto"] == prod and r["fecha"] <= FECHA_COSTEO]
        if not cand:
            continue
        r = max(cand, key=lambda x: (x["fecha"], x["factura"]))
        precio[prod] = r["neto_aj"] / r["cant_base"]
        log.append(f"{prod} {r['factura']} r{r['renglon']} {r['fecha']} "
                   f"neto={float(r['neto_aj']):.2f} cant={float(r['cant_base']):g}"
                   f"{unidad_base[prod]} notas={r['notas'] or '-'} "
                   f"precio={float(precio[prod]):.6f}/{unidad_base[prod]}")
    return precio


# ---------------------------------------------------------------- recetas
def costear(recetas, precio, unidad_base, rend):
    por_cod = {r["codigo"]: r for r in recetas}
    memo, en_curso = {}, set()

    def costo_tanda(cod):
        if cod in memo:
            return memo[cod]
        if cod in en_curso:
            raise ValueError(f"ciclo en recetas: {cod}")
        en_curso.add(cod)
        total = Fraction(0)
        for ing in por_cod[cod]["ingredientes"]:
            p, q, u, e = ing["producto"], ing["cantidad"], ing["unidad"], ing["estado"]
            if e == "preparado":
                sub = por_cod[p]
                if u != sub["unidad_rendimiento"]:
                    raise ValueError(f"{cod}: unidad {u} vs rendimiento de {p}")
                total += q * costo_tanda(p) / sub["rendimiento"]
                continue
            if u != unidad_base[p]:
                raise ValueError(f"{cod}: unidad {u} vs base {unidad_base[p]} de {p}")
            lsb, csl = rend[p]
            factor = {"bruto": Fraction(1), "limpio": 1 / lsb, "cocido": 1 / (lsb * csl)}[e]
            total += q * factor * precio[p]           # cantidad bruta equivalente x precio
        en_curso.discard(cod)
        memo[cod] = total
        return total

    platos = [r for r in recetas if r["unidad_rendimiento"] == "porción"]
    return {r["codigo"]: costo_tanda(r["codigo"]) / r["rendimiento"] for r in platos}


def redondear(x):
    return (Decimal(x.numerator) / Decimal(x.denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", required=True, type=Path)
    ap.add_argument("--salida", required=True, type=Path)
    a = ap.parse_args()

    equiv, unidad_base = cargar_catalogo(a.datos / "catalogo.csv")
    rend = cargar_rendimientos(a.datos / "rendimientos.csv")
    with open(a.datos / "recetas.json", encoding="utf-8") as f:
        recetas = json.load(f, parse_float=Fraction, parse_int=Fraction)

    log = []
    precio = precios_efectivos(a.datos, equiv, unidad_base, log)
    print("\n".join(log), file=sys.stderr)
    costos = costear(recetas, precio, unidad_base, rend)

    with open(a.salida, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["plato", "costo_por_porcion"])
        for cod in sorted(costos):
            w.writerow([cod, f"{redondear(costos[cod]):.2f}"])
    print(f"{len(costos)} platos -> {a.salida}", file=sys.stderr)


if __name__ == "__main__":
    main()
