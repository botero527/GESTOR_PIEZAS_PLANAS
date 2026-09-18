# PIEZAS_PLANAS

## Quién es el usuario

Andrés Botero (spina@agpglass.com), AGP Glass. Trátalo bro a bro, directo, sin rodeos ni relleno
corporativo. Le gusta ir rápido pero SIEMPRE quiere que confirmes lógica de negocio antes de
asumirla (son piezas reales de vidrio — un offset mal calculado es plata perdida). Desde el
18-sept-2026 pidió explícitamente: **cada respuesta que toque código debe traer 3 tips cortos —
teórico, técnico y práctico** — quiere ir mejorando como programador con cada sesión, no solo que
le resuelvan el problema.

## ⚠️ LEE ESTO PRIMERO SI ERES UNA SESIÓN/CUENTA NUEVA DE CLAUDE

El 18-sept-2026 Andrés avisó que iba a cambiar de cuenta de Claude y pidió dejar todo documentado
para que la sesión nueva "vaya a la par" sin perder nada. Este archivo ya está actualizado a esa
fecha. Además hay un handoff más narrativo (con la historia de CÓMO se llegó a cada decisión, útil
si algo de aquí no cuadra con lo que ves en el código) en:

- `C:\Users\abotero\OneDrive - AGP GROUP\Documentos\_respaldo_memoria_claude\HANDOFF_PIEZAS_PLANAS.md`
- `C:\Users\abotero\OneDrive - AGP GROUP\Documentos\CEREBRO\proyectos\PIEZAS_PLANAS.md` (misma info, formato "CEREBRO")

Si algo de negocio no te cuadra (una regla de compensación, un offset, el orden del wizard),
**pregunta con AskUserQuestion antes de asumir** — así se ha trabajado este proyecto desde el
principio y es como Andrés prefiere.

## Qué es este proyecto (reescrito por completo, sept-2026)

App de escritorio Python + **pywebview** (UI en HTML/CSS/JS, NO CustomTkinter — eso se abandonó)
que automatiza AutoCAD vía COM (`pywin32`) para trazar offsets de corte/perforación/tapas sobre DWG
de "piezas planas" (vidrio/policarbonato con marcos). Se empaqueta como .exe con PyInstaller y se
distribuye por red — no necesita Python instalado en la PC que lo usa.

**Desplegado en:**
`\\192.168.2.37\ingenieria\PRODUCCION\AGP PLANOS TECNICOS\Users\ANDRES ING\PIEZAS_PLANAS\PiezasPlanas_AGP.exe`
Cada vez que se cambia código hay que recompilar (`py -m PyInstaller PiezasPlanas.spec` o
`build_exe.bat`) y volver a copiar el .exe a esa ruta — no se actualiza solo.

### Modelo del dibujo (importante, no es intuitivo)

El layer `PERIMETRO` en el DWG SIEMPRE tiene una sola pieza (una polilínea cerrada) — no una por
lite. Esa misma pieza se reusa para calcular TODOS los lites/PC/TAPA que pida el usuario. Regla de
oro repetida varias veces por Andrés: **cada cálculo sale SIEMPRE del PERIMETRO/TECOFLEX original,
nunca se encadena un resultado sobre otro** (el offset de un lite nunca sale del offset ya
calculado de otro lite).

### Flujo del wizard (6 pasos + procesar)

1. **Archivo** — detecta DWG(s) abiertos en cualquier instancia de AutoCAD. Si el documento no se
   ha guardado nunca en disco (ej. `Drawing1.dwg` sin ruta real), se bloquea la selección con aviso
   — sin esto, el guardado final revienta con errores crípticos.
2. **Tecoflex** — ¿tiene? Si sí: offset 3mm hacia ADENTRO de PERIMETRO, una sola vez → layer
   `TECOFLEX` (rojo). Ese resultado (o PERIMETRO si no hay tecoflex) es la "fuente común" para todo
   lo demás.
3. **Tamaño** — ¿grande/mediana o pequeña? Global, una sola respuesta (como tecoflex), afecta la
   tabla de compensación de TODOS los lites y la lógica de la TAPA.
4. **Datos** — cantidad de lites (usuario la escribe, genera posiciones 100/200/300... de 100 en
   100), nombre general de la pieza, carpeta de destino.
