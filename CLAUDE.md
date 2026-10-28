# PIEZAS_PLANAS

## Quién es el usuario

Andrés Botero, Ingeniería/IT en AGP Glass (equipo con Laura Peláez, que define las reglas de negocio).
Trato bro a bro, todo en español. **Antes de asumir una regla de negocio, preguntar** (son piezas
reales de vidrio: un offset mal calculado es plata perdida). En cada entrega: explicar qué se hizo y
por qué, y cerrar con 3 tips (teórico, técnico, lógica). Protocolo completo en
`Documentos\CEREBRO\PROTOCOLO_TRABAJO_ANDRES.md`; lecciones en `CEREBRO\LECCIONES_APRENDIDAS.md`;
estado del proyecto en `CEREBRO\proyectos\PIEZAS_PLANAS.md`.

## Qué es

App de escritorio Python + **pywebview** (UI en `ui/`: HTML/CSS/JS) que maneja AutoCAD por COM
(`pywin32`) para sacar los offsets de "piezas planas" (vidrio/policarbonato). Se empaqueta con
PyInstaller (`PiezasPlanas.spec`) y se publica en
`\\192.168.2.37\ingenieria\PRODUCCION\AGP PLANOS TECNICOS\Users\ANDRES ING\PIEZAS_PLANAS\`
(si el .exe está en uso, se copia como `_v2`, `_v3`...). No se actualiza solo: recompilar y copiar.

## Modelo del dibujo

- `PERIMETRO` (alias `0100`): **siempre una sola** polilínea cerrada, reusada para todos los lites.
- `OFFSET` (alias `BASE`): opcional; si existe, todo lo que no es el lite 100 sale de ahí.
- **Regla de oro:** cada resultado sale de su fuente original, nunca encadenado sobre otro resultado.
- **Fuente del resto** (`fuente_resto`: lites ≠ 100, PC, TAPA de PC, PU) = TECOFLEX de la base si
  hay tecoflex; si no, OFFSET si existe; si no, PERIMETRO. Las 4 combinaciones
  (hay_offset × tiene_tecoflex) se prueban por separado: ya hubo un bug en una de ellas.
- **Lite 100**: siempre desde PERIMETRO crudo, salvo **PACHA** (entonces desde TECOFLEX).

## Asistente (5 pasos)

1. **Archivo** abierto en AutoCAD (bloquea dibujos nunca guardados en disco).
2. **¿Tecoflex?** (3 mm hacia adentro, layer `TECOFLEX` o `TECOFLEX_BASE`) → si sí, **¿PACHA?**
3. **Datos**: cantidad de lites, nombre en 4 campos (vehículo + versión + letra + tipo de pieza),
   carpeta y casilla **Simetría**.
4. **Lites**: tipo de cristal (por defecto Sodalime/White), espesor, pintura, **Caso** (1 o 2, solo
   con pintura y obligatorio), **Notch** (en el código sigue siendo `caja`: misma columna de la tabla
   de compensación, solo cambió el nombre en pantalla).
5. **PC / AL / PC y AL** (+ cantidad de PC) y **¿PU?**

No hay paso de tamaño: siempre se calcula como pieza pequeña (`pieza_grande=False`).

## Salidas

| Salida | Cálculo | Nombre (1890 + 000 + A, pieza 001) |
|---|---|---|
| Lite N | compensación de `compensacion.py` hacia afuera; layer `<pos>_<mm>` | `1890000A{N/100}001.dxf` |
| PC_1..PC_n | escalera hacia adentro desde la fuente del resto: `cantidad+3` bajando a 4 mm **medidos desde la base cruda** (con tecoflex se resta 3) | `1890000APC001.dxf`, **espejado** |
| TAPA | PC: 1 mm hacia afuera de la fuente del resto. AL o PC+AL: copia exacta de PERIMETRO | `1890000A9001.dxf` |
| PU | 10 mm hacia afuera de la fuente del resto | `1890000APU001.dxf` |
| Comparativo | todo lo fabricado en fila (cada slot con su base + tecoflex + resultado) | `1890000A001_comparativo.dxf` |

- Todo en **DXF** (`SaveAs(..., 65)` desde una copia DWG temporal), cada archivo solo con su
  resultado, esquina inferior izquierda en (0,0,0) y purgado. El archivo principal queda en DWG.
- **Caso 1**: mismo resultado, archivo del lite espejado. Caso 2: sin cambios.
- **Simetría**: además guarda el **espejo del archivo normal** de cada lite, PC, TAPA y PU, con el
  tipo de pieza par de `PARES_SIMETRIA` (copia de `_PARES_SIMETRIA` de MODULO_5: 001↔002 …
  028↔029). Espejo de algo ya espejado (PC, Caso 1) = sin espejar. Sin par → error. El
  comparativo nunca lleva simetría.

## Archivos

- `main.py` — bootstrap pywebview. **Nunca guardar la ventana como atributo del objeto js_api**
  (`self.window = ...`): pywebview recorre sus atributos y entra en recursión infinita al arrancar.
  Usar `webview.windows[0]` en el momento. Maximizar: pywebview 6 no tiene `is_maximized`, se lleva
  un bool `_maximizada` sincronizado con `events.maximized/restored`.
- `api.py` — puente único UI↔Python; `procesar(payload)` mide el tiempo real de cada proceso.
- `compensacion.py` — tabla de compensación + mensajes de error chistosos a propósito.
- `lites_processor.py` — toda la lógica: detección de layers por alias, offsets, PC/AL/TAPA/PU,
  guardado por copia (`_guardar_solo_layers`, `_espejar_horizontal`, `_centrar_en_origen`,
  `_guardar_comparativo` con slots), `_enumerar_msp_seguro()` (pide `doc.ModelSpace` fresco en cada
  reintento), `_retry_com` / `_retry_cualquier_error`, `_purgar_dibujo`.
- `dxf_processor.py` — legacy; se reusan `get_all_open_documents`, `_get_live_doc`, `_ensure_layer`
  (blindado contra timing de COM), `_apply_layer_color` (fuerza `ConstantWidth = 0`).
- `tracking.py` + `db_config.py` — tiempos de uso en Azure SQL (`AGP_Ingenieria`, esquema
  `TIEMPOS`), todo "mejor esfuerzo": un fallo de red nunca frena la app.
- `ui/pacman.js` — easter egg (escribir "pacman"), aislado de la lógica.

## Seguridad (leer antes de tocar git)

- `db_config.py` tiene la clave de Azure SQL y **no se sube** (`.gitignore`; plantilla en
  `db_config.example.py`). Tampoco `build/`, `dist/` ni `__pycache__/`: el .exe lleva la clave
  adentro.
- El repo `botero527/GESTOR_PIEZAS_PLANAS` es **público** y el commit del 2026-10-01 tuvo la clave:
  sigue en el historial. Pendiente: repo privado + rotar la clave de `DevIngenieria`.
- El clasificador de Claude Code bloquea compilar con PyInstaller (embebe la clave): el build lo
  corre Andrés (`py -m PyInstaller PiezasPlanas.spec --noconfirm`). Copiar el .exe a la red sí.

## Estilo y cuidado

- Comentarios en español, solo cuando explican un porqué no obvio. Igualar el estilo vecino.
- **Nunca** cerrar AutoCAD ni sus documentos "todos de una": puede haber trabajo del usuario.
  Cerrar los de prueba por nombre.
- Probar contra AutoCAD real. Para espejos, usar una pieza asimétrica (trapecio); un rectángulo
  espejado se ve igual y la prueba pasaría aunque el espejo no se aplicara.
- Desplegar solo con OK explícito de Andrés.
