"""Procesador de Piezas Planas — trabaja directo sobre AutoCAD abierto."""
import pythoncom
import win32com.client
from pathlib import Path


COLOR_RED    = 1   # TECOFLEX
COLOR_CYAN   = 4   # PC_1
COLOR_BLUE   = 5   # PC_2


# ── Conexión ──────────────────────────────────────────────────────────────────

def get_all_open_documents() -> list:
    """
    Enumera todos los DWG abiertos en TODAS las instancias de AutoCAD.
    Escanea el ROT completo sin filtrar por nombre.
    """
    pythoncom.CoInitialize()
    results    = []
    seen_paths = set()
    seen_apps  = set()

    def _harvest_app(app):
        try:
            app_key = f"{app.Name}_{app.Hwnd}"
        except Exception:
            app_key = str(id(app))
        if app_key in seen_apps:
            return
        seen_apps.add(app_key)
        try:
            for i in range(app.Documents.Count):
                doc  = app.Documents.Item(i)
                path = doc.FullName or doc.Name
                if path not in seen_paths:
                    seen_paths.add(path)
                    results.append({"name": doc.Name, "path": path,
                                    "app": app, "doc": doc})
        except Exception:
            pass

    # Estrategia 1: ROT completo
    try:
        rot = pythoncom.GetRunningObjectTable()
        for moniker in rot.EnumRunning():
            try:
                raw  = rot.GetObject(moniker)
                disp = raw.QueryInterface(pythoncom.IID_IDispatch)
                app  = win32com.client.Dispatch(disp)
                _    = app.Documents.Count
                _harvest_app(app)
            except Exception:
                pass
    except Exception:
        pass

    # Estrategia 2: GetActiveObject fallback
    try:
        app = win32com.client.GetActiveObject("AutoCAD.Application")
        _harvest_app(app)
    except Exception:
        pass

    return results


def get_active_file_info() -> dict:
    docs = get_all_open_documents()
    if docs:
        return {"name": docs[0]["name"], "path": docs[0]["path"], "ok": True}
    return {"name": "", "path": "", "ok": False,
            "error": "No se encontró AutoCAD abierto."}


# ── Layers ────────────────────────────────────────────────────────────────────

def _ensure_layer(doc, name, color):
    try:
        layer = doc.Layers.Item(name)
    except Exception:
        layer = doc.Layers.Add(name)
    layer.color = color


# ── Offset nativo ─────────────────────────────────────────────────────────────

def _bbox_diagonal(entity):
    try:
        mn, mx = entity.GetBoundingBox()
        return ((mx[0]-mn[0])**2 + (mx[1]-mn[1])**2) ** 0.5
    except Exception:
        return 0.0


def _do_offset(entity, distance):
    result = entity.Offset(distance)
    if isinstance(result, (tuple, list)):
        return [r for r in result if r is not None]
    items = []
    for i in range(result.Count):
        items.append(result.Item(i))
    return items


def _offset_entity(entity, distance):
    """Offset inward: compara tamaños para detectar la dirección correcta."""
    src_diag = _bbox_diagonal(entity)
    for sign in (-1, 1):
        try:
            result = _do_offset(entity, abs(distance) * sign)
            if not result:
                continue
            res_diag = _bbox_diagonal(result[0])
            if res_diag <= src_diag + 0.001:
                return result
            for e in result:
                try:
                    e.Delete()
                except Exception:
                    pass
        except Exception:
            continue
    raise RuntimeError(
        f"No se pudo calcular el offset inward ({distance} mm).\n"
        "Verifica que la polilínea del PERÍMETRO sea válida y cerrada."
    )


def _apply_layer_color(entities, layer_name, color):
    for e in entities:
        try:
            e.Layer = layer_name
            e.color = color
        except Exception:
            pass


def _layer_match(entity, layer_name):
    try:
        return entity.Layer.upper() == layer_name.upper()
    except Exception:
        return False


# ── Obtener doc vivo (evita referencias COM expiradas) ───────────────────────

