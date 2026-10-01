"""Configuración de la base de datos de AGP Ingeniería — Azure SQL.

Texto plano a propósito, mismo patrón ya aceptado en macro_jefferson y
en macro_stivencito/PipeMirror (db_config.py). Esta carpeta no tiene
repositorio remoto público — aun así, no subas este archivo a ningún
repo público ni lo compartas fuera de la red de AGP.

PIEZAS_PLANAS NO tiene login (a diferencia de PipeMirror) — solo mide
tiempos de uso, en su propio esquema `TIEMPOS` (esquema compartido para
tracking de tiempos entre apps AGP, pero cada app con sus propias tablas
prefijadas `PIEZAS_PLANAS_*` — la misma lección aprendida en PipeMirror:
nunca mezclar datos de dos apps en una misma tabla).
"""

SERVIDOR_BD = "agpcolombia.database.windows.net"
USUARIO_BD = "DevIngenieria"
CONTRASENIA_BD = "HiJE068i0LQVrwA"
BASE_DE_DATOS = "AGP_Ingenieria"

VERSION_APP = "PiezasPlanas-1.0"

TIMEOUT_CONEXION_SEG = 10
MINUTOS_SESION_HUERFANA = 30
SEGUNDOS_LATIDO = 60
SEGUNDOS_THROTTLE_ACTIVIDAD = 20
