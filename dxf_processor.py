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
    Escanea el ROT completo sin filtrar por nombre — así encuentra
    múltiples instancias de AutoCAD y todas sus pestañas.
    """
    pythoncom.CoInitialize()
    results   = []
    seen_paths = set()
    seen_apps  = set()   # identificador estable por instancia

    def _harvest_app(app):
        """Extrae todos los documentos de una instancia de AutoCAD."""
        try:
            # Identificador estable: nombre del exe + hwnd de la ventana
            app_key = f"{app.Name}_{app.Hwnd}"
        except Exception:
            app_key = str(id(app))
        if app_key in seen_apps:
            return
        seen_apps.add(app_key)
        try:
            for i in range(app.Documents.Count):
                doc = app.Documents.Item(i)
                path = doc.FullName or doc.Name
                if path not in seen_paths:
                    seen_paths.add(path)
                    results.append({"name": doc.Name, "path": path,
                                    "app": app, "doc": doc})
        except Exception:
            pass

    # ── Estrategia 1: ROT completo, probar cada objeto ────────────────────
    try:
        rot = pythoncom.GetRunningObjectTable()
        for moniker in rot.EnumRunning():
            try:
                raw  = rot.GetObject(moniker)
                disp = raw.QueryInterface(pythoncom.IID_IDispatch)
                app  = win32com.client.Dispatch(disp)
                # Si tiene Documents.Count es AutoCAD
                _ = app.Documents.Count
                _harvest_app(app)
            except Exception:
                pass
    except Exception:
        pass

    # ── Estrategia 2: GetActiveObject como fallback ───────────────────────
    try:
        app = win32com.client.GetActiveObject("AutoCAD.Application")
        _harvest_app(app)
    except Exception:
        pass

    return results


def get_active_file_info() -> dict:
    """Devuelve el primer documento encontrado (para compatibilidad)."""
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
    """Offset inward: detecta dirección correcta comparando tamaños."""
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


# ── Geometría de entidades ────────────────────────────────────────────────────

def _get_entity_coords(entity):
    """Lee coordenadas y bulges de una entidad LWPOLYLINE."""
    coords = list(entity.Coordinates)
    pts = [(coords[i], coords[i+1]) for i in range(0, len(coords)-1, 2)]
    bulges = []
    for i in range(len(pts)):
        try:
            bulges.append(float(entity.Bulge(i)))
        except Exception:
            bulges.append(0.0)
    try:
        closed = bool(entity.Closed)
    except Exception:
        closed = True
    return pts, bulges, closed


def _get_bbox_center(entities):
    """Calcula el centro del bounding box de un conjunto de entidades."""
    min_x = min_y = float('inf')
    max_x = max_y = float('-inf')
    for e in entities:
        try:
            mn, mx = e.GetBoundingBox()
            min_x = min(min_x, mn[0]); max_x = max(max_x, mx[0])
            min_y = min(min_y, mn[1]); max_y = max(max_y, mx[1])
        except Exception:
            pass
    return (min_x + max_x) / 2, (min_y + max_y) / 2


def _mirror_pts(pts, cx):
    """Refleja puntos horizontalmente sobre x = cx."""
    return [(2*cx - x, y) for x, y in pts]


def _write_lwpolyline(msp, pts, bulges, closed, layer, color):
    """Escribe una LWPOLYLINE en el modelspace dado."""
    flat = []
    for x, y in pts:
        flat.extend([float(x), float(y)])
    coords_var = win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8, flat
    )
    pline = msp.AddLightWeightPolyline(coords_var)
    pline.Closed = closed
    pline.Layer = layer
    pline.color = color
    # Aplicar bulges (mirror invierte el signo)
    for i, b in enumerate(bulges):
        try:
            pline.SetBulge(i, b)
        except Exception:
            pass
    return pline


# ── Crear archivo PC separado (mirrored) ──────────────────────────────────────

def _create_pc_file(acad, pc_groups, save_path):
    """
    pc_groups: lista de (layer_name, color, [entities])
    Crea un DWG nuevo con esas entidades reflejadas horizontalmente.
    """
    new_doc = acad.Documents.Add()
    new_msp = new_doc.ModelSpace

    # Recoger todas las entidades para calcular centro
    all_entities = [e for _, _, ents in pc_groups for e in ents]
    cx, _ = _get_bbox_center(all_entities)

    for layer_name, color, entities in pc_groups:
        _ensure_layer(new_doc, layer_name, color)
        for src in entities:
            try:
                etype = src.EntityName.upper()
                if "POLYLINE" in etype:
                    pts, bulges, closed = _get_entity_coords(src)
                    # Mirror X + invertir signo de bulges
                    m_pts = _mirror_pts(pts, cx)
                    m_bulges = [-b for b in bulges]
                    _write_lwpolyline(new_msp, m_pts, m_bulges, closed, layer_name, color)
            except Exception:
                pass

    new_doc.SaveAs(str(save_path))
    new_doc.Close(False)


# ── Función principal ─────────────────────────────────────────────────────────

def _get_live_doc(acad_doc: dict):
    """
    Re-obtiene el documento vivo desde AutoCAD usando la ruta guardada.
    Evita usar objetos COM cacheados que pueden expirar.
    """
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


def process_dxf(_dxf_path=None, has_tecoflex=False, tipo="PC", num_pc=1,
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

    msp = doc.ModelSpace

    # Buscar PERIMETRO
    perimetro_entities = [
        e for e in msp
        if _layer_match(e, "PERIMETRO")
    ]
    if not perimetro_entities:
        raise ValueError(
            "No se encontró el layer 'PERIMETRO' en el archivo.\n"
            "Verifica que el layer se llame exactamente 'PERIMETRO'."
        )

    warnings = []
    pc_output = None
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
    has_pc = tipo in ("PC", "PC_AL")
    # pc_groups: [(layer_name, color, [entities]), ...]
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

        # PC_AL → archivo separado con layers PC_1/PC_2 mirrored
        if tipo == "PC_AL" and pc_groups and save_folder and save_name:
            fname = save_name if save_name.lower().endswith(".dwg") else save_name + ".dwg"
            pc_output = str(Path(save_folder) / fname)
            try:
                _create_pc_file(acad, pc_groups, pc_output)
            except Exception as ex:
                warnings.append(f"No se pudo crear el archivo PC: {ex}")
                pc_output = None

    # Guardar archivo principal en su lugar
    try:
        doc.Save()
    except Exception:
        try:
            doc.SaveAs(doc.FullName)
        except Exception as ex:
            warnings.append(f"No se pudo guardar el archivo principal: {ex}")

    return {
        "main_output": doc.FullName,
        "pc_output": pc_output,
        "warnings": warnings,
    }


def _layer_match(entity, layer_name):
    try:
        return entity.Layer.upper() == layer_name.upper()
    except Exception:
        return False
