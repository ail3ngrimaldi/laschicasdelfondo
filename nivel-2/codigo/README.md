# Nivel 2 · Costo de ingredientes por porción al 31/10/2026

`costeo.py` genera `nivel-2/costos.csv` (encabezado `plato,costo_por_porcion`, una fila por cada plato P01–P50, dos decimales).

## Cómo reproducirlo

```bash
pip install pdfplumber
python3 costeo.py --datos <carpeta nivel-2 descomprimida> --salida ../costos.csv
```

La única dependencia externa es `pdfplumber`, que se usa para leer el texto de los PDF. Por `stderr` el script imprime, para cada producto, qué factura y renglón usó, qué notas aplicó y el precio efectivo resultante.

## Entradas

| Archivo | Uso |
|---|---|
| `recetas.json` | 50 platos (rendimiento: 1 porción) y 15 subrecetas S01–S15 (rendimiento: tamaño de la tanda). Se leen con `Fraction` para que la aritmética sea exacta. |
| `catalogo.csv` | Equivalencia `(producto, presentación) → cantidad base` (g, ml o unidad). La clave es el par, porque la misma presentación vale distinto según el producto: la bolsa de papa tiene 5000 g y la de cebolla 10000 g; la unidad de aceite tiene 1500 ml y la de leche 1000 ml. |
| `rendimientos.csv` | Cocientes limpio/bruto y cocido/limpio de cada producto. |
| `facturas/*.pdf` | 40 facturas, cada una con fecha y 8 renglones. El orden de las columnas cambia según el proveedor, así que el script lee el encabezado de cada factura para saber qué columna es cuál. |
| `notas/*.pdf` | 4 notas de crédito, cada una con su factura y renglón de origen, el concepto, la cantidad devuelta y el importe acreditado. |

## Cálculo

1. **Lectura de facturas.** Se toma de cada renglón: producto, presentación, cantidad, precio unitario, bonificación y neto. A modo de control se verifica que el neto sea cantidad × precio × (1 − bonif.) y que el TOTAL sea la suma de los netos. Las 40 facturas cumplen ambos controles.
2. **Cantidad equivalente.** Es la cantidad comprada × la equivalencia del catálogo para ese producto y esa presentación.
3. **Notas de crédito.** Cada nota con fecha ≤ 31/10/2026 se aplica a su factura y renglón de origen. No se trata como una compra nueva y no cambia la fecha de la compra. Hay dos conceptos:
   - *bonificación*: resta importe y deja la cantidad igual;
   - *devolución*: resta el importe y también las unidades devueltas, convertidas con el catálogo.
4. **Factura vigente.** Para cada producto se toma el renglón de la última factura con fecha ≤ 31/10/2026. Si hay empate de fecha, gana el identificador de factura mayor.
5. **Precio efectivo.** Es el neto ajustado dividido por la cantidad equivalente ajustada, en $/g, $/ml o $/unidad.
6. **Recetas.** Cada ingrediente se pasa a cantidad bruta según su estado:
   - `bruto`: la cantidad tal cual;
   - `limpio`: cantidad ÷ (limpio/bruto);
   - `cocido`: cantidad ÷ (limpio/bruto × cocido/limpio). En cereales y legumbres el cociente cocido/limpio es mayor que 1 porque absorben agua.
   - `preparado`: cantidad × (costo de la tanda ÷ rendimiento de la tanda). Se calcula de forma recursiva y con memoria, y además se detectan ciclos. No se le vuelven a aplicar rendimientos, porque la subreceta ya los incorpora.

   El agua no tiene costo. Se comprueba que la unidad de cada ingrediente coincida con la unidad base del producto o con la unidad de rendimiento de la subreceta.
7. **Salida.** Costo por porción con redondeo a 2 decimales, mitad hacia arriba, aplicado una sola vez al final. Las subrecetas no aparecen como filas.

## Facturas y notas usadas al 31/10/2026

- Huerta del Andén: F-037. Frigorífico del Muelle: F-038. Almacén del Molino Azul: F-039. Granja La Ochava: F-040. Todas son del 24/10/2026.
- NC-003 (25/10, bonificación de $2384,64 sobre F-039 renglón 3, lenteja): el neto baja de 19872,00 a 17487,36 para 5000 g.
- NC-004 (26/10, devolución de 36 huevos y $10784,53 sobre F-040 renglón 5): quedan 144 unidades y $43138,14.
- NC-001 (sobre F-005) y NC-002 (sobre F-022) ajustan facturas que ya no son las vigentes, así que no cambian el resultado.
