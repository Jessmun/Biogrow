"""
models.py — Modelos de datos de BioGrow Desktop
Clases de datos puras (sin dependencias de UI ni de base de datos).
Mapean exactamente las tablas SQLite existentes.
"""
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Modelos base (mapean tablas SQLite)
# ---------------------------------------------------------------------------

@dataclass
class Experimento:
    """
    Mapea la tabla `experimentos`.
    Representa un lote de semillas registrado en el sistema.
    """
    nombre_experimento: str
    tipo_semilla: str
    fecha_registro: Optional[str] = None   # DATETIME, puede ser None → SQLite usa CURRENT_TIMESTAMP
    id: Optional[int] = None               # None antes de insertarse en la BD


@dataclass
class Medicion:
    """
    Mapea la tabla `mediciones_semillas`.
    Representa una medición individual de una semilla dentro de un experimento.
    """
    experimento_id: int
    num_muestra: int
    condicion_tratamiento: str
    longitud_raiz: float
    longitud_tallo: float
    germino: int                            # 0 o 1 — calculado con la regla de negocio
    id: Optional[int] = None               # None antes de insertarse en la BD


# ---------------------------------------------------------------------------
# Vista de historial (resultado del JOIN)
# ---------------------------------------------------------------------------

@dataclass
class RegistroHistorial:
    """
    Representa una fila del historial consolidado.
    Resultado del JOIN entre `experimentos` y `mediciones_semillas`.
    No tiene representación directa en la BD; es una vista de consulta.
    """
    nombre_lote: str
    tipo_semilla: str
    num_muestra: int
    condicion_tratamiento: str
    longitud_raiz: float
    longitud_tallo: float
    germino: int

    @property
    def resultado_texto(self) -> str:
        """Devuelve la etiqueta de germinación en español."""
        return "Germinó" if self.germino == 1 else "No germinó"

    @property
    def raiz_fmt(self) -> str:
        """Longitud de raíz formateada con 2 decimales y unidad."""
        return f"{self.longitud_raiz:.2f}"

    @property
    def tallo_fmt(self) -> str:
        """Longitud de tallo formateada con 2 decimales y unidad."""
        return f"{self.longitud_tallo:.2f}"


# ---------------------------------------------------------------------------
# Contenedor de datos de formulario (para el guardado por lote)
# ---------------------------------------------------------------------------

@dataclass
class DatosLote:
    """
    Agrupa los datos del formulario de captura listos para persistir.
    Se construye en la UI y se pasa al DatabaseManager.
    """
    nombre_lote: str
    tipo_semilla: str
    fecha_registro: Optional[str]
    tiempo_tratamiento: str
    mediciones: list = field(default_factory=list)   # Lista de dicts con raiz/tallo por muestra
