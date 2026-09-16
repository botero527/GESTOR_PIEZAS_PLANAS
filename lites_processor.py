"""
Procesador de LITES — nueva lógica de piezas planas.

Modelo real del dibujo: el layer PERIMETRO tiene SIEMPRE una sola pieza
(una polilínea cerrada). Esa misma pieza se usa para calcular TODOS los
lites que pidió el usuario — no hay una polilínea por lite.

Regla de oro (no negociable): cada lite se calcula SIEMPRE agarrando de
nuevo el PERIMETRO original (o su TECOFLEX, si aplica) — nunca se
encadena el resultado de un lite para calcular otro. Lite 200 jamás
sale del resultado ya compensado del lite 100; ambos salen del mismo
original.

Flujo por archivo (un solo DWG abierto en AutoCAD, se trabaja sobre el
original):

    1. Se valida que el layer PERIMETRO exista, tenga UNA sola pieza, y
       que esté cerrada.
    2. Si tiene TECOFLEX: se calcula UNA vez el offset de 3mm hacia
       adentro desde el PERIMETRO original -> layer TECOFLEX. Ese
       resultado (o el PERIMETRO mismo si no hay TECOFLEX) es la fuente
       común que se reutiliza para cada lite (releer/reofsetear desde
       una fuente sin modificarla es seguro: Offset() en AutoCAD no
       consume ni altera la entidad original, solo crea una nueva).
    3. Por cada lite: se busca la compensación en la tabla
       (compensacion.py) y se hace un offset hacia AFUERA desde esa
       fuente común -> layer RESULTADO_<posicion>.
    4. Si se eligió PC: por cada PC (1..n) un offset independiente hacia
       adentro desde la fuente común -> layers PC_1..PC_n (PC_1 =
       cantidad_pc+3 mm, bajando de a 1 hasta 4 en el último).
    5. TAPA (siempre que se eligió PC o AL, AL requiere TECOFLEX):
       pieza pequeña -> 2mm hacia adentro de la fuente común; pieza
       grande/mediana -> si tiene TECOFLEX, el PERIMETRO original tal
       cual; si no, 1mm hacia afuera del PERIMETRO.
    6. Se guarda el archivo principal (SaveAs, como siempre).
    7. Se genera un DWG independiente por lite, uno para PC (con todos
       los PC_1..PC_n + TAPA), uno para TAPA sola, y un DWG comparativo
       (fila de piezas: el original + el resultado de cada lite, con
       etiqueta de posición, para revisar visualmente que compensó bien).
"""
import os
import shutil
import time
from pathlib import Path

import pythoncom
import win32com.client
import pywintypes

from dxf_processor import (
    _get_live_doc,
    _ensure_layer,
    _offset_entity,
    _bbox_diagonal,
    _do_offset,
    _apply_layer_color,
    _layer_match,
    COLOR_RED,
)
import compensacion

COLOR_RESULTADO = 3   # verde — layer RESULTADO_<posicion>
COLOR_PC_BASE = 4      # cian — layer PC_<n> (se corre +1 por cada PC adicional)
COLOR_TAPA = 6          # magenta — layer TAPA
GAP_COMPARATIVO = 50.0  # separación (mm) entre piezas en el archivo comparativo


def _retry_com(func, intentos=8, espera=0.5):
    """Reintenta una llamada COM ante AutoCAD ocupado (RPC_E_CALL_REJECTED
    y similares) — al generar varios archivos seguidos (uno por lite +
    comparativo), AutoCAD a veces rechaza la siguiente llamada porque
    todavía está terminando la anterior."""
    ultimo_error = None
    for intento in range(intentos):
        try:
            return func()
        except pywintypes.com_error as ex:
            ultimo_error = ex
            time.sleep(espera * (intento + 1))
    raise ultimo_error


# ── Offset hacia afuera (opuesto a _offset_entity, que es hacia adentro) ──

