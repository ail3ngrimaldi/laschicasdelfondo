#!/usr/bin/env python3
"""Recorta y endereza el papel de cada foto (factura/ticket) antes del OCR.

1. Máscara del papel: gris + desenfoque + umbral de Otsu (el papel es claro, la mesa oscura).
2. Cierre morfológico y contorno de mayor área.
3. Cuatro esquinas: approxPolyDP sobre la envolvente convexa (si no da 4, minAreaRect).
4. Transformación de perspectiva a un rectángulo recto (corrige rotación e inclinación).

Uso:
    python preprocesar.py --entrada <carpeta> [<carpeta> ...] --salida <carpeta>
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np


def ordenar(pts):
    pts = pts.reshape(4, 2).astype("float32")
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], "float32")


def esquinas(img):
    gris = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (9, 9), 0)
    _, masc = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    masc = cv2.morphologyEx(masc, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    conts, _ = cv2.findContours(masc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(conts, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.15 * img.shape[0] * img.shape[1]:
        return None
    casco = cv2.convexHull(c)
    per = cv2.arcLength(casco, True)
    for eps in (0.01, 0.02, 0.03, 0.05):
        ap = cv2.approxPolyDP(casco, eps * per, True)
        if len(ap) == 4:
            return ordenar(ap)
    return ordenar(cv2.boxPoints(cv2.minAreaRect(c)))


def enderezar(img):
    q = esquinas(img)
    if q is None:
        return img, False
    tl, tr, br, bl = q
    w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], "float32")
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(q, dst), (w, h)), True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", nargs="+", required=True, type=Path)
    ap.add_argument("--salida", required=True, type=Path)
    a = ap.parse_args()
    a.salida.mkdir(parents=True, exist_ok=True)
    for p in sorted(x for d in a.entrada for x in d.glob("*.jpg")):
        img = cv2.imread(str(p))
        out, ok = enderezar(img)
        cv2.imwrite(str(a.salida / p.name), out, [cv2.IMWRITE_JPEG_QUALITY, 92])
        print(f"{p.name}: {img.shape[1]}x{img.shape[0]} -> {out.shape[1]}x{out.shape[0]}"
              f"{'' if ok else '  (sin papel detectado, se deja igual)'}", file=sys.stderr)


if __name__ == "__main__":
    main()
