"""
database.py — Capa de acceso a datos de BioGrow Desktop
Toda la comunicación con SQLite está centralizada aquí.
No contiene lógica de UI ni de negocio (excepto la regla de germinación
que también existe en el backend Flask original).
"""
import sqlite3
import os
import shutil
from typing import List, Optional, Tuple

from models import Experimento, Medicion, RegistroHistorial, DatosLote


# ---------------------------------------------------------------------------
# Ruta de la base de datos
# ---------------------------------------------------------------------------

def _resolver_ruta_db() -> str:
    """
    Determina la ruta final de la base de datos:
    1. Prioridad: BioGrow_Desktop/experimentos.db (carpeta local del módulo)
    2. Fallback: experimentos.db en la carpeta raíz del proyecto (donde vive la versión web)
    3. Si ninguna existe, crea una nueva en BioGrow_Desktop/
    Además, si la BD de la raíz existe y la de Desktop no, la copia automáticamente
    para no perder los datos ya registrados.
    """
    # Directorio donde vive este archivo (BioGrow_Desktop/)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    local_db = os.path.join(base_dir, "experimentos.db")

    # Directorio padre (raíz del proyecto, donde está la versión Flask)
    parent_db = os.path.join(os.path.dirname(base_dir), "experimentos.db")

    if not os.path.exists(local_db):
        if os.path.exists(parent_db):
            # Copiar la BD existente de la versión web para reutilizar los datos
            shutil.copy2(parent_db, local_db)
            print(f"[BioGrow] Base de datos copiada desde la versión web: {parent_db}")
        # Si no hay ninguna, init_db() la creará desde cero

    return local_db


DB_PATH = _resolver_ruta_db()


# ---------------------------------------------------------------------------
# DatabaseManager
# ---------------------------------------------------------------------------

