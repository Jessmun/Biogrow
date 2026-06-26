import sqlite3
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__, static_folder='styles', static_url_path='/styles')
DATABASE = "experimentos.db"


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
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

    # Seed initial data if the database is empty
    cursor.execute("SELECT COUNT(*) FROM experimentos")
    if cursor.fetchone()[0] == 0:
        seed_data = [
            ("Lote A-1", "Semilla-B", 1, "T-1M", 12.5, 15.2, 1),
            ("Lote A-1", "Semilla-B", 2, "T-1M", 10.1, 11.4, 1),
            ("LOTE B-4", "Semilla-Rosa", 1, "45s", 3.1, 4.0, 0),
            ("LOTE B-4", "Semilla-Rosa", 2, "45s", 14.1, 11.2, 1),
            ("Lote C-10", "Semilla-B", 1, "Control", 9.0, 10.5, 1),
            ("Lote C-10", "Semilla-Rosa", 2, "Control", 0.0, 0.0, 0)
        ]
        for name, seed_type, sample_num, cond, root, stem, germ in seed_data:
            cursor.execute("""
                INSERT INTO experimentos (nombre_experimento, tipo_semilla)
                VALUES (?, ?)
            """, (name, seed_type))
            exp_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO mediciones_semillas (
                    experimento_id, num_muestra, condicion_tratamiento, longitud_raiz, longitud_tallo, germino
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (exp_id, sample_num, cond, root, stem, germ))
        conn.commit()
    conn.close()


@app.route("/")
def index():
    conn = get_db_connection()

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
        ORDER BY m.id DESC
    """

    registros = conn.execute(query).fetchall()
    conn.close()

    datos = [dict(row) for row in registros]

    return render_template("index.html", datos=datos)


@app.route("/insertar_muestra", methods=["POST"])
def insertar_muestra():
    nombre_lote = request.form["nombre_lote"]
    tipo_semilla = request.form["tipo_semilla"]
    num_muestra = int(request.form["num_muestra"])
    condicion = request.form["condicion_tratamiento"]
    raiz = float(request.form["longitud_raiz"])
    tallo = float(request.form["longitud_tallo"])
    germino = int(request.form["germino"])

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO experimentos (nombre_experimento, tipo_semilla)
        VALUES (?, ?)
    """, (nombre_lote, tipo_semilla))

    experimento_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO mediciones_semillas (
            experimento_id,
            num_muestra,
            condicion_tratamiento,
            longitud_raiz,
            longitud_tallo,
            germino
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (experimento_id, num_muestra, condicion, raiz, tallo, germino))

    conn.commit()
    conn.close()

    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)