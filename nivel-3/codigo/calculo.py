#!/usr/bin/env python3
"""Nivel 3 · Costos por porción al 31/10/2026 y márgenes del trimestre ago-oct 2026.

Uso:
    python3 calculo.py --datos2 <carpeta nivel-2 descomprimida> --datos3 <carpeta nivel-3 descomprimida> \
                       --salida <carpeta donde escribir costos.csv y margenes.csv>

Compras:
  * lote anterior: facturas F-001..F-040 y notas NC-001..NC-004 (PDF del nivel 2), leídas con el
    parser de nivel-2/codigo/costeo.py;
  * compras nuevas: 12 remitos manuscritos (M-001..M-012) y 15 tickets (T-001..T-015), transcriptos en
    compras_imagenes.csv (validados contra totales_imagenes.csv).

Precio de un producto a una fecha D: renglón de la última compra con fecha <= D (empate de fecha: id mayor),
ajustado por las notas de ese renglón emitidas hasta D. Recetas, catálogo y rendimientos: los del nivel 2.

Aritmética exacta con Fraction; redondeo final mitad hacia arriba.
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parents[1] / "nivel-2" / "codigo"))
import costeo  # noqa: E402  (parser de PDF, catálogo, rendimientos y costeo recursivo del nivel 2)

CIERRE = date(2026, 10, 31)
INICIO = date(2026, 8, 1)
TOL = Fraction(1, 100)


def d2(x, q="0.01"):
    return (Decimal(x.numerator) / Decimal(x.denominator)).quantize(Decimal(q), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ compras
def compras_pdf(datos2):
    renglones = []
    for p in sorted((datos2 / "facturas").glob("*.pdf")):
        renglones += costeo.parsear_factura(p)
    notas = [costeo.parsear_nota(p) for p in sorted((datos2 / "notas").glob("*.pdf"))]
    return renglones, notas


def compras_imagenes(ruta_renglones, ruta_totales):
    renglones, suma = [], defaultdict(Fraction)
    with open(ruta_renglones, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            cant, precio, bonif, neto = (Fraction(r[k]) for k in ("cantidad", "precio_unitario", "bonif_pct", "neto"))
            calc = cant * precio * (1 - bonif / 100)
            if abs(calc - neto) > TOL:
                raise ValueError(f"{r['documento']} r{r['renglon']}: neto {neto} != {float(calc):.2f}")
            suma[r["documento"]] += neto
            renglones.append({"factura": r["documento"], "fecha": date.fromisoformat(r["fecha"]),
                              "renglon": int(r["renglon"]), "producto": r["producto"],
                              "unidad": r["presentacion"], "cantidad": cant, "neto": neto})
    with open(ruta_totales, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if abs(suma[r["documento"]] - Fraction(r["total"])) > TOL:
                raise ValueError(f"{r['documento']}: suma de netos {float(suma[r['documento']])} != total {r['total']}")
    return renglones


class Precios:
    """Precio efectivo por producto a cualquier fecha (última compra <= fecha + notas emitidas <= fecha)."""

    def __init__(self, renglones, notas, equiv, unidad_base):
        self.unidad_base = unidad_base
        self.por_prod = defaultdict(list)
        for r in renglones:
            r["cant_base"] = r["cantidad"] * equiv[(r["producto"], r["unidad"])]
            self.por_prod[r["producto"]].append(r)
        idx = {(r["factura"], r["renglon"]): r for r in renglones}
        self.notas = defaultdict(list)
        for n in notas:
            r = idx[(n["factura"], n["renglon"])]
            if r["producto"] != n["producto"]:
                raise ValueError(f"{n['nota']}: producto no coincide con su renglón")
            cant = n["cantidad"] * equiv[(n["producto"], n["unidad"])] if n["cantidad"] else Fraction(0)
            self.notas[(n["factura"], n["renglon"])].append((n["fecha"], n["importe"], cant, n["nota"]))

    def vigente(self, prod, fecha):
        cand = [r for r in self.por_prod[prod] if r["fecha"] <= fecha]
        if not cand:
            raise ValueError(f"sin compras de {prod} al {fecha}")
        r = max(cand, key=lambda x: (x["fecha"], x["factura"]))
        empate = [c for c in cand if c["fecha"] == r["fecha"] and c["factura"][0] != r["factura"][0]]
        if empate:
            raise ValueError(f"empate entre series distintas para {prod} el {r['fecha']}")
        neto, cant, aplicadas = r["neto"], r["cant_base"], []
        for f, imp, c, nid in self.notas[(r["factura"], r["renglon"])]:
            if f <= fecha:
                neto, cant = neto - imp, cant - c
                aplicadas.append(nid)
        return neto / cant, r, aplicadas

    def tabla(self, fecha):
        return {p: self.vigente(p, fecha)[0] for p in sorted(self.unidad_base)}


# ------------------------------------------------------------------ caja
def cargar_caja(datos3):
    caja = datos3 / "caja"
    art = defaultdict(list)
    with open(caja / "articulos.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            art[r["articulo"]].append((date.fromisoformat(r["desde"]), date.fromisoformat(r["hasta"]), r["plato"]))
    combos = defaultdict(list)
    with open(caja / "combos.csv", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            combos[r["combo"]].append((r["plato"], Fraction(r["unidades"]), Fraction(r["peso_ingreso"])))
    movs = []
    for p in sorted(caja.glob("2026-*.csv")):
        with open(p, encoding="utf-8", newline="") as f:
            movs += list(csv.DictReader(f))
    return art, combos, movs


def plato_de(art, codigo, fecha):
    hits = [pl for desde, hasta, pl in art[codigo] if desde <= fecha <= hasta]
    if len(hits) != 1:
        raise ValueError(f"artículo {codigo} sin vigencia única al {fecha}")
    return hits[0]


def margenes(art, combos, movs, costo_en):
    """Devuelve {plato: [unidades, ingreso, costo]} y un resumen de control."""
    por_id = {m["id"]: m for m in movs}
    if len(por_id) != len(movs):
        raise ValueError("ids de movimiento repetidos")
    acum = defaultdict(lambda: [Fraction(0), Fraction(0), Fraction(0)])
    cuenta = defaultdict(int)
    revertidos = set()

    def componentes(m):
        """Reparto de un movimiento VTA/COM: lista de (plato, unidades, ingreso, costo) en sentido positivo."""
        fecha = date.fromisoformat(m["fecha_hora"][:10])
        cant = Fraction(m["cantidad"])
        cobro = Fraction(m["importe_bruto"]) - Fraction(m["descuento"])
        costos = costo_en(fecha)
        if m["tipo"] == "VTA":
            pl = plato_de(art, m["articulo"], fecha)
            return [(pl, cant, cobro, cant * costos[pl])]
        comp = combos[m["articulo"]]
        if not comp:
            raise ValueError(f"combo desconocido {m['articulo']}")
        peso_total = sum(w for _, _, w in comp)
        return [(pl, cant * u, cobro * w / peso_total, cant * u * costos[pl]) for pl, u, w in comp]

    for m in movs:
        t = m["tipo"]
        cuenta[t] += 1
        if t in ("VTA", "COM"):
            signo, base = 1, m
        elif t == "REV":
            base = por_id.get(m["referencia"])
            if base is None or base["tipo"] not in ("VTA", "COM"):
                raise ValueError(f"REV {m['id']} con referencia inválida {m['referencia']}")
            if base["id"] in revertidos:
                raise ValueError(f"{base['id']} revertido dos veces")
            for k in ("articulo", "cantidad", "importe_bruto", "descuento"):
                if base[k] != m[k]:
                    raise ValueError(f"REV {m['id']} no replica {k} de {base['id']}")
            revertidos.add(base["id"])
            signo = -1   # reparto y costo del original (fecha original), con sentido inverso
        elif t == "EXT":
            continue     # propina del personal: fuera de la facturación de platos
        else:
            raise ValueError(f"tipo desconocido {t}")
        for pl, u, ing, cos in componentes(base):
            a = acum[pl]
            a[0] += signo * u
            a[1] += signo * ing
            a[2] += signo * cos
    return acum, dict(cuenta), len(revertidos)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos2", required=True, type=Path)
    ap.add_argument("--datos3", required=True, type=Path)
    ap.add_argument("--salida", required=True, type=Path)
    ap.add_argument("--compras", type=Path, default=AQUI / "compras_imagenes.csv")
    ap.add_argument("--totales", type=Path, default=AQUI / "totales_imagenes.csv")
    a = ap.parse_args()
    a.salida.mkdir(parents=True, exist_ok=True)

    equiv, unidad_base = costeo.cargar_catalogo(a.datos2 / "catalogo.csv")
    rend = costeo.cargar_rendimientos(a.datos2 / "rendimientos.csv")
    with open(a.datos2 / "recetas.json", encoding="utf-8") as f:
        recetas = json.load(f, parse_float=Fraction, parse_int=Fraction)
    platos = sorted(r["codigo"] for r in recetas if r["unidad_rendimiento"] == "porción")

    ren_pdf, notas = compras_pdf(a.datos2)
    ren_img = compras_imagenes(a.compras, a.totales)
    precios = Precios(ren_pdf + ren_img, notas, equiv, unidad_base)

    memo = {}

    def costo_en(fecha):
        if fecha not in memo:
            memo[fecha] = costeo.costear(recetas, precios.tabla(fecha), unidad_base, rend)
        return memo[fecha]

    # ---- costos al cierre
    for p in sorted(unidad_base):
        pr, r, ns = precios.vigente(p, CIERRE)
        print(f"{p} {r['factura']} r{r['renglon']} {r['fecha']} notas={ns or '-'} "
              f"precio={float(pr):.6f}/{unidad_base[p]}", file=sys.stderr)
    cierre = costo_en(CIERRE)
    with open(a.salida / "costos.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["plato", "costo_por_porcion"])
        for pl in platos:
            w.writerow([pl, f"{d2(cierre[pl])}"])

    # ---- márgenes del trimestre
    art, combos, movs = cargar_caja(a.datos3)
    acum, cuenta, nrev = margenes(art, combos, movs, costo_en)
    with open(a.salida / "margenes.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["plato", "unidades_vendidas", "ingreso_neto", "costo", "margen"])
        for pl in platos:
            u, ing, cos = acum.get(pl, (Fraction(0),) * 3)
            if u.denominator != 1:
                raise ValueError(f"unidades no enteras para {pl}")
            mg = Fraction(0) if ing == 0 else (ing - cos) / ing
            w.writerow([pl, u.numerator, f"{d2(ing)}", f"{d2(cos)}", f"{d2(mg, '0.000001')}"])
    extra = sorted(set(acum) - set(platos))
    if extra:
        raise ValueError(f"ventas de platos fuera del recetario: {extra}")
    print(f"movimientos {cuenta}, reversiones aplicadas {nrev}, fechas costeadas {len(memo)}", file=sys.stderr)
    print(f"-> {a.salida / 'costos.csv'} y {a.salida / 'margenes.csv'}", file=sys.stderr)


if __name__ == "__main__":
    main()
