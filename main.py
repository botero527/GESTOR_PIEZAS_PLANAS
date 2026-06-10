"""Piezas Planas - AGP GROUP | Herramienta de procesamiento DXF."""
import customtkinter as ctk
from tkinter import messagebox, filedialog
import threading
import os
from pathlib import Path

from dxf_processor import process_dxf, get_all_open_documents  # noqa: F401 used in _step_file
# ── Tema ──────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT   = "#2563EB"
ACCENT2  = "#1D4ED8"
DANGER   = "#EF4444"
SUCCESS  = "#22C55E"
WARN     = "#F59E0B"
SURFACE  = "#1E293B"
SURFACE2 = "#0F172A"
TEXT     = "#F1F5F9"
SUBTEXT  = "#94A3B8"
CARD     = "#273449"

FONT_TITLE  = ("Segoe UI", 22, "bold")
FONT_HEADER = ("Segoe UI", 14, "bold")
FONT_BODY   = ("Segoe UI", 12)
FONT_SMALL  = ("Segoe UI", 10)
FONT_BTN    = ("Segoe UI", 12, "bold")


# ── Widgets reutilizables ──────────────────────────────────────────────────────

class StepDot(ctk.CTkLabel):
    def __init__(self, master, number: int, active=False, done=False, **kw):
        color = ACCENT if active else (SUCCESS if done else "#334155")
        super().__init__(master, text=str(number) if not done else "✓",
                         font=("Segoe UI", 11, "bold"),
                         width=28, height=28,
                         fg_color=color,
                         text_color=TEXT,
                         corner_radius=14, **kw)


class BigButton(ctk.CTkButton):
    def __init__(self, master, text, command=None, color=ACCENT, **kw):
        super().__init__(master, text=text, command=command,
                         font=FONT_BTN, height=44,
                         fg_color=color, hover_color=ACCENT2,
                         corner_radius=10, **kw)


class Card(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color=CARD, corner_radius=14, **kw)


# ── Aplicación principal ───────────────────────────────────────────────────────

