"""
Procesador de LITES — nueva lógica de piezas planas.

Modelo real del dibujo: el layer PERIMETRO (o su alias "0100") tiene
SIEMPRE una sola pieza (una polilínea cerrada). Esa misma pieza se usa
para calcular el lite 100. Si además existe un layer OFFSET (o su alias
"BASE"), TODO LO DEMÁS (los demás lites, PC y TAPA) sale de ESE layer en
vez de PERIMETRO — el lite 100 es la única excepción, siempre sale de
PERIMETRO. Si no existe OFFSET, todo (incluido el lite 100) sale de
PERIMETRO, tal como funcionaba antes de que existiera esta distinción.

El lite 100 NUNCA pasa por TECOFLEX — compensa directo sobre el
PERIMETRO crudo, así la pieza tenga TECOFLEX activado o no (el TECOFLEX
de PERIMETRO igual se calcula y se guarda como capa, pero solo para
poder compararlo visualmente en el archivo comparativo, no se usa como
fuente de ningún cálculo). ÚNICA EXCEPCIÓN: si la pieza es PACHA
(pregunta global nueva, requiere TECOFLEX activo), el lite 100 SÍ
compensa desde TECOFLEX. PACHA no afecta a ningún otro lite, ni a PC,
ni a TAPA.

Regla de oro (no negociable): cada lite/PC/TAPA se calcula SIEMPRE
agarrando de nuevo su fuente original (PERIMETRO u OFFSET, con o sin
TECOFLEX) — nunca se encadena el resultado de uno para calcular otro.

Flujo por archivo (un solo DWG abierto en AutoCAD, se trabaja sobre el
original):

    1. Se valida que el layer PERIMETRO/0100 exista, tenga UNA sola
       pieza, y que esté cerrada. Si existe además un layer OFFSET/BASE,
       se valida igual (opcional, pero si existe también debe ser una
       sola pieza cerrada).
    2. Si tiene TECOFLEX: offset de 3mm hacia adentro desde PERIMETRO
       (layer TECOFLEX, solo para comparar visualmente, el lite 100 NO
       lo usa) y, si hay OFFSET, otro offset de 3mm desde OFFSET (layer
       TECOFLEX_BASE, esta sí es la fuente real de "el resto").
    3. Por cada lite: se busca la compensación en la tabla
       (compensacion.py) y se hace un offset hacia AFUERA desde la
       fuente que le toque (PERIMETRO crudo si es el lite 100,
       OFFSET/TECOFLEX_BASE si no) -> layer "<posicion>_<compensacion>"
       (ej. "200_1.5").
    4. Si se eligió PC: por cada PC (1..n) un offset independiente hacia
       adentro desde la fuente de "el resto" -> layers PC_1..PC_n (PC_1 =
       cantidad_pc+3 mm, bajando de a 1 hasta 4 en el último).
    5. TAPA (siempre que se eligió PC o AL, AL requiere TECOFLEX): la
       fórmula depende del modo de accesorio (no de PACHA). PC: 1mm hacia
       AFUERA de la fuente de "el resto" (esa fuente ya es el tecoflex de
       la base si hay tecoflex, o la base cruda si no) — el tamaño de la
       pieza (grande/pequeña) ya no cambia esta cuenta. AL: copia EXACTA
       de PERIMETRO, sin ningún offset (0mm).
    6. Se guarda el archivo principal (SaveAs, como siempre — este sí
       queda en DWG, es el archivo de trabajo original del usuario).
    7. Se genera un DXF independiente por lite (SOLO su resultado,
       centrado en el origen), uno para PC (SOLO PC_1..PC_n, sin TAPA),
       uno para TAPA sola, y un DXF comparativo (fila de piezas: la base
       original + su TECOFLEX si aplica + el resultado de cada lite, con
       etiqueta de posición — este es el único que conserva más de una
       cosa por diseño, para poder comparar). Todos (lite/PC/TAPA/
       comparativo) se guardan en DXF, no DWG.

Nombre de los archivos de salida (lo arma el usuario con 4 campos):
código de vehículo + versión + letra + <dígito de posición, o "9" para
TAPA, o "PC" para el archivo PC> + tipo de pieza, todo pegado (ej.
"1890" + "000" + "A" + "2" + "001" = "1890000A2001.dxf" para el lite de
posición 200; "1890000A9001.dxf" para la TAPA; "1890000APC001.dxf" para
el PC). El comparativo usa la misma base + tipo de pieza + sufijo
"_comparativo.dxf".
"""
import os
import shutil
import tempfile
import time
import uuid
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
    COLOR_RED,
)
import compensacion

COLOR_RESULTADO = 2        # amarillo (ACI) — usado en TODOS los resultados: lites, PC_1..PC_n, TAPA
GAP_COMPARATIVO = 50.0       # separación (mm) entre piezas en el archivo comparativo