5. **Lites** — tabla, una fila por posición: tipo de cristal (Sodalime/White, Aluminum, **Otros**),
   espesor (dropdown validado contra la tabla — si no existe, mensaje de error CHISTOSO a propósito,
   ver `compensacion.py`), pintura, caja → compensación calculada en vivo. "Otros" ignora
   espesor/pintura/caja: siempre 2.5mm hacia afuera, fijo.
6. **PC / AL** — ¿es PC o AL? AL solo está disponible si hay TECOFLEX ("lo que no tiene TECOFLEX no
   tiene AL" — regla textual de Andrés). Si PC: cantidad entera → offsets descendentes
   `cantidad+3, cantidad+2, ..., 4` (1 PC→4mm, 2→5,4, 3→6,5,4...), cada uno independiente desde la
   fuente común, capas `PC_1..PC_n`. TAPA siempre se genera si se eligió PC o AL: pieza pequeña →
   2mm hacia adentro de la fuente común; grande/mediana → si hay tecoflex, el PERIMETRO original tal
   cual (sin tocar); si no hay tecoflex, 1mm hacia afuera del PERIMETRO.

**Guardado:** archivo principal (SaveAs sobre el original), un DWG independiente por lite, uno para
PC (con todos los PC_1..PC_n + TAPA), uno para TAPA sola, y un comparativo (todas las piezas en fila
con etiqueta de posición, para revisar visualmente que compensó bien).

### Compensación (tabla completa en `compensacion.py`)

| Tipo cristal | Espesor | Con pintura | Con caja | Sin caja | Pieza grande (todas las opciones) |
|---|---|---|---|---|---|
| Sodalime/White | 3,4,5,6 | 2.5 | 1 | N/A (matado de filos) | 2.5 |
| Sodalime/White | 8 | 2.5 | 1 | 1 | 2.5 |
| Sodalime/White | 10,12 | 2.5 | 1.5 | 1.5 | 2.5 |
| Sodalime/White | 15,19 | 3 | 3 | 3 | 3 |
| Aluminum | 5,6,5.8 | 1.5 | 1.5 | 1.5 | 2.5 |
| Aluminum | 10 | 2.5 | 2.5 | 2.5 | 2.5 |
| Otros | (no aplica) | — | — | — | siempre 2.5 |

"N/A (matado de filos)" no es error: significa "no hay nada extra que maquinar aparte del offset
base de 3mm" — se muestra como aviso informativo, no como fallo.

## Archivos clave

- `main.py` — bootstrap de pywebview (ventana frameless, `WindowApi(Api)`).
  **⚠️ REGLA DE ORO DE ESTE ARCHIVO: nunca guardar la ventana como atributo del objeto `js_api`**
  (`self.window = window`). Causa un `RecursionError` en vivo al arrancar (pywebview intenta
  describir el objeto expuesto a JS, se mete al control nativo de Windows, entra en loop infinito
  con `AccessibilityObject`, la app se cierra sola). Usar siempre `webview.windows[0]` en el momento
  que se necesite, dentro de cada método — patrón ya probado en PipeMirror.
- `api.py` — clase `Api`, único puente pywebview↔Python. Método central: `procesar(payload)`.
- `compensacion.py` — tabla de compensación + `espesores_validos()` + mensajes de error chistosos.
- `lites_processor.py` — lógica real: detección/validación de PERIMETRO (debe ser UNA sola pieza
  cerrada), offsets, PC/AL/TAPA, guardado por copia (`_guardar_lite_independiente`,
  `_guardar_por_layers`, `_guardar_comparativo`). `_retry_com()` reintenta ante AutoCAD ocupado.
  `_verificar_carpeta_escribible()` valida permisos ANTES de tocar el dibujo (falla rápido y claro
  en vez de ofsetear todo y reventar al final). `_traducir_error_guardado()` explica en español las
  causas comunes de un fallo de `SaveAs` (AutoCAD siempre da el mismo error genérico de COM sin
  decir la causa real).
- `dxf_processor.py` — legacy: `get_all_open_documents()` / `_get_live_doc()` (SÍ se reusan en
  `lites_processor.py`), y la lógica VIEJA de PC/AL simple (`process_dxf`, offsets fijos 1mm/2mm)
  que quedó **congelada, sin usar** por si se retoma ese flujo original más adelante. No borrar.
- `ui/` — pywebview: `index.html` + `style.css` + `app.js` (wizard) + `pacman.js` (easter egg, ver
  abajo). Paleta celeste/blanco/gris de AGP, reusa patrones de PipeMirror (titlebar frameless
  arrastrable, canvas de partículas, shockwave en botones).
- `PiezasPlanas.spec` + `build_exe.bat` — build con PyInstaller (`datas=[('ui','ui')]`,
  hiddenimports pywin32).
- `requirements.txt` — solo `pywin32` + `pywebview` (se limpiaron `customtkinter`/`ezdxf`/`shapely`,
  ya no se usan).

### Easter egg: Pac-Man (`ui/pacman.js`)

Se activa escribiendo "pacman" en cualquier momento (buffer de teclas en `app.js`, se ignora si el
foco está en un input/select real). Laberinto propio, 4 fantasmas con IA por personalidad
(Blinky/Pinky/Inky/Clyde), power pellets, vidas, puntaje + highscore en `localStorage`. Cero riesgo
para la lógica real (archivo aparte, no toca `api.py`/`lites_processor.py`/etc.).

**Bug ya corregido (18-sept-2026):** el chequeo de "¿está alineado con la grilla?" usaba un umbral
más grande que el avance por frame, así que Pac-Man y los fantasmas quedaban atrapados
reenganchándose a la misma casilla cada frame sin moverse nunca. Se agregó una bandera `procesado`
por entidad (comer pellet/decidir dirección de fantasma solo UNA vez por casilla; la dirección de
Pac-Man se sigue reevaluando cada frame para que el teclado responda de inmediato incluso detenido).
Si algún día se nota "lento" o "pegado" de nuevo, empieza a mirar por ahí.

## Pendientes conocidos

- `build_exe.bat`/`PiezasPlanas.spec` ya incluyen `ui/` — si se agregan más archivos a `ui/` (otro
  asset, otra imagen), no hace falta tocar el spec (`datas=[('ui','ui')]` copia toda la carpeta).
- `README.md` sigue vacío/corrupto — no se ha priorizado, no es bloqueante.
- `prueba.py` es un archivo residual sin función (broma personal) — se puede borrar sin miedo.
- No hay tests automatizados; validación es manual abriendo AutoCAD (aunque en esta sesión se probó
  bastante contra el DWG real de ejemplo del usuario y con simulaciones headless en Node para el
  Pac-Man — ver el HANDOFF para la metodología, vale la pena reusarla).
- La lógica vieja de PC/AL (`dxf_processor.process_dxf`) sigue sin integrarse al flujo nuevo — quedó
  reemplazada por la lógica de PC/AL/TAPA de `lites_processor.py`. No se ha discutido si hace falta
  retomar algo de la vieja.
- Repo sin `.gitignore` — `build/`, `dist/`, `__pycache__` quedan trackeados en git (deuda técnica
  heredada, no se ha tocado).

## Estilo de trabajo

- Comentarios en código en español, scripts simples y directos, sin sobre-ingeniería.
- No hay credenciales ni conexiones de red en este proyecto — todo es automatización COM local con
  AutoCAD (aparte de la ruta de red interna de despliegue del .exe, que no es secreta).
- **Nunca matar `acad.exe` a la fuerza sin confirmar que no hay una sesión real del usuario en
  curso** — pasó una vez por error en esta sesión mientras Andrés estaba conectado por AnyDesk
  usando la app en ese mismo momento. Preguntar o verificar antes.
- Cuando algo de la lógica de negocio no cuadra (offsets, capas, compensaciones, orden del wizard),
  usar `AskUserQuestion` en vez de asumir.
- Validar contra el DWG de ejemplo real del usuario cuando se pueda
  (`C:\Users\abotero\Downloads\PRUEBA PLANAS.dwg`) en vez de solo revisar código — varias veces reveló
  supuestos incorrectos que la sola lectura de código no hubiera detectado (ej. al principio se
  asumió "una polilínea por lite" cuando en realidad es una sola pieza física reusada N veces).
