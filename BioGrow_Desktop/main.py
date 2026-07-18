"""
main.py — Punto de entrada de BioGrow Desktop
Ejecutar con: python main.py
Compilar con: pyinstaller --onefile --windowed --name BioGrow_Analytics main.py
"""
import sys
import os

# Asegurar que el directorio del módulo esté en el path de Python
# (necesario para imports relativos cuando se ejecuta como script)
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from database import DatabaseManager
from interfaz import BioGrowApp


def main() -> None:
    """
    Punto de entrada principal de BioGrow Analytics.
    1. Inicializa la base de datos (crea tablas si no existen).
    2. Arranca la ventana principal de CustomTkinter.
    """
    # Inicializar la base de datos
    db = DatabaseManager()
    db.init_db()

    # Crear y arrancar la aplicación
    app = BioGrowApp(db)
    app.mainloop()


if __name__ == "__main__":
    main()
