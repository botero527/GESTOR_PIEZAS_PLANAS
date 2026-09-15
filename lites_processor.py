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
    4. Se guarda el archivo principal (SaveAs, como siempre).
    5. Se genera un DWG independiente por lite (copia del original,
       dejando solo PERIMETRO + TECOFLEX + el RESULTADO de ese lite) y
       un DWG comparativo (copia con una fila de piezas: el original +
       el resultado de cada lite, una al lado de otra con su etiqueta
       de posición, para revisar visualmente que compensó bien).
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
                    nombre_general: str, carpeta_destino: str) -> dict:
    """
    lites: lista de dicts, uno por lite (posición 100, 200, 300...):
        {"posicion": 100, "tipo_cristal": "SODALIME_WHITE", "espesor": 8,
         "pintura": bool, "caja": bool, "pieza_grande": bool}

    Todos los lites se calculan a partir del MISMO PERIMETRO original
    (o su TECOFLEX), nunca uno a partir de otro.

    Devuelve:
        {"main_output", "archivos_lites", "comparativo_output",
         "detalle", "warnings"}
    """
    pythoncom.CoInitialize()
    acad, doc = _get_live_doc(acad_doc)
    original_path = str(acad_doc.get("path", doc.FullName))
    msp = doc.ModelSpace

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
                cfg["pintura"], cfg["caja"], cfg["pieza_grande"],
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

    # ── Guardar archivo principal (todo junto, como hoy) ─────────────────
    try:
        _retry_com(lambda: doc.SaveAs(str(original_path)))
        main_output = original_path
    except Exception as ex:
        warnings.append(f"No se pudo guardar el archivo principal: {ex}")
        main_output = str(doc.FullName)

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

    return {
        "main_output": main_output,
        "archivos_lites": archivos_lites,
        "comparativo_output": comparativo_output,
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
