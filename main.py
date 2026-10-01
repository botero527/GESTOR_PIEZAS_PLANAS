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
import getpass
import os
import socket
import sys

import webview

import tracking
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

    def toggle_maximize(self):
        window = webview.windows[0]
        if getattr(window, "is_maximized", False):
            window.restore()
        else:
            window.maximize()

    def close_app(self):
        webview.windows[0].destroy()

    def on_closing(self):
        """Enganchado a window.events.closing — cubre la X del titlebar
        propio, Alt+F4 y close_app(). Cierra la sesión de tracking (mejor
        esfuerzo: si falla, no bloquea el cierre de la app)."""
        tracking.cerrar_sesion(self._sesion_id)


def _arrancar_tracking(api):
    """Corre en el hilo que pywebview arranca junto con la ventana (ver
    webview.start(func=...) más abajo) — así el tracking nunca bloquea ni
    retrasa que la UI aparezca, aunque Azure SQL esté lento o inalcanzable."""
    tracking.limpiar_huerfanas()
    equipo = f"{socket.gethostname()}\\{getpass.getuser()}"
    api._sesion_id = tracking.abrir_sesion(equipo)
    tracking.iniciar_latido(api._sesion_id)


def main():
    api = WindowApi()
    window = webview.create_window(
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
    window.events.closing += api.on_closing
    webview.start(_arrancar_tracking, api)


if __name__ == "__main__":
    main()