# Nombres alternativos aceptados para cada layer fuente (todo en mayúsculas,
# la comparación siempre es case-insensitive).
ALIAS_PERIMETRO = {"PERIMETRO", "0100"}
ALIAS_OFFSET = {"OFFSET", "BASE"}

# AutoCAD necesita editar en DWG (formato nativo), pero los archivos de
# salida (lite/PC/TAPA/comparativo) deben quedar en DXF. AC2018_DXF=65 es
# una constante fija confirmada en la documentación oficial de Autodesk —
# se usa el número literal en vez de pedirle la constante con nombre a
# `win32com.client.constants` porque esa vía depende de que pywin32 pueda
# generar su caché de tipos (falla en instalaciones/exe empaquetados),
# mismo fix ya probado en producción en PipeMirror.
DXF_TYPE = 65


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


def _fmt_valor(v):
    """Formatea un número de compensación para usarlo en un nombre de layer:
    3.0 -> "3", 1.5 -> "1.5" (sin ceros decimales de más, sin puntos raros)."""
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else str(v)


def _limpiar_layer(doc, nombre_layer):
    """Borra cualquier entidad que ya exista en ese layer — necesario
    para que reprocesar el mismo archivo abierto no vaya acumulando
    resultados viejos junto a los nuevos."""
    nombre_layer = nombre_layer.upper()
    for e in _enumerar_msp_seguro(doc):
        try:
            if e.Layer.upper() == nombre_layer:
                e.Delete()
        except Exception:
            pass


def _limpiar_layers_de_posicion(doc, pos):
    """El layer de resultado ahora se llama '<posicion>_<compensacion>'
    (ej. "200_1.5"), así que si se reprocesa el mismo archivo con un
    espesor/pintura/caja distinto, el NOMBRE del layer cambia (la
    compensación es otra) y un borrado por nombre exacto ya no encuentra
    el layer viejo — quedaría huérfano con entidades viejas. Esto borra
    las entidades de cualquier layer que empiece por "<posicion>_", sin
    importar qué compensación tenía la vez anterior, y de paso borra la
    definición del layer ya vacío para no dejar basura en el dibujo."""
    prefijo = str(pos)
    capas_afectadas = set()
    for e in _enumerar_msp_seguro(doc):
        try:
            capa = e.Layer
        except Exception:
            continue
        if capa.split("_", 1)[0] == prefijo:
            capas_afectadas.add(capa)
            try:
                e.Delete()
            except Exception:
                pass
    for nombre_capa in capas_afectadas:
        try:
            doc.Layers.Item(nombre_capa).Delete()
        except Exception:
            pass  # capa "0"/actual/con algo más adentro no se puede borrar, no pasa nada


def _mover(entity, dx, dy=0.0):
    """Traslada una entidad (dx, dy) usando Move nativo de AutoCAD."""
    p1 = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [0.0, 0.0, 0.0])
    p2 = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [dx, dy, 0.0])
    entity.Move(p1, p2)


def _espejar_horizontal(doc):
    """Espeja horizontalmente (izquierda-derecha) TODAS las entidades del
    ModelSpace dado, REEMPLAZANDO cada una por su versión espejada (no
    deja las dos) — usado solo para el archivo PC, según pidió el
    usuario ("guardarlo invertido horizontalmente, un mirror")."""
    entidades = _enumerar_msp_seguro(doc)
    if not entidades:
        return
    min_x = max_x = None
    for e in entidades:
        try:
            mn, mx = e.GetBoundingBox()
        except Exception:
            continue
        if min_x is None:
            min_x, max_x = mn[0], mx[0]
        else:
            min_x = min(min_x, mn[0]); max_x = max(max_x, mx[0])
    if min_x is None:
        return
    eje_x = (min_x + max_x) / 2.0  # eje vertical por el centro del conjunto
    p1 = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [eje_x, 0.0, 0.0])
    p2 = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [eje_x, 1.0, 0.0])
    for e in entidades:
        try:
            espejo = e.Mirror(p1, p2)
            espejo.Layer = e.Layer
            espejo.color = e.color
            e.Delete()
        except Exception:
            pass


def _centrar_en_origen(doc):
    """Mueve TODAS las entidades del ModelSpace dado para que la ESQUINA
    inferior-izquierda de su bounding-box conjunto quede exactamente en
    (0,0,0) — no el centro geométrico. Todas las coordenadas quedan en
    positivo, como se ve en la imagen de referencia (UCS/origen pegado a
    la esquina de abajo-izquierda de la pieza). Se usa al guardar los
    archivos individuales (lite/PC/TAPA)."""
    entidades = _enumerar_msp_seguro(doc)
    if not entidades:
        return
    min_x = min_y = 1e18
    max_x = max_y = -1e18
    for e in entidades:
        try:
            mn, mx = e.GetBoundingBox()
        except Exception:
            continue
        min_x = min(min_x, mn[0]); max_x = max(max_x, mx[0])
        min_y = min(min_y, mn[1]); max_y = max(max_y, mx[1])
    if min_x > max_x:
        return  # ninguna entidad tenía bounding box válido
    cx = min_x
    cy = min_y
    for e in entidades:
        try:
            _mover(e, -cx, -cy)
        except Exception:
            pass


