"""Medición de tiempos de uso — PIEZAS_PLANAS.

Tres cosas se miden, cada una en su propia tabla dentro del esquema
TIEMPOS (Azure SQL, AGP_Ingenieria):

- TIEMPOS.PIEZAS_PLANAS_SESIONES: cuánto dura la app abierta por equipo.
  Lleva `ultimo_latido` (cada SEGUNDOS_LATIDO, desde un hilo de fondo —
  prueba de "la app sigue abierta") separado de `ultima_actividad`
  (solo ante interacción real del usuario, mouse/teclado, con throttle
  desde JS) — así se distingue "abierta sin usar" de "en uso real",
  mismo patrón ya validado en macro_stivencito/PipeMirror.
- TIEMPOS.PIEZAS_PLANAS_PASOS: cuánto se demora el usuario en cada
  pantalla del wizard (una fila por paso abandonado, con su duración).
- TIEMPOS.PIEZAS_PLANAS_PROCESAMIENTOS: duración REAL de cada click en
  "Procesar" (la parte pesada: llamadas COM a AutoCAD + guardado de
  archivos), con cantidad de lites/PC y si terminó en éxito o error —
  esto es lo más valioso para saber si la app se está poniendo lenta.

Regla de oro (estampada en el nombre de la función): TODO lo de acá es
"mejor esfuerzo". Si Azure SQL está caído, con latencia, o el usuario no
tiene red, el tracking se traga el error y sigue — NUNCA debe poder
bloquear ni hacer más lento el flujo real de la app (compensación de
lites, offsets, guardado de DWG/DXF).
"""

import functools
import logging
import threading
import time

import pymssql

from db_config import (
    BASE_DE_DATOS,
    CONTRASENIA_BD,
    MINUTOS_SESION_HUERFANA,
    SEGUNDOS_LATIDO,
    SERVIDOR_BD,
    TIMEOUT_CONEXION_SEG,
    USUARIO_BD,
    VERSION_APP,
)

logger = logging.getLogger("piezasplanas.tracking")


def _conectar():
    return pymssql.connect(
        server=SERVIDOR_BD,
        user=USUARIO_BD,
        password=CONTRASENIA_BD,
        database=BASE_DE_DATOS,
        login_timeout=TIMEOUT_CONEXION_SEG,
        timeout=TIMEOUT_CONEXION_SEG,
    )


def _mejor_esfuerzo(fn):
    """Nunca deja que un fallo de red/BD se propague fuera de acá — solo
    loguea localmente y devuelve None. El resultado de estas funciones
    nunca se usa para decidir nada del flujo real de la app."""

    @functools.wraps(fn)
    def envoltura(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("tracking.%s falló (no crítico, se ignora)", fn.__name__)
            return None

    return envoltura


# ── Sesión (sin login — PIEZAS_PLANAS no tiene usuarios) ────────────────


@_mejor_esfuerzo
def limpiar_huerfanas(minutos=MINUTOS_SESION_HUERFANA):
    """Se llama una vez al arrancar, antes de abrir la sesión nueva.
    Cierra sola cualquier sesión que quedó con fin IS NULL y el último
    latido hace más de `minutos` — señal de cierre anormal (crash, Task
    Manager, apagón) en vez de cierre por la X."""
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE TIEMPOS.PIEZAS_PLANAS_SESIONES "
            "SET fin = ultimo_latido, "
            "    duracion_seg = DATEDIFF(SECOND, inicio, ultimo_latido), "
            "    cierre_tipo = 'huerfana' "
            "WHERE fin IS NULL AND ultimo_latido < DATEADD(MINUTE, -%s, GETDATE())",
            (minutos,),
        )
        conn.commit()
    finally:
        conn.close()


@_mejor_esfuerzo
def abrir_sesion(equipo):
    """Devuelve el id de sesión nuevo, o None si no hubo conexión — a
    propósito NO se propaga la excepción: sin tracking la app debe
    seguir funcionando igual, solo no se sabrá cuánto duró esta sesión."""
    conn = _conectar()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO TIEMPOS.PIEZAS_PLANAS_SESIONES "
            "(equipo, version_app, inicio, ultimo_latido) "
            "OUTPUT inserted.id "
            "VALUES (%s, %s, GETDATE(), GETDATE())",
            (equipo, VERSION_APP),
        )
        sesion_id = cur.fetchone()[0]
        conn.commit()
        return sesion_id
    finally:
        conn.close()


