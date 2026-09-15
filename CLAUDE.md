# PIEZAS_PLANAS

## Quién es el usuario

Andrés Botero (spina@agpglass.com), AGP Glass. Trátalo bro a bro, directo, sin rodeos ni relleno corporativo.

## Qué es este proyecto

App de escritorio Python + CustomTkinter que automatiza AutoCAD vía COM (`pywin32`) para trazar offsets de corte/perforación sobre DWG de "piezas planas" (vidrio/policarbonato con marcos). Usa `ezdxf`/`shapely` para geometría, se empaqueta como .exe con PyInstaller.

Flujo (wizard):
1. Detecta el DWG abierto en AutoCAD (soporta varias instancias).
2. Si tiene layer TECOFLEX → offset de 3mm hacia adentro del layer PERIMETRO, nuevo layer TECOFLEX (rojo).
3. Pregunta tipo de accesorio: PC, AL o ambos.
   - Si PC → offsets de 1mm (layer PC_1, cian) y 2mm (layer PC_2, azul).
4. Si es PC_AL, puede guardar un DWG separado solo con capas PC, con espejo horizontal.
5. Guarda el archivo principal (SaveAs) y opcionalmente el archivo PC separado.

## Archivos clave

- `main.py` — GUI/wizard (CustomTkinter)
- `dxf_processor.py` — lógica real: conexión COM con AutoCAD, cálculo de offsets, manejo de layers
- `debug_acad.py` — script de diagnóstico de conexión con AutoCAD
- `build_exe.bat` — build a .exe con PyInstaller
- `instalar_y_ejecutar.bat` — instala dependencias y ejecuta
- `requirements.txt` — customtkinter, ezdxf, shapely

## Pendientes conocidos

- `requirements.txt` falta `pywin32` aunque se usa en el código para COM. Agregarlo.
- `README.md` está vacío/corrupto, sin contenido útil. Reescribir si se va a compartir el repo.
- `prueba.py` es un archivo residual sin función (broma personal) — se puede borrar sin miedo.
- No hay tests automatizados; validación es manual abriendo AutoCAD.

## Estilo de trabajo

- Comentarios en español.
- Scripts simples y directos, sin sobre-ingeniería.
- No hay credenciales ni conexiones de red en este proyecto — todo es automatización COM local con AutoCAD.