# ── Detección y validación de layers fuente (PERIMETRO/0100, OFFSET/BASE) ──

def _enumerar_msp_seguro(doc, intentos=6, espera=0.3):
    """Recorre ModelSpace de forma segura, pidiéndolo FRESCO desde `doc`
    en cada intento (no reutiliza el mismo objeto Python).

    Lo que pasaba: después de varias operaciones seguidas sobre el
    dibujo (offsets, limpiezas de layers viejos), el enumerador COM que
    pywin32 cachea en el objeto `ModelSpace` que ya tenías en una
    variable quedaba en mal estado, y NINGÚN reintento sobre ESE MISMO
    objeto lo arreglaba, ni esperando — porque el problema no era
    timing, era el objeto en sí. Pedir `doc.ModelSpace` de nuevo cada
    vez entrega un objeto fresco, sin ese enumerador viejo cacheado."""
    ultimo_error = None
    for intento in range(intentos):
        try:
            msp_fresco = doc.ModelSpace
            return list(msp_fresco)
        except pywintypes.com_error as ex:
            ultimo_error = ex
            time.sleep(espera * (intento + 1))
    raise RuntimeError(
        "No se pudo leer el contenido del dibujo (AutoCAD no respondió bien "
        f"al enumerar las entidades). Detalle: {ultimo_error}"
    )


def _closed_polyline_por_alias(doc, aliases):
    """Todas las polilíneas cerradas cuyo layer coincide (sin distinguir
    mayúsculas) con alguno de los nombres en `aliases`."""
    return [
        e for e in _enumerar_msp_seguro(doc)
        if e.ObjectName == "AcDbPolyline" and _nombre_layer(e).upper() in aliases
    ]


def _nombre_layer(entity):
    try:
        return entity.Layer
    except Exception:
        return ""


def _entidad_unica_por_alias(doc, aliases, etiqueta):
    """Devuelve la ÚNICA polilínea cerrada cuyo layer sea alguno de
    `aliases` (ej. PERIMETRO/0100). Error duro (con humor) si no hay
    ninguna, si hay más de una, o si no está cerrada."""
    entidades = _closed_polyline_por_alias(doc, aliases)
    nombres = "/".join(sorted(aliases))
    if not entidades:
        raise ValueError(
            f"No se encontró el layer '{nombres}' en el archivo.\n"
            f"Verifica que el layer se llame exactamente así."
        )
    if len(entidades) > 1:
        raise ValueError(
            f"El layer '{nombres}' debe tener una sola pieza, pero "
            f"encontré {len(entidades)}. Revisa el dibujo antes de seguir, bro."
        )
    entidad = entidades[0]
    if not entidad.Closed:
        raise ValueError(
            f"La polilínea de '{nombres}' no está cerrada.\n"
            "¿Esto quedó abierto o el vidrio también? Ciérrala e intenta de nuevo."
        )
    return entidad


def _entidad_opcional_por_alias(doc, aliases, etiqueta):
    """Como _entidad_unica_por_alias, pero devuelve None si el layer
    simplemente no existe (es opcional). Si SÍ existe, igual debe ser
    una sola pieza cerrada — si no, error duro."""
    entidades = _closed_polyline_por_alias(doc, aliases)
    if not entidades:
        return None
    return _entidad_unica_por_alias(doc, aliases, etiqueta)


# ── Proceso principal ─────────────────────────────────────────────────────