@_mejor_esfuerzo
def _latido(sesion_id):
    conn = _conectar()
    try:
        conn.cursor().execute(
            "UPDATE TIEMPOS.PIEZAS_PLANAS_SESIONES SET ultimo_latido = GETDATE() WHERE id = %s",
            (sesion_id,),
        )
        conn.commit()
    finally:
        conn.close()


def iniciar_latido(sesion_id, intervalo_seg=SEGUNDOS_LATIDO):
    """Lanza un hilo daemon que manda latido cada `intervalo_seg` mientras
    la app esté abierta. Daemon = no impide que el proceso cierre."""
    if not sesion_id:
        return

    def _loop():
        while True:
            time.sleep(intervalo_seg)
            _latido(sesion_id)

    threading.Thread(target=_loop, name="tiempos-latido", daemon=True).start()


@_mejor_esfuerzo
def marcar_actividad(sesion_id):
    """Se llama ante interacción real del usuario (click/tecla/mouse),
    con throttle desde JS para no saturar la BD. Junto con el latido,
    esto separa 'abierta sin usar' de 'en uso real'."""
    if not sesion_id:
        return
    conn = _conectar()
    try:
        conn.cursor().execute(
            "UPDATE TIEMPOS.PIEZAS_PLANAS_SESIONES SET ultima_actividad = GETDATE() WHERE id = %s",
            (sesion_id,),
        )
        conn.commit()
    finally:
        conn.close()


@_mejor_esfuerzo
def cerrar_sesion(sesion_id, cierre_tipo="normal"):
    if not sesion_id:
        return
    conn = _conectar()
    try:
        conn.cursor().execute(
            "UPDATE TIEMPOS.PIEZAS_PLANAS_SESIONES "
            "SET fin = GETDATE(), "
            "    duracion_seg = DATEDIFF(SECOND, inicio, GETDATE()), "
            "    cierre_tipo = %s "
            "WHERE id = %s",
            (cierre_tipo, sesion_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── Pasos del wizard ──────────────────────────────────────────────────


@_mejor_esfuerzo
def registrar_paso(sesion_id, paso, duracion_ms):
    """Una fila por cada pantalla del wizard que el usuario abandona
    (archivo/tecoflex/tamano/datos/tabla/accesorio/procesando), con
    cuánto se demoró en ella. Sirve para ver en qué paso se traba la
    gente (ej. la tabla de lites con muchas posiciones)."""
    conn = _conectar()
    try:
        conn.cursor().execute(
            "INSERT INTO TIEMPOS.PIEZAS_PLANAS_PASOS (sesion_id, paso, duracion_ms, momento) "
            "VALUES (%s, %s, %s, GETDATE())",
            (sesion_id, paso, duracion_ms),
        )
        conn.commit()
    finally:
        conn.close()


# ── Procesamiento real (lo más pesado: COM + AutoCAD) ────────────────


@_mejor_esfuerzo
def registrar_procesamiento(
    sesion_id,
    cantidad_lites,
    modo_accesorio,
    cantidad_pc,
    tiene_tecoflex,
    pieza_grande,
    duracion_ms,
    exito,
    detalle_error=None,
):
    """Una fila por cada click en 'Procesar' — la métrica más importante
    desde el punto de vista técnico, porque mide el tiempo real de las
    llamadas COM a AutoCAD (offsets + guardado de N archivos DXF), que es
    la parte que puede ponerse lenta con dibujos grandes o AutoCAD
    ocupado. `exito=False` + `detalle_error` deja ver qué tan seguido
    falla en campo y por qué."""
    conn = _conectar()
    try:
        conn.cursor().execute(
            "INSERT INTO TIEMPOS.PIEZAS_PLANAS_PROCESAMIENTOS "
            "(sesion_id, momento, cantidad_lites, modo_accesorio, cantidad_pc, "
            " tiene_tecoflex, pieza_grande, duracion_ms, exito, detalle_error) "
            "VALUES (%s, GETDATE(), %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                sesion_id,
                cantidad_lites,
                modo_accesorio,
                cantidad_pc,
                tiene_tecoflex,
                pieza_grande,
                duracion_ms,
                exito,
                (detalle_error or "")[:500] or None,
            ),
        )
        conn.commit()
    finally:
        conn.close()