def _get_live_doc(acad_doc: dict):
    """Re-obtiene el documento vivo desde AutoCAD usando la ruta guardada."""
    pythoncom.CoInitialize()
    target_path = acad_doc.get("path", "")
    target_name = acad_doc.get("name", "")

    all_docs = get_all_open_documents()
    for d in all_docs:
        if d["path"] == target_path or d["name"] == target_name:
            return d["app"], d["doc"]

    raise RuntimeError(
        f"No se encontró el archivo '{target_name}' en AutoCAD.\n"
        "Asegúrate de que sigue abierto."
    )


# ── Crear archivo PC separado ─────────────────────────────────────────────────

def _mirror_entities_in_msp(msp, pc_layers_upper):
    """
    Hace espejo (Mirror) de todas las entidades PC al lado derecho.
    El eje de simetría queda a GAP/2 a la derecha del bounding box.
    """
    # Recolectar entidades PC
    pc_entities = []
    for entity in msp:
        try:
            if entity.Layer.upper() in pc_layers_upper:
                pc_entities.append(entity)
        except Exception:
            pass

    if not pc_entities:
        return

    # Bounding box del conjunto
    min_x = min_y =  1e18
    max_x = max_y = -1e18
    for e in pc_entities:
        try:
            mn, mx = e.GetBoundingBox()
            min_x = min(min_x, mn[0]); max_x = max(max_x, mx[0])
            min_y = min(min_y, mn[1]); max_y = max(max_y, mx[1])
        except Exception:
            pass

    GAP = 20.0
    mirror_x = max_x + GAP / 2   # eje vertical a la derecha con separación GAP

    p1 = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        [mirror_x, min_y - 1e6, 0.0]
    )
    p2 = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        [mirror_x, max_y + 1e6, 0.0]
    )

    for e in list(pc_entities):
        try:
            mirrored = e.Mirror(p1, p2)   # crea copia, original queda intacto
            mirrored.Layer = e.Layer
            mirrored.color = e.color
        except Exception:
            pass


def _create_pc_file(acad, original_path, pc_layer_names, save_path):
    """
    Crea el archivo PC con Mirror.

    Flujo (sin doble SaveAs — ese era el problema):
    1.  shutil.copy2(original_path → save_path)   copia a nivel de SO, sin COM
    2.  acad.Documents.Open(save_path)             abre la copia
    3.  Borrar entidades no-PC
    4.  Mirror de entidades PC al lado derecho
    5.  acad.ActiveDocument.Save()                 guarda en su propio path
    6.  acad.ActiveDocument.Close(False)
    El original nunca se cierra, no hay que reabrirlo.
    """
    import os
    import shutil
    pythoncom.CoInitialize()

    pc_layers_upper   = {n.upper() for n in pc_layer_names}
    save_path_str     = str(save_path).replace("/", "\\")
    original_path_str = str(original_path).replace("/", "\\")

    # ── 1. Copiar DWG ya guardado (solo lectura del original) ─────────────
    if os.path.exists(save_path_str):
        try:
            os.remove(save_path_str)
        except Exception:
            pass
    try:
        shutil.copy2(original_path_str, save_path_str)
    except Exception as ex:
        raise RuntimeError(f"Paso 1 (copiar DWG): {ex}")

    # ── 2. Abrir la copia en AutoCAD ──────────────────────────────────────
    try:
        copy_doc = acad.Documents.Open(save_path_str)
    except Exception as ex:
        raise RuntimeError(f"Paso 2 (abrir copia): {ex}")

    try:
        copy_doc.Activate()
    except Exception:
        pass

    copy_msp = acad.ActiveDocument.ModelSpace

    # ── 3. Borrar entidades que NO son PC ─────────────────────────────────
    to_delete = []
    for entity in copy_msp:
        try:
            if entity.Layer.upper() not in pc_layers_upper:
                to_delete.append(entity)
        except Exception:
            pass
    for e in to_delete:
        try:
            e.Delete()
        except Exception:
            pass

    # ── 4. Mirror ─────────────────────────────────────────────────────────
    copy_msp = acad.ActiveDocument.ModelSpace  # refrescar tras borrados
    _mirror_entities_in_msp(copy_msp, pc_layers_upper)

    # ── 5. Guardar (Save, no SaveAs — ya está en el path correcto) ─────────
    try:
        acad.ActiveDocument.Save()
    except Exception as ex:
        raise RuntimeError(f"Paso 5 (Save PC): {ex}")

    # ── 6. Cerrar (el original sigue abierto, no hay que reabrirlo) ───────
    try:
        acad.ActiveDocument.Close(False)
    except Exception:
        pass