def _offset_outward(entity, distance):
    """Offset hacia AFUERA: se queda con el resultado de MAYOR diagonal
    (la pieza crece), al contrario de _offset_entity (que busca la de
    menor diagonal, hacia adentro)."""
    if distance <= 0:
        return [entity.Copy()]
    src_diag = _bbox_diagonal(entity)
    for sign in (1, -1):
        try:
            result = _do_offset(entity, abs(distance) * sign)
            if not result:
                continue
            res_diag = _bbox_diagonal(result[0])
            if res_diag >= src_diag - 0.001:
                return result
            for e in result:
                try:
                    e.Delete()
                except Exception:
                    pass
        except Exception:
            continue
    raise RuntimeError(
        f"No se pudo calcular el offset hacia afuera ({distance} mm).\n"
        "Verifica que la polilínea sea válida."
    )


def _traducir_error_guardado(ex) -> str:
    """AutoCAD casi siempre devuelve el MISMO error genérico de COM al
    fallar un guardado ('Error saving the document'), sin decir la causa
    real. En vez de mostrar solo el código crudo, se listan las causas
    más comunes para que el usuario las descarte una por una."""
    return (
        "AutoCAD no pudo guardar el archivo. Causas mas comunes a revisar:\n"
        "  1. Que el archivo NO este en modo solo lectura (clic derecho -> Propiedades).\n"
        "  2. Que tengas permisos de escritura en esa carpeta (ojo si es una carpeta de red).\n"
        "  3. Que nadie mas tenga el archivo abierto al mismo tiempo.\n"
        "  4. Que haya espacio suficiente en el disco/servidor.\n"
        f"Detalle tecnico de AutoCAD: {ex}"
    )


def _verificar_carpeta_escribible(ruta: str, etiqueta: str, es_carpeta: bool = False):
    """Prueba a escribir un archivo temporal en la carpeta antes de
    tocar AutoCAD — así, si no hay permisos, se corta de una en vez de
    ofsetear todo el dibujo y recién ahí descubrir que no se puede
    guardar nada.

    es_carpeta=True: `ruta` YA es la carpeta a validar (ej. carpeta de
    destino elegida por el usuario). es_carpeta=False: `ruta` es un
    archivo, se valida la carpeta que lo contiene (ej. el DWG original)."""
    carpeta = ruta if es_carpeta else os.path.dirname(ruta)
    if not carpeta or not os.path.isdir(carpeta):
        raise RuntimeError(f"{etiqueta}: la carpeta '{carpeta}' no existe o no es accesible.")
    prueba = os.path.join(carpeta, f".piezasplanas_test_{os.getpid()}.tmp")
    try:
        with open(prueba, "w") as f:
            f.write("test")
    except Exception as ex:
        raise RuntimeError(
            f"{etiqueta}: no tienes permisos de escritura en '{carpeta}'. "
            f"Revísalo antes de procesar (detalle: {ex})."
        )
    finally:
        try:
            os.remove(prueba)
        except Exception:
            pass


def _limpiar_layer(msp, nombre_layer):
    """Borra cualquier entidad que ya exista en ese layer — necesario
    para que reprocesar el mismo archivo abierto no vaya acumulando
    resultados viejos junto a los nuevos."""
    nombre_layer = nombre_layer.upper()
    for e in list(msp):
        try:
            if e.Layer.upper() == nombre_layer:
                e.Delete()
        except Exception:
            pass


def _mover(entity, dx, dy=0.0):
    """Traslada una entidad (dx, dy) usando Move nativo de AutoCAD."""
    p1 = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [0.0, 0.0, 0.0])
    p2 = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [dx, dy, 0.0])
    entity.Move(p1, p2)


# ── Detección y validación del PERIMETRO (una sola pieza) ────────────────

