"""
utils.py — Funciones auxiliares de BioGrow Desktop
Validaciones, formateo de datos y utilidades compartidas.
Sin dependencias de UI ni de base de datos.
"""
from datetime import datetime
from typing import Tuple


# ---------------------------------------------------------------------------
# Regla de negocio: germinación
# ---------------------------------------------------------------------------

def calcular_germino(raiz: float, tallo: float) -> int:
    """
    Determina el estado de germinación según la regla de negocio del sistema.
    Idéntica a la regla del backend Flask y del JavaScript frontend.

    Regla: germino = 1 si raíz > 0.01 AND tallo > 0.01, de lo contrario = 0

    Args:
        raiz:  Longitud de raíz en mm
        tallo: Longitud de tallo en mm

    Returns:
        1 si germinó, 0 si no germinó
    """
    return 1 if (raiz > 0.01 and tallo > 0.01) else 0


def estado_germinacion_texto(germino: int) -> str:
    """
    Convierte el valor entero de germinación a texto en español.

    Args:
        germino: 0 o 1

    Returns:
        "Germinó" o "No germinó"
    """
    return "Germinó" if germino == 1 else "No germinó"


# ---------------------------------------------------------------------------
# Validaciones de formulario
# ---------------------------------------------------------------------------

def validar_campos_lote(
    nombre_lote: str,
    tipo_semilla: str,
    fecha_registro: str,
    tiempo_tratamiento: str,
) -> Tuple[bool, str]:
    """
    Valida los campos del formulario principal antes de guardar.
    Replica las validaciones del JavaScript original.

    Args:
        nombre_lote:        Identificador del lote
        tipo_semilla:       Variedad de semilla seleccionada
        fecha_registro:     Fecha de registro (cadena)
        tiempo_tratamiento: Condición de tratamiento

    Returns:
        (True, "") si todo es válido
        (False, "mensaje de error") si hay un campo inválido
    """
    if not nombre_lote or not nombre_lote.strip():
        return False, "El campo 'Identificador del Lote' es obligatorio."

    if not tipo_semilla or not tipo_semilla.strip():
        return False, "Debe seleccionar una 'Variedad de Semilla'."

    if not fecha_registro or not fecha_registro.strip():
        return False, "El campo 'Fecha de Registro' es obligatorio."

    if not tiempo_tratamiento or not tiempo_tratamiento.strip():
        return False, "El campo 'Tiempo de Tratamiento' es obligatorio."

    return True, ""


def validar_valor_numerico(valor_str: str, nombre_campo: str = "valor") -> Tuple[bool, float, str]:
    """
    Intenta convertir una cadena a float para los campos de medición.

    Args:
        valor_str:   Cadena a convertir
        nombre_campo: Nombre del campo para el mensaje de error

    Returns:
        (True, valor_float, "") si la conversión es exitosa
        (False, 0.0, "mensaje de error") si falla
    """
    if valor_str is None or valor_str == "":
        return True, 0.0, ""   # Vacío se trata como 0.00
    try:
        valor = float(valor_str.replace(",", "."))
        if valor < 0:
            return False, 0.0, f"El {nombre_campo} no puede ser negativo."
        return True, valor, ""
    except ValueError:
        return False, 0.0, f"'{valor_str}' no es un número válido para {nombre_campo}."


# ---------------------------------------------------------------------------
# Formateo de datos
# ---------------------------------------------------------------------------

def formatear_fecha_actual() -> str:
    """
    Devuelve la fecha y hora actual formateada para el campo de registro.
    Formato: YYYY-MM-DD HH:MM (compatible con SQLite DATETIME)

    Returns:
        Cadena de fecha/hora actual
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def formatear_numero(valor: float, decimales: int = 2) -> str:
    """
    Formatea un número flotante con el número especificado de decimales.

    Args:
        valor:     Valor a formatear
        decimales: Número de decimales (por defecto 2)

    Returns:
        Cadena con el número formateado (e.g., "12.50")
    """
    return f"{valor:.{decimales}f}"


def parsear_float(texto: str, default: float = 0.0) -> float:
    """
    Convierte una cadena a float de forma segura.
    Maneja tanto punto (.) como coma (,) como separador decimal.

    Args:
        texto:   Cadena a convertir
        default: Valor de retorno si la conversión falla

    Returns:
        Valor flotante parseado o default si no es posible parsear
    """
    if not texto or not texto.strip():
        return default
    try:
        return float(texto.strip().replace(",", "."))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Utilidades de interfaz
# ---------------------------------------------------------------------------

def truncar_texto(texto: str, max_chars: int = 25) -> str:
    """
    Trunca un texto largo y añade puntos suspensivos si excede el límite.
    Útil para mostrar en columnas de Treeview con ancho limitado.

    Args:
        texto:     Texto a truncar
        max_chars: Número máximo de caracteres permitidos

    Returns:
        Texto truncado con "..." si excede max_chars, o texto original
    """
    if len(texto) <= max_chars:
        return texto
    return texto[:max_chars - 3] + "..."


def centrar_ventana(ventana, ancho: int, alto: int) -> None:
    """
    Centra una ventana de Tkinter/CTk en la pantalla.

    Args:
        ventana: Instancia de Tk/CTk
        ancho:   Ancho de la ventana en píxeles
        alto:    Alto de la ventana en píxeles
    """
    ventana.update_idletasks()
    screen_w = ventana.winfo_screenwidth()
    screen_h = ventana.winfo_screenheight()
    x = (screen_w - ancho) // 2
    y = (screen_h - alto) // 2
    ventana.geometry(f"{ancho}x{alto}+{x}+{y}")
