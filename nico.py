import win32com.client
def crear_triangulo():
    try:
        acad = win32com.client.GetActiveObject("AutoCAD.Application")
        document = acad.ActivateDocument
        modelo = document.ModelSapace

        tamaño = float (input("ingrese el tamaño no se haga el huevon"))
        x = 0
        y = 0

        guias = [
            (x,y),
            (x + tamaño, y),
            (x + tamaño, y + tamaño),
            (x,y + tamaño),
            (x, y)
            

        ]