def procesar_lites(acad_doc: dict, tiene_tecoflex: bool, lites: list,
                    codigo_vehiculo: str, version: str, letra: str,
                    tipo_pieza: str, carpeta_destino: str,
                    pieza_grande: bool = False, modo_accesorio: str = None,
                    cantidad_pc: int = 0, pacha: bool = False,
                    tapa_formula: str = None, pu: bool = False) -> dict:
    """
    lites: lista de dicts, uno por lite (posición 100, 200, 300...):
        {"posicion": 100, "tipo_cristal": "SODALIME_WHITE", "espesor": 8,
         "pintura": bool, "caja": bool}

    codigo_vehiculo/version/letra/tipo_pieza: arman el nombre de los
        archivos de salida (todos en DXF). Por lite: codigo+version+letra
        +<posicion/100>+tipo_pieza (ej. "1890"+"000"+"A"+"2"+"001" =
        "1890000A2001.dxf" para el lite 200). TAPA: mismo esquema con "9"
        en vez del dígito de posición ("1890000A9001.dxf"). PC: "PC" en
        vez del dígito ("1890000APC001.dxf"). PU: "PU" en vez del dígito
        ("1890000APU001.dxf"). Comparativo: la base + tipo de pieza +
        "_comparativo.dxf".

    pieza_grande: True = grande/mediana, False = pequeña. Define tanto
        la compensación de cada lite (tabla) como la lógica de la TAPA.

    modo_accesorio: None (no aplica), "PC", "AL" o "PC_AL".
        - "PC": se generan `cantidad_pc` layers PC_1..PC_n con offset
          hacia adentro (PC_1 = cantidad_pc+3, bajando de a 1 hasta 4 en
          el último), cada uno independiente (nunca encadenado), + un
          archivo PC aparte con todos esos layers. TAPA = 1mm hacia
          afuera de la fuente del resto (fórmula de siempre).
        - "AL": no genera layers PC. Requiere tiene_tecoflex (una pieza
          sin TECOFLEX no puede ir en AL). TAPA = copia EXACTA de
          PERIMETRO, sin ningún offset (0mm) — regla distinta a PC.
        - "PC_AL": genera layers PC_1..PC_n igual que "PC" (requiere
          tiene_tecoflex, igual que AL). La fórmula de TAPA no se asume
          sola — la elige el usuario en la UI vía `tapa_formula` ("PC" o
          "AL"), porque es una pieza que combina ambos accesorios y no
          hay una única regla de negocio clara para ese caso.
        Todos generan siempre el archivo TAPA (con la fórmula que le
        corresponda).

    pacha: True/False, global (como tecoflex). SOLO cambia el lite 100:
        si es pacha, el lite 100 compensa desde TECOFLEX en vez de
        PERIMETRO crudo (única excepción a la regla de "el lite 100
        nunca pasa por tecoflex"). Requiere tiene_tecoflex=True — no
        tiene sentido un PACHA sin TECOFLEX (se valida abajo). No afecta
        a ningún otro lite, ni a PC, ni a TAPA.

    pu: True/False, independiente de PC/AL/PC_AL. Si True, genera un
        layer y archivo PU adicional: 10mm hacia AFUERA de "la fuente
        del resto" (`fuente_resto` — TECOFLEX de la base si hay tecoflex,
        si no el OFFSET si existe, si no el PERIMETRO). Mismo criterio de
        fuente que ya usan el resto de lites/PC/TAPA, solo cambia la
        magnitud (10mm en vez de la compensación de la tabla o 1mm).

    Detección de layers fuente: PERIMETRO (o su alias "0100") SIEMPRE
    debe existir, una sola pieza cerrada — es la fuente del lite 100.
    Si ADEMÁS existe un layer OFFSET (o su alias "BASE", también una
    sola pieza cerrada), TODO LO DEMÁS (los otros lites, PC, TAPA, PU) sale
    de OFFSET en vez de PERIMETRO — el lite 100 es la única excepción,
    siempre sale de PERIMETRO (salvo PACHA, ver arriba). Si TECOFLEX
    está activo, se calcula por separado para cada fuente (PERIMETRO ->
    layer TECOFLEX, OFFSET -> layer TECOFLEX_BASE).

    Devuelve:
        {"main_output", "archivos_lites", "comparativo_output",
         "archivo_pc", "archivo_tapa", "archivo_pu", "detalle", "warnings"}
    """
    if modo_accesorio in ("AL", "PC_AL") and not tiene_tecoflex:
        raise ValueError(
            "AL (solo o combinado con PC) necesita que la pieza tenga "
            "TECOFLEX — lo que no tiene TECOFLEX no tiene AL, bro. "
            "Revisa esa respuesta."
        )
    if modo_accesorio in ("PC", "PC_AL") and (not isinstance(cantidad_pc, int) or cantidad_pc < 1):
        raise ValueError("La cantidad de PC debe ser un número entero de 1 para arriba.")
    if modo_accesorio == "PC_AL" and tapa_formula not in ("PC", "AL"):
        raise ValueError(
            "Con PC y AL combinados hace falta saber qué fórmula usa la "
            "TAPA (PC o AL) — falta esa respuesta."
        )
    if pacha and not tiene_tecoflex:
        raise ValueError(
            "PACHA necesita que la pieza tenga TECOFLEX — no puede haber "
            "PACHA sin TECOFLEX, revisa esa respuesta, bro."
        )

    pythoncom.CoInitialize()
    acad, doc = _get_live_doc(acad_doc)
    original_path = str(acad_doc.get("path", doc.FullName))

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

    perimetro = _entidad_unica_por_alias(doc, ALIAS_PERIMETRO, "PERIMETRO")
    offset_entity = _entidad_opcional_por_alias(doc, ALIAS_OFFSET, "OFFSET")
    hay_offset = offset_entity is not None

    mn, mx = perimetro.GetBoundingBox()
    ancho_pieza = mx[0] - mn[0]

    warnings = []
    detalle = []

    # ── TECOFLEX ───────────────────────────────────────────────────────────
    # El lite 100 NUNCA usa tecoflex — compensa directo sobre el PERIMETRO
    # crudo. Aun así, si tiene_tecoflex está activo, se calcula igual el
    # offset de 3mm desde PERIMETRO (layer TECOFLEX) SOLO para poder verlo
    # en el archivo comparativo — no alimenta ningún cálculo real.
    fuente_100 = perimetro
    tecoflex_100_layer = None
    tecoflex_100_entity = None
    if tiene_tecoflex:
        _ensure_layer(doc, "TECOFLEX", COLOR_RED)
        _limpiar_layer(doc, "TECOFLEX")
        try:
            result = _offset_entity(perimetro, -3.0)
        except Exception as ex:
            raise RuntimeError(f"TECOFLEX falló: {ex}")
        _apply_layer_color(result, "TECOFLEX", COLOR_RED)
        tecoflex_100_layer = "TECOFLEX"
        tecoflex_100_entity = result[0]

    if pacha:
        # PACHA: única excepción a "el lite 100 nunca pasa por tecoflex".
        # Ya se validó arriba que pacha siempre viene con tiene_tecoflex
        # =True, así que tecoflex_100_entity siempre existe acá.
        fuente_100 = tecoflex_100_entity

    # Fuente de "el resto" (todo menos el lite 100): PERIMETRO si no hay
    # OFFSET (todo funciona como antes, una sola fuente); si hay OFFSET,
    # sale de ahí en vez de PERIMETRO. OJO: esto es independiente de si
    # hay TECOFLEX — a diferencia del lite 100 (que NUNCA pasa por
    # TECOFLEX), "el resto" SÍ debe pasar por TECOFLEX cuando está activo,
    # exista o no un OFFSET separado.
    base_resto = offset_entity if hay_offset else perimetro
    tecoflex_resto_layer = None
    if tiene_tecoflex:
        if hay_offset:
            _ensure_layer(doc, "TECOFLEX_BASE", COLOR_RED)
            _limpiar_layer(doc, "TECOFLEX_BASE")
            try:
                result_base = _offset_entity(offset_entity, -3.0)
            except Exception as ex:
                raise RuntimeError(f"TECOFLEX sobre OFFSET falló: {ex}")
            _apply_layer_color(result_base, "TECOFLEX_BASE", COLOR_RED)
            fuente_resto = result_base[0]
            tecoflex_resto_layer = "TECOFLEX_BASE"
        else:
            # Sin OFFSET, "el resto" comparte la misma base que el lite 100
            # (PERIMETRO) — pero a diferencia del lite 100, si hay TECOFLEX
            # sí debe compensar desde ahí. Bug real corregido acá: antes
            # esto quedaba en `fuente_100` (PERIMETRO crudo), saltándose el
            # TECOFLEX por completo cuando no había OFFSET.
            fuente_resto = tecoflex_100_entity
            tecoflex_resto_layer = tecoflex_100_layer
    else:
        fuente_resto = base_resto

    def _nombre_base(pos):
        """El nombre real del layer PERIMETRO/OFFSET (o sus alias) que le
        toca a este lite — usado para elegir qué capa base copiar en el
        comparativo."""
        return perimetro.Layer if pos == 100 else base_resto.Layer

    def _nombre_tecoflex(pos):
        """El layer TECOFLEX que le corresponde a este lite para el
        comparativo (None si tecoflex no está activo)."""
        return tecoflex_100_layer if pos == 100 else tecoflex_resto_layer

    # ── Compensación por lite (todos parten de su fuente, sin encadenar) ──
    resultados_por_lite = []
    for cfg in lites:
        pos = cfg["posicion"]
        fuente = fuente_100 if pos == 100 else fuente_resto

        try:
            comp = compensacion.obtener_compensacion(
                cfg["tipo_cristal"], cfg["espesor"],
                cfg["pintura"], cfg["caja"], pieza_grande,
            )
        except ValueError as ex:
            raise ValueError(f"Lite {pos}: {ex}")

        # Nombre del layer = posicion_compensacion (ej. "200_1.5") para que
        # se vea de una en AutoCAD cuánto se compensó esa pieza, sin tener
        # que consultar la tabla de resultado aparte.
        layer_resultado = f"{pos}_{_fmt_valor(comp['valor'])}"
        # Una sola pasada de limpieza (no dos seguidas): recorrer y borrar
        # ModelSpace dos veces seguidas revienta el enumerador COM de AutoCAD.
        _limpiar_layers_de_posicion(doc, pos)
        _ensure_layer(doc, layer_resultado, COLOR_RESULTADO)

        if comp["aplica"] and comp["valor"] > 0:
            resultado_ents = _offset_outward(fuente, comp["valor"])
        else:
            resultado_ents = [fuente.Copy()]
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
            "base_layer_name": _nombre_base(pos),
            "tecoflex_layer_name": _nombre_tecoflex(pos),
        })
        detalle.append({
            "posicion": pos,
            "compensacion_mm": comp["valor"],
            "aplica": comp["aplica"],
        })

    # ── PC (layers PC_1..PC_n, cada uno independiente desde fuente_resto) ──
    # Fuente: si hay tecoflex, sale del tecoflex de "el resto" (TECOFLEX o
    # TECOFLEX_BASE, lo que sea que fuente_resto ya represente); si no hay
    # tecoflex, sale directo del OFFSET/PERIMETRO que le toque.
    #
    # La tabla de magnitudes (PC_1=cantidad+3, bajando de a 1 hasta 4) es
    # la distancia TOTAL desde la base cruda (antes de tecoflex) — el
    # tecoflex YA representa 3mm de esa distancia. Si hay tecoflex,
    # `fuente_resto` ya está 3mm adentro, así que solo hay que ofsetear
    # el resto (total-3) DESDE ahí — si se le aplicara el total completo
    # otra vez sobre algo que ya tiene el tecoflex encima, quedaría 3mm
    # de más (bug real que hubo aquí). Sin tecoflex, `fuente_resto` es la
    # base cruda, así que ahí sí se aplica el total completo.
    # Ej. cantidad=2, con tecoflex: PC_1 = tecoflex -2mm, PC_2 = tecoflex -1mm
    # (2+3=5 y 1+3=4 en total desde la base cruda, cuadra con la tabla).
    layers_pc = []
    if modo_accesorio in ("PC", "PC_AL"):
        totales_pc = list(range(cantidad_pc + 3, 3, -1))  # distancia total desde la base cruda
        for i, total in enumerate(totales_pc, start=1):
            layer_pc = f"PC_{i}"
            dist = (total - 3) if tiene_tecoflex else total
            _ensure_layer(doc, layer_pc, COLOR_RESULTADO)
            _limpiar_layer(doc, layer_pc)
            try:
                resultado_pc = _offset_entity(fuente_resto, -abs(dist))
            except Exception as ex:
                raise RuntimeError(f"PC_{i} (offset {dist}mm) falló: {ex}")
            _apply_layer_color(resultado_pc, layer_pc, COLOR_RESULTADO)
            layers_pc.append(layer_pc)

    # ── TAPA (siempre que se eligió PC, AL o PC_AL) ───────────────────────
    # La fórmula depende del modo de accesorio (regla nueva, no tiene nada
    # que ver con PACHA):
    #   - PC: 1mm hacia AFUERA de la fuente de "el resto" (fuente_resto ya
    #     es el tecoflex de esa base si tiene tecoflex, o la base cruda si
    #     no) — ya no depende de si la pieza es grande o pequeña.
    #   - AL: copia EXACTA de PERIMETRO, sin ningún offset (0mm).
    #   - PC_AL: no hay una regla de negocio única para este caso (pieza
    #     combina los dos accesorios), así que la UI le pregunta al
    #     usuario cuál de las 2 fórmulas aplica (`tapa_formula`).
    layer_tapa = None
    if modo_accesorio in ("PC", "AL", "PC_AL"):
        formula_tapa = "AL" if modo_accesorio == "AL" else (
            tapa_formula if modo_accesorio == "PC_AL" else "PC"
        )
        layer_tapa = "TAPA"
        _ensure_layer(doc, layer_tapa, COLOR_RESULTADO)
        _limpiar_layer(doc, layer_tapa)
        if formula_tapa == "AL":
            tapa_ents = [perimetro.Copy()]
        else:
            tapa_ents = _offset_outward(fuente_resto, 1.0)
        _apply_layer_color(tapa_ents, layer_tapa, COLOR_RESULTADO)

    # ── PU (independiente de PC/AL/PC_AL) ─────────────────────────────────
    # 10mm hacia AFUERA de "la fuente del resto" (fuente_resto), el mismo
    # criterio de fuente que ya usan el resto de lites/PC/TAPA: TECOFLEX de
    # la base si hay tecoflex, si no el OFFSET si existe, si no el
    # PERIMETRO. Solo cambia la magnitud (10mm fijo).
    layer_pu = None
    if pu:
        layer_pu = "PU"
        _ensure_layer(doc, layer_pu, COLOR_RESULTADO)
        _limpiar_layer(doc, layer_pu)
        try:
            pu_ents = _offset_outward(fuente_resto, 10.0)
        except Exception as ex:
            raise RuntimeError(f"PU (offset 10mm) falló: {ex}")
        _apply_layer_color(pu_ents, layer_pu, COLOR_RESULTADO)

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

    nombre_base = f"{codigo_vehiculo}{version}{letra}"  # sin tipo_pieza ni dígito/código de posición

    # ── Archivos independientes por lite (SOLO el resultado, centrado) ────
    archivos_lites = []
    for info in resultados_por_lite:
        pos = info["posicion"]
        digito_pos = pos // 100
        fname = f"{nombre_base}{digito_pos}{tipo_pieza}.dxf"
        destino = str(Path(carpeta_destino) / fname)
        try:
            _guardar_solo_layers(acad, original_path, destino, {info["layer_resultado"]})
            archivos_lites.append({"posicion": pos, "ruta": destino})
        except Exception as ex:
            warnings.append(
                f"Lite {pos}: no se pudo guardar el archivo independiente: {ex}"
            )

    # ── Archivo comparativo (base + tecoflex + resultado, sin centrar) ────
    comparativo_output = None
    try:
        fname = f"{nombre_base}{tipo_pieza}_comparativo.dxf"
        destino = str(Path(carpeta_destino) / fname)
        _guardar_comparativo(acad, original_path, destino, resultados_por_lite, ancho_pieza)
        comparativo_output = destino
    except Exception as ex:
        warnings.append(f"No se pudo crear el archivo comparativo: {ex}")

    # ── Archivo PC (SOLO los layers PC_1..PC_n, sin TAPA, espejado) ───────
    # En el nombre, donde va el dígito de posición, para PC va literal "PC".
    # Este es el único archivo que se guarda invertido horizontalmente.
    archivo_pc = None
    if modo_accesorio in ("PC", "PC_AL"):
        try:
            fname = f"{nombre_base}PC{tipo_pieza}.dxf"
            destino = str(Path(carpeta_destino) / fname)
            _guardar_solo_layers(acad, original_path, destino, set(layers_pc), espejar=True)
            archivo_pc = destino
        except Exception as ex:
            warnings.append(f"No se pudo crear el archivo PC: {ex}")

    # ── Archivo TAPA (SOLO el layer TAPA, centrado) ───────────────────────
    # En el nombre, donde va el dígito de posición, para TAPA va literal "9".
    archivo_tapa = None
    if layer_tapa:
        try:
            fname = f"{nombre_base}9{tipo_pieza}.dxf"
            destino = str(Path(carpeta_destino) / fname)
            _guardar_solo_layers(acad, original_path, destino, {layer_tapa})
            archivo_tapa = destino
        except Exception as ex:
            warnings.append(f"No se pudo crear el archivo TAPA: {ex}")

    # ── Archivo PU (SOLO el layer PU, centrado) ───────────────────────────
    # En el nombre, donde va el dígito de posición, para PU va literal "PU".
    archivo_pu = None
    if layer_pu:
        try:
            fname = f"{nombre_base}PU{tipo_pieza}.dxf"
            destino = str(Path(carpeta_destino) / fname)
            _guardar_solo_layers(acad, original_path, destino, {layer_pu})
            archivo_pu = destino
        except Exception as ex:
            warnings.append(f"No se pudo crear el archivo PU: {ex}")

    return {
        "main_output": main_output,
        "archivos_lites": archivos_lites,
        "comparativo_output": comparativo_output,
        "archivo_pc": archivo_pc,
        "archivo_tapa": archivo_tapa,
        "archivo_pu": archivo_pu,
        "detalle": detalle,
        "warnings": warnings,
    }