def _perimetro_unico(msp):
    """Devuelve la ÚNICA polilínea cerrada del layer PERIMETRO. Error
    duro (con humor) si no hay layer, si hay más de una pieza, o si no
    está cerrada — el layer PERIMETRO siempre debe tener una sola pieza
    cerrada."""
    entidades = [
        e for e in msp
        if _layer_match(e, "PERIMETRO") and e.ObjectName == "AcDbPolyline"
    ]
    if not entidades:
        raise ValueError(
            "No se encontró el layer 'PERIMETRO' en el archivo.\n"
            "Verifica que el layer se llame exactamente 'PERIMETRO'."
        )
    if len(entidades) > 1:
        raise ValueError(
            f"El layer 'PERIMETRO' debe tener una sola pieza, pero "
            f"encontré {len(entidades)}. Revisa el dibujo antes de seguir, bro."
        )
    entidad = entidades[0]
    if not entidad.Closed:
        raise ValueError(
            "La polilínea de 'PERIMETRO' no está cerrada.\n"
            "¿Esto quedó abierto o el vidrio también? Ciérrala e intenta de nuevo."
        )
    return entidad


# ── Proceso principal ─────────────────────────────────────────────────────

def procesar_lites(acad_doc: dict, tiene_tecoflex: bool, lites: list,
                    nombre_general: str, carpeta_destino: str,
                    pieza_grande: bool = False, modo_accesorio: str = None,
                    cantidad_pc: int = 0) -> dict:
    """
    lites: lista de dicts, uno por lite (posición 100, 200, 300...):
        {"posicion": 100, "tipo_cristal": "SODALIME_WHITE", "espesor": 8,
         "pintura": bool, "caja": bool}
        (pieza_grande ya NO va por lite — es una sola respuesta global,
        igual que tiene_tecoflex, y aplica para todos los lites y para
        la TAPA.)

    pieza_grande: True = grande/mediana, False = pequeña. Define tanto
        la compensación de cada lite (tabla) como la lógica de la TAPA.

    modo_accesorio: None (no aplica), "PC" o "AL".
        - "PC": se generan `cantidad_pc` layers PC_1..PC_n con offset
          hacia adentro desde PERIMETRO/TECOFLEX (PC_1 = cantidad_pc+3,
          bajando de a 1 hasta 4 en el último), cada uno independiente
          (nunca encadenado), + un archivo PC aparte con todos esos
          layers + TAPA.
        - "AL": no genera layers PC, solo TAPA. Requiere tiene_tecoflex
          (una pieza sin TECOFLEX no puede ir en AL).
        Ambos casos generan siempre el archivo TAPA.

    Todos los lites (y PC/TAPA) se calculan a partir del MISMO PERIMETRO
    original (o su TECOFLEX), nunca uno a partir de otro.

    Devuelve:
        {"main_output", "archivos_lites", "comparativo_output",
         "archivo_pc", "archivo_tapa", "detalle", "warnings"}
    """
    if modo_accesorio == "AL" and not tiene_tecoflex:
        raise ValueError(
            "AL solo aplica si la pieza tiene TECOFLEX — lo que no "
            "tiene TECOFLEX no tiene AL, bro. Revisa esa respuesta."
        )
    if modo_accesorio == "PC" and (not isinstance(cantidad_pc, int) or cantidad_pc < 1):
        raise ValueError("La cantidad de PC debe ser un número entero de 1 para arriba.")

    pythoncom.CoInitialize()
    acad, doc = _get_live_doc(acad_doc)
    original_path = str(acad_doc.get("path", doc.FullName))
    msp = doc.ModelSpace

    # Si el dibujo nunca se ha guardado en disco (ej. "Drawing1.dwg" recién
    # creado), AutoCAD no le da una ruta real — mejor decirlo claro que
    # dejar que la validación de carpeta de abajo tire un error críptico
    # de "la carpeta '' no existe".
    if not os.path.isabs(original_path):
        raise RuntimeError(
            "El archivo abierto en AutoCAD todavía no se ha guardado en disco "
            f"(aparece como '{original_path}', sin carpeta real). Guárdalo "
            "primero en AutoCAD (Ctrl+S) eligiendo dónde y con qué nombre, y "
            "vuelve a intentar."
        )

    # Verificar permisos ANTES de tocar el dibujo — si esto va a fallar,
    # mejor saberlo ya que ofsetear todo y descubrirlo al final.
    _verificar_carpeta_escribible(original_path, "Archivo principal", es_carpeta=False)
    _verificar_carpeta_escribible(carpeta_destino, "Carpeta de destino", es_carpeta=True)

    perimetro = _perimetro_unico(msp)
    mn, mx = perimetro.GetBoundingBox()
    ancho_pieza = mx[0] - mn[0]

    warnings = []
    detalle = []

    # ── TECOFLEX (una sola vez, fuente común para todos los lites) ───────
    if tiene_tecoflex:
        _ensure_layer(doc, "TECOFLEX", COLOR_RED)
        _limpiar_layer(msp, "TECOFLEX")
        try:
            result = _offset_entity(perimetro, -3.0)
        except Exception as ex:
            raise RuntimeError(f"TECOFLEX falló: {ex}")
        _apply_layer_color(result, "TECOFLEX", COLOR_RED)
        fuente_comun = result[0]
    else:
        fuente_comun = perimetro

    # ── Compensación por lite (todos parten de fuente_comun, sin encadenar) ──
    resultados_por_lite = []
    for cfg in lites:
        pos = cfg["posicion"]
        try:
            comp = compensacion.obtener_compensacion(
                cfg["tipo_cristal"], cfg["espesor"],
                cfg["pintura"], cfg["caja"], pieza_grande,
            )
        except ValueError as ex:
            raise ValueError(f"Lite {pos}: {ex}")

        layer_resultado = f"RESULTADO_{pos}"
        _ensure_layer(doc, layer_resultado, COLOR_RESULTADO)
        _limpiar_layer(msp, layer_resultado)

        if comp["aplica"] and comp["valor"] > 0:
            resultado_ents = _offset_outward(fuente_comun, comp["valor"])
        else:
            resultado_ents = [fuente_comun.Copy()]
            warnings.append(
                f"Lite {pos}: sin compensación aplicable (matado de "
                "filos) — no hay nada extra que maquinar aparte del "
                "offset base."
            )

        _apply_layer_color(resultado_ents, layer_resultado, COLOR_RESULTADO)

        resultados_por_lite.append({
            "posicion": pos,
            "compensacion_mm": comp["valor"],
            "layer_resultado": layer_resultado,
        })
        detalle.append({
            "posicion": pos,
            "compensacion_mm": comp["valor"],
            "aplica": comp["aplica"],
        })

    # ── PC (layers PC_1..PC_n, cada uno independiente desde fuente_comun) ──
    layers_pc = []
    if modo_accesorio == "PC":
        # PC_1 = cantidad_pc+3, bajando de a 1 hasta 4 en el último.
        offsets_pc = list(range(cantidad_pc + 3, 3, -1))
        for i, dist in enumerate(offsets_pc, start=1):
            layer_pc = f"PC_{i}"
            color = min(COLOR_PC_BASE + (i - 1), 255)
            _ensure_layer(doc, layer_pc, color)
            _limpiar_layer(msp, layer_pc)
            try:
                resultado_pc = _offset_entity(fuente_comun, -abs(dist))
            except Exception as ex:
                raise RuntimeError(f"PC_{i} (offset {dist}mm) falló: {ex}")
            _apply_layer_color(resultado_pc, layer_pc, color)
            layers_pc.append(layer_pc)

    # ── TAPA (siempre que se eligió PC o AL) ──────────────────────────────
    layer_tapa = None
    if modo_accesorio in ("PC", "AL"):
        layer_tapa = "TAPA"
        _ensure_layer(doc, layer_tapa, COLOR_TAPA)
        _limpiar_layer(msp, layer_tapa)
        if pieza_grande:
            if tiene_tecoflex:
                # Grande/mediana + tecoflex -> la tapa es el PERIMETRO original, sin tocar.
                tapa_ents = [perimetro.Copy()]
            else:
                # Grande/mediana + sin tecoflex -> 1mm hacia afuera del PERIMETRO.
                tapa_ents = _offset_outward(perimetro, 1.0)
        else:
            # Pequeña -> 2mm hacia adentro de la fuente común (tecoflex o perimetro).
            try:
                tapa_ents = _offset_entity(fuente_comun, -2.0)
            except Exception as ex:
                raise RuntimeError(f"TAPA (offset 2mm) falló: {ex}")
        _apply_layer_color(tapa_ents, layer_tapa, COLOR_TAPA)

    # ── Guardar archivo principal (todo junto, como hoy) ─────────────────
    # Si esto falla, se corta TODO el proceso acá mismo: generar los
    # archivos de lite/PC/TAPA/comparativo a partir de un archivo que
    # nunca se guardó bien solo producía una cascada de errores confusos
    # más adelante (WinError 2 al copiar un archivo mal escrito).
    try:
        _retry_com(lambda: doc.SaveAs(str(original_path)))
    except Exception as ex:
        raise RuntimeError(_traducir_error_guardado(ex))
    main_output = original_path

    # ── Archivos independientes por lite ──────────────────────────────────
    archivos_lites = []
    for info in resultados_por_lite:
        pos = info["posicion"]
        fname = f"{nombre_general}_{pos}.dwg"
        destino = str(Path(carpeta_destino) / fname)
        try:
            _guardar_lite_independiente(acad, original_path, destino, info)
            archivos_lites.append(destino)
        except Exception as ex:
            warnings.append(
                f"Lite {pos}: no se pudo guardar el archivo independiente: {ex}"
            )

    # ── Archivo comparativo (una fila con el original + cada resultado) ──
    comparativo_output = None
    try:
        fname = f"{nombre_general}_comparativo.dwg"
        destino = str(Path(carpeta_destino) / fname)
        _guardar_comparativo(acad, original_path, destino, resultados_por_lite, ancho_pieza)
        comparativo_output = destino
    except Exception as ex:
        warnings.append(f"No se pudo crear el archivo comparativo: {ex}")

    # ── Archivo PC (todos los layers PC_1..PC_n + TAPA) ───────────────────
    archivo_pc = None
    if modo_accesorio == "PC":
        try:
            fname = f"{nombre_general}_PC.dwg"
            destino = str(Path(carpeta_destino) / fname)
            layers_conservar = set(layers_pc) | ({layer_tapa} if layer_tapa else set())
            _guardar_por_layers(acad, original_path, destino, layers_conservar)
            archivo_pc = destino
        except Exception as ex:
            warnings.append(f"No se pudo crear el archivo PC: {ex}")

    # ── Archivo TAPA (solo el layer TAPA) ──────────────────────────────────
    archivo_tapa = None
    if layer_tapa:
        try:
            fname = f"{nombre_general}_TAPA.dwg"
            destino = str(Path(carpeta_destino) / fname)
            _guardar_por_layers(acad, original_path, destino, {layer_tapa})
            archivo_tapa = destino
        except Exception as ex:
            warnings.append(f"No se pudo crear el archivo TAPA: {ex}")

    return {
        "main_output": main_output,
        "archivos_lites": archivos_lites,
        "comparativo_output": comparativo_output,
        "archivo_pc": archivo_pc,
        "archivo_tapa": archivo_tapa,
        "detalle": detalle,
        "warnings": warnings,
    }


