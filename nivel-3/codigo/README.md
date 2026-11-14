# Nivel 3 · Costos al 31/10/2026 y márgenes ago–oct 2026

`calculo.py` genera `nivel-3/costos.csv` y `nivel-3/margenes.csv`.

```bash
pip install pdfplumber
python3 calculo.py --datos2 <carpeta nivel-2 descomprimida> --datos3 <carpeta nivel-3 descomprimida> --salida ..
```

## Compras
- **Lote anterior:** facturas F-001..F-040 y notas NC-001..NC-004 (PDF del nivel 2), leídas con `nivel-2/codigo/costeo.py`.
- **Compras nuevas:** 12 remitos manuscritos (M-001..M-012, `facturas/`) y 15 tickets (T-001..T-015, `tickets/`), transcriptos en `compras_imagenes.csv` (120 renglones) con sus totales en `totales_imagenes.csv`. Se toman los valores vigentes (los tachados se descartan). El script verifica que cada neto = cantidad × precio × (1 − bonif.) y que la suma de netos = total de cada documento; los 27 documentos cierran.
- La transcripción se revisó contra cada imagen y se cruzó con una segunda lectura independiente (coincidencia total). `preprocesar.py` (recorte y enderezado del papel con OpenCV) y `ocr_pipeline.py` (LightOnOCR-3-0.8B en CPU, workers en paralelo acotados por un semáforo según núcleos y RAM) forman el pipeline de OCR local; no se usó su salida para los números finales.

## Precio de un producto a una fecha D
Renglón de la última compra con fecha ≤ D (empate de fecha: id de documento mayor, p. ej. T-005 sobre T-001, T-010 sobre T-006, T-015 sobre T-011), ajustado por las notas de ese renglón emitidas hasta D (bonificación: resta importe; devolución: resta importe y cantidad). Precio = neto ajustado / cantidad en unidad base del catálogo. Recetas, catálogo y rendimientos son los del nivel 2; el costeo de recetas es el mismo (estados bruto/limpio/cocido/preparado, subrecetas recursivas).

## costos.csv
Costo por porción de P01–P50 con los precios al 31/10/2026, redondeo a 2 decimales al final.

## margenes.csv
Exportación de caja (100.000 movimientos):
- `VTA`: el código de caja se traduce a plato con la vigencia de `articulos.csv` en la fecha de la venta.
- `COM`: el cobro neto (bruto − descuento) se reparte entre componentes en proporción a `peso_ingreso`, sin redondeo intermedio; unidades = cantidad × unidades del componente.
- `REV`: resta el reparto y el costo de su movimiento original (fecha y precios del original). Se valida que replique artículo, cantidad e importes y que cada original se revierta una sola vez.
- `EXT` (propinas): excluido.
- Costo de cada venta: unidades × costo por porción con las compras disponibles en la fecha de la venta (compras del mismo día incluidas) y notas emitidas hasta esa fecha.
- Margen = (ingreso − costo) / ingreso, 6 decimales (0.000000 si el ingreso es 0).