# ── Generación de archivos por copia (mismo patrón que _create_pc_file) ──

def _abrir_copia_temporal(acad, original_path):
    """Copia el DWG original a un archivo DWG temporal (AutoCAD necesita
    editar en DWG, no puede editar un DXF en vivo de la misma forma) y lo
    abre. Devuelve (doc, ruta_temporal) — quien llama guarda el resultado
    final donde corresponda (típicamente DXF, vía SaveAs) y después borra
    la ruta temporal con `_borrar_temp`."""
    original_path = str(original_path).replace("/", "\\")
    temp_path = os.path.join(
        tempfile.gettempdir(), f"piezasplanas_{os.getpid()}_{uuid.uuid4().hex[:8]}.dwg"
    )
    try:
        shutil.copy2(original_path, temp_path)
    except Exception as ex:
        raise RuntimeError(f"No se pudo copiar el DWG: {ex}")
    try:
        doc = _retry_com(lambda: acad.Documents.Open(temp_path))
    except Exception as ex:
        raise RuntimeError(f"No se pudo abrir la copia: {ex}")
    try:
        doc.Activate()
    except Exception:
        pass

    # El documento recién abierto a veces no está "listo" de inmediato —
    # pedirle .ModelSpace un instante después de Open() puede fallar con
    # AttributeError (no pywintypes.com_error, por eso _retry_com no lo
    # atrapa). Se espera a que responda antes de devolverlo.
    for intento in range(10):
        try:
            _ = doc.ModelSpace.Count
            break
        except Exception:
            time.sleep(0.3 * (intento + 1))
    else:
        raise RuntimeError("La copia del DWG no terminó de abrir a tiempo.")

    return doc, temp_path