# ── Generación de archivos por copia (mismo patrón que _create_pc_file) ──

def _abrir_copia(acad, original_path, destino):
    destino = str(destino).replace("/", "\\")
    original_path = str(original_path).replace("/", "\\")
    if os.path.exists(destino):
        try:
            os.remove(destino)
        except Exception:
            pass
    try:
        shutil.copy2(original_path, destino)
    except Exception as ex:
        raise RuntimeError(f"No se pudo copiar el DWG: {ex}")
    try:
        doc = _retry_com(lambda: acad.Documents.Open(destino))
    except Exception as ex:
        raise RuntimeError(f"No se pudo abrir la copia: {ex}")
    try:
        doc.Activate()
    except Exception:
        pass
    return doc


def _guardar_lite_independiente(acad, original_path, destino, info):
    """Copia el DWG original y deja solo: PERIMETRO, TECOFLEX (si existe)
    y el layer RESULTADO_<posicion> de ESTE lite. Borra los demás
    RESULTADO_<otra posición> (y cualquier otra cosa que no sea esa)."""
    _abrir_copia(acad, original_path, destino)
    msp = acad.ActiveDocument.ModelSpace

    layers_conservar = {"PERIMETRO", "TECOFLEX", info["layer_resultado"].upper()}

    to_delete = []
    for e in msp:
        try:
            layer = e.Layer.upper()
        except Exception:
            to_delete.append(e)
            continue
        if layer not in layers_conservar:
            to_delete.append(e)

    for e in to_delete:
        try:
            e.Delete()
        except Exception:
            pass

    _retry_com(lambda: acad.ActiveDocument.Save())
    _retry_com(lambda: acad.ActiveDocument.Close(False))


