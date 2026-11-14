#!/usr/bin/env python3
"""OCR local de facturas y tickets con LightOnOCR-3-0.8B (CPU), en paralelo.

Uso:
    python ocr_pipeline.py --entrada <carpeta con .jpg> [<carpeta> ...] --salida <carpeta> [--workers N]

- Cada worker es un proceso que carga el modelo una sola vez.
- Un semáforo acotado (BoundedSemaphore) limita cuántas imágenes se procesan a la vez;
  el límite se calcula según núcleos y RAM disponibles (o --workers).
- Por cada imagen escribe <nombre>.txt con la transcripción cruda del modelo.
"""
import argparse
import os
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

MODEL_ID = "lightonai/LightOnOCR-3-0.8B"
MEM_POR_WORKER_GB = 5.0     # pesos fp32 (~3,6 GB) + activaciones
MIN_HILOS_POR_WORKER = 2
LADO_MAX = 1540             # se reduce la imagen para acotar tokens visuales

_modelo = _proc = None


def capacidad(workers_pedidos=None):
    nucleos = os.cpu_count() or 1
    try:
        with open("/proc/meminfo") as f:
            info = {l.split(":")[0]: int(l.split()[1]) for l in f}
        ram_gb = info["MemAvailable"] / 1024 / 1024
    except OSError:
        ram_gb = 8.0
    por_cpu = max(1, nucleos // MIN_HILOS_POR_WORKER)
    por_ram = max(1, int(ram_gb // MEM_POR_WORKER_GB))
    n = min(por_cpu, por_ram)
    if workers_pedidos:
        n = min(n, workers_pedidos)
    hilos = max(1, nucleos // n)
    return n, hilos, nucleos, ram_gb


def _init(hilos):
    global _modelo, _proc
    import torch
    from transformers import AutoProcessor, Qwen3_5ForConditionalGeneration
    torch.set_num_threads(hilos)
    _modelo = Qwen3_5ForConditionalGeneration.from_pretrained(MODEL_ID, dtype=torch.float32)
    _modelo.eval()
    _proc = AutoProcessor.from_pretrained(MODEL_ID)


def _ocr(ruta, salida):
    import torch
    from PIL import Image
    t0 = time.time()
    img = Image.open(ruta).convert("RGB")
    img.thumbnail((LADO_MAX, LADO_MAX))
    conv = [{"role": "user", "content": [{"type": "image", "image": img}]}]  # prompt vacío = transcripción
    inputs = _proc.apply_chat_template(conv, add_generation_prompt=True, tokenize=True,
                                       return_dict=True, return_tensors="pt", enable_thinking=False)
    with torch.inference_mode():
        out = _modelo.generate(**inputs, max_new_tokens=1200, do_sample=False)
    texto = _proc.decode(out[0, inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    destino = Path(salida) / (Path(ruta).stem + ".txt")
    destino.write_text(texto, encoding="utf-8")
    return str(ruta), time.time() - t0, len(texto)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", nargs="+", required=True, type=Path)
    ap.add_argument("--salida", required=True, type=Path)
    ap.add_argument("--workers", type=int)
    ap.add_argument("--solo-faltantes", action="store_true")
    a = ap.parse_args()
    a.salida.mkdir(parents=True, exist_ok=True)

    imgs = sorted(p for d in a.entrada for p in d.glob("*.jpg"))
    if a.solo_faltantes:
        imgs = [p for p in imgs if not (a.salida / (p.stem + ".txt")).exists()]
    n, hilos, nucleos, ram = capacidad(a.workers)
    print(f"{len(imgs)} imágenes | {nucleos} núcleos, {ram:.1f} GB libres -> "
          f"{n} workers x {hilos} hilos", file=sys.stderr, flush=True)

    sem = threading.BoundedSemaphore(n)   # semáforo: nunca más de n imágenes en vuelo
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=n, initializer=_init, initargs=(hilos,)) as ex:
        futs = []
        for p in imgs:
            sem.acquire()
            f = ex.submit(_ocr, str(p), str(a.salida))
            f.add_done_callback(lambda _f: sem.release())
            futs.append(f)
        for f in as_completed(futs):
            ruta, seg, largo = f.result()
            print(f"  {Path(ruta).name}: {seg:.0f}s, {largo} caracteres", file=sys.stderr, flush=True)
    print(f"listo en {time.time() - t0:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