def _guardar_como_dxf(acad, doc, destino_dxf, temp_path):
    """Guarda `doc` como DXF en `destino_dxf` (AC2018_DXF), lo cierra, y
    borra el DWG temporal que se usó para editar."""
    destino_dxf = str(destino_dxf).replace("/", "\\")
    if os.path.exists(destino_dxf):
        try:
            os.remove(destino_dxf)
        except Exception:
            pass
    try:
        _retry_com(lambda: doc.SaveAs(destino_dxf, DXF_TYPE))
    finally:
        try:
            _retry_com(lambda: acad.ActiveDocument.Close(False))
        except Exception:
            pass
        try:
            os.remove(temp_path)
        except Exception:
            pass


def _guardar_solo_layers(acad, original_path, destino_dxf, layers_a_conservar, espejar=False):
    """Copia el DWG original y deja SOLO los layers indicados (nada de
    PERIMETRO/OFFSET/TECOFLEX de referencia) — cada archivo individual
    (lite/PC/TAPA) debe quedar con únicamente su resultado. Si
    espejar=True (solo el archivo PC), lo invierte horizontalmente antes
    de centrar. Al final centra en el origen (esquina inferior-izquierda
    en 0,0,0) y guarda como DXF."""
    copia_doc, temp_path = _abrir_copia_temporal(acad, original_path)

    layers_conservar = {n.upper() for n in layers_a_conservar}

    to_delete = []
    for e in _enumerar_msp_seguro(copia_doc):
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

    if espejar:
        _espejar_horizontal(copia_doc)

    _centrar_en_origen(copia_doc)

    _guardar_como_dxf(acad, copia_doc, destino_dxf, temp_path)