# ── Función principal ─────────────────────────────────────────────────────────

def process_dxf(has_tecoflex=False, tipo="PC", num_pc=1,
                save_folder=None, save_name=None, acad_doc=None) -> dict:
    """Procesa el documento de AutoCAD especificado usando Offset nativo."""
    pythoncom.CoInitialize()
    if acad_doc is not None:
        acad, doc = _get_live_doc(acad_doc)
    else:
        docs = get_all_open_documents()
        if not docs:
            raise RuntimeError("No se encontró AutoCAD abierto.")
        acad, doc = docs[0]["app"], docs[0]["doc"]

    # La ruta autoritativa es la que el usuario seleccionó en la UI.
    # Esto corrige el bug de "guardado como tmpXXX" cuando una corrida anterior
    # dejó el doc apuntando a un archivo temporal.
    if acad_doc is not None:
        original_path = str(acad_doc.get("path", doc.FullName))
    else:
        original_path = str(doc.FullName)

    msp = doc.ModelSpace

    # Buscar PERIMETRO
    perimetro_entities = [e for e in msp if _layer_match(e, "PERIMETRO")]
    if not perimetro_entities:
        raise ValueError(
            "No se encontró el layer 'PERIMETRO' en el archivo.\n"
            "Verifica que el layer se llame exactamente 'PERIMETRO'."
        )

    warnings      = []
    pc_output     = None
    pc_source_entities = perimetro_entities

    # ── TECOFLEX ──────────────────────────────────────────────────────────────
    if has_tecoflex:
        _ensure_layer(doc, "TECOFLEX", COLOR_RED)
        tecoflex_entities = []
        for e in perimetro_entities:
            try:
                result = _offset_entity(e, -3.0)
                _apply_layer_color(result, "TECOFLEX", COLOR_RED)
                tecoflex_entities.extend(result)
            except Exception as ex:
                warnings.append(f"TECOFLEX offset falló: {ex}")
        if tecoflex_entities:
            pc_source_entities = tecoflex_entities
        else:
            warnings.append("TECOFLEX (-3 mm) no produjo resultado.")

    # ── PC ────────────────────────────────────────────────────────────────────
    has_pc   = tipo in ("PC", "PC_AL")
    pc_groups = []

    if has_pc:
        offsets = [(-1.0, "PC_1", COLOR_CYAN)]
        if num_pc == 2:
            offsets.append((-2.0, "PC_2", COLOR_BLUE))

        for dist, layer_name, color in offsets:
            _ensure_layer(doc, layer_name, color)
            group_entities = []
            for e in pc_source_entities:
                try:
                    result = _offset_entity(e, dist)
                    _apply_layer_color(result, layer_name, color)
                    group_entities.extend(result)
                except Exception as ex:
                    warnings.append(f"{layer_name} offset {abs(dist)} mm falló: {ex}")
            if group_entities:
                pc_groups.append((layer_name, color, group_entities))
            else:
                warnings.append(f"{layer_name} ({abs(dist)} mm) no produjo resultado.")

    # ── Guardar archivo principal ─────────────────────────────────────────────
    # Usamos SaveAs con la ruta original para corregir cualquier desviación.
    try:
        doc.SaveAs(str(original_path))
        main_output = original_path
    except Exception as ex:
        warnings.append(f"No se pudo guardar el archivo principal: {ex}")
        main_output = str(doc.FullName)

    # ── Crear archivo PC (solo PC_AL) ─────────────────────────────────────────
    if has_pc and tipo == "PC_AL" and pc_groups and save_folder and save_name:
        fname     = save_name if save_name.lower().endswith(".dwg") else save_name + ".dwg"
        pc_output = str(Path(save_folder) / fname)
        try:
            pc_layer_names = [name for name, _, _ in pc_groups]
            _create_pc_file(acad, original_path, pc_layer_names, pc_output)
        except Exception as ex:
            warnings.append(f"No se pudo crear el archivo PC: {ex}")
            pc_output = None

    return {
        "main_output": main_output,
        "pc_output":   pc_output,
        "warnings":    warnings,
    }
