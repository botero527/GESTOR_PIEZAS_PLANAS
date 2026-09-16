"""
Puente entre la UI (pywebview / HTML-JS) y la lógica real de Python.

Todo lo que la interfaz necesita de Python pasa por la clase Api. Cada
método devuelve dicts/listas planas (JSON-friendly) — la UI nunca toca
objetos COM directamente.
"""
import os
from pathlib import Path

import webview

from dxf_processor import get_all_open_documents
import compensacion
from lites_processor import procesar_lites

TIPOS_CRISTAL = [
    {"id": "SODALIME_WHITE", "label": "Sodalime / White"},
    {"id": "ALUMINUM", "label": "Aluminum"},
    {"id": "OTROS", "label": "Otros"},
]


class Api:
    # ── Archivo AutoCAD ────────────────────────────────────────────────

    def listar_documentos(self):
        """Lista los DWG abiertos en cualquier instancia de AutoCAD."""
        try:
            docs = get_all_open_documents()
        except Exception as ex:
            return {"ok": False, "error": str(ex), "documentos": []}
        return {
            "ok": True,
            "documentos": [
                {"name": d["name"], "path": d["path"], "guardado": os.path.isabs(d["path"])}
                for d in docs
            ],
        }

    # ── Datos de referencia para la tabla de lites ──────────────────────

    def tipos_cristal(self):
        return TIPOS_CRISTAL

    def espesores_validos(self, tipo_cristal: str):
        try:
            return {"ok": True, "espesores": compensacion.espesores_validos(tipo_cristal)}
        except Exception as ex:
            return {"ok": False, "error": str(ex), "espesores": []}

    def calcular_compensacion(self, tipo_cristal, espesor, pintura, caja, pieza_grande):
        """Preview en vivo del valor de compensación mientras el usuario
        llena la tabla — sin tocar AutoCAD todavía."""
        try:
            comp = compensacion.obtener_compensacion(
                tipo_cristal, espesor, bool(pintura), bool(caja), bool(pieza_grande)
            )
            return {"ok": True, **comp}
        except ValueError as ex:
            return {"ok": False, "error": str(ex)}

    # ── Carpeta de destino (diálogo nativo) ─────────────────────────────

    def elegir_carpeta(self):
        # OJO: nunca guardar la ventana como atributo de esta clase (self.window = ...).
        # pywebview expone este objeto tal cual a JS vía js_api, e intenta describir
        # sus atributos — si uno de ellos es la ventana (que carga el control nativo
        # de Windows), pywebview termina recorriendo su AccessibilityObject y entra
        # en una recursión infinita que revienta la app al arrancar. Por eso se pide
        # la ventana viva en cada llamada, igual que en PipeMirror/main.py.
        if not webview.windows:
            return {"ok": False, "error": "Ventana no inicializada."}
        resultado = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if not resultado:
            return {"ok": False, "carpeta": None}
        return {"ok": True, "carpeta": resultado[0]}

    # ── Procesamiento real ───────────────────────────────────────────────

    def procesar(self, payload: dict):
        """
        payload esperado:
            {
              "documento": {"name": ..., "path": ...},
              "tiene_tecoflex": bool,
              "pieza_grande": bool,          # global, una sola respuesta (como tecoflex)
              "modo_accesorio": "PC"|"AL"|None,
              "cantidad_pc": int,             # solo si modo_accesorio == "PC"
              "lites": [{"posicion":100,"tipo_cristal":...,"espesor":...,
                         "pintura":bool,"caja":bool}, ...],
              "nombre_general": "PIEZA",
              "carpeta_destino": "C:/..."
            }
        """
        try:
            resultado = procesar_lites(
                acad_doc=payload["documento"],
                tiene_tecoflex=bool(payload.get("tiene_tecoflex")),
                lites=payload["lites"],
                nombre_general=payload["nombre_general"],
                carpeta_destino=payload["carpeta_destino"],
                pieza_grande=bool(payload.get("pieza_grande")),
                modo_accesorio=payload.get("modo_accesorio"),
                cantidad_pc=int(payload.get("cantidad_pc") or 0),
            )
            return {"ok": True, **resultado}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    # ── Utilidades de resultado ──────────────────────────────────────────

    def abrir_carpeta(self, ruta_archivo: str):
        """Abre en el explorador de Windows la carpeta que contiene el
        archivo indicado (usado en la pantalla de resultado)."""
        try:
            os.startfile(str(Path(ruta_archivo).parent))
            return {"ok": True}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
