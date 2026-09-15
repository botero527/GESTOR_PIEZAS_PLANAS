"""
Tabla de compensación para piezas planas.

Regla general (siempre igual, sin importar el resto):
    PERIMETRO (o TECOFLEX si existe) -> offset 3mm hacia ADENTRO
    -> resultado -> offset hacia AFUERA por el valor de compensación de esta tabla

La compensación depende de: tipo de cristal, espesor, si lleva pintura,
si lleva caja, y si la pieza es "grande" (checkbox manual del usuario).

Nota: por ahora solo se preguntan 2 banderas al usuario (pintura, caja).
Prioridad si se marca más de una: pieza_grande > pintura > caja > sin caja.
La columna "bases y protectores" de la tabla original no se expone todavía
como pregunta (no hace parte del flujo actual) — queda documentada por si
se necesita más adelante.
"""
import random

SODALIME_WHITE = "SODALIME_WHITE"
ALUMINUM = "ALUMINUM"

# Grupos de espesor -> valores de compensación (mm) por escenario.
# sin_caja=None significa "N/A (matado de filos)": no aplica offset de compensación.
_TABLA = {
    SODALIME_WHITE: [
        {"espesores": (3, 4, 5, 6),   "pintura": 2.5, "con_caja": 1.0, "sin_caja": None, "bases": 1.0},
        {"espesores": (8,),           "pintura": 2.5, "con_caja": 1.0, "sin_caja": 1.0,  "bases": 1.0},
        {"espesores": (10, 12),       "pintura": 2.5, "con_caja": 1.5, "sin_caja": 1.5,  "bases": 1.0},
        {"espesores": (15, 19),       "pintura": 3.0, "con_caja": 3.0, "sin_caja": 3.0,  "bases": None},
    ],
    ALUMINUM: [
        {"espesores": (5, 6, 5.8),    "pintura": 1.5, "con_caja": 1.5, "sin_caja": 1.5,  "bases": None},
        {"espesores": (10,),          "pintura": 2.5, "con_caja": 2.5, "sin_caja": 2.5,  "bases": None},
    ],
}

# Pieza grande: un solo valor por grupo de espesor, sin importar pintura/caja.
_TABLA_PIEZA_GRANDE = {
    SODALIME_WHITE: [
        {"espesores": (3, 4, 5, 6, 8, 10, 12), "valor": 2.5},
        {"espesores": (15, 19),                "valor": 3.0},
    ],
    ALUMINUM: [
        {"espesores": (5, 6, 5.8, 10), "valor": 2.5},
    ],
}

OFFSET_BASE_MM = 3.0  # offset fijo hacia adentro, siempre, antes de la compensación

FRASES_ERROR_ESPESOR = [
    "¿Estás tonto? Ese espesor no existe en la tabla.",
    "¿Todo bien en casa? Porque ese espesor no cuadra con nada.",
    "¿Cómo así que solo venimos a calentar silla? Espesor inválido, parce.",
    "Ese espesor te lo inventaste vos solito. Mira la tabla otra vez.",
    "Nel bro, ese número no existe pa' este tipo de cristal.",
]


def espesores_validos(tipo_cristal: str) -> list:
    """Lista plana de espesores válidos para el tipo de cristal dado."""
    grupos = _TABLA.get(tipo_cristal, [])
    validos = []
    for g in grupos:
        validos.extend(g["espesores"])
    return validos


def _buscar_grupo(tabla: dict, tipo_cristal: str, espesor: float) -> dict:
    grupos = tabla.get(tipo_cristal)
    if grupos is None:
        raise ValueError(f"Tipo de cristal desconocido: '{tipo_cristal}'.")
    for g in grupos:
        if espesor in g["espesores"]:
            return g
    raise ValueError(random.choice(FRASES_ERROR_ESPESOR))


def obtener_compensacion(tipo_cristal: str, espesor: float,
                          tiene_pintura: bool, tiene_caja: bool,
                          pieza_grande: bool) -> dict:
    """
    Busca la compensación (mm) a offsetear hacia afuera, según la tabla.

    Devuelve {"valor": float, "aplica": bool}.
      - aplica=True  -> valor es el offset a aplicar.
      - aplica=False -> caso N/A (matado de filos): no hay nada que
        offsetear, solo queda el offset base de 3mm. No es un error del
        usuario, es un resultado válido de la tabla.

    Lanza ValueError (con mensaje chistoso) si el espesor no existe en
    la tabla para ese tipo de cristal.

    Nota: pieza_grande manda su propia tabla (un solo valor por espesor,
    sin importar pintura/caja), pero pintura/caja igual se preguntan al
    usuario para dejar el dato registrado.
    """
    if pieza_grande:
        grupo = _buscar_grupo(_TABLA_PIEZA_GRANDE, tipo_cristal, espesor)
        return {"valor": grupo["valor"], "aplica": True}

    grupo = _buscar_grupo(_TABLA, tipo_cristal, espesor)

    if tiene_pintura:
        valor = grupo["pintura"]
    elif tiene_caja:
        valor = grupo["con_caja"]
    else:
        valor = grupo["sin_caja"]

    if valor is None:
        return {"valor": 0.0, "aplica": False}
    return {"valor": valor, "aplica": True}
