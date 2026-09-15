"""Piezas Planas — AGP GROUP | punto de entrada.

Ventana nativa (pywebview) sobre ui/index.html. Misma convención que
macro_stivencito/main.py (PipeMirror): js_api expone métodos que la UI
llama vía `await pywebview.api.metodo(...)`, y todo vuelve siempre como
un dict {"ok": bool, ...}.

La lógica real (AutoCAD, offsets, tabla de compensación) vive en api.py
(clase Api) — ese archivo es el contrato ya cerrado con la UI y no se
toca aquí. Lo único que agrega este main.py son los controles de la
ventana (minimizar/cerrar) que necesita el titlebar propio, porque el
wizard corre frameless (sin marco nativo de Windows).
"""
import os
import sys

import webview

from api import Api

# ── Rutas (compatibles con PyInstaller: sys._MEIPASS cuando es .exe) ──────
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    RES_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RES_DIR = BASE_DIR

INDEX_PATH = os.path.join(RES_DIR, "ui", "index.html")


class WindowApi(Api):
    """Api + controles de ventana (titlebar propio, frameless).

    Se extiende por herencia para no tocar api.py: ese archivo es el
    contrato de negocio ya validado, esto es solo plomería de la UI.

    OJO: nunca guardar la ventana como atributo de esta clase (self.window
    = ...). Este objeto se expone tal cual a JS vía js_api, y pywebview
    intenta describir sus atributos — si uno de ellos es la ventana (que
    carga el control nativo de Windows), termina recorriendo su
    AccessibilityObject y entra en una recursión infinita que revienta la
    app al arrancar (visto en vivo: "maximum recursion depth exceeded").
    Por eso siempre se pide `webview.windows[0]` en el momento, igual que
    en PipeMirror/main.py.
    """

    def minimize(self):
        webview.windows[0].minimize()

    def close_app(self):
        webview.windows[0].destroy()


def main():
    api = WindowApi()
    webview.create_window(
        "Piezas Planas · AGP GROUP",
        INDEX_PATH,
        js_api=api,
        width=1200,
        height=800,
        min_size=(1000, 700),
        frameless=True,
        easy_drag=False,
        background_color="#f4f7fa",
    )
    webview.start()


if __name__ == "__main__":
    main()
