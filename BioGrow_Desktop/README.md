# BioGrow Analytics — Aplicación de Escritorio

Monitor de Germinación y Biometría de Semillas  
Desarrollado en Python + CustomTkinter + SQLite3

---

## Requisitos

- Python 3.10 o superior
- pip

## Instalación

```bash
pip install -r requirements.txt
```

## Ejecución

```bash
python main.py
```

## Generar ejecutable (.exe)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name BioGrow_Analytics main.py
```
El ejecutable se generará en `dist/BioGrow_Analytics.exe`.

---

## Estructura del proyecto

```
BioGrow_Desktop/
├── main.py        → Punto de entrada
├── database.py    → Capa de acceso a SQLite
├── interfaz.py    → Interfaz gráfica (CustomTkinter + ttk)
├── models.py      → Modelos de datos (dataclasses)
├── utils.py       → Funciones auxiliares y validaciones
├── requirements.txt
├── README.md
└── assets/        → Recursos (iconos, imágenes)
```

## Base de datos

El archivo `experimentos.db` se busca automáticamente en este orden:
1. `BioGrow_Desktop/experimentos.db` (copia local)
2. Carpeta raíz del proyecto (versión web Flask)

Si la versión web tiene datos, se copian automáticamente al primer arranque.

## Tablas SQLite (sin modificación)

| Tabla | Descripción |
|---|---|
| `experimentos` | Lotes registrados |
| `mediciones_semillas` | 27 mediciones por lote |

## Regla de germinación

```
germino = 1   si   longitud_raiz > 0.01  AND  longitud_tallo > 0.01
germino = 0   en cualquier otro caso
```

## Navegación por teclado (tabla de captura)

| Tecla | Acción |
|---|---|
| `Doble clic` | Editar celda |
| `↑` `↓` | Mover entre filas |
| `←` `→` | Mover entre columnas (Raíz / Tallo) |
| `Enter` | Confirmar y mover a la siguiente fila |
| `Tab` | Mover a la siguiente celda |
| `Escape` | Cancelar edición |