class App(ctk.CTk):
    STEPS = 4

    def __init__(self):
        super().__init__()
        self.title("Piezas Planas · AGP GROUP")
        self.geometry("640x560")
        self.resizable(False, False)
        self.configure(fg_color=SURFACE2)

        # State
        self.dxf_path    = ctk.StringVar()
        self.acad_doc    = None  # dict {name, path, app, doc} seleccionado
        self.tecoflex    = None
        self.tipo        = None   # "PC" / "AL" / "PC_AL"
        self.num_pc      = None   # 1 / 2
        self.save_folder = None   # solo para PC_AL
        self.save_name   = None   # nombre del archivo PC separado
        self.step        = 0

        self._build_header()
        self._build_step_bar()
        self._build_content()
        self._show_step(0)

    # ── Layout base ─────────────────────────────────────────────────────────

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="⬛  Piezas Planas", font=FONT_TITLE,
                     text_color=TEXT).pack(side="left", padx=24, pady=14)
        ctk.CTkLabel(hdr, text="AGP GROUP", font=FONT_SMALL,
                     text_color=SUBTEXT).pack(side="right", padx=24)

    def _build_step_bar(self):
        self.step_bar = ctk.CTkFrame(self, fg_color=SURFACE2, height=56)
        self.step_bar.pack(fill="x")
        self.step_bar.pack_propagate(False)
        self._dots = []
        labels = ["Archivo", "Tecoflex", "Tipo", "Detalle"]
        inner = ctk.CTkFrame(self.step_bar, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")
        for i, lbl in enumerate(labels):
            dot = StepDot(inner, i + 1)
            dot.grid(row=0, column=i * 3, padx=4)
            self._dots.append(dot)
            ctk.CTkLabel(inner, text=lbl, font=FONT_SMALL,
                         text_color=SUBTEXT).grid(row=1, column=i * 3, padx=4)
            if i < len(labels) - 1:
                ctk.CTkFrame(inner, width=40, height=2,
                             fg_color="#334155").grid(row=0, column=i * 3 + 1,
                                                      columnspan=2, padx=2)

    def _update_step_bar(self):
        labels = ["Archivo", "Tecoflex", "Tipo", "Detalle"]
        for i, dot in enumerate(self._dots):
            if i < self.step:
                dot.configure(text="✓", fg_color=SUCCESS)
            elif i == self.step:
                dot.configure(text=str(i + 1), fg_color=ACCENT)
            else:
                dot.configure(text=str(i + 1), fg_color="#334155")

    def _build_content(self):
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=24, pady=16)

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    # ── Paso dispatcher ──────────────────────────────────────────────────────

    def _show_step(self, step: int):
        self.step = step
        self._update_step_bar()
        self._clear_content()
        {0: self._step_file,
         1: self._step_tecoflex,
         2: self._step_tipo,
         3: self._step_detalle,
         4: self._step_processing,
         5: self._step_result}[step]()

    # ── Paso 0: Seleccionar archivo de AutoCAD ───────────────────────────────

    def _step_file(self):
        card = Card(self.content)
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(card, text="Seleccionar archivo",
                     font=FONT_HEADER, text_color=TEXT).pack(pady=(20, 4))
        ctk.CTkLabel(card,
                     text="Archivos DWG abiertos en AutoCAD:",
                     font=FONT_SMALL, text_color=SUBTEXT).pack(pady=(0, 8))

        # Lista scrollable de documentos
        self._list_frame = ctk.CTkScrollableFrame(card, fg_color="#1a2640",
                                                   corner_radius=10, height=200)
        self._list_frame.pack(fill="x", padx=24, pady=(0, 10))

        self._btn_next_file = BigButton(card, "Continuar →",
                                        command=lambda: self._show_step(1),
                                        color="#1e3a2f")
        self._btn_next_file.pack(padx=24, fill="x", pady=(0, 6))
        self._btn_next_file.configure(state="disabled")

        BigButton(card, "🔄  Actualizar lista",
                  command=self._refresh_doc_list,
                  color="#1e293b").pack(padx=24, fill="x", pady=(0, 10))

        self.after(200, self._refresh_doc_list)

    def _refresh_doc_list(self):
        # Limpiar lista
        for w in self._list_frame.winfo_children():
            w.destroy()

        docs = get_all_open_documents()

        if not docs:
            ctk.CTkLabel(self._list_frame,
                         text="No se encontró AutoCAD abierto.\nAbre un DWG e intenta de nuevo.",
                         font=FONT_SMALL, text_color=DANGER).pack(pady=20)
            self._btn_next_file.configure(state="disabled", fg_color="#1e3a2f")
            return

        self._doc_buttons = []
        for d in docs:
            btn = ctk.CTkButton(
                self._list_frame,
                text=f"  📄  {d['name']}",
                font=FONT_BODY,
                anchor="w",
                fg_color="#1e293b",
                hover_color="#2d4a6e",
                text_color=SUBTEXT,
                corner_radius=8,
                height=40,
                command=lambda doc=d: self._select_doc(doc),
            )
            btn.pack(fill="x", padx=4, pady=3)
            self._doc_buttons.append((btn, d))

    def _select_doc(self, doc: dict):
        self.acad_doc = doc
        self.dxf_path.set(doc["path"])
        # Resaltar el botón seleccionado
        for btn, d in self._doc_buttons:
            if d["path"] == doc["path"]:
                btn.configure(fg_color=ACCENT, text_color=TEXT)
            else:
                btn.configure(fg_color="#1e293b", text_color=SUBTEXT)
        self._btn_next_file.configure(state="normal", fg_color=ACCENT)

    # ── Paso 1: ¿Tiene Tecoflex? ─────────────────────────────────────────────

    def _step_tecoflex(self):
        card = Card(self.content)
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(card, text="¿La pieza tiene TECOFLEX?",
                     font=FONT_HEADER, text_color=TEXT).pack(pady=(40, 8))
        ctk.CTkLabel(card,
                     text="Si tiene TECOFLEX, se creará un offset de 3 mm\nhacia adentro del perímetro en un layer rojo.",
                     font=FONT_BODY, text_color=SUBTEXT, justify="center").pack(pady=(0, 36))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(pady=8)

        def sel(val):
            self.tecoflex = val
            self._show_step(2)

        BigButton(row, "✅  Sí, tiene TECOFLEX",
                  command=lambda: sel(True),
                  color="#14532d", width=220).pack(side="left", padx=10)
        BigButton(row, "❌  No tiene TECOFLEX",
                  command=lambda: sel(False),
                  color="#450a0a", width=220).pack(side="left", padx=10)

        ctk.CTkButton(card, text="← Atrás", font=FONT_SMALL,
                      fg_color="transparent", text_color=SUBTEXT,
                      hover_color="#1e293b",
                      command=lambda: self._show_step(0)).pack(pady=(30, 0))

    # ── Paso 2: PC / AL / Ambos ──────────────────────────────────────────────

    def _step_tipo(self):
        card = Card(self.content)
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(card, text="¿Qué tipo de accesorio tiene?",
                     font=FONT_HEADER, text_color=TEXT).pack(pady=(36, 8))
        ctk.CTkLabel(card,
                     text="Selecciona si la pieza lleva PC (policarbonato),\nAL (aluminio) o ambos.",
                     font=FONT_BODY, text_color=SUBTEXT, justify="center").pack(pady=(0, 28))

        opts = [
            ("💎  Solo PC",       "PC",    ACCENT),
            ("🔩  Solo AL",       "AL",    "#78350f"),
            ("⚙️  PC + AL",      "PC_AL", "#312e81"),
        ]
        for lbl, val, col in opts:
            def sel(v=val):
                self.tipo = v
                if v == "AL":
                    self._start_processing_direct()  # AL: no hay PC, procesar directo
                else:
                    self._show_step(3)  # PC o PC_AL: preguntar cuántos PC
            BigButton(card, lbl, command=sel, color=col, width=280
                      ).pack(pady=6)

        ctk.CTkButton(card, text="← Atrás", font=FONT_SMALL,
                      fg_color="transparent", text_color=SUBTEXT,
                      hover_color="#1e293b",
                      command=lambda: self._show_step(1)).pack(pady=(20, 0))

    # ── Paso 3: ¿Cuántos PC? ────────────────────────────────────────────────

    def _step_detalle(self):
        card = Card(self.content)
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(card, text="¿Cuántos PC tiene la pieza?",
                     font=FONT_HEADER, text_color=TEXT).pack(pady=(44, 8))

        src = "TECOFLEX" if self.tecoflex else "PERÍMETRO"
        ctk.CTkLabel(card,
                     text=f"El offset del PC se calcula desde el layer {src}.\n"
                          f"  • 1 PC → layer PC_1 (offset 1 mm)\n"
                          f"  • 2 PC → layer PC_1 (1 mm) + PC_2 (2 mm)",
                     font=FONT_BODY, text_color=SUBTEXT, justify="left").pack(pady=(0, 30), padx=40)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(pady=8)

        def sel(val):
            self.num_pc = val
            # PC_AL → pedir dónde guardar el archivo PC; otros → procesar directo
            if self.tipo == "PC_AL":
                self._show_step(4)
            else:
                self._start_processing_direct()

        BigButton(row, "1  PC", command=lambda: sel(1),
                  color="#1e3a5f", width=160).pack(side="left", padx=16)
        BigButton(row, "2  PC", command=lambda: sel(2),
                  color="#1e3a5f", width=160).pack(side="left", padx=16)

        ctk.CTkButton(card, text="← Atrás", font=FONT_SMALL,
                      fg_color="transparent", text_color=SUBTEXT,
                      hover_color="#1e293b",
                      command=lambda: self._show_step(2)).pack(pady=(30, 0))

    # ── Paso 4: Solo para PC+AL — elegir carpeta y nombre del archivo PC ──────

    def _step_processing(self):
        """Paso 4: pedir destino del archivo PC separado (solo para PC_AL)."""
        card = Card(self.content)
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(card, text="Guardar archivo PC (espejo)",
                     font=FONT_HEADER, text_color=TEXT).pack(pady=(24, 4))
        ctk.CTkLabel(card,
                     text="Elige la carpeta y el nombre del archivo DWG\nque contendrá solo los layers PC (con espejo).",
                     font=FONT_BODY, text_color=SUBTEXT, justify="center").pack(pady=(0, 14))

        # Carpeta
        folder_box = ctk.CTkFrame(card, fg_color="#1a2640", corner_radius=8,
                                  border_width=2, border_color="#334155", height=56)
        folder_box.pack(fill="x", padx=24, pady=(0, 6))
        folder_box.pack_propagate(False)
        self._folder_icon  = ctk.CTkLabel(folder_box, text="📁", font=("Segoe UI", 20))
        self._folder_icon.pack(side="left", padx=10)
        self._folder_label = ctk.CTkLabel(folder_box, text="Sin carpeta",
                                          font=FONT_SMALL, text_color=SUBTEXT, anchor="w")
        self._folder_label.pack(side="left", fill="x", expand=True)

        BigButton(card, "📂  Elegir carpeta…",
                  command=self._pick_save_folder).pack(padx=24, fill="x", pady=(0, 10))

        # Nombre del archivo
        ctk.CTkLabel(card, text="Nombre del archivo:", font=FONT_SMALL,
                     text_color=SUBTEXT, anchor="w").pack(padx=24, fill="x")
        self._name_entry = ctk.CTkEntry(card, placeholder_text="Ej: pieza_PC",
                                        font=FONT_BODY, height=38)
        self._name_entry.pack(padx=24, fill="x", pady=(4, 12))

        self._btn_procesar = BigButton(card, "⚙️  Procesar ahora",
                                       command=self._validate_and_process,
                                       color="#14532d")
        self._btn_procesar.pack(padx=24, fill="x", pady=(0, 6))

        ctk.CTkButton(card, text="← Atrás", font=FONT_SMALL,
                      fg_color="transparent", text_color=SUBTEXT,
                      hover_color="#1e293b",
                      command=lambda: self._show_step(3)).pack(pady=(2, 0))

    def _pick_save_folder(self):
        folder = filedialog.askdirectory(title="Elegir carpeta de destino")
        if folder:
            self.save_folder = folder
            self._folder_label.configure(text=folder, text_color=TEXT)
            self._folder_icon.configure(text="✅")

    def _validate_and_process(self):
        name = self._name_entry.get().strip()
        if not self.save_folder:
            messagebox.showwarning("Falta carpeta", "Elige una carpeta de destino.")
            return
        if not name:
            messagebox.showwarning("Falta nombre", "Escribe el nombre del archivo.")
            return
        self.save_name = name
        self._start_processing()

    def _start_processing_direct(self):
        """Inicia procesado sin pedir ruta (caso PC solo o AL solo)."""
        self.save_folder = None
        self.save_name   = None
        self._start_processing()

    def _start_processing(self):
        self._clear_content()
        card = Card(self.content)
        card.pack(fill="both", expand=True)
        ctk.CTkLabel(card, text="Procesando…", font=FONT_HEADER,
                     text_color=TEXT).pack(pady=(60, 16))
        self._prog = ctk.CTkProgressBar(card, width=380, mode="indeterminate",
                                        progress_color=ACCENT)
        self._prog.pack(pady=(0, 16))
        self._prog.start()
        ctk.CTkLabel(card, text="Aplicando offsets en AutoCAD…",
                     font=FONT_BODY, text_color=SUBTEXT).pack()
        threading.Thread(target=self._run_processing, daemon=True).start()

    def _run_processing(self):
        try:
            result = process_dxf(
                has_tecoflex = self.tecoflex,
                tipo         = self.tipo,
                num_pc       = self.num_pc if self.num_pc else 1,
                save_folder  = self.save_folder,
                save_name    = self.save_name,
                acad_doc     = self.acad_doc,
            )
            self._result = result
            self.after(0, lambda: self._show_step(5))
        except Exception as exc:
            self._proc_error = str(exc)
            self.after(0, self._show_error)

    def _show_error(self):
        self._prog.stop()
        messagebox.showerror("Error al procesar", self._proc_error)
        self._show_step(0)

    # ── Paso 5: Resultado ────────────────────────────────────────────────────

    def _step_result(self):
        card = Card(self.content)
        card.pack(fill="both", expand=True)

        ctk.CTkLabel(card, text="✅  ¡Proceso completado!",
                     font=FONT_HEADER, text_color=SUCCESS).pack(pady=(32, 8))

        r = self._result
        files_frame = ctk.CTkFrame(card, fg_color="#1a2640", corner_radius=10)
        files_frame.pack(fill="x", padx=24, pady=(8, 16))

        def file_row(parent, label, path, color=TEXT):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(row, text=label, font=FONT_SMALL,
                         text_color=SUBTEXT, width=140, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=Path(path).name, font=FONT_SMALL,
                         text_color=color, anchor="w").pack(side="left")

        file_row(files_frame, "Archivo principal:", r["main_output"], TEXT)
        if r.get("pc_output"):
            file_row(files_frame, "Archivo PC separado:", r["pc_output"], ACCENT)

        if r.get("warnings"):
            warn_frame = ctk.CTkFrame(card, fg_color="#422006", corner_radius=8)
            warn_frame.pack(fill="x", padx=24, pady=(0, 12))
            for w in r["warnings"]:
                ctk.CTkLabel(warn_frame, text=f"⚠  {w}", font=FONT_SMALL,
                             text_color=WARN, anchor="w").pack(padx=12, pady=4, fill="x")

        # Resumen
        lines = []
        if self.tecoflex:
            lines.append("• Layer TECOFLEX: offset 3 mm desde PERÍMETRO (rojo)")
        if self.tipo in ("PC", "PC_AL"):
            src = "TECOFLEX" if self.tecoflex else "PERÍMETRO"
            lines.append(f"• Layer PC_1: offset 1 mm desde {src} (cian)")
            if self.num_pc == 2:
                lines.append(f"• Layer PC_2: offset 2 mm desde {src} (azul)")
        if self.tipo == "PC_AL":
            lines.append("• Archivo PC separado (con espejo) creado")

        summary = ctk.CTkFrame(card, fg_color="transparent")
        summary.pack(fill="x", padx=24)
        for l in lines:
            ctk.CTkLabel(summary, text=l, font=FONT_SMALL,
                         text_color=SUBTEXT, anchor="w").pack(fill="x")

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(pady=(20, 8))

        BigButton(btn_row, "📂  Abrir carpeta",
                  command=lambda: os.startfile(Path(r["main_output"]).parent),
                  color="#14532d", width=200).pack(side="left", padx=8)
        BigButton(btn_row, "🔄  Procesar otro",
                  command=self._reset,
                  color=ACCENT, width=200).pack(side="left", padx=8)

    # ── Reset ────────────────────────────────────────────────────────────────

    def _reset(self):
        self.dxf_path.set("")
        self.acad_doc    = None
        self.tecoflex    = None
        self.tipo        = None
        self.num_pc      = None
        self.save_folder = None
        self.save_name   = None
        self._show_step(0)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
