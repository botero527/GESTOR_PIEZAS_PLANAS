"""Debug: imprime info del layer PERIMETRO en AutoCAD abierto."""
import math
import pythoncom
import win32com.client
from shapely.geometry import Polygon

pythoncom.CoInitialize()
acad = win32com.client.GetActiveObject("AutoCAD.Application")
doc  = acad.ActiveDocument
msp  = doc.ModelSpace

print(f"\nArchivo: {doc.Name}")
print("=" * 60)

perimetro = []
for e in msp:
    try:
        if e.Layer.upper() == "PERIMETRO":
            perimetro.append(e)
    except:
        pass

print(f"Entidades en PERIMETRO: {len(perimetro)}")

for idx, e in enumerate(perimetro):
    print(f"\n--- Entidad {idx} ---")
    try:
        print(f"  Tipo:   {e.EntityName}")
        print(f"  Layer:  {e.Layer}")
        try:
            print(f"  Closed: {e.Closed}")
        except Exception as ex:
            print(f"  Closed ERROR: {ex}")

        try:
            coords = list(e.Coordinates)
            raw_pts = [(coords[i], coords[i+1]) for i in range(0, len(coords)-1, 2)]
            print(f"  Vértices: {len(raw_pts)}")
            print(f"  Primer punto: {raw_pts[0]}")
            print(f"  Último punto: {raw_pts[-1]}")
        except Exception as ex:
            print(f"  Coordinates ERROR: {ex}")

        try:
            bulges = list(e.GetBulges())
            non_zero = [b for b in bulges if abs(b) > 1e-10]
            print(f"  Bulges no-cero: {len(non_zero)} de {len(bulges)}")
        except Exception as ex:
            print(f"  GetBulges ERROR: {ex}")

        # Intentar crear polígono directo
        try:
            coords = list(e.Coordinates)
            pts = [(coords[i], coords[i+1]) for i in range(0, len(coords)-1, 2)]
            poly = Polygon(pts)
            print(f"  Polygon válido: {poly.is_valid}, vacío: {poly.is_empty}, área: {poly.area:.2f}")
        except Exception as ex:
            print(f"  Polygon ERROR: {ex}")

    except Exception as ex:
        print(f"  ERROR general: {ex}")

print("\n" + "=" * 60)
input("\nPresiona Enter para cerrar...")