class DatabaseManager:
    """
    Gestiona todas las operaciones de base de datos de BioGrow.
    Uso como context manager:
        with DatabaseManager() as db:
            db.guardar_lote(...)
    También puede usarse directamente:
        db = DatabaseManager()
        registros = db.obtener_historial()
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        """Abre una conexión con row_factory para acceso por nombre de columna."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        # Habilitar integridad referencial en SQLite
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def __enter__(self):
        self._conn = self._connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._conn.close()
        return False

    # -----------------------------------------------------------------------
    # Inicialización de la base de datos
    # -----------------------------------------------------------------------

    def init_db(self) -> None:
        """
        Crea las tablas si no existen.
        Siembra datos iniciales si la tabla de experimentos está vacía.
        Replica exactamente el comportamiento de init_db() en app.py Flask.
        """
        conn = self._connect()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS experimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_experimento TEXT NOT NULL,
                tipo_semilla TEXT NOT NULL,
                fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mediciones_semillas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experimento_id INTEGER NOT NULL,
                num_muestra INTEGER NOT NULL,
                condicion_tratamiento TEXT NOT NULL,
                longitud_raiz REAL NOT NULL,
                longitud_tallo REAL NOT NULL,
                germino INTEGER CHECK(germino IN (0, 1)),
                FOREIGN KEY (experimento_id) REFERENCES experimentos(id)
            )
        """)
        conn.commit()

        # Sembrar datos iniciales si la BD está vacía
        cursor.execute("SELECT COUNT(*) FROM experimentos")
        if cursor.fetchone()[0] == 0:
            self._sembrar_datos_iniciales(conn)

        conn.close()

    def _sembrar_datos_iniciales(self, conn: sqlite3.Connection) -> None:
        """
        Inserta datos de ejemplo idénticos a los del app.py Flask.
        Solo se ejecuta si la tabla está vacía.
        """
        seed_data = [
            ("Lote A-1",   "Semilla-B",    1, "T-1M",    12.5, 15.2, 1),
            ("Lote A-1",   "Semilla-B",    2, "T-1M",    10.1, 11.4, 1),
            ("LOTE B-4",   "Semilla-Rosa", 1, "45s",      3.1,  4.0, 0),
            ("LOTE B-4",   "Semilla-Rosa", 2, "45s",     14.1, 11.2, 1),
            ("Lote C-10",  "Semilla-B",    1, "Control",  9.0, 10.5, 1),
            ("Lote C-10",  "Semilla-Rosa", 2, "Control",  0.0,  0.0, 0),
        ]
        cursor = conn.cursor()
        for name, seed_type, sample_num, cond, root, stem, germ in seed_data:
            cursor.execute(
                "INSERT INTO experimentos (nombre_experimento, tipo_semilla) VALUES (?, ?)",
                (name, seed_type)
            )
            exp_id = cursor.lastrowid
            cursor.execute(
                """INSERT INTO mediciones_semillas
                   (experimento_id, num_muestra, condicion_tratamiento, longitud_raiz, longitud_tallo, germino)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (exp_id, sample_num, cond, root, stem, germ)
            )
        conn.commit()
        print("[BioGrow] Datos iniciales sembrados correctamente.")

    # -----------------------------------------------------------------------
    # Guardado por lote (transacción única)
    # -----------------------------------------------------------------------

    def guardar_lote(self, datos: DatosLote) -> Tuple[bool, str]:
        """
        Guarda un experimento completo con sus 27 mediciones en una única transacción.
        Replica exactamente el comportamiento de /guardar_lote en app.py Flask.

        Returns:
            (True, "mensaje de éxito") o (False, "mensaje de error")
        """
        if not datos.nombre_lote or not datos.tipo_semilla or not datos.tiempo_tratamiento:
            return False, "Faltan campos obligatorios: Lote, Variedad y Tiempo de Tratamiento."

        if not datos.mediciones:
            return False, "No se proporcionaron mediciones de semillas."

        conn = self._connect()
        cursor = conn.cursor()

        try:
            # Insertar experimento
            if datos.fecha_registro:
                fecha_limpia = datos.fecha_registro.replace("T", " ")
                cursor.execute(
                    "INSERT INTO experimentos (nombre_experimento, tipo_semilla, fecha_registro) VALUES (?, ?, ?)",
                    (datos.nombre_lote, datos.tipo_semilla, fecha_limpia)
                )
            else:
                cursor.execute(
                    "INSERT INTO experimentos (nombre_experimento, tipo_semilla) VALUES (?, ?)",
                    (datos.nombre_lote, datos.tipo_semilla)
                )

            experimento_id = cursor.lastrowid

            # Insertar cada medición
            for med in datos.mediciones:
                num_muestra = int(med.get("num_muestra", 0))
                raiz = float(med.get("longitud_raiz", 0.0))
                tallo = float(med.get("longitud_tallo", 0.0))
                # Regla de germinación — idéntica al backend Flask
                germino = 1 if (raiz > 0.01 and tallo > 0.01) else 0

                cursor.execute(
                    """INSERT INTO mediciones_semillas
                       (experimento_id, num_muestra, condicion_tratamiento, longitud_raiz, longitud_tallo, germino)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (experimento_id, num_muestra, datos.tiempo_tratamiento, raiz, tallo, germino)
                )

            conn.commit()
            return True, f"Lote '{datos.nombre_lote}' guardado correctamente con {len(datos.mediciones)} mediciones."

        except Exception as e:
            conn.rollback()
            return False, f"Error al guardar el lote: {str(e)}"

        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Consulta de historial con filtros
    # -----------------------------------------------------------------------

    def obtener_historial(
        self,
        texto_busqueda: str = "",
        filtro_semilla: str = "",
        filtro_germino: str = ""
    ) -> List[RegistroHistorial]:
        """
        Obtiene el historial consolidado con JOIN, aplicando los filtros opcionales.
        Replica la lógica del JavaScript de filtrado del index.html.

        Args:
            texto_busqueda: Filtra por lote, tratamiento o tipo de semilla (LIKE)
            filtro_semilla: "Semilla-B", "Semilla-Rosa" o "" (todas)
            filtro_germino: "1" (germinó), "0" (no germinó) o "" (todos)

        Returns:
            Lista de RegistroHistorial ordenada por id DESC (más reciente primero)
        """
        query = """
            SELECT
                e.nombre_experimento AS nombre_lote,
                e.tipo_semilla,
                m.num_muestra,
                m.condicion_tratamiento,
                m.longitud_raiz,
                m.longitud_tallo,
                m.germino
            FROM mediciones_semillas m
            JOIN experimentos e ON m.experimento_id = e.id
            WHERE 1=1
        """
        params = []

        # Filtro de búsqueda general (lote, tratamiento o semilla)
        if texto_busqueda:
            like = f"%{texto_busqueda}%"
            query += """
                AND (
                    e.nombre_experimento LIKE ?
                    OR m.condicion_tratamiento LIKE ?
                    OR e.tipo_semilla LIKE ?
                )
            """
            params.extend([like, like, like])

        # Filtro por tipo de semilla
        if filtro_semilla:
            query += " AND e.tipo_semilla = ?"
            params.append(filtro_semilla)

        # Filtro por estado de germinación
        if filtro_germino in ("0", "1"):
            query += " AND m.germino = ?"
            params.append(int(filtro_germino))

        query += " ORDER BY m.id DESC"

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [
                RegistroHistorial(
                    nombre_lote=row["nombre_lote"],
                    tipo_semilla=row["tipo_semilla"],
                    num_muestra=row["num_muestra"],
                    condicion_tratamiento=row["condicion_tratamiento"],
                    longitud_raiz=row["longitud_raiz"],
                    longitud_tallo=row["longitud_tallo"],
                    germino=row["germino"],
                )
                for row in rows
            ]
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Helpers de consulta específicos
    # -----------------------------------------------------------------------

    def buscar_por_lote(self, texto: str) -> List[RegistroHistorial]:
        """Filtra el historial por identificador de lote."""
        return self.obtener_historial(texto_busqueda=texto)

    def filtrar_por_semilla(self, tipo: str) -> List[RegistroHistorial]:
        """Filtra el historial por tipo de semilla."""
        return self.obtener_historial(filtro_semilla=tipo)

    def filtrar_por_estado(self, germino: str) -> List[RegistroHistorial]:
        """Filtra el historial por estado de germinación ('0' o '1')."""
        return self.obtener_historial(filtro_germino=germino)

    def contar_registros(self) -> dict:
        """
        Devuelve estadísticas básicas del historial para el header.
        Útil para mostrar KPIs en la UI.
        """
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM mediciones_semillas").fetchone()[0]
            germinadas = conn.execute(
                "SELECT COUNT(*) FROM mediciones_semillas WHERE germino = 1"
            ).fetchone()[0]
            lotes = conn.execute(
                "SELECT COUNT(DISTINCT id) FROM experimentos"
            ).fetchone()[0]
            return {
                "total": total,
                "germinadas": germinadas,
                "no_germinadas": total - germinadas,
                "lotes": lotes,
            }
        finally:
            conn.close()