def _guardar_comparativo(acad, original_path, destino, resultados_por_lite, ancho_pieza):
    """Copia el DWG original y arma una fila de piezas: la base original
    de cada lite (PERIMETRO para el lite 100, OFFSET para el resto, más
    su TECOFLEX si existe) junto al RESULTADO de ese lite, uno al lado
    del otro con un espacio, y una etiqueta de texto con la posición —
    para poder ver a simple vista cómo compensó cada uno. A diferencia
    de los archivos individuales, este SÍ conserva más de una cosa por
    diseño (esa es la idea, comparar) — pero SOLO lo relevante: nada de
    PC_1/PC_2/TAPA ni layers viejos de otra corrida, eso se borra antes."""
    copia_doc, temp_path = _abrir_copia_temporal(acad, original_path)
    msp = copia_doc.ModelSpace  # solo para AddText — las lecturas usan _enumerar_msp_seguro

    # Borrar todo lo que no sea la base/tecoflex/resultado de ALGÚN lite —
    # sin esto, PC_1/PC_2/TAPA y cualquier layer huérfano de una corrida
    # anterior venían "de regalo" en la copia completa del archivo principal.
    layers_relevantes = set()
    for info in resultados_por_lite:
        layers_relevantes.add(info["base_layer_name"].upper())
        layers_relevantes.add(info["layer_resultado"].upper())
        if info.get("tecoflex_layer_name"):
            layers_relevantes.add(info["tecoflex_layer_name"].upper())
    for e in _enumerar_msp_seguro(copia_doc):
        try:
            if e.Layer.upper() not in layers_relevantes:
                e.Delete()
        except Exception:
            pass

    for i, info in enumerate(resultados_por_lite):
        dx = i * (ancho_pieza + GAP_COMPARATIVO)

        entidades_msp = _enumerar_msp_seguro(copia_doc)
        entidades_base = [
            e for e in entidades_msp
            if e.Layer.upper() == info["base_layer_name"].upper()
        ]
        entidades_resultado = [
            e for e in entidades_msp
            if e.Layer.upper() == info["layer_resultado"].upper()
        ]
        entidades_tecoflex = []
        if info.get("tecoflex_layer_name"):
            entidades_tecoflex = [
                e for e in entidades_msp
                if e.Layer.upper() == info["tecoflex_layer_name"].upper()
            ]
        if not entidades_base:
            continue
        mn, _ = entidades_base[0].GetBoundingBox()
        x0, y0 = mn[0], mn[1]

        for e in entidades_resultado:
            try:
                _mover(e, dx)
            except Exception:
                pass

        if i > 0:
            for base in entidades_base:
                try:
                    copia = base.Copy()
                    _mover(copia, dx)
                except Exception:
                    pass
            for tf in entidades_tecoflex:
                try:
                    copia = tf.Copy()
                    _mover(copia, dx)
                except Exception:
                    pass
        else:
            # El TECOFLEX del lite 100 (i=0) no se movió con el resultado
            # (el resultado del lite 100 tampoco sale de tecoflex), así que
            # simplemente se queda donde está — no hace falta copiarlo.
            pass

        punto = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_R8,
            [x0 + dx, y0 - 20.0, 0.0]
        )
        try:
            texto = msp.AddText(f"LITE {info['posicion']}", punto, 20.0)
            texto.Layer = "0"
        except Exception:
            pass

    _guardar_como_dxf(acad, copia_doc, destino, temp_path)