def _guardar_por_layers(acad, original_path, destino, layers_extra):
    """Copia el DWG original y deja solo PERIMETRO + TECOFLEX (si existe)
    + los layers extra indicados (ej. PC_1, PC_2, TAPA). Borra el resto.
    Mismo patrón que _guardar_lite_independiente, genérico para PC/TAPA."""
    _abrir_copia(acad, original_path, destino)
    msp = acad.ActiveDocument.ModelSpace

    layers_conservar = {"PERIMETRO", "TECOFLEX"} | {n.upper() for n in layers_extra}

    to_delete = []
    for e in msp:
        try:
            layer = e.Layer.upper()
        except Exception:
            to_delete.append(e)
            continue
        if layer not in layers_conservar:
            to_delete.append(e)

    for e in to_delete:
        try:
            e.Delete()
        except Exception:
            pass

    _retry_com(lambda: acad.ActiveDocument.Save())
    _retry_com(lambda: acad.ActiveDocument.Close(False))


def _guardar_comparativo(acad, original_path, destino, resultados_por_lite, ancho_pieza):
    """Copia el DWG original y arma una fila de piezas: el PERIMETRO
    (y TECOFLEX si existe) repetido + el RESULTADO de cada lite, uno al
    lado del otro con un espacio, y una etiqueta de texto con la
    posición — para poder ver a simple vista cómo compensó cada uno."""
    _abrir_copia(acad, original_path, destino)
    msp = acad.ActiveDocument.ModelSpace

    entidades_base = [
        e for e in msp
        if e.Layer.upper() in ("PERIMETRO", "TECOFLEX")
    ]
    if not entidades_base:
        return

    mn, _ = entidades_base[0].GetBoundingBox()
    x0_original, y0_original = mn[0], mn[1]
    paso = ancho_pieza + GAP_COMPARATIVO

    for i, info in enumerate(resultados_por_lite):
        dx = i * paso

        # Mover el resultado de este lite a su lugar en la fila.
        for e in msp:
            try:
                if e.Layer.upper() == info["layer_resultado"].upper():
                    _mover(e, dx)
            except Exception:
                pass

        # Copiar y mover una base (PERIMETRO/TECOFLEX) de referencia
        # junto a ese resultado (la base original, en i=0, se queda quieta).
        if i > 0:
            for base in entidades_base:
                try:
                    copia = base.Copy()
                    _mover(copia, dx)
                except Exception:
                    pass

        # Etiqueta de posición.
        punto = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_R8,
            [x0_original + dx, y0_original - 20.0, 0.0]
        )
        try:
            texto = msp.AddText(f"LITE {info['posicion']}", punto, 20.0)
            texto.Layer = "0"
        except Exception:
            pass

    _retry_com(lambda: acad.ActiveDocument.Save())
    _retry_com(lambda: acad.ActiveDocument.Close(False))
