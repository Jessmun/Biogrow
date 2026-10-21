
from __future__ import annotations

import colorsys
import hashlib
import io
import json
import math
import random
import re
import unicodedata
import zipfile
from datetime import datetime
from itertools import combinations
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

try:
    from streamlit import config as _st_config
    _st_config.set_option("runner.magicEnabled", False)
except Exception:
    pass



PATRON_TITULO = re.compile(r"^\s*T\s*[-–]\s*(0*)(\d+)\s*([MNmn]?)\s*$")

PATRON_FECHA_HOJA = re.compile(
    r"(\d{1,2})\s*(?:de\s+)?("
    r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
    r"septiembre|octubre|noviembre|diciembre)",
    re.IGNORECASE,
)

MES_A_NUMERO = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

TRATAMIENTOS_POR_FECHA = {
    (28, 2): {"ambos": 120},           
    (7, 3): {"par": 60, "impar": 30}, 
    (14, 3): {"par": 60, "impar": 30},  
    (21, 3): {"par": 75, "impar": 45},  
    (25, 4): {"par": 75, "impar": 45},  
    (2, 5): {"par": 45, "impar": 30},   
    (16, 5): {"par": 45, "impar": 30},  # no está en la tabla del protocolo: confirmar
}

NS_MAIN = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = {
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}



def _col_a_indice(letras: str) -> int:
    indice = 0
    for caracter in letras:
        indice = indice * 26 + (ord(caracter.upper()) - ord("A") + 1)
    return indice


def _partir_celda(referencia: str):
    coincidencia = re.match(r"([A-Z]+)(\d+)", referencia)
    letras, numero = coincidencia.groups()
    return letras, int(numero)


def _leer_cadenas_compartidas(zf: zipfile.ZipFile):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []

    raiz = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    cadenas = []
    for si in raiz.findall("m:si", NS_MAIN):
        texto = "".join(t.text or "" for t in si.iter("{%s}t" % NS_MAIN["m"]))
        cadenas.append(texto)
    return cadenas


def _mapa_hojas(zf: zipfile.ZipFile):
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))

    rid_a_destino = {}
    for rel in rels.findall("pr:Relationship", NS_REL):
        rid_a_destino[rel.get("Id")] = rel.get("Target")

    hojas = []
    for hoja in workbook.find("m:sheets", NS_MAIN).findall("m:sheet", NS_MAIN):
        nombre = hoja.get("name")
        rid = hoja.get("{%s}id" % NS_REL["r"])
        destino = rid_a_destino.get(rid, "")
        if not destino.startswith("/"):
            destino = "xl/" + destino
        else:
            destino = destino.lstrip("/")
        hojas.append((nombre, destino))
    return hojas


def _leer_celdas(zf: zipfile.ZipFile, ruta_hoja: str, cadenas):
    raiz = ET.fromstring(zf.read(ruta_hoja))
    datos = raiz.find("m:sheetData", NS_MAIN)
    celdas = {}

    if datos is None:
        return celdas

    for fila in datos.findall("m:row", NS_MAIN):
        for celda in fila.findall("m:c", NS_MAIN):
            referencia = celda.get("r")
            if not referencia:
                continue

            letras, numero_fila = _partir_celda(referencia)
            col = _col_a_indice(letras)
            tipo = celda.get("t")
            v = celda.find("m:v", NS_MAIN)

            if v is None or v.text is None:
                is_ = celda.find("m:is", NS_MAIN)
                if is_ is not None:
                    texto = "".join(
                        t.text or "" for t in is_.iter("{%s}t" % NS_MAIN["m"])
                    )
                    celdas[(numero_fila, col)] = texto
                continue

            texto = v.text

            if tipo == "s":  
                celdas[(numero_fila, col)] = cadenas[int(texto)]
            elif tipo == "b":  
                celdas[(numero_fila, col)] = int(texto)
            else:
                try:
                    numero = float(texto)
                    celdas[(numero_fila, col)] = int(numero) if numero.is_integer() else numero
                except ValueError:
                    celdas[(numero_fila, col)] = texto

    return celdas

def _fecha_de_hoja(nombre_hoja: str):
    coincidencia = PATRON_FECHA_HOJA.search(nombre_hoja.lower())
    if not coincidencia:
        return None, None, None

    dia = int(coincidencia.group(1))
    mes_texto = coincidencia.group(2).lower()
    mes = MES_A_NUMERO[mes_texto]
    etiqueta = f"{dia:02d} {mes_texto}"
    return dia, mes, etiqueta


def _color_de_hoja(nombre_hoja: str) -> str:
    texto = nombre_hoja.lower()
    if "cacahuazintle" in texto:
        return "C"
    if "criollo" in texto:
        return "CR"
    if "rosa" in texto or re.search(r"datos-?r\b", texto) or "-r " in texto or "(r" in texto:
        return "R"
    if "blanc" in texto or re.search(r"datos-?b\b", texto):
        return "B"
    marca = re.search(r"datos-?([a-z]+)", texto)
    if marca:
        codigo = marca.group(1)
        if codigo in ("c", "cacahuazintle"):
            return "C"
        if codigo in ("cr", "criollo"):
            return "CR"
        if codigo == "r":
            return "R"
        if codigo == "b":
            return "B"
    return "?"


PATRON_LEYENDA = re.compile(r"^\s*(\d+)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*(s|seg|min)\b", re.IGNORECASE)
PATRON_TIEMPO = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(s|seg|segundos|min|minutos)\s*$", re.IGNORECASE)


def _a_segundos(numero_txt, unidad):
    valor = float(str(numero_txt).replace(",", "."))
    return valor * 60 if unidad.lower().startswith("min") else valor


def _leyenda_paridad(celdas):
    """Lee la leyenda que algunas hojas traen en las primeras filas, p. ej.
    '1 - 45s' / '2 - 75s'  ->  {impar: 45, par: 75}.
    Tiene prioridad sobre la tabla fija TRATAMIENTOS_POR_FECHA, porque la tabla
    está indexada solo por fecha y hay fechas con dos variedades que recibieron
    tiempos distintos (p. ej. 2 de mayo: Blanca 30/45 s, Rosa 45/75 s)."""
    regla = {}
    for (fila, _col), valor in celdas.items():
        if fila > 2 or not isinstance(valor, str):
            continue
        m = PATRON_LEYENDA.match(valor.strip())
        if m:
            clave = "par" if int(m.group(1)) % 2 == 0 else "impar"
            regla[clave] = _a_segundos(m.group(2), m.group(3))
    return regla if {"par", "impar"} <= set(regla) else None


def _anotacion_bloque(celdas, fila_titulo, col_bloque):
    """Texto escrito justo encima de un bloque (fila anterior, en la columna del
    título o la siguiente). En los datos aparece como '2min', 'Sin aire' o
    'Plasma en el petri'. Devuelve (segundos_override, condición)."""
    for col in (col_bloque, col_bloque + 1):
        valor = celdas.get((fila_titulo - 1, col))
        if not isinstance(valor, str) or not valor.strip():
            continue
        texto = valor.strip()
        if PATRON_TITULO.match(texto) or PATRON_LEYENDA.match(texto):
            continue
        m = PATRON_TIEMPO.match(texto.replace(" ", ""))
        if m:
            return _a_segundos(m.group(1), m.group(2)), None
        return None, texto
    return None, None


def _segundos_tratamiento(dia, mes, tirada, regla_hoja=None):
    regla = regla_hoja or TRATAMIENTOS_POR_FECHA.get((dia, mes))

    if regla is None:
        return None  # sin información: mejor "Sin definir" que inventar un tiempo

    if "ambos" in regla:
        return regla["ambos"]
    return regla["par"] if tirada % 2 == 0 else regla["impar"]


def _datos_clase(letra: str):
    letra = (letra or "").upper()
    if letra == "M":
        return "M", "Embrión"
    if letra == "N":
        return "N", "Endospermo"
    return "S", "Patrón"

_OFFSETS = {"No": 0, "Raíz": 1, "Tallo": 2, "Germinó": 3}


def _extraer_bloques_de_hoja(nombre_hoja, celdas, advertencias):
    dia, mes, etiqueta_fecha = _fecha_de_hoja(nombre_hoja)
    color = _color_de_hoja(nombre_hoja)
    regla_hoja = _leyenda_paridad(celdas)
    regla_tabla = TRATAMIENTOS_POR_FECHA.get((dia, mes))
    if regla_hoja and regla_tabla and regla_hoja != regla_tabla:
        advertencias.append(
            f"{nombre_hoja}: la leyenda de la hoja indica impar={regla_hoja['impar']:g} s / "
            f"par={regla_hoja['par']:g} s y difiere de la tabla fija por fecha; "
            "se usó la leyenda de la hoja."
        )
    titulos = []
    for (fila, col), valor in celdas.items():
        if isinstance(valor, str):
            coincidencia = PATRON_TITULO.match(valor.strip())
            if coincidencia:
                cero = coincidencia.group(1)
                tirada = int(coincidencia.group(2))
                letra = coincidencia.group(3)
                titulos.append((fila, col, tirada, letra, cero, valor.strip()))

    titulos.sort()
    # Las corridas nuevas ya no separan embrión (M) y endospermo (N). Si la hoja
    # no tiene ningún bloque M/N, los bloques sin cero inicial (T-1, T-2…) son
    # semillas tratadas por el endospermo y solo T-01…T-05 son el control.
    hoja_con_mn = any(t[3] for t in titulos)
    if titulos and not hoja_con_mn and any(not t[4] for t in titulos):
        advertencias.append(
            f"{nombre_hoja}: la hoja no tiene bloques M/N. Los bloques T-1, T-2… se tomaron "
            "como semillas tratadas (endospermo) y T-01…T-05 como control."
        )

    registros = []
    contador_replica = {}

    for fila_titulo, col_bloque, tirada, letra, cero, titulo_texto in titulos:
        if letra:
            codigo_clase, nombre_clase = _datos_clase(letra)
        elif cero or hoja_con_mn:
            codigo_clase, nombre_clase = "S", "Patrón"
        else:
            codigo_clase, nombre_clase = "N", "Endospermo"
        seg_anot, condicion = _anotacion_bloque(celdas, fila_titulo, col_bloque)

        if codigo_clase == "S":
            segundos = 0
            fuente_tiempo = "Control: sin tratamiento (0 s)"
        elif seg_anot is not None:
            segundos = seg_anot
            condicion = condicion or f"Tiempo anotado ({seg_anot:g} s)"
            fuente_tiempo = f"Nota escrita sobre el bloque ({seg_anot:g} s)"
        else:
            segundos = _segundos_tratamiento(dia, mes, tirada, regla_hoja)
            paridad = "par" if tirada % 2 == 0 else "impar"
            if segundos is None:
                fuente_tiempo = "Sin definir: la fecha no está en las especificaciones"
            elif regla_hoja:
                fuente_tiempo = f"Leyenda de la hoja (tirada {paridad})"
            elif "ambos" in (TRATAMIENTOS_POR_FECHA.get((dia, mes)) or {}):
                fuente_tiempo = "Especificaciones por fecha (todas las tiradas)"
            elif (dia, mes) == (16, 5):
                fuente_tiempo = (f"Tabla del código original, tirada {paridad} "
                                 "(16 de mayo no está en las especificaciones)")
            else:
                fuente_tiempo = f"Especificaciones por fecha (tirada {paridad})"
        condicion = condicion or "Estándar"

        clave_replica = (tirada, codigo_clase)
        contador_replica[clave_replica] = contador_replica.get(clave_replica, 0) + 1
        numero_replica = contador_replica[clave_replica]

       
        fila_datos = fila_titulo + 2
        n_leidas = 0

        while True:
            celda_no = celdas.get((fila_datos, col_bloque + _OFFSETS["No"]))
            if not isinstance(celda_no, (int, float)):
                break

            raiz = celdas.get((fila_datos, col_bloque + _OFFSETS["Raíz"]))
            tallo = celdas.get((fila_datos, col_bloque + _OFFSETS["Tallo"]))
            germino = celdas.get((fila_datos, col_bloque + _OFFSETS["Germinó"]))

            registros.append(
                {
                    "Hoja": nombre_hoja,
                    "Fecha etiqueta": etiqueta_fecha or nombre_hoja,
                    "Día": dia,
                    "Mes": mes,
                    "Color": color,
                    "Tirada": tirada,
                    "Paridad": "Par" if tirada % 2 == 0 else "Impar",
                    "Clase": codigo_clase,
                    "Clase nombre": nombre_clase,
                    "Bloque": titulo_texto,
                    "Réplica": numero_replica,
                    "No": int(celda_no),
                    "Raíz": raiz if isinstance(raiz, (int, float)) else None,
                    "Tallo": tallo if isinstance(tallo, (int, float)) else None,
                    "Germinó": int(germino) if isinstance(germino, (int, float)) else None,
                    "Tratamiento (s)": segundos,
                    "Condición": condicion,
                    "Fuente del tiempo": fuente_tiempo,
                }
            )
            n_leidas += 1
            fila_datos += 1

        if n_leidas == 0:
            advertencias.append(
                f"{nombre_hoja}: el bloque '{titulo_texto}' no tenía filas de datos legibles."
            )

    if etiqueta_fecha is None:
        advertencias.append(
            f"{nombre_hoja}: no se reconoció una fecha en el nombre de la hoja; "
            "el tratamiento en segundos quedó sin definir para esta pestaña."
        )

    return registros

# ---------------------------------------------------------------------------
# Tipos de experimento. Cada archivo se clasifica según su contenido y el
# dashboard adapta variables, agrupación por defecto y textos a ese tipo.
# ---------------------------------------------------------------------------

TIPO_TIEMPO = "Tiempo de tratamiento por fecha (Blanco / Rosa)"
TIPO_TIEMPO30 = "Tiempo 30 s por variedad (Cacahuazintle / Criollo)"
TIPO_TEMPERATURA = "Temperatura del tratamiento (Criollo)"

CONFIG_TIPO = {
    TIPO_TIEMPO: {
        "dims": ["Tratamiento", "Clase nombre", "Variedad", "Condición", "Tirada", "Bloque", "Hoja", "Archivo"],
        "default": ["Tratamiento"],
        "descripcion": (
            "Hojas 'Datos-B/R (fecha)'. **T**=tirada · **M**=embrión · **N**=endospermo · "
            "T-01…T-05 = **patrón sin tratamiento**. Tiempo por fecha y paridad de la tirada: "
            "28 feb = 120 s; 7 y 14 mar = impar 30 s / par 60 s; 21 mar y 25 abr = impar 45 s / "
            "par 75 s; 2 may = impar 30 s / par 45 s. Si la hoja trae su propia leyenda "
            "('1 - 45s / 2 - 75s') se usa esa. Bloques anotados ('2min', 'Sin aire', "
            "'Plasma en el petri') se separan en 'Condición'."
        ),
        "pregunta": "¿Qué tiempo de tratamiento favorece la germinación y el crecimiento?",
    },
    TIPO_TIEMPO30: {
        "dims": ["Clase nombre", "Variedad", "Tratamiento", "Tirada", "Bloque"],
        "default": ["Clase nombre"],
        "descripcion": (
            "Todas las semillas tratadas recibieron 30 s. Se compara la cara expuesta "
            "(**Embrión / Endospermo**) contra el **Control** y entre variedades. Los "
            "'Experimento 1, 2, 3' son las cajas (réplicas). Longitudes en mm."
        ),
        "pregunta": "¿Importa qué cara de la semilla se expone? ¿Responde igual cada variedad?",
    },
    TIPO_TEMPERATURA: {
        "dims": ["Temperatura", "Bloque", "Hoja", "Archivo", "Tratamiento"],
        "default": ["Temperatura"],
        "descripcion": (
            "Nomenclatura **'Mx - Txx'**: x = número de muestra (caja), xx = temperatura del "
            "tratamiento (Tamb = ambiente). T-01…T-05 = **patrón sin tratamiento**. Las "
            "longitudes vienen en **cm** y se convierten a **mm** para que sean comparables "
            "con los demás archivos. Los bloques de plantilla vacíos se descartan."
        ),
        "pregunta": "¿Qué temperatura durante el tratamiento favorece la germinación y el crecimiento?",
    },
}

PATRON_MUESTRA = re.compile(
    r"^\s*M\s*0*(\d+)\s*[-–]\s*T?\s*(amb(?:iente)?|\d+(?:[.,]\d+)?)\s*(?:°\s*C)?\s*$",
    re.IGNORECASE,
)
PATRON_FECHA_ARCHIVO = re.compile(r"(\d{1,2})[-_ ]([A-Za-zé]+)[-_ ](\d{4})")
PATRON_T_NOTA = re.compile(r"\bt\s*=\s*(\d+(?:[.,]\d+)?)\s*s\b", re.IGNORECASE)
PATRON_T_ARCHIVO = re.compile(r"(?:^|[_\-\s]|t)(\d+(?:[.,]\d+)?)\s*s(?:\b|_|\.|$)", re.IGNORECASE)


def _es_formato_temperatura(celdas):
    return any(isinstance(v, str) and PATRON_MUESTRA.match(v.strip()) for v in celdas.values())


def _unidad_longitud(celdas):
    """Detecta la nota 'Longitud dada en cm'. Devuelve el factor para pasar a mm."""
    for (fila, _c), valor in celdas.items():
        if fila <= 3 and isinstance(valor, str) and re.search(r"\bcm\b", valor, re.IGNORECASE):
            return 10.0, "cm"
    return 1.0, "mm"


def _tiempo_temperatura(celdas, nombre_archivo, advertencias):
    """Tiempo de tratamiento: nota en la hoja ('t=60s') > nombre del archivo ('45s')."""
    en_hoja = None
    for (fila, _c), valor in celdas.items():
        if fila <= 2 and isinstance(valor, str):
            m = PATRON_T_NOTA.search(valor)
            if m:
                en_hoja = float(m.group(1).replace(",", "."))
    m = PATRON_T_ARCHIVO.search(Path(nombre_archivo or "").stem)
    en_nombre = float(m.group(1).replace(",", ".")) if m else None

    if en_hoja is not None and en_nombre is not None and en_hoja != en_nombre:
        advertencias.append(
            f"El nombre del archivo dice {en_nombre:g} s pero la hoja indica t={en_hoja:g} s; "
            "se usó el valor de la hoja. Verifica cuál es el correcto."
        )
    if en_hoja is not None:
        return en_hoja, f"Nota de la hoja (t={en_hoja:g} s)"
    if en_nombre is not None:
        return en_nombre, f"Nombre del archivo ({en_nombre:g} s)"
    return None, "Sin definir"


def _etiqueta_desde_archivo(nombre_archivo, respaldo):
    m = PATRON_FECHA_ARCHIVO.search(Path(nombre_archivo or "").stem)
    if not m:
        return respaldo
    variedad = "Criollo" if "criollo" in (nombre_archivo or "").lower() else respaldo
    return f"{variedad} {int(m.group(1)):02d}-{m.group(2).capitalize()}-{m.group(3)}"


def _extraer_hoja_temperatura(nombre_hoja, celdas, advertencias, nombre_archivo=""):
    factor, unidad = _unidad_longitud(celdas)
    segundos, fuente_seg = _tiempo_temperatura(celdas, nombre_archivo, advertencias)
    color = _color_de_hoja(nombre_hoja)
    etiqueta_hoja = _etiqueta_desde_archivo(nombre_archivo, nombre_hoja)

    titulos = []
    for (fila, col), valor in celdas.items():
        if not isinstance(valor, str):
            continue
        texto = valor.strip()
        m = PATRON_MUESTRA.match(texto)
        if m:
            titulos.append((fila, col, "M", int(m.group(1)), m.group(2), texto))
            continue
        m = PATRON_TITULO.match(texto)
        if m:
            # T-01…T-05 = control; T-5M, T-7N… = bloques con letra
            extra = m.group(3) if (m.group(3) or not m.group(1)) else ""
            titulos.append((fila, col, "T", int(m.group(2)), extra, texto))
    titulos.sort()

    # columnas sueltas tipo 'R' / 'T' (sin No ni Germinó): no se pueden usar
    for (fila, col), valor in celdas.items():
        if (isinstance(valor, str) and valor.strip().upper() == "R"
                and str(celdas.get((fila, col + 1), "")).strip().upper() == "T"):
            n = sum(isinstance(celdas.get((f, col)), (int, float)) for f in range(fila + 1, fila + 40))
            advertencias.append(
                f"Hay {n} valores en columnas sueltas 'R'/'T' (celda {chr(64 + col)}{fila}) sin "
                "número de semilla ni 'Germinó' ni nombre de muestra; no se incluyeron."
            )

    registros, vacios, contador = [], [], {}
    for fila_t, col_t, tipo, numero, extra, texto in titulos:
        filas_bloque, fila = [], fila_t + 2
        while isinstance(celdas.get((fila, col_t)), (int, float)):
            raiz = celdas.get((fila, col_t + 1))
            tallo = celdas.get((fila, col_t + 2))
            germ = celdas.get((fila, col_t + 3))
            filas_bloque.append((
                int(celdas[(fila, col_t)]),
                raiz * factor if isinstance(raiz, (int, float)) else None,
                tallo * factor if isinstance(tallo, (int, float)) else None,
                int(germ) if isinstance(germ, (int, float)) else None,
            ))
            fila += 1

        if not filas_bloque:
            advertencias.append(f"{texto}: bloque sin filas de datos legibles.")
            continue
        if all(not (r or t or g) for _, r, t, g in filas_bloque):
            vacios.append(texto)  # plantilla sin usar
            continue

        if tipo == "M":
            temp_txt = extra.lower()
            if temp_txt.startswith("amb"):
                temp_num, temp_lbl = np.nan, "Ambiente"
            else:
                temp_num = float(temp_txt.replace(",", "."))
                temp_lbl = f"{temp_num:g} °C"
            codigo, nombre_clase = "T", "Tratada"
            seg = segundos
            tirada = numero
        else:
            codigo, nombre_clase = _datos_clase(extra)
            if codigo == "S":
                temp_num, temp_lbl, seg = np.nan, "Control", 0
            else:
                temp_num, temp_lbl, seg = np.nan, "Sin anotar", segundos
                advertencias.append(f"{texto}: bloque con datos pero sin temperatura anotada.")
            tirada = numero if codigo != "S" else 0

        clave = (tipo, texto.upper().replace(" ", ""))
        contador[clave] = contador.get(clave, 0) + 1

        for no, raiz, tallo, germ in filas_bloque:
            registros.append({
                "Hoja": etiqueta_hoja, "Fecha etiqueta": etiqueta_hoja,
                "Día": None, "Mes": None, "Color": color,
                "Tirada": tirada, "Paridad": "Par" if tirada % 2 == 0 else "Impar",
                "Clase": codigo, "Clase nombre": nombre_clase,
                "Bloque": re.sub(r"\s+", " ", texto), "Réplica": contador[clave],
                "No": no, "Raíz": raiz, "Tallo": tallo, "Germinó": germ,
                "Tratamiento (s)": seg, "Condición": "Estándar",
                "Temperatura": temp_lbl, "Temperatura (°C)": temp_num,
                "Unidad original": unidad,
                "Fuente del tiempo": ("Control: sin tratamiento (0 s)" if seg == 0 else fuente_seg),
            })

    if vacios:
        advertencias.append(
            f"Se descartaron {len(vacios)} bloques de plantilla vacíos (todo en 0): "
            + ", ".join(vacios)
        )
    if segundos is None:
        advertencias.append("No se encontró el tiempo de tratamiento ni en la hoja ni en el nombre.")
    return registros


def _leer_libro(fuente):
    """Devuelve [(nombre_hoja, celdas)] desde una ruta o bytes de un .xlsx."""
    if isinstance(fuente, (bytes, bytearray)):
        fuente = io.BytesIO(fuente)
    hojas = []
    with zipfile.ZipFile(fuente) as zf:
        cadenas = _leer_cadenas_compartidas(zf)
        for nombre_hoja, ruta_hoja in _mapa_hojas(zf):
            hojas.append((nombre_hoja, _leer_celdas(zf, ruta_hoja, cadenas)))
    return hojas


def cargar_datos(fuente, nombre_archivo=None):
    """Lee un Excel (ruta o bytes), detecta el formato de cada hoja y extrae los datos."""
    if nombre_archivo is None and not isinstance(fuente, (bytes, bytearray)):
        nombre_archivo = Path(fuente).name
    advertencias, todos = [], []

    for nombre_hoja, celdas in _leer_libro(fuente):
        if not celdas:
            continue
        if _es_formato_temperatura(celdas):
            tipo = TIPO_TEMPERATURA
            registros = _extraer_hoja_temperatura(nombre_hoja, celdas, advertencias, nombre_archivo)
        elif _es_formato_tiempo(celdas):
            tipo = TIPO_TIEMPO30
            registros = _extraer_hoja_tiempo(nombre_hoja, celdas, advertencias)
        else:
            tipo = TIPO_TIEMPO
            registros = _extraer_bloques_de_hoja(nombre_hoja, celdas, advertencias)
        for r in registros:
            r["Tipo de experimento"] = tipo
        todos.extend(registros)

    df = pd.DataFrame(todos)
    if df.empty:
        return df, advertencias
    return _postprocesar(df), advertencias


def _etiqueta_tratamiento(seg):
    if pd.isna(seg):
        return "Sin definir"
    if seg == 0:
        return "Control (0 s)"
    return f"{int(seg)} s" if float(seg).is_integer() else f"{seg:g} s"


def _postprocesar(df):
    for columna in ["Raíz", "Tallo", "Germinó", "Tratamiento (s)"]:
        df[columna] = pd.to_numeric(df[columna], errors="coerce")

    for col, defecto in [("Condición", "Estándar"), ("Temperatura", "No registrada"),
                         ("Fuente del tiempo", "Sin definir"),
                         ("Unidad original", "mm"), ("Tipo de experimento", TIPO_TIEMPO)]:
        if col not in df.columns:
            df[col] = defecto
        df[col] = df[col].fillna(defecto)
    if "Temperatura (°C)" not in df.columns:
        df["Temperatura (°C)"] = np.nan

    # Coherencia: si hay longitud > 0 la semilla germinó.
    creció = (df["Raíz"].fillna(0) > 0) | (df["Tallo"].fillna(0) > 0)
    df.loc[df["Germinó"].isna() & creció, "Germinó"] = 1

    df["Tratamiento"] = df["Tratamiento (s)"].apply(_etiqueta_tratamiento)
    df["Estado germinación"] = df["Germinó"].map({1: "Germinó", 0: "No germinó"})

    df["Corrida"] = (
        df["Color"].astype(str) + " | " + df["Bloque"].astype(str)
        + " | rep " + df["Réplica"].astype(str)
        + " | " + df["Hoja"].astype(str)
    )
    return df


def cargar_varios(fuentes):
    """fuentes: lista de rutas o de tuplas (nombre, bytes)."""
    marcos, advertencias = [], []

    for fuente in fuentes:
        if isinstance(fuente, tuple):
            nombre, contenido = fuente
        else:
            nombre, contenido = Path(fuente).name, fuente
        try:
            df_parcial, avisos = cargar_datos(contenido, nombre)
        except Exception as error:
            advertencias.append(f"No se pudo leer {nombre}: {error}")
            continue

        advertencias.extend(f"{nombre}: {a}" for a in avisos)
        if not df_parcial.empty:
            df_parcial = df_parcial.copy()
            df_parcial["Archivo"] = nombre
            marcos.append(df_parcial)
        else:
            advertencias.append(f"{nombre}: no se reconoció ningún bloque de datos.")

    if not marcos:
        return pd.DataFrame(), advertencias

    df = pd.concat(marcos, ignore_index=True)

    # Si dos archivos tienen hojas con el mismo nombre (p. ej. 'Datos-Criollo'),
    # se distinguen para que sus cajas no se mezclen.
    repetidas = df.groupby("Hoja")["Archivo"].nunique()
    repetidas = repetidas[repetidas > 1].index
    if len(repetidas):
        mask = df["Hoja"].isin(repetidas)
        df.loc[mask, "Hoja"] = df.loc[mask, "Hoja"] + " [" + df.loc[mask, "Archivo"].map(lambda x: Path(x).stem) + "]"
    df["Corrida"] = (
        df["Color"].astype(str) + " | " + df["Bloque"].astype(str)
        + " | rep " + df["Réplica"].astype(str) + " | " + df["Hoja"].astype(str)
    )
    # Identificador único de cada semilla (para descartes manuales)
    df["ID semilla"] = df["Archivo"].astype(str) + " | " + df["Corrida"] + " | No " + df["No"].astype(str)
    if df["ID semilla"].duplicated().any():
        df["ID semilla"] = df["ID semilla"] + " | fila " + df.groupby("ID semilla").cumcount().astype(str)
    return df, advertencias


def variedad_por_color(
    df,
    nombre_blanca="PBB-DH-183",
    nombre_rosa="H-392 A",
    nombre_cacahuazintle="CACAHUAZINTLE",
    nombre_criollo="CRIOLLO",
):
    mapa = {
        "B": nombre_blanca,
        "R": nombre_rosa,
        "C": nombre_cacahuazintle,
        "CR": nombre_criollo,
        "CACAHUAZINTLE": nombre_cacahuazintle,
        "CRIOLLO": nombre_criollo,
    }
    salida = df.copy()
    salida["Variedad"] = salida["Color"].apply(
        lambda valor: mapa.get(str(valor).strip().upper(), valor)
    )
    return salida


ENCABEZADO_RAIZ = "raíz [mm]"
TEXTO_SIN_GERMINAR = "sin germinar"
SEGUNDOS_TIEMPO30 = 30


def _clase_desde_texto(texto):
    t = (texto or "").strip().lower().rstrip(":")
    if t.startswith("embri"):
        return "M", "Embrión"
    if t.startswith("endosperm"):
        return "N", "Endospermo"
    return "S", "Patrón"


def _leer_bloques_tiempo30(celdas, col_datos, variedad, etiqueta_hoja, advertencias):
    registros = []

    encabezados = sorted(
        fila for (fila, col), valor in celdas.items()
        if col == col_datos and isinstance(valor, str)
        and valor.strip().lower() == ENCABEZADO_RAIZ
    )

    contador_replica = {}

    for fila_enc in encabezados:
        etiqueta_izq = celdas.get((fila_enc, col_datos - 1))
        etiqueta_izq = str(etiqueta_izq).strip() if etiqueta_izq else ""

        m = re.search(r"experimento\s*(\d+)", etiqueta_izq, re.IGNORECASE)
        if m:
            tirada = int(m.group(1))
            texto_clase = celdas.get((fila_enc - 1, col_datos)) or ""
            codigo, nombre_clase = _clase_desde_texto(str(texto_clase))
            nombre_bloque = f"Exp{tirada}-{codigo}"
        else:
            tirada = 0
            codigo, nombre_clase = "S", "Patrón"
            nombre_bloque = "Control"
        segundos_bloque = 0 if codigo == "S" else SEGUNDOS_TIEMPO30

        clave = (tirada, codigo)
        contador_replica[clave] = contador_replica.get(clave, 0) + 1
        replica = contador_replica[clave]
        fila = fila_enc + 1
        valores = []
        sin_germinar = 0
        limite = max(f for (f, _c) in celdas) + 2

        while fila < limite:
            celda = celdas.get((fila, col_datos))

            if isinstance(celda, str):
                if TEXTO_SIN_GERMINAR in celda.strip().lower():
                    conteo = celdas.get((fila, col_datos + 1))
                    sin_germinar = int(conteo) if isinstance(conteo, (int, float)) else 0
                break

            if isinstance(celda, (int, float)):
                tallo = celdas.get((fila, col_datos + 1))
                valores.append(
                    (float(celda), float(tallo) if isinstance(tallo, (int, float)) else None)
                )

            fila += 1

        if not valores and sin_germinar == 0:
            advertencias.append(
                f"{etiqueta_hoja} | {variedad} | {nombre_bloque}: bloque sin datos legibles."
            )
            continue

        numero = 0
        for raiz, tallo in valores:
            numero += 1
            registros.append({
                "Hoja": etiqueta_hoja,
                "Fecha etiqueta": etiqueta_hoja,
                "Día": None, "Mes": None,
                "Color": variedad,
                "Tirada": tirada,
                "Paridad": "Par" if tirada % 2 == 0 else "Impar",
                "Clase": codigo,
                "Clase nombre": nombre_clase,
                "Bloque": nombre_bloque,
                "Réplica": replica,
                "No": numero,
                "Raíz": raiz,
                "Tallo": tallo,
                "Germinó": 1,
                "Tratamiento (s)": segundos_bloque,
                "Condición": "Estándar",
                "Fuente del tiempo": ("Control: sin tratamiento (0 s)" if segundos_bloque == 0
                                      else "Encabezado del archivo (t = 30 s)"),
            })

        for _ in range(sin_germinar):
            numero += 1
            registros.append({
                "Hoja": etiqueta_hoja,
                "Fecha etiqueta": etiqueta_hoja,
                "Día": None, "Mes": None,
                "Color": variedad,
                "Tirada": tirada,
                "Paridad": "Par" if tirada % 2 == 0 else "Impar",
                "Clase": codigo,
                "Clase nombre": nombre_clase,
                "Bloque": nombre_bloque,
                "Réplica": replica,
                "No": numero,
                "Raíz": 0.0,   # se convierte a NaN en el análisis de crecimiento
                "Tallo": 0.0,
                "Germinó": 0,
                "Tratamiento (s)": segundos_bloque,
                "Condición": "Estándar",
                "Fuente del tiempo": ("Control: sin tratamiento (0 s)" if segundos_bloque == 0
                                      else "Encabezado del archivo (t = 30 s)"),
            })

    return registros


def _es_formato_tiempo(celdas):
    for valor in celdas.values():
        if isinstance(valor, str) and valor.strip().lower() == ENCABEZADO_RAIZ:
            return True
    return False


def _extraer_hoja_tiempo(nombre_hoja, celdas, advertencias):
    etiqueta = "Tiempo 30 s"
    for (fila, col), valor in celdas.items():
        if isinstance(valor, str) and re.match(r"^\s*t\s*=", valor.strip(), re.IGNORECASE):
            etiqueta = valor.strip().replace("t =", "Tiempo").strip()
            break

    variedades = []
    for (fila, col), valor in sorted(celdas.items()):
        if fila > 3 or not isinstance(valor, str):
            continue
        texto = valor.strip()
        if texto and texto.isupper() and not texto.lower().startswith("t ="):
            variedades.append((col, texto))

    if not variedades:
        advertencias.append(f"{nombre_hoja}: no se encontraron nombres de variedad.")
        return []

    registros = []
    for col_variedad, nombre_variedad in variedades:
        col_datos = col_variedad + 1
        encontrados = _leer_bloques_tiempo30(
            celdas, col_datos, nombre_variedad, etiqueta, advertencias
        )
        if not encontrados:
            encontrados = _leer_bloques_tiempo30(
                celdas, col_variedad, nombre_variedad, etiqueta, advertencias
            )
        registros.extend(encontrados)

    return registros



from scipy import stats

try:
    import statsmodels.formula.api as smf
    from statsmodels.stats.anova import anova_lm
    HAY_STATSMODELS = True
except Exception:  # la app sigue funcionando sin el ANOVA factorial
    HAY_STATSMODELS = False


SIG = "Diferencia significativa"
NO_SIG = "Sin diferencia significativa"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def ajustar_holm(p):
    """Corrección de Holm (controla el error familiar, más potente que Bonferroni)."""
    p = np.asarray(p, dtype=float)
    m = len(p)
    if m == 0:
        return p
    orden = np.argsort(p)
    ajust = np.empty(m)
    acumulado = 0.0
    for rango, idx in enumerate(orden):
        acumulado = max(acumulado, (m - rango) * p[idx])
        ajust[idx] = min(1.0, acumulado)
    return ajust


def _grupos_validos(df, variable, columna_grupo, minimo=2):
    grupos = []
    for nombre, sub in df.groupby(columna_grupo, dropna=False):
        valores = pd.to_numeric(sub[variable], errors="coerce").dropna()
        if len(valores) >= minimo:
            grupos.append((str(nombre), valores.astype(float)))
    return grupos


def preparar_variable(df, variable, incluir_no_germinadas=False):
    """Raíz y Tallo solo tienen sentido en semillas que germinaron.
    Una semilla no germinada no tiene longitud 0: no tiene longitud. Si se dejan
    los ceros, la media mezcla 'germinó o no' con 'cuánto creció' y la
    distribución queda inflada en cero (viola normalidad y homocedasticidad)."""
    salida = df.copy()
    if variable in ("Raíz", "Tallo") and not incluir_no_germinadas:
        salida.loc[salida["Germinó"] == 0, variable] = np.nan
    return salida


def agregar_por_unidad(df, variable, columnas_extra=()):
    """Pasa de semillas a unidades experimentales (una fila por caja/corrida).
    Las semillas de una misma caja comparten tratamiento, manipulación y
    microambiente: no son réplicas independientes. Tratar cada semilla como
    réplica infla los grados de libertad del error (pseudorreplicación)."""
    claves = ["Corrida", "Grupo"] + [c for c in columnas_extra if c not in ("Corrida", "Grupo")]
    claves = list(dict.fromkeys(claves))
    datos = df.copy()
    datos[variable] = pd.to_numeric(datos[variable], errors="coerce")
    agregado = (datos.groupby(claves, dropna=False)
                .agg(**{variable: (variable, "mean"),
                        "Semillas en la caja": (variable, "size"),
                        "Semillas con dato": (variable, "count")})
                .reset_index())
    agregado = agregado.dropna(subset=[variable])
    if variable == "Germinó":
        agregado[variable] = agregado[variable] * 100  # % de germinación por caja
    return agregado


# ---------------------------------------------------------------------------
# Descriptivos
# ---------------------------------------------------------------------------

def descriptivos_serie(serie, alfa=0.05):
    valores = pd.to_numeric(serie, errors="coerce").dropna()
    n = len(valores)

    base = {
        "n": n, "Media": np.nan, "Desviación estándar": np.nan,
        "Varianza": np.nan, "SEM": np.nan, "IC inf": np.nan, "IC sup": np.nan,
        "CV %": np.nan, "Q1": np.nan, "Mediana": np.nan,
        "Q3": np.nan, "IQR": np.nan, "Mínimo": np.nan, "Máximo": np.nan,
        "Atípicos (IQR)": 0,
    }
    if n == 0:
        return base

    media = valores.mean()
    sd = valores.std(ddof=1) if n > 1 else np.nan
    var = valores.var(ddof=1) if n > 1 else np.nan
    sem = sd / math.sqrt(n) if n > 1 else np.nan
    if n > 1:
        t = stats.t.ppf(1 - alfa / 2, n - 1)
        ic_inf, ic_sup = media - t * sem, media + t * sem
    else:
        ic_inf = ic_sup = np.nan

    q1 = valores.quantile(0.25)
    q3 = valores.quantile(0.75)
    iqr = q3 - q1
    atipicos = int(((valores < q1 - 1.5 * iqr) | (valores > q3 + 1.5 * iqr)).sum())

    base.update({
        "Media": media, "Desviación estándar": sd, "Varianza": var,
        "SEM": sem, "IC inf": ic_inf, "IC sup": ic_sup,
        "CV %": (sd / media * 100) if (n > 1 and media != 0) else np.nan,
        "Q1": q1, "Mediana": valores.median(), "Q3": q3,
        "IQR": iqr, "Mínimo": valores.min(), "Máximo": valores.max(),
        "Atípicos (IQR)": atipicos,
    })
    return base


def tabla_descriptivos(df, columna_grupo, variable, alfa=0.05):
    filas = []
    for nombre, sub in df.groupby(columna_grupo, dropna=False):
        fila = {"Grupo": str(nombre)}
        fila.update(descriptivos_serie(sub[variable], alfa))
        filas.append(fila)
    salida = pd.DataFrame(filas)
    if salida.empty:
        return salida
    return salida.sort_values("Media", ascending=False).reset_index(drop=True)


def ic_wilson(exitos, n, alfa=0.05):
    """IC de Wilson para una proporción (mejor que el de Wald con n pequeño o p cercana a 0/1)."""
    if n == 0:
        return np.nan, np.nan
    z = stats.norm.ppf(1 - alfa / 2)
    p = exitos / n
    den = 1 + z ** 2 / n
    centro = (p + z ** 2 / (2 * n)) / den
    medio = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / den
    return max(0.0, centro - medio), min(1.0, centro + medio)


# ---------------------------------------------------------------------------
# Supuestos
# ---------------------------------------------------------------------------

def supuestos(df, variable, columna_grupo, alfa=0.05):
    grupos = _grupos_validos(df, variable, columna_grupo)
    if len(grupos) < 2:
        return None

    residuos = np.concatenate([(v - v.mean()).values for _, v in grupos])
    n_res = len(residuos)
    if n_res < 3 or np.allclose(residuos, 0):
        return None

    if n_res <= 5000:
        w, p_norm = stats.shapiro(residuos)
        prueba_norm = "Shapiro-Wilk (residuos)"
    else:
        w, p_norm = stats.normaltest(residuos)
        prueba_norm = "D'Agostino-Pearson (residuos)"

    lev, p_lev = stats.levene(*[v.values for _, v in grupos], center="median")

    n_min = min(len(v) for _, v in grupos)
    normal = p_norm >= alfa
    homogeneo = p_lev >= alfa
    # Con ≥30 unidades por grupo el ANOVA es robusto a la no normalidad (TLC),
    # pero no a varianzas desiguales con n desbalanceado.
    normal_efectivo = normal or n_min >= 30

    if normal_efectivo and homogeneo:
        recomendado = "ANOVA + Tukey"
    elif normal_efectivo:
        recomendado = "Welch + Games-Howell"
    else:
        recomendado = "Kruskal-Wallis + Dunn"

    tabla = pd.DataFrame([
        {"Supuesto": "Normalidad", "Prueba": prueba_norm, "Estadístico": w,
         "p-valor": p_norm, "¿Se cumple?": "Sí" if normal else
         ("No (pero n≥30 por grupo: ANOVA robusto)" if n_min >= 30 else "No")},
        {"Supuesto": "Homogeneidad de varianzas", "Prueba": "Levene (Brown-Forsythe, mediana)",
         "Estadístico": lev, "p-valor": p_lev, "¿Se cumple?": "Sí" if homogeneo else "No"},
    ])
    return {"tabla": tabla, "residuos": residuos, "normal": normal,
            "homogeneo": homogeneo, "n mínimo": n_min, "recomendado": recomendado}


# ---------------------------------------------------------------------------
# Pruebas globales
# ---------------------------------------------------------------------------

def anova_una_via(df, variable, columna_grupo, alfa=0.05):
    grupos = _grupos_validos(df, variable, columna_grupo)
    k = len(grupos)
    if k < 2:
        return None

    n_total = sum(len(v) for _, v in grupos)
    gran_media = np.concatenate([v.values for _, v in grupos]).mean()

    sc_entre = sum(len(v) * (v.mean() - gran_media) ** 2 for _, v in grupos)
    sc_dentro = sum(((v - v.mean()) ** 2).sum() for _, v in grupos)
    sc_total = sc_entre + sc_dentro

    gl_entre, gl_dentro, gl_total = k - 1, n_total - k, n_total - 1
    if gl_dentro <= 0:
        return None

    cm_entre = sc_entre / gl_entre
    cm_dentro = sc_dentro / gl_dentro
    f_calc = cm_entre / cm_dentro if cm_dentro > 0 else np.inf
    f_crit = stats.f.ppf(1 - alfa, gl_entre, gl_dentro)
    p_valor = stats.f.sf(f_calc, gl_entre, gl_dentro)
    significativo = p_valor < alfa

    eta2 = sc_entre / sc_total if sc_total > 0 else np.nan
    omega2 = ((sc_entre - gl_entre * cm_dentro) / (sc_total + cm_dentro)
              if sc_total > 0 else np.nan)

    col_fc = f"F crítica (α={alfa:g}; {gl_entre}, {gl_dentro})"
    signo = ">" if f_calc > f_crit else "≤"
    tabla = pd.DataFrame([
        {"Fuente": "Entre grupos (tratamiento)", "Suma de cuadrados": sc_entre,
         "GL": gl_entre, "Cuadrado medio": cm_entre, "F calculada": f_calc,
         col_fc: f_crit, "Comparación": f"{f_calc:.3f} {signo} {f_crit:.3f}",
         "p-valor": p_valor, "Resultado": SIG if significativo else NO_SIG},
        {"Fuente": "Dentro de grupos (error)", "Suma de cuadrados": sc_dentro,
         "GL": gl_dentro, "Cuadrado medio": cm_dentro, "F calculada": np.nan,
         col_fc: np.nan, "Comparación": "", "p-valor": np.nan, "Resultado": ""},
        {"Fuente": "Total", "Suma de cuadrados": sc_total, "GL": gl_total,
         "Cuadrado medio": np.nan, "F calculada": np.nan, col_fc: np.nan,
         "Comparación": "", "p-valor": np.nan, "Resultado": ""},
    ])

    medias = pd.DataFrame([
        {"Grupo": nombre, "n": len(v), "Media": v.mean(), "Varianza": v.var(ddof=1)}
        for nombre, v in grupos
    ])

    return {
        "metodo": "ANOVA de una vía", "tabla": tabla, "medias": medias,
        "CM error": cm_dentro, "GL error": gl_dentro, "GL entre": gl_entre,
        "k": k, "n total": n_total, "estadistico": f_calc,
        "nombre estadistico": "F", "F calculada": f_calc, "F crítica": f_crit,
        "p-valor": p_valor, "significativo": significativo, "alfa": alfa,
        "GL total": gl_total, "SC entre": sc_entre, "SC error": sc_dentro,
        "CM entre": cm_entre,
        "efecto": {"η² (eta cuadrada)": eta2, "ω² (omega cuadrada, menos sesgada)": omega2},
    }


def anova_welch(df, variable, columna_grupo, alfa=0.05):
    """ANOVA de Welch: no asume varianzas iguales."""
    grupos = _grupos_validos(df, variable, columna_grupo)
    k = len(grupos)
    if k < 2:
        return None
    n = np.array([len(v) for _, v in grupos], float)
    m = np.array([v.mean() for _, v in grupos])
    s2 = np.array([v.var(ddof=1) for _, v in grupos])
    if np.any(s2 <= 0):
        return None
    w = n / s2
    media_w = (w * m).sum() / w.sum()
    a = (w * (m - media_w) ** 2).sum() / (k - 1)
    lam = ((1 - w / w.sum()) ** 2 / (n - 1)).sum()
    b = 1 + 2 * (k - 2) / (k ** 2 - 1) * lam
    f = a / b
    gl1, gl2 = k - 1, (k ** 2 - 1) / (3 * lam)
    p = stats.f.sf(f, gl1, gl2)

    medias = pd.DataFrame([{"Grupo": g, "n": len(v), "Media": v.mean(), "Varianza": v.var(ddof=1)}
                           for g, v in grupos])
    todos = np.concatenate([v.values for _, v in grupos])
    sc_entre = sum(len(v) * (v.mean() - todos.mean()) ** 2 for _, v in grupos)
    sc_total = ((todos - todos.mean()) ** 2).sum()

    tabla = pd.DataFrame([{"Prueba": "ANOVA de Welch", "F": f, "GL num": gl1,
                           "GL den": gl2, "p-valor": p,
                           "Resultado": SIG if p < alfa else NO_SIG}])
    return {"metodo": "ANOVA de Welch", "tabla": tabla, "medias": medias,
            "k": k, "n total": int(n.sum()), "estadistico": f, "nombre estadistico": "F",
            "GL entre": gl1, "GL error": gl2, "p-valor": p, "significativo": p < alfa,
            "alfa": alfa,
            "efecto": {"η² (descriptiva)": sc_entre / sc_total if sc_total > 0 else np.nan}}


def kruskal_wallis(df, variable, columna_grupo, alfa=0.05):
    grupos = _grupos_validos(df, variable, columna_grupo)
    k = len(grupos)
    if k < 2:
        return None
    try:
        h, p = stats.kruskal(*[v.values for _, v in grupos])
    except ValueError:  # todos los valores idénticos
        return None
    n = sum(len(v) for _, v in grupos)
    eps2 = h / ((n ** 2 - 1) / (n + 1)) if n > 1 else np.nan
    medias = pd.DataFrame([{"Grupo": g, "n": len(v), "Media": v.mean(),
                            "Mediana": v.median()} for g, v in grupos])
    tabla = pd.DataFrame([{"Prueba": "Kruskal-Wallis", "H": h, "GL": k - 1,
                           "p-valor": p, "Resultado": SIG if p < alfa else NO_SIG}])
    return {"metodo": "Kruskal-Wallis", "tabla": tabla, "medias": medias, "k": k,
            "n total": n, "estadistico": h, "nombre estadistico": "H",
            "GL entre": k - 1, "GL error": np.nan, "p-valor": p,
            "significativo": p < alfa, "alfa": alfa,
            "efecto": {"ε² (épsilon cuadrada)": eps2}, "_grupos": grupos}


# ---------------------------------------------------------------------------
# Post-hoc
# ---------------------------------------------------------------------------

def tukey_hsd(anova):
    """Prueba de Tukey (Tukey-Kramer, válida con n desiguales).
    Para cada par se compara |diferencia de medias| contra la DHS
    (diferencia honestamente significativa) = q crítica × √(CMerror/2 · (1/n1 + 1/n2)).
    Es equivalente a comparar q calculada contra q crítica."""
    if anova is None or anova.get("metodo") != "ANOVA de una vía":
        return pd.DataFrame()
    medias, cm_error = anova["medias"], anova["CM error"]
    gl_error, k, alfa = anova["GL error"], anova["k"], anova["alfa"]
    if len(medias) < 2 or cm_error <= 0 or gl_error <= 0:
        return pd.DataFrame()

    q_crit = stats.studentized_range.ppf(1 - alfa, k, gl_error)
    filas = []
    for (_, g1), (_, g2) in combinations(medias.iterrows(), 2):
        dif = g1["Media"] - g2["Media"]
        error = math.sqrt((cm_error / 2) * (1 / g1["n"] + 1 / g2["n"]))
        q_calc = abs(dif) / error if error > 0 else np.inf
        dhs = q_crit * error
        p_aj = stats.studentized_range.sf(q_calc, k, gl_error)
        signif = abs(dif) > dhs
        filas.append({
            "Grupo 1": g1["Grupo"], "Grupo 2": g2["Grupo"],
            "n1": int(g1["n"]), "n2": int(g2["n"]),
            "Media 1": g1["Media"], "Media 2": g2["Media"],
            "|Diferencia|": abs(dif), "DHS": dhs,
            "Comparación |dif| vs DHS": f"{abs(dif):.3f} {'>' if signif else '≤'} {dhs:.3f}",
            "q calculada": q_calc, "q crítica": q_crit,
            "Comparación q": f"{q_calc:.3f} {'>' if signif else '≤'} {q_crit:.3f}",
            "k (medias)": k, "GL error": gl_error, "p ajustada": p_aj,
            "Resultado": SIG if signif else NO_SIG,
        })
    return pd.DataFrame(filas).sort_values("|Diferencia|", ascending=False).reset_index(drop=True)


def lsd(anova):
    """Prueba LSD de Fisher (diferencia mínima significativa).
    Para cada par se compara |diferencia de medias| contra
    LSD = t crítica(α/2; GL error) × √(CMerror · (1/n1 + 1/n2)),
    equivalente a comparar t calculada contra t crítica.
    Según Fisher, solo se interpreta si el ANOVA fue significativo; la tabla
    muestra la comparación siempre y el dashboard avisa cuando no aplica."""
    if anova is None or anova.get("metodo") != "ANOVA de una vía":
        return pd.DataFrame()
    medias, cm_error = anova["medias"], anova["CM error"]
    gl_error, alfa = anova["GL error"], anova["alfa"]
    if len(medias) < 2 or cm_error <= 0 or gl_error <= 0:
        return pd.DataFrame()

    t_crit = stats.t.ppf(1 - alfa / 2, gl_error)
    filas = []
    for (_, g1), (_, g2) in combinations(medias.iterrows(), 2):
        dif = abs(g1["Media"] - g2["Media"])
        error = math.sqrt(cm_error * (1 / g1["n"] + 1 / g2["n"]))
        t_calc = dif / error if error > 0 else np.inf
        valor_lsd = t_crit * error
        p = 2 * stats.t.sf(t_calc, gl_error)
        signif = dif > valor_lsd
        filas.append({
            "Grupo 1": g1["Grupo"], "Grupo 2": g2["Grupo"],
            "n1": int(g1["n"]), "n2": int(g2["n"]),
            "Media 1": g1["Media"], "Media 2": g2["Media"],
            "|Diferencia|": dif, "LSD": valor_lsd,
            "Comparación |dif| vs LSD": f"{dif:.3f} {'>' if signif else '≤'} {valor_lsd:.3f}",
            "t calculada": t_calc, "t crítica": t_crit,
            "Comparación t": f"{t_calc:.3f} {'>' if signif else '≤'} {t_crit:.3f}",
            "GL error": gl_error, "p-valor": p,
            "Resultado": SIG if signif else NO_SIG,
        })
    return pd.DataFrame(filas).sort_values("|Diferencia|", ascending=False).reset_index(drop=True)


def games_howell(resultado):
    """Post-hoc para varianzas desiguales (acompaña al ANOVA de Welch)."""
    if resultado is None:
        return pd.DataFrame()
    medias, k, alfa = resultado["medias"], resultado["k"], resultado["alfa"]
    filas = []
    for (_, g1), (_, g2) in combinations(medias.iterrows(), 2):
        v1, v2 = g1["Varianza"] / g1["n"], g2["Varianza"] / g2["n"]
        dif = g1["Media"] - g2["Media"]
        se = math.sqrt((v1 + v2) / 2)
        gl = (v1 + v2) ** 2 / (v1 ** 2 / (g1["n"] - 1) + v2 ** 2 / (g2["n"] - 1))
        q = abs(dif) / se if se > 0 else np.inf
        p = stats.studentized_range.sf(q, k, gl)
        medio_ic = stats.studentized_range.ppf(1 - alfa, k, gl) * se
        filas.append({"Grupo 1": g1["Grupo"], "Grupo 2": g2["Grupo"],
                      "n1": int(g1["n"]), "n2": int(g2["n"]),
                      "Media 1": g1["Media"], "Media 2": g2["Media"],
                      "Diferencia": abs(dif), "IC inf": dif - medio_ic, "IC sup": dif + medio_ic,
                      "q": q, "GL (Welch)": gl, "p ajustada": p,
                      "Resultado": SIG if p < alfa else NO_SIG})
    return pd.DataFrame(filas).sort_values("Diferencia", ascending=False).reset_index(drop=True)


def dunn(resultado):
    """Post-hoc de Dunn (rangos) con corrección de Holm; acompaña a Kruskal-Wallis."""
    if resultado is None:
        return pd.DataFrame()
    grupos, alfa = resultado["_grupos"], resultado["alfa"]
    todos = np.concatenate([v.values for _, v in grupos])
    rangos = stats.rankdata(todos)
    n = len(todos)
    _, conteos = np.unique(todos, return_counts=True)
    corr_empates = (conteos ** 3 - conteos).sum() / (12 * (n - 1)) if n > 1 else 0

    rango_medio, tam, inicio = {}, {}, 0
    for nombre, v in grupos:
        rango_medio[nombre] = rangos[inicio:inicio + len(v)].mean()
        tam[nombre] = len(v)
        inicio += len(v)

    filas = []
    for (a, _), (b, _) in combinations(grupos, 2):
        se = math.sqrt((n * (n + 1) / 12 - corr_empates) * (1 / tam[a] + 1 / tam[b]))
        z = (rango_medio[a] - rango_medio[b]) / se if se > 0 else 0.0
        filas.append({"Grupo 1": a, "Grupo 2": b, "n1": tam[a], "n2": tam[b],
                      "Rango medio 1": rango_medio[a], "Rango medio 2": rango_medio[b],
                      "z": abs(z), "p sin ajustar": 2 * stats.norm.sf(abs(z))})
    tabla = pd.DataFrame(filas)
    if tabla.empty:
        return tabla
    tabla["p ajustada (Holm)"] = ajustar_holm(tabla["p sin ajustar"].values)
    tabla["Resultado"] = np.where(tabla["p ajustada (Holm)"] < alfa, SIG, NO_SIG)
    return tabla.sort_values("z", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Germinación (variable binaria) a nivel semilla
# ---------------------------------------------------------------------------

def chi2_germinacion(df, columna_grupo, alfa=0.05):
    datos = df.dropna(subset=["Germinó"])
    tabla = pd.crosstab(datos[columna_grupo], datos["Germinó"].astype(int))
    for c in (0, 1):
        if c not in tabla.columns:
            tabla[c] = 0
    tabla = tabla[[0, 1]]
    if len(tabla) < 2:
        return None

    resumen = []
    for g, fila in tabla.iterrows():
        n = int(fila.sum()); x = int(fila[1])
        li, ls = ic_wilson(x, n, alfa)
        resumen.append({"Grupo": str(g), "n": n, "Germinaron": x,
                        "Media": x / n * 100 if n else np.nan,  # % germinación
                        "IC inf %": li * 100, "IC sup %": ls * 100})
    resumen = pd.DataFrame(resumen)

    if (tabla[1].sum() == 0) or (tabla[0].sum() == 0):
        chi2, p, gl, esperadas = 0.0, 1.0, len(tabla) - 1, tabla.values.astype(float)
    else:
        chi2, p, gl, esperadas = stats.chi2_contingency(tabla.values, correction=False)
    n_tot = tabla.values.sum()
    v_cramer = math.sqrt(chi2 / n_tot) if n_tot else np.nan
    pct_bajas = float((np.asarray(esperadas) < 5).mean() * 100)

    salida = pd.DataFrame([{"Prueba": "χ² de independencia", "χ²": chi2, "GL": gl,
                            "p-valor": p, "V de Cramér": v_cramer,
                            "% celdas con esperado < 5": pct_bajas,
                            "Resultado": SIG if p < alfa else NO_SIG}])
    return {"metodo": "χ² de independencia", "tabla": salida, "medias": resumen,
            "k": len(tabla), "n total": int(n_tot), "estadistico": chi2,
            "nombre estadistico": "χ²", "GL entre": gl, "GL error": np.nan,
            "p-valor": p, "significativo": p < alfa, "alfa": alfa,
            "efecto": {"V de Cramér": v_cramer}, "_contingencia": tabla,
            "aviso esperadas": pct_bajas > 20}


def pares_proporciones(resultado_chi2):
    """Comparaciones por pares con prueba exacta de Fisher + corrección de Holm."""
    if resultado_chi2 is None:
        return pd.DataFrame()
    tabla, alfa = resultado_chi2["_contingencia"], resultado_chi2["alfa"]
    filas = []
    for a, b in combinations(tabla.index, 2):
        sub = tabla.loc[[a, b]].values
        _, p = stats.fisher_exact(sub)
        pa = sub[0, 1] / sub[0].sum() * 100
        pb = sub[1, 1] / sub[1].sum() * 100
        filas.append({"Grupo 1": str(a), "Grupo 2": str(b),
                      "% germ. 1": pa, "% germ. 2": pb,
                      "Diferencia (pp)": abs(pa - pb), "p sin ajustar": p})
    t = pd.DataFrame(filas)
    if t.empty:
        return t
    t["p ajustada (Holm)"] = ajustar_holm(t["p sin ajustar"].values)
    t["Resultado"] = np.where(t["p ajustada (Holm)"] < alfa, SIG, NO_SIG)
    return t.sort_values("Diferencia (pp)", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# ANOVA factorial (dos o más factores)
# ---------------------------------------------------------------------------

def anova_factorial(df, variable, factores, alfa=0.05):
    """ANOVA factorial tipo II con interacción. Unir varios factores en un solo
    'Grupo' y hacer ANOVA de una vía no permite separar efectos principales de
    la interacción (p. ej. ¿el efecto del tiempo depende de la cara expuesta?)."""
    if not HAY_STATSMODELS or len(factores) < 2:
        return None
    datos = df[[variable] + list(factores)].dropna().copy()
    if datos.empty:
        return None
    nombres = {}
    for i, f in enumerate(factores):
        nuevo = f"F{i}"
        datos[nuevo] = datos[f].astype(str)
        nombres[nuevo] = f
    datos = datos.rename(columns={variable: "Y"})
    niveles = [datos[c].nunique() for c in nombres]
    if min(niveles) < 2:
        return {"error": "Algún factor tiene un solo nivel con los filtros actuales."}

    celdas = datos.groupby(list(nombres)).size()
    esperadas = int(np.prod(niveles))
    incompleto = len(celdas) < esperadas
    termino = " * ".join(f"C({c})" for c in nombres)
    if incompleto:
        termino = " + ".join(f"C({c})" for c in nombres)  # sin interacción si faltan celdas
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            modelo = smf.ols(f"Y ~ {termino}", data=datos).fit()
            exog = modelo.model.exog
            if np.linalg.matrix_rank(exog) < exog.shape[1]:
                return {"error": (
                    "Los factores elegidos están confundidos (anidados): algún nivel de un "
                    "factor solo aparece junto con un nivel del otro. Ejemplo típico: "
                    "'Control (0 s)' solo existe en la clase 'Patrón'. Para el factorial "
                    "Tratamiento × Clase filtra Clase = Embrión y Endospermo (sin patrón).")}
            tabla = anova_lm(modelo, typ=2)
    except Exception as e:
        return {"error": f"No se pudo ajustar el modelo: {e}"}

    def renombrar(indice):
        texto = indice
        for corto, largo in nombres.items():
            texto = texto.replace(f"C({corto})", largo)
        return texto.replace("Residual", "Error").replace(":", " × ")

    tabla.index = [renombrar(i) for i in tabla.index]
    sc_error = tabla.loc["Error", "sum_sq"]
    tabla["η² parcial"] = tabla["sum_sq"] / (tabla["sum_sq"] + sc_error)
    tabla.loc["Error", "η² parcial"] = np.nan
    tabla["Resultado"] = np.where(tabla["PR(>F)"] < alfa, SIG, NO_SIG)
    tabla.loc["Error", "Resultado"] = ""
    tabla = tabla.rename(columns={"sum_sq": "Suma de cuadrados", "df": "GL",
                                  "F": "F calculada", "PR(>F)": "p-valor"})
    tabla = tabla.reset_index().rename(columns={"index": "Fuente"})
    return {"tabla": tabla, "incompleto": incompleto, "celdas": len(celdas),
            "esperadas": esperadas, "residuos": modelo.resid.values}


# ---------------------------------------------------------------------------
# Letras (compact letter display) — algoritmo inserción-absorción (Piepho 2004)
# ---------------------------------------------------------------------------

def letras_cld(medias, comparaciones_df):
    """Asigna letras de modo que:
      * dos grupos que NO difieren comparten al menos una letra, y
      * dos grupos que SÍ difieren no comparten ninguna.
    El algoritmo anterior (voraz) garantizaba lo segundo pero no lo primero:
    podía dejar sin letra común a pares que no diferían."""
    if medias is None or medias.empty or comparaciones_df is None or comparaciones_df.empty:
        return pd.DataFrame()

    medias = medias.sort_values("Media", ascending=False).reset_index(drop=True)
    grupos = medias["Grupo"].astype(str).tolist()

    distintos = set()
    for _, f in comparaciones_df.iterrows():
        if f["Resultado"] == SIG:
            distintos.add(frozenset((str(f["Grupo 1"]), str(f["Grupo 2"]))))

    columnas = [set(grupos)]
    for par in distintos:
        a, b = tuple(par)
        nuevas = []
        for col in columnas:
            if a in col and b in col:
                nuevas.append(col - {a})
                nuevas.append(col - {b})
            else:
                nuevas.append(col)
        # absorción: quitar columnas vacías, duplicadas o contenidas en otra
        nuevas = [c for c in nuevas if c]
        unicas = []
        for c in sorted(nuevas, key=len, reverse=True):
            if not any(c <= u for u in unicas):
                unicas.append(c)
        columnas = unicas

    # ordenar letras: 'a' para la columna que contiene la media más alta
    posicion = {g: i for i, g in enumerate(grupos)}
    columnas.sort(key=lambda c: min(posicion[g] for g in c))

    abecedario = "abcdefghijklmnopqrstuvwxyz"
    letras = {g: "" for g in grupos}
    for i, col in enumerate(columnas):
        letra = abecedario[i] if i < 26 else abecedario[i // 26 - 1] + abecedario[i % 26]
        for g in grupos:
            if g in col:
                letras[g] += letra

    salida = medias.copy()
    salida["Letras"] = salida["Grupo"].astype(str).map(letras)
    return salida[["Grupo", "n", "Media", "Letras"]]


def letras_tukey(anova, comparaciones_df):
    """Compatibilidad con el nombre anterior."""
    if anova is None:
        return pd.DataFrame()
    return letras_cld(anova["medias"], comparaciones_df)


def analisis_completo(df, variable, columna_grupo, metodo, alfa=0.05, nivel_semilla_binario=False):
    """Ejecuta prueba global + post-hoc según el método elegido.
    Devuelve dict con: global, posthoc, nombre_posthoc, letras, supuestos, metodo_usado."""
    if nivel_semilla_binario:
        glob = chi2_germinacion(df, columna_grupo, alfa)
        post = pares_proporciones(glob)
        return {"global": glob, "posthoc": post, "nombre_posthoc": "Fisher exacta por pares (Holm)",
                "letras": letras_cld(glob["medias"], post) if glob else pd.DataFrame(),
                "supuestos": None, "metodo_usado": "χ² + Fisher (Holm)"}

    sup = supuestos(df, variable, columna_grupo, alfa)
    usado = sup["recomendado"] if (metodo.startswith("Automático") and sup) else metodo
    if usado.startswith("Automático"):
        usado = "ANOVA + Tukey"

    if usado == "Welch + Games-Howell":
        glob = anova_welch(df, variable, columna_grupo, alfa)
        post, nombre = games_howell(glob), "Games-Howell"
    elif usado == "Kruskal-Wallis + Dunn":
        glob = kruskal_wallis(df, variable, columna_grupo, alfa)
        post, nombre = dunn(glob), "Dunn (Holm)"
    else:
        glob = anova_una_via(df, variable, columna_grupo, alfa)
        post, nombre = tukey_hsd(glob), "Tukey HSD"
        usado = "ANOVA + Tukey"

    return {"global": glob, "posthoc": post, "nombre_posthoc": nombre,
            "letras": letras_cld(glob["medias"], post) if glob else pd.DataFrame(),
            "supuestos": sup, "metodo_usado": usado}




PALETA_BASE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
PALETA = list(PALETA_BASE)
COLOR_PRINCIPAL = PALETA[0]
COLOR_CONTROL = "#8a8984"


def generar_paleta(semilla, n=16):
    rng = random.Random(semilla)
    inicio = rng.random()
    saturacion = rng.uniform(0.6, 0.8)
    luces = (rng.uniform(0.42, 0.48), rng.uniform(0.58, 0.64))
    orden = [0, 3, 6, 1, 4, 7, 2, 5]
    colores = []
    for i in range(n):
        h = (inicio + orden[i % 8] / 8 + (i // 8) / 16) % 1.0
        r, g, b = colorsys.hls_to_rgb(h, luces[(i + i // 8) % 2], saturacion)
        colores.append("#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255)))
    return colores


def establecer_colores(semilla=None):
    global PALETA, COLOR_PRINCIPAL
    PALETA = list(PALETA_BASE) if semilla is None else generar_paleta(semilla)
    COLOR_PRINCIPAL = PALETA[0]


def paleta_aleatoria(n, semilla=0):
    return [PALETA[i % len(PALETA)] for i in range(max(n, 1))]


def obtener_paleta(nombre_o_semilla=0, n=12):
    try:
        semilla = int(nombre_o_semilla)
    except (TypeError, ValueError):
        semilla = 0
    return paleta_aleatoria(max(n, 12), semilla)


def aplicar_tipografia(fig, escala=1.0):
    base = 13 * escala
    fig.update_layout(
        font=dict(size=base),
        title=dict(font=dict(size=base * 1.35)),
        legend=dict(font=dict(size=base)),
        xaxis=dict(title=dict(font=dict(size=base * 1.1)),
                   tickfont=dict(size=base)),
        yaxis=dict(title=dict(font=dict(size=base * 1.1)),
                   tickfont=dict(size=base)),
    )
    for anot in fig.layout.annotations:
        actual = anot.font.size if anot.font and anot.font.size else 13
        anot.font.size = actual * escala
    fig.update_traces(textfont=dict(size=base * 0.95),
                      selector=dict(type="bar"))
    return fig



def _dispersion_columnas(resumen, dispersion):
    if dispersion == "Cuartiles (IQR)":
        arriba = (resumen["Q3"] - resumen["Media"]).clip(lower=0)
        abajo = (resumen["Media"] - resumen["Q1"]).clip(lower=0)
        return arriba, abajo, "cuartiles (Q1–Q3)", None
    if dispersion == "Error estándar (SEM)":
        return resumen["SEM"], None, "error estándar (SEM)", "SEM"
    if dispersion == "IC 95% de la media":
        arriba = (resumen["IC sup"] - resumen["Media"]).clip(lower=0)
        abajo = (resumen["Media"] - resumen["IC inf"]).clip(lower=0)
        return arriba, abajo, "IC 95% de la media", None
    return resumen["Desviación estándar"], None, "desviación estándar", "Desviación estándar"


# GRÁFICO INTEGRADO DE LETRAS DE TUKEY  (pieza central)


def describir_prueba(res):
    if res is None:
        return ""
    est = res.get("estadistico", np.nan)
    gl1, gl2 = res.get("GL entre"), res.get("GL error")
    gl_txt = f"GL={gl1:g}" if gl1 is not None and pd.notna(gl1) else ""
    if gl2 is not None and pd.notna(gl2):
        gl_txt = f"GL=({gl1:g}, {gl2:.4g})"
    return (f"{res['metodo']}: {res['nombre estadistico']}={est:.3f} · {gl_txt} · "
            f"p={res['p-valor']:.4g}")


def grafico_letras_tukey(df, variable, columna_grupo, anova, letras,
                         dispersion="Desviación estándar", referencia=None,
                         subtitulo_filtros="", escala_fuente=1.0,
                         etiqueta_eje=None, semilla_color=0,
                         nombre_posthoc="Tukey", etiqueta_y=None):
    if anova is None or letras is None or letras.empty:
        return None

    datos = df.dropna(subset=[variable]).copy()
    if datos.empty:
        return None

    orden = (datos.groupby(columna_grupo)[variable].mean()
             .sort_values(ascending=False).index.tolist())

    mapa_letras = dict(zip(letras["Grupo"].astype(str), letras["Letras"]))

    letras_unicas = []
    for g in orden:
        clave = mapa_letras.get(str(g), "-") or "-"
        if clave not in letras_unicas:
            letras_unicas.append(clave)
    _cols_letra = paleta_aleatoria(max(len(letras_unicas), 3), semilla_color)
    color_por_letra = {c: _cols_letra[i % len(_cols_letra)]
                       for i, c in enumerate(letras_unicas)}

    fig = go.Figure()
    fences = []  
    for g in orden:
        serie = datos[datos[columna_grupo] == g][variable].dropna()
        clave = mapa_letras.get(str(g), "-") or "-"
        color = color_por_letra[clave]
        media = serie.mean() if len(serie) else 0
        mediana = serie.median() if len(serie) else 0
        letra = mapa_letras.get(str(g), "")
        fig.add_trace(go.Box(
            y=serie, name=str(g),
            marker_color="#555", line_color="#555",
            fillcolor=color, boxmean=True, showlegend=False, width=0.5,
            boxpoints=False,   
            hovertemplate=(
                f"<b>{g}</b><br>Letra ({nombre_posthoc}): <b>{letra}</b><br>"
                f"Media: {media:.2f}<br>Mediana: {mediana:.2f}<br>"
                "Q1: %{q1:.2f}<br>Q3: %{q3:.2f}<br>n=" + str(len(serie)) +
                "<extra></extra>"
            ),
        ))
        if len(serie) >= 1:
            q1 = serie.quantile(0.25); q3 = serie.quantile(0.75)
            fence = q3 + 1.5 * (q3 - q1)
            dentro = serie[serie <= fence]
            fences.append(dentro.max() if len(dentro) else serie.max())
        else:
            fences.append(0)

    tope = max(fences) if fences else 1
    y_letra = tope * 1.06 if tope > 0 else 1

    for g in orden:
        letra = mapa_letras.get(str(g), "")
        if letra:
            fig.add_annotation(
                x=str(g), y=y_letra, text=f"<b>{letra}</b>",
                showarrow=False, yanchor="bottom",
                font=dict(size=20, color="#111"),
                bgcolor="rgba(255,255,255,0.92)",
                bordercolor="#333", borderwidth=1, borderpad=4,
            )

    if referencia is not None and referencia["n"] > 0:
        media = referencia["Media"]
        sd = referencia["Desviación estándar"] or 0
        fig.add_hrect(y0=media - sd, y1=media + sd, fillcolor="gray",
                      opacity=0.10, line_width=0)
        fig.add_hline(y=media, line_dash="dash", line_color="gray",
                      annotation_text=f"Patrón (control): {media:.2f} ± {sd:.2f}",
                      annotation_position="top left")

    nombre_eje = etiqueta_eje or columna_grupo
    titulo = (
        f"<b>{variable} por {nombre_eje} — letras de {nombre_posthoc}</b><br>"
        f"<sub>Grupos que comparten letra NO difieren (α={anova['alfa']}) · "
        f"{describir_prueba(anova)}"
    )
    if subtitulo_filtros:
        titulo += f"<br>{subtitulo_filtros}"
    titulo += "</sub>"

    fig.update_layout(
        title=titulo,
        xaxis_title=nombre_eje,
        yaxis_title=etiqueta_y or f"{variable}",
        xaxis=dict(type="category", tickangle=-30, automargin=True),
        yaxis=dict(range=[None, y_letra * 1.10 if y_letra > 0 else None]),
        boxgap=0.35,
        margin=dict(t=110),
    )
    return aplicar_tipografia(fig, escala_fuente)


def medias_por_grupo(df, variable, columna_grupo, dispersion="Desviación estándar",
                     referencia=None, mostrar_valores=True, grado_polinomio=0,
                     semilla_color=0, subtitulo="", subtitulo_filtros="",
                     orden="Por media (descendente)", escala_fuente=1.0,
                     etiqueta_eje=None):
    resumen = tabla_descriptivos(df, columna_grupo, variable)
    if resumen.empty:
        return None

    valor_num = pd.to_numeric(
        resumen["Grupo"].astype(str).str.extract(r"(\d+)", expand=False),
        errors="coerce",
    )
    eje_es_numerico = valor_num.notna().all()

    if orden == "Por valor del eje (ascendente)" and eje_es_numerico:
        resumen = resumen.assign(_v=valor_num.values).sort_values("_v").reset_index(drop=True)
        x_curva_num = resumen["_v"].values.astype(float)
    else:
        resumen = resumen.sort_values("Media", ascending=False).reset_index(drop=True)
        x_curva_num = np.arange(len(resumen), dtype=float)

    arriba, abajo, etiqueta_disp, col_disp = _dispersion_columnas(resumen, dispersion)

    textos = []
    for i, (_, fila) in enumerate(resumen.iterrows()):
        if not mostrar_valores:
            textos.append("")
            continue
        t = f"{fila['Media']:.2f}"
        if col_disp is not None:
            t += f"±{fila[col_disp]:.2f}"
        textos.append(t)

    colores = paleta_aleatoria(max(len(resumen), 3), semilla_color)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=resumen["Grupo"], y=resumen["Media"],
        error_y=dict(type="data", array=arriba,
                     arrayminus=abajo if abajo is not None else None, visible=True),
        text=textos, textposition="outside",
        marker_color=[colores[i % len(colores)] for i in range(len(resumen))],
        name="Media", showlegend=False,
    ))

    if grado_polinomio and len(resumen) > grado_polinomio:
        coef = np.polyfit(x_curva_num, resumen["Media"].values, grado_polinomio)
        x_suave = np.linspace(x_curva_num.min(), x_curva_num.max(), 100)
        y_suave = np.polyval(coef, x_suave)
        idx = [int(np.argmin(np.abs(x_curva_num - xv))) for xv in x_suave]
        fig.add_trace(go.Scatter(
            x=[resumen["Grupo"].iloc[i] for i in idx],
            y=y_suave, mode="lines",
            line=dict(color="crimson", width=2),
            name=f"Ajuste polinomial (grado {grado_polinomio})",
        ))

    if referencia is not None and referencia["n"] > 0:
        media = referencia["Media"]
        sd = referencia["Desviación estándar"] or 0
        fig.add_hrect(y0=media - sd, y1=media + sd, fillcolor="gray", opacity=0.12, line_width=0)
        fig.add_hline(y=media, line_dash="dash", line_color="gray",
                      annotation_text=f"Patrón: {media:.2f} ± {sd:.2f}",
                      annotation_position="top left")

    nombre_eje = etiqueta_eje or columna_grupo
    titulo = f"Media de {variable} por {nombre_eje} (dispersión: {etiqueta_disp})"
    linea2 = " · ".join([x for x in [subtitulo, subtitulo_filtros] if x])
    if linea2:
        titulo += f"<br><sub>{linea2}</sub>"
    fig.update_layout(title=titulo, xaxis_title=nombre_eje,
                      yaxis_title=f"Media de {variable}",
                      xaxis=dict(type="category", tickangle=-30, automargin=True),
                      showlegend=grado_polinomio > 0, margin=dict(t=90))
    fig.update_traces(cliponaxis=False, selector=dict(type="bar"))
    return aplicar_tipografia(fig, escala_fuente)



def comparacion_corridas(df, variable, columna_grupo, dispersion="Desviación estándar",
                         referencia=None, semilla_color=0, subtitulo_filtros="",
                         escala_fuente=1.0, etiqueta_eje=None):
    datos = df.dropna(subset=[variable]).copy()
    if datos.empty:
        return None

    filas = []
    for corrida, sub in datos.groupby("Corrida"):
        serie = sub[variable].dropna()
        if len(serie) == 0:
            continue
        n = len(serie)
        sd = serie.std(ddof=1) if n > 1 else 0.0
        sem = sd / (n ** 0.5) if n > 0 else 0.0
        filas.append({
            "Corrida": corrida,
            "Bloque": str(sub["Bloque"].iloc[0]) if "Bloque" in sub else str(corrida),
            "Réplica": sub["Réplica"].iloc[0] if "Réplica" in sub else "",
            "Hoja": str(sub["Hoja"].iloc[0]) if "Hoja" in sub else "",
            "Grupo": str(sub[columna_grupo].iloc[0]),
            "Media": serie.mean(),
            "Desviación estándar": sd,
            "SEM": sem,
            "n": n,
        })

    resumen = pd.DataFrame(filas)
    if resumen.empty:
        return None
    resumen = resumen.sort_values(["Grupo", "Media"], ascending=[True, False]).reset_index(drop=True)

    if dispersion == "Error estándar (SEM)":
        col_err = "SEM"
        etiqueta = "error estándar (SEM)"
    else:
        col_err = "Desviación estándar"
        etiqueta = "desviación estándar"

    def hoja_corta(h):
        m = re.search(r"(\d{1,2})[-_ ]*(?:de\s+)?([A-Za-zé]{3})", h)
        return f"{m.group(1)}-{m.group(2).capitalize()}" if m else h[:12]

    varias_hojas = resumen["Hoja"].nunique() > 1
    resumen["Color"] = resumen["Corrida"].str.split(" | ", regex=False).str[0]
    varios_colores = resumen["Color"].nunique() > 1
    resumen["etiqueta_x"] = [
        f"{b} r{r}" + (f" · {hoja_corta(h)}" if varias_hojas else "") + (f" · {c}" if varios_colores else "")
        for b, r, h, c in zip(resumen["Bloque"], resumen["Réplica"], resumen["Hoja"], resumen["Color"])]
    repetidas = resumen["etiqueta_x"].duplicated(keep=False)
    resumen.loc[repetidas, "etiqueta_x"] = (resumen.loc[repetidas, "etiqueta_x"] + " #" +
                                            resumen[repetidas].groupby("etiqueta_x").cumcount().add(1).astype(str))

    fig = px.scatter(
        resumen, x="etiqueta_x", y="Media", color="Grupo",
        error_y=col_err,
        color_discrete_sequence=paleta_aleatoria(
            max(resumen["Grupo"].nunique(), 3), semilla_color),
        hover_data={"etiqueta_x": False, "Corrida": True, "Grupo": True, "Media": ":.2f",
                    "Desviación estándar": ":.2f", "SEM": ":.2f", "n": True},
        title=(f"Comparación entre cajas — {variable} (media ± {etiqueta})" +
               (f"<br><sub>{subtitulo_filtros}</sub>" if subtitulo_filtros else "")),
    )
    fig.update_traces(marker=dict(size=9))

    if referencia is not None and referencia["n"] > 0:
        media = referencia["Media"]
        sd = referencia["Desviación estándar"] or 0
        fig.add_hrect(y0=media - sd, y1=media + sd, fillcolor="gray", opacity=0.10, line_width=0)
        fig.add_hline(y=media, line_dash="dash", line_color="gray",
                      annotation_text=f"Patrón: {media:.2f} ± {sd:.2f}",
                      annotation_position="top left")

    fig.update_layout(
        xaxis_title="Caja (bloque, réplica" + (" y fecha)" if varias_hojas else ")"),
        yaxis_title=("Germinación (proporción 0–1)" if variable == "Germinó" else f"{variable} (mm)")
        + f" · media ± {'SEM' if col_err == 'SEM' else 'DE'}",
        height=560,
        legend_title=(etiqueta_eje or "Grupo de comparación"),
        xaxis=dict(type="category", tickangle=-45, automargin=True),
        margin=dict(t=90))
    return aplicar_tipografia(fig, escala_fuente)




def conteo_germinacion(df, columna_grupo, semilla_color=0, mostrar_valores=True,
                       subtitulo_filtros="", escala_fuente=1.0, etiqueta_eje=None,
                       germinacion_patron=None):
    datos = df.dropna(subset=["Germinó"]).copy()
    if datos.empty:
        return None

    conteo = datos.groupby([columna_grupo, "Estado germinación"]).size().reset_index(name="Semillas")
    totales = datos.groupby(columna_grupo).size().reset_index(name="Total")
    conteo = conteo.merge(totales, on=columna_grupo)
    conteo["%"] = (conteo["Semillas"] / conteo["Total"] * 100).round(1)

    conteo["etiqueta"] = conteo["%"].map(lambda v: f"{v:.1f} %")

    fig = px.bar(
        conteo, x=columna_grupo, y="Semillas", color="Estado germinación",
        barmode="stack", text="etiqueta" if mostrar_valores else None,
        hover_data={columna_grupo: True, "Estado germinación": True,
                    "Semillas": True, "%": True, "Total": True},
        color_discrete_map={"Germinó": PALETA[0], "No germinó": "#b4b2a9"},
        title=(f"Germinaron vs no germinaron por {etiqueta_eje or columna_grupo}" +
               (f"<br><sub>{subtitulo_filtros}</sub>" if subtitulo_filtros else "")),
    )
    if mostrar_valores:
        fig.update_traces(textposition="inside", insidetextanchor="middle",
                          textfont=dict(color="white", size=12))
        fig.update_layout(uniformtext=dict(minsize=9, mode="hide"))


    if germinacion_patron is not None and not conteo.empty:
        total_tipico = conteo.groupby(columna_grupo)["Total"].first().median()
        equivalente = total_tipico * germinacion_patron / 100.0
        fig.add_hline(
            y=equivalente, line_dash="dash", line_color="gold",
            annotation_text=f"Germinación del patrón: {germinacion_patron:.1f}%",
            annotation_position="top left",
        )

    fig.update_layout(xaxis_title=etiqueta_eje or columna_grupo,
                      yaxis_title="Número de semillas", legend_title="Estado",
                      xaxis=dict(type="category", tickangle=-30, automargin=True),
                      margin=dict(t=90))
    return aplicar_tipografia(fig, escala_fuente)




def raiz_vs_tallo(df, columna_grupo, dispersion="Desviación estándar",
                  semilla_color=0, subtitulo_filtros="", escala_fuente=1.0,
                  etiqueta_eje=None, mostrar_valores=True):
    filas = []
    for nombre, sub in df.groupby(columna_grupo, dropna=False):
        for variable in ("Raíz", "Tallo"):
            serie = pd.to_numeric(sub[variable], errors="coerce").dropna()
            if len(serie) == 0:
                continue
            n = len(serie)
            sd = serie.std(ddof=1) if n > 1 else 0.0
            sem = sd / (n ** 0.5) if n > 0 else 0.0
            q1, q3 = serie.quantile(0.25), serie.quantile(0.75)
            filas.append({
                "Grupo": str(nombre), "Variable": variable, "n": n,
                "Media": serie.mean(), "Desviación estándar": sd, "SEM": sem,
                "Q1": q1, "Q3": q3,
            })

    resumen = pd.DataFrame(filas)
    if resumen.empty:
        return None

   
    orden = (resumen[resumen["Variable"] == "Raíz"]
             .sort_values("Media", ascending=False)["Grupo"].tolist())
    if not orden:
        orden = sorted(resumen["Grupo"].unique())

    colores = paleta_aleatoria(2, semilla_color)
    fig = go.Figure()

    for indice, variable in enumerate(("Raíz", "Tallo")):
        datos = resumen[resumen["Variable"] == variable].set_index("Grupo").reindex(orden).reset_index()

        if dispersion == "Cuartiles (IQR)":
            err_mas = (datos["Q3"] - datos["Media"]).clip(lower=0)
            err_menos = (datos["Media"] - datos["Q1"]).clip(lower=0)
            col_txt = None
        elif dispersion == "Error estándar (SEM)":
            err_mas, err_menos, col_txt = datos["SEM"], None, "SEM"
        else:
            err_mas, err_menos, col_txt = datos["Desviación estándar"], None, "Desviación estándar"

        textos = []
        for _, fila in datos.iterrows():
            if not mostrar_valores or pd.isna(fila["Media"]):
                textos.append("")
                continue
            textos.append(f"{fila['Media']:.1f}")

        disp_hover = (datos[col_txt] if col_txt is not None else (datos["Q3"] - datos["Q1"])).fillna(0)
        fig.add_trace(go.Bar(
            x=datos["Grupo"], y=datos["Media"], name=variable,
            marker_color=colores[indice],
            error_y=dict(type="data", array=err_mas,
                         arrayminus=err_menos if err_menos is not None else None,
                         visible=True, color="rgba(150,150,150,0.9)", thickness=1.3, width=4),
            customdata=np.stack([datos["n"].fillna(0), disp_hover], axis=1),
            hovertemplate=(f"<b>%{{x}}</b><br>{variable}: %{{y:.2f}} mm<br>"
                           f"{'IQR' if col_txt is None else ('SEM' if col_txt == 'SEM' else 'DE')}: "
                           "%{customdata[1]:.2f} mm<br>n = %{customdata[0]}<extra></extra>"),
        ))

    etiqueta_disp = {
        "Cuartiles (IQR)": "cuartiles (Q1–Q3)",
        "Error estándar (SEM)": "error estándar (SEM)",
    }.get(dispersion, "desviación estándar")

    titulo = f"Raíz vs Tallo por {etiqueta_eje or columna_grupo} (dispersión: {etiqueta_disp})"
    if subtitulo_filtros:
        titulo += f"<br><sub>{subtitulo_filtros}</sub>"

    fig.update_layout(
        title=titulo, barmode="group",
        xaxis_title=etiqueta_eje or columna_grupo,
        yaxis_title="Media (mm)",
        xaxis=dict(type="category", tickangle=-30, automargin=True),
        legend_title="Medición", margin=dict(t=90),
    )
    fig.update_layout(uniformtext=dict(minsize=9, mode="hide"))
    return aplicar_tipografia(fig, escala_fuente)


def grafico_germinacion_letras(resultado, letras, subtitulo_filtros="", escala_fuente=1.0,
                               etiqueta_eje=None, semilla_color=0, germinacion_patron=None):
    """% de germinación por grupo con IC de Wilson y letras de comparaciones por pares."""
    if resultado is None:
        return None
    med = resultado["medias"].sort_values("Media", ascending=False).reset_index(drop=True)
    mapa = dict(zip(letras["Grupo"], letras["Letras"])) if letras is not None and not letras.empty else {}
    colores = paleta_aleatoria(max(len(med), 3), semilla_color)
    fig = go.Figure(go.Bar(
        x=med["Grupo"], y=med["Media"],
        error_y=dict(type="data", array=med["IC sup %"] - med["Media"],
                     arrayminus=med["Media"] - med["IC inf %"], visible=True),
        marker_color=[colores[i % len(colores)] for i in range(len(med))],
        text=[f"{m:.1f}%  {mapa.get(g, '')}" for g, m in zip(med["Grupo"], med["Media"])],
        textposition="outside", cliponaxis=False,
        customdata=np.stack([med["n"], med["Germinaron"]], axis=1),
        hovertemplate="<b>%{x}</b><br>%{y:.1f}% (%{customdata[1]}/%{customdata[0]})<extra></extra>",
    ))
    if germinacion_patron is not None:
        fig.add_hline(y=germinacion_patron, line_dash="dash", line_color="gray",
                      annotation_text=f"Patrón: {germinacion_patron:.1f}%",
                      annotation_position="top left")
    titulo = (f"<b>% de germinación por {etiqueta_eje or 'grupo'} (IC 95% de Wilson)</b><br>"
              f"<sub>Letras: Fisher exacta por pares con corrección de Holm · "
              f"{describir_prueba(resultado)}")
    if subtitulo_filtros:
        titulo += f"<br>{subtitulo_filtros}"
    titulo += "</sub>"
    fig.update_layout(title=titulo, yaxis_title="% de germinación",
                      yaxis=dict(range=[0, 115]), xaxis_title=etiqueta_eje or "Grupo",
                      xaxis=dict(type="category", tickangle=-30, automargin=True),
                      margin=dict(t=110), showlegend=False)
    return aplicar_tipografia(fig, escala_fuente)


def grafico_qq(residuos, escala_fuente=1.0):
    """Gráfico Q-Q de residuos para juzgar normalidad visualmente."""
    residuos = np.sort(np.asarray(residuos, float))
    n = len(residuos)
    if n < 3:
        return None
    teoricos = stats.norm.ppf((np.arange(1, n + 1) - 0.5) / n)
    sd = residuos.std(ddof=1) or 1
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=teoricos, y=residuos, mode="markers",
                             marker=dict(size=5, opacity=0.6), name="Residuos"))
    fig.add_trace(go.Scatter(x=[teoricos[0], teoricos[-1]],
                             y=[teoricos[0] * sd, teoricos[-1] * sd],
                             mode="lines", line=dict(color="crimson"), name="Normal teórica"))
    fig.update_layout(title="Q-Q de residuos (si los puntos siguen la recta, hay normalidad)",
                      xaxis_title="Cuantiles teóricos N(0,1)", yaxis_title="Residuos",
                      showlegend=False, height=380)
    return aplicar_tipografia(fig, escala_fuente)





CARPETA = Path(__file__).resolve().parent

def encontrar_excels():
    return sorted(p for p in CARPETA.glob("*.xlsx") if not p.name.startswith("~$"))


def redondear(df, decimales=4):
    salida = df.copy()
    for c in salida.select_dtypes(include="number").columns:
        salida[c] = salida[c].round(decimales)
    return salida


@st.cache_data(show_spinner="Leyendo los archivos de Excel…")
def _cargar(fuentes):
    """fuentes: tupla de (nombre, bytes). El contenido forma parte de la clave de
    caché, así que si el archivo cambia se vuelve a leer."""
    return cargar_varios(list(fuentes))


def construir_grupo(df, dimensiones):
    if not dimensiones:
        dimensiones = ["Bloque"]

  
    prefijos = {
        "Tirada": "Tirada ",
        "Réplica": "Réplica ",
        "No": "Semilla ",
    }

    partes = []
    for dim in dimensiones:
        if dim == "Tirada":
            serie = df[dim].apply(
                lambda v: "Control (patrón)" if str(v) in ("0", "0.0") else f"Tirada {v}"
            )
        elif dim in prefijos:
            serie = prefijos[dim] + df[dim].astype(str)
        else:
            serie = df[dim].astype(str)
        partes.append(serie)

    if len(partes) == 1:
        return partes[0]

    salida = partes[0]
    for extra in partes[1:]:
        salida = salida + " | " + extra
    return salida



def _bloquear_traduccion_automatica():
    """Evita que el traductor automático del navegador rompa la página.
    Si la versión de Streamlit ya no tiene este componente, simplemente se omite."""
    try:
        import streamlit.components.v1 as components
        components.html(
            """<script>try{const d=window.parent.document;
            d.documentElement.setAttribute('translate','no');
            d.documentElement.classList.add('notranslate');}catch(e){}</script>""",
            height=0,
        )
    except Exception:
        pass


COLUMNAS_CAJA = ["Hoja", "Archivo", "Variedad", "Clase nombre", "Tratamiento",
                 "Tratamiento (s)", "Condición", "Tirada", "Bloque", "Réplica", "Color",
                 "Temperatura", "Tipo de experimento"]

COLUMNAS_REGISTRO = ["ID semilla", "Hoja", "Bloque", "Réplica", "No", "Grupo",
                     "Germinó", "Raíz", "Tallo"]


# ---------------------------------------------------------------------------
# Descartes
# ---------------------------------------------------------------------------

def cajas_vacias(df):
    """Cajas en las que ninguna semilla tiene longitud registrada (bloques de
    plantilla que no se realizaron, capturados con Germinó = 0)."""
    largo = (pd.to_numeric(df["Raíz"], errors="coerce").fillna(0) > 0) | \
            (pd.to_numeric(df["Tallo"], errors="coerce").fillna(0) > 0)
    con_dato = largo.groupby(df["Corrida"]).any()
    return set(con_dato[~con_dato].index)


def aplicar_descartes(df, variable, op):
    """Aplica los descartes elegidos y devuelve (datos, registro).

    Hay dos tipos de descarte:
      * Se quita la semilla completa (caja vacía, caja o semilla excluida por el
        usuario): deja de contar también en el % de germinación.
      * Se quita solo el valor de la variable (no germinó, cero, fuera de rango,
        atípico): la semilla sigue contando para el % de germinación.
    """
    d = df.copy()
    d[variable] = pd.to_numeric(d[variable], errors="coerce")
    registro = []

    def anotar(mascara, motivo, quita_semilla):
        if mascara.any():
            r = d.loc[mascara, [c for c in COLUMNAS_REGISTRO if c in d.columns]].copy()
            r["Motivo"] = motivo if isinstance(motivo, str) else motivo[mascara].values
            r["Efecto"] = ("Semilla excluida del análisis" if quita_semilla
                           else f"Valor de {variable} excluido")
            registro.append(r)

    # --- se quita la semilla completa -------------------------------------
    if op.get("cajas_vacias"):
        m = d["Corrida"].isin(cajas_vacias(d))
        anotar(m, "Caja vacía (sin ninguna longitud registrada)", True)
        d = d[~m]
    if op.get("cajas_excluidas"):
        m = d["Corrida"].isin(op["cajas_excluidas"])
        anotar(m, "Caja excluida por el usuario", True)
        d = d[~m]
    if op.get("numeros_excluidos"):
        m = d["No"].isin(op["numeros_excluidos"])
        anotar(m, "Número de semilla excluido por el usuario", True)
        d = d[~m]
    manuales = op.get("manuales") or {}
    if manuales:
        m = d["ID semilla"].isin(manuales.keys())
        anotar(m, d["ID semilla"].map(manuales).fillna("Descarte manual"), True)
        d = d[~m]

    # --- se quita solo el valor de la variable ----------------------------
    if variable in ("Raíz", "Tallo"):
        no_germ = d["Germinó"] == 0
        if op.get("no_germinadas", "excluir") == "excluir":
            anotar(no_germ & d[variable].notna(), "No germinó", False)
            d.loc[no_germ, variable] = np.nan
        else:
            d.loc[no_germ, variable] = d.loc[no_germ, variable].fillna(0)

        if op.get("ceros_germinadas"):
            m = (d["Germinó"] == 1) & (d[variable] == 0)
            anotar(m, f"Germinó pero {variable} = 0", False)
            d.loc[m, variable] = np.nan
            if variable == "Raíz":
                d["Germinó (conteo)"] = d["Germinó"].where(~m, 0)

        rango = op.get("rango")
        if rango:
            m = d[variable].notna() & ((d[variable] < rango[0]) | (d[variable] > rango[1]))
            anotar(m, f"Fuera del rango {rango[0]}–{rango[1]} mm", False)
            d.loc[m, variable] = np.nan

        if op.get("atipicos"):
            factor = op.get("factor_iqr", 1.5)
            q1 = d.groupby("Grupo")[variable].transform(lambda x: x.quantile(0.25))
            q3 = d.groupby("Grupo")[variable].transform(lambda x: x.quantile(0.75))
            iqr = q3 - q1
            m = d[variable].notna() & ((d[variable] < q1 - factor * iqr) |
                                       (d[variable] > q3 + factor * iqr))
            anotar(m, f"Atípico en su grupo (regla {factor:g}×IQR)", False)
            d.loc[m, variable] = np.nan

    reg = pd.concat(registro, ignore_index=True) if registro else pd.DataFrame(
        columns=COLUMNAS_REGISTRO + ["Motivo", "Efecto"])
    return d, reg


def tabla_correcciones(op, variable, hojas_cm, manuales, registro, df_semilla, advertencias):
    def cuenta(prefijo):
        if registro.empty:
            return 0
        return int(registro["Motivo"].astype(str).str.startswith(prefijo).sum())

    filas = []
    plantillas = [a for a in advertencias if "bloques de plantilla vacíos" in a]
    n_pl = sum(len(a.split("(todo en 0):")[-1].split(",")) for a in plantillas) if plantillas else 0
    filas.append(("Bloques de plantilla vacíos (todo en 0)", "Sí, siempre",
                  "Al leer el Excel no se toman los bloques sin usar.",
                  f"{n_pl} bloque(s)" if n_pl else "Ninguno"))
    sueltas = [a for a in advertencias if "columnas sueltas" in a]
    if sueltas:
        n_s = sum(int(re.search(r"Hay (\d+)", a).group(1)) for a in sueltas if re.search(r"Hay (\d+)", a))
        filas.append(("Columnas sueltas 'R'/'T' sin número ni 'Germinó'", "Sí, siempre",
                      "No se pueden asignar a una caja; no se incluyen.", f"{n_s} valor(es)"))
    filas.append(("Hojas medidas en cm (convertir a mm)", "Sí: " + ", ".join(hojas_cm) if hojas_cm else "No",
                  "Multiplica por 10 las longitudes de esas hojas.", "—"))
    n = cuenta("Caja vacía")
    filas.append(("Excluir cajas vacías (no realizadas)", "Sí" if op.get("cajas_vacias") else "No",
                  "Quita cajas sin ninguna longitud registrada (no cuentan en la germinación).",
                  f"{n} semilla(s)"))
    if variable in ("Raíz", "Tallo"):
        v = variable.lower()
        if op.get("no_germinadas") == "excluir":
            filas.append(("Semillas que no germinaron", "Excluidas del promedio",
                          f"No entran al promedio de {v}; sí cuentan en el % de germinación.",
                          f"{cuenta('No germinó')} semilla(s)"))
        else:
            n_ng = int((df_semilla["Germinó"] == 0).sum())
            filas.append(("Semillas que no germinaron", "Incluidas con longitud 0",
                          f"Entran al promedio de {v} con 0 mm.", f"{n_ng} semilla(s)"))
        filas.append((f"Excluir germinadas con {v} = 0", "Sí" if op.get("ceros_germinadas") else "No",
                      f"Germinadas con {v} = 0 salen del promedio"
                      + ("; en el % de germinación cuentan como no germinadas." if variable == "Raíz" else "."),
                      f"{cuenta('Germinó pero')} semilla(s)"))
        r = op.get("rango")
        filas.append(("Excluir valores fuera de un rango", f"Sí: {r[0]}–{r[1]} mm" if r else "No",
                      f"Valores de {v} fuera del rango salen del promedio.", f"{cuenta('Fuera del rango')} valor(es)"))
        filas.append(("Excluir valores atípicos de cada grupo",
                      f"Sí: regla {op.get('factor_iqr', 1.5):g} × IQR" if op.get("atipicos") else "No",
                      f"Valores de {v} fuera de Q1 − k·IQR y Q3 + k·IQR de su grupo salen del promedio.",
                      f"{cuenta('Atípico')} valor(es)"))
    n_m = len(registro) - sum(cuenta(p) for p in ("Caja vacía", "Caja excluida", "Número de semilla",
                                                   "No germinó", "Germinó pero", "Fuera del rango", "Atípico"))
    filas.append(("Semillas descartadas a mano", f"Sí: {len(manuales)}" if manuales else "No",
                  "Semillas quitadas por el usuario en la pestaña Descartes.", f"{max(n_m, 0)} semilla(s)"))
    return pd.DataFrame(filas, columns=["Corrección", "¿Aplicada?", "Qué hace", "Datos afectados"])


def revisar_calidad(df):
    """Inconsistencias en los datos crudos que conviene corregir en el Excel."""
    avisos = []
    malas = df[(df["Germinó"] == 0) & ((df["Raíz"].fillna(0) > 0) | (df["Tallo"].fillna(0) > 0))]
    for _, f in malas.iterrows():
        avisos.append(f"{f['Hoja']} · {f['Bloque']} · semilla {f['No']}: Germinó=0 pero tiene "
                      f"Raíz={f['Raíz']} / Tallo={f['Tallo']}.")
    ceros = df[(df["Germinó"] == 1) & (df["Raíz"].fillna(0) == 0) & (df["Tallo"].fillna(0) == 0)]
    for _, f in ceros.iterrows():
        avisos.append(f"{f['Hoja']} · {f['Bloque']} · semilla {f['No']}: Germinó=1 pero Raíz y "
                      "Tallo son 0. Verifica el registro.")
    # cajas con exactamente los mismos valores (posible copia)
    for hoja, sub in df.groupby("Hoja"):
        firmas = {}
        for corrida, c in sub.groupby("Corrida"):
            vals = tuple(zip(c["Raíz"].fillna(-1).round(3), c["Tallo"].fillna(-1).round(3)))
            if any(v[0] > 0 or v[1] > 0 for v in vals):
                firmas.setdefault(vals, []).append(corrida)
        for grupo in firmas.values():
            if len(grupo) > 1:
                avisos.append(f"{hoja}: las cajas {' y '.join(g.split(' | ')[1] for g in grupo)} "
                              "tienen exactamente los mismos valores (posible copia). "
                              "Puedes excluir una en la pestaña '🧹 Descartes'.")
    # hojas que parecen medidas en cm sin indicarlo
    for hoja, sub in df[df["Unidad original"] == "mm"].groupby("Hoja"):
        g = sub[sub["Germinó"] == 1]
        if len(g) > 20 and g["Raíz"].quantile(0.9) < 30 and g["Tallo"].quantile(0.9) < 30:
            avisos.append(f"{hoja}: las longitudes parecen estar en cm (90 % de las raíces "
                          f"< {g['Raíz'].quantile(0.9):.1f}) y la hoja no lo indica. Si es así, "
                          "márcala en '5 · Descartes y correcciones → Hojas medidas en cm'.")
    return avisos


def hojas_probables_cm(df):
    salida = []
    for hoja, sub in df[df["Unidad original"] == "mm"].groupby("Hoja"):
        g = sub[sub["Germinó"] == 1]
        if len(g) > 20 and g["Raíz"].quantile(0.9) < 30 and g["Tallo"].quantile(0.9) < 30:
            salida.append(hoja)
    return salida


def pruebas_requeridas(datos, variable, alfa):
    """ANOVA de una vía + Tukey + LSD + letras de ambas pruebas."""
    anova = anova_una_via(datos, variable, "Grupo", alfa)
    tk = tukey_hsd(anova) if anova else pd.DataFrame()
    ls = lsd(anova) if anova else pd.DataFrame()
    return {
        "anova": anova, "tukey": tk, "lsd": ls,
        "letras_tukey": letras_cld(anova["medias"], tk) if anova else pd.DataFrame(),
        "letras_lsd": letras_cld(anova["medias"], ls) if anova else pd.DataFrame(),
    }


def _ordenar_columnas(tabla, columnas):
    return tabla[[c for c in columnas if c in tabla.columns]]


# ---------------------------------------------------------------------------
# Utilidades de presentación
# ---------------------------------------------------------------------------

SI_DIFIEREN = "✔ Sí difieren"
NO_DIFIEREN = "✘ No difieren"


def _tabla(df, **kw):
    """st.dataframe a todo lo ancho, compatible con versiones viejas y nuevas."""
    kw.setdefault("hide_index", True)
    try:
        return st.dataframe(df, width="stretch", **kw)
    except TypeError:
        return st.dataframe(df, use_container_width=True, **kw)


_FIGURAS = {}


def _partir_linea(linea, limite):
    def visible(t):
        return len(re.sub(r"<[^>]+>", "", t))
    if visible(linea) <= limite or " · " not in linea:
        return [linea]
    lineas, actual = [], ""
    for pieza in linea.split(" · "):
        candidata = pieza if not actual else f"{actual} · {pieza}"
        if actual and visible(candidata) > limite:
            lineas.append(actual)
            actual = pieza
        else:
            actual = candidata
    lineas.append(actual)
    return lineas


def _sin_encimados(fig):
    tam = fig.layout.font.size if fig.layout.font and fig.layout.font.size else 13
    escala = max(tam / 13, 0.6)
    titulo = fig.layout.title.text
    if titulo:
        lineas = []
        for linea in titulo.split("<br>"):
            lineas += _partir_linea(linea, int(120 / escala))
        fig.update_layout(title=dict(text="<br>".join(lineas), automargin=True, yref="paper", y=1,
                                     yanchor="bottom", xref="container", x=0.01, xanchor="left",
                                     pad=dict(b=16)))
        fig.update_layout(margin=dict(t=30))
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(automargin=True)
    if fig.layout.height is None:
        fig.update_layout(height=round(500 * min(escala, 1.4)))
    return fig


def _grafica(fig, key):
    fig = _sin_encimados(fig)
    _FIGURAS[key] = fig
    try:
        return st.plotly_chart(fig, width="stretch", key=key)
    except TypeError:
        return st.plotly_chart(fig, use_container_width=True, key=key)


def _caja():
    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def _es_columna_p(nombre):
    n = str(nombre).lower()
    return n.startswith("p-valor") or n.startswith("p ajustada") or n.startswith("p sin")


def _fmt(df, dec=3):
    """Formato de tabla: 3 decimales (4 en p-valores), enteros sin decimales y
    celdas vacías en blanco en lugar de 'None'."""
    formatos = {}
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            formatos[c] = "{:.4f}" if _es_columna_p(c) else "{:.%df}" % dec
    try:
        return df.style.format(formatos, na_rep="")
    except Exception:
        return df.round(dec)


def _es_control(nombre):
    t = str(nombre).lower()
    return "control" in t or "patrón" in t or "patron" in t


def _unidades(variable):
    if variable == "Germinó":
        return "%", "%²", "Germinación"
    return "mm", "mm²", variable


def columna_germinacion(df):
    return "Germinó (conteo)" if "Germinó (conteo)" in df.columns else "Germinó"


def germinacion_por_grupo(df, columna="Grupo"):
    c = columna_germinacion(df)
    d = df.dropna(subset=[c])
    return d.groupby(columna)[c].agg(["sum", "count"])


def tabla_ranking(desc, letras_tk, letras_lsd, u, germ=None):
    t = desc[["Grupo", "n", "Media", "Desviación estándar"]].copy()
    t["Promedio ± DE"] = [f"{m:.2f} ± {s:.2f}" if pd.notna(s) else f"{m:.2f}"
                          for m, s in zip(t["Media"], t["Desviación estándar"])]
    t["Letras Tukey"] = t["Grupo"].map(dict(zip(letras_tk["Grupo"], letras_tk["Letras"]))) if not letras_tk.empty else ""
    t["Letras LSD"] = t["Grupo"].map(dict(zip(letras_lsd["Grupo"], letras_lsd["Letras"]))) if not letras_lsd.empty else ""
    t = t.sort_values("Media", ascending=False).reset_index(drop=True)
    t.insert(0, "Lugar", range(1, len(t) + 1))
    columnas = ["Lugar", "Grupo", "n", "Promedio ± DE", "Letras Tukey", "Letras LSD"]
    if germ is not None and not germ.empty:
        t["% germinación"] = [
            f"{germ.loc[g, 'sum'] / germ.loc[g, 'count'] * 100:.1f} % "
            f"({int(germ.loc[g, 'sum'])}/{int(germ.loc[g, 'count'])})"
            if g in germ.index and germ.loc[g, "count"] else "—" for g in t["Grupo"]]
        columnas.insert(4, "% germinación")
    return t[columnas].rename(columns={"Promedio ± DE": f"Promedio ± DE ({u})"})


def tabla_tukey_clara(tk, u):
    if tk.empty:
        return tk
    t = tk.copy()
    t["Conclusión"] = np.where(t["Resultado"] == SIG, SI_DIFIEREN, NO_DIFIEREN)
    t = t.rename(columns={
        "Grupo 1": "Grupo A", "Grupo 2": "Grupo B", "n1": "n A", "n2": "n B",
        "Media 1": f"Promedio A ({u})", "Media 2": f"Promedio B ({u})",
        "|Diferencia|": f"|A − B| ({u})", "DHS": f"DHS ({u})",
        "Comparación |dif| vs DHS": "|A − B| vs DHS",
        "Comparación q": "q calculada vs q crítica",
        "k (medias)": "k (grupos)", "GL error": "GL del error",
    })
    cols = ["Grupo A", "Grupo B", "Conclusión", f"|A − B| ({u})", f"DHS ({u})", "|A − B| vs DHS",
            "q calculada", "q crítica", "q calculada vs q crítica", "k (grupos)", "GL del error",
            "p ajustada", f"Promedio A ({u})", f"Promedio B ({u})", "n A", "n B"]
    return t[[c for c in cols if c in t.columns]]


def tabla_lsd_clara(ls, u):
    if ls.empty:
        return ls
    t = ls.copy()
    t["Conclusión"] = np.where(t["Resultado"] == SIG, SI_DIFIEREN, NO_DIFIEREN)
    t = t.rename(columns={
        "Grupo 1": "Grupo A", "Grupo 2": "Grupo B", "n1": "n A", "n2": "n B",
        "Media 1": f"Promedio A ({u})", "Media 2": f"Promedio B ({u})",
        "|Diferencia|": f"|A − B| ({u})", "LSD": f"LSD ({u})",
        "Comparación |dif| vs LSD": "|A − B| vs LSD",
        "Comparación t": "t calculada vs t crítica", "GL error": "GL del error",
    })
    cols = ["Grupo A", "Grupo B", "Conclusión", f"|A − B| ({u})", f"LSD ({u})", "|A − B| vs LSD",
            "t calculada", "t crítica", "t calculada vs t crítica", "GL del error", "p-valor",
            f"Promedio A ({u})", f"Promedio B ({u})", "n A", "n B"]
    return t[[c for c in cols if c in t.columns]]


def tabla_anova_clara(anova, u2):
    t = anova["tabla"].copy()
    col_fc = [c for c in t.columns if c.startswith("F crítica")][0]
    t["Conclusión"] = t["Resultado"].map({SIG: "✔ Hay diferencia", NO_SIG: "✘ No hay diferencia"}).fillna("")
    t = t.rename(columns={"Fuente": "Fuente de variación",
                          "Suma de cuadrados": f"SC ({u2})", "Cuadrado medio": f"CM ({u2})",
                          col_fc: "F crítica", "Comparación": "F calc. vs F crít."})
    t = t.drop(columns=["Resultado"])
    return t[["Fuente de variación", "GL", f"SC ({u2})", f"CM ({u2})", "F calculada",
              "F crítica", "F calc. vs F crít.", "p-valor", "Conclusión"]]


def pares_significativos(tk, u):
    """Frases tipo 'A (47.2 mm) > B (34.3 mm)' para los pares que difieren."""
    frases = []
    for _, f in tk[tk["Resultado"] == SIG].iterrows():
        a, b, ma, mb = f["Grupo 1"], f["Grupo 2"], f["Media 1"], f["Media 2"]
        if mb > ma:
            a, b, ma, mb = b, a, mb, ma
        frases.append(f"**{a}** ({ma:.2f} {u}) es mayor que **{b}** ({mb:.2f} {u})")
    return frases


def texto_reporte(variable, u, agrupacion, unidad_txt, anova, tk, alfa, desc):
    nombre = "el porcentaje de germinación" if variable == "Germinó" else f"la longitud de {variable.lower()}"
    signo = "indicó" if anova["significativo"] else "no indicó"
    txt = (f"Se compararon los promedios de {nombre} ({u}) entre grupos de "
           f"{agrupacion.lower()}, usando {anova['n total']} {unidad_txt} como réplicas. "
           f"El ANOVA de una vía {signo} diferencias significativas "
           f"(F calculada = {anova['F calculada']:.3f}, F crítica = {anova['F crítica']:.3f}; "
           f"GL = {anova['GL entre']} y {anova['GL error']}; p = {anova['p-valor']:.4f}; α = {alfa}). ")
    sig = tk[tk["Resultado"] == SIG] if not tk.empty else tk
    if anova["significativo"] and not sig.empty:
        partes = []
        for _, f in sig.iterrows():
            a, b, ma, mb = f["Grupo 1"], f["Grupo 2"], f["Media 1"], f["Media 2"]
            if mb > ma:
                a, b, ma, mb = b, a, mb, ma
            partes.append(f"{a} ({ma:.2f} {u}) fue mayor que {b} ({mb:.2f} {u})")
        txt += f"Según la prueba de Tukey (α = {alfa}), " + "; ".join(partes) + ". "
    elif anova["significativo"]:
        txt += (f"Aunque el ANOVA fue significativo, la prueba de Tukey (α = {alfa}) no "
                "separó ningún par de grupos. ")
    mejor = desc.sort_values("Media", ascending=False).iloc[0]
    txt += f"El promedio más alto fue el de {mejor['Grupo']} ({mejor['Media']:.2f} {u})."
    return txt


# ---------------------------------------------------------------------------
# Gráficas principales
# ---------------------------------------------------------------------------

def _estilo(fig, escala, titulo, eje_x, eje_y):
    base = 13 * escala
    fig.update_layout(
        title=dict(text=titulo, font=dict(size=base * 1.3)),
        font=dict(size=base),
        xaxis=dict(title=eje_x, type="category", tickangle=-25, automargin=True,
                   showgrid=False),
        yaxis=dict(title=eje_y, rangemode="tozero", gridcolor="rgba(128,128,128,0.18)",
                   zeroline=True, zerolinecolor="rgba(128,128,128,0.35)"),
        margin=dict(t=95, l=60, r=20, b=60), showlegend=False, bargap=0.35,
    )
    try:
        fig.update_layout(barcornerradius=4)
    except Exception:
        pass
    return fig


COLOR_LINEA_PATRON = "#e8a33d"


def _valor_patron(grupos, medias, referencia):
    for g, m in zip(grupos, medias):
        if _es_control(g) and pd.notna(m):
            return float(m)
    if referencia is not None and referencia.get("n", 0) > 0 and pd.notna(referencia.get("Media")):
        return float(referencia["Media"])
    return None


def _linea_patron(fig, valor, u):
    fig.add_hline(y=valor, line_dash="dash", line_color=COLOR_LINEA_PATRON, line_width=2,
                  annotation_text=f"Patrón (control): {valor:.2f} {u}",
                  annotation_position="top right",
                  annotation_font=dict(color=COLOR_LINEA_PATRON, size=12))


def grafico_barras_letras(desc, letras, variable, u, eje_x, titulo, subtitulo="",
                          dispersion="Desviación estándar", referencia=None, escala=1.0,
                          nombre_letras="Tukey"):
    """Promedio por grupo con barra de error y letras encima (presentación típica en
    agronomía). Grupos tratados en color, control en gris."""
    if desc is None or desc.empty:
        return None
    d = desc.sort_values("Media", ascending=False).reset_index(drop=True)
    if dispersion == "Error estándar (SEM)":
        arriba = abajo = d["SEM"].fillna(0); txt_disp = "error estándar"
    elif dispersion == "IC 95% de la media":
        arriba = (d["IC sup"] - d["Media"]).fillna(0); abajo = (d["Media"] - d["IC inf"]).fillna(0)
        txt_disp = "intervalo de confianza 95 %"
    else:
        arriba = abajo = d["Desviación estándar"].fillna(0); txt_disp = "desviación estándar"
    mapa = dict(zip(letras["Grupo"], letras["Letras"])) if letras is not None and not letras.empty else {}
    colores = [COLOR_CONTROL if _es_control(g) else COLOR_PRINCIPAL for g in d["Grupo"]]

    fig = go.Figure(go.Bar(
        x=d["Grupo"], y=d["Media"], marker_color=colores,
        error_y=dict(type="data", array=arriba, arrayminus=abajo, visible=True,
                     thickness=1.5, width=6, color="rgba(90,90,90,0.9)"),
        customdata=np.stack([d["n"], d["Desviación estándar"].fillna(0),
                             [mapa.get(g, "") for g in d["Grupo"]]], axis=1),
        hovertemplate=("<b>%{x}</b><br>Promedio: %{y:.2f} " + u +
                       "<br>Desviación estándar: %{customdata[1]:.2f} " + u +
                       "<br>n = %{customdata[0]}<br>Letras: %{customdata[2]}<extra></extra>"),
    ))
    tope = (d["Media"] + arriba).max()
    for g, m, a in zip(d["Grupo"], d["Media"], arriba):
        if mapa.get(g):
            fig.add_annotation(x=g, y=m + a, text=f"<b>{mapa[g]}</b>", showarrow=False,
                               yshift=14, font=dict(size=16 * escala))
    patron = _valor_patron(d["Grupo"], d["Media"], referencia) if referencia is not None else None
    if patron is not None:
        _linea_patron(fig, patron, u)
        tope = max(tope, patron)
    sub = f"Barras: promedio · líneas: ± {txt_disp}"
    if patron is not None:
        sub += " · línea naranja punteada: promedio del patrón"
    if mapa:
        sub += f" · letras: {nombre_letras} (misma letra = no difieren)"
    if subtitulo:
        sub += f"<br>{subtitulo}"
    nombre = "Germinación" if variable == "Germinó" else variable
    fig = _estilo(fig, escala, f"<b>{titulo}</b><br><sub>{sub}</sub>", eje_x,
                  f"{nombre} promedio ({u})")
    fig.update_yaxes(range=[0, tope * 1.18 if tope > 0 else 1])
    return fig


def grafico_cajas_letras(datos, variable, letras, u, eje_x, titulo, subtitulo="",
                         escala=1.0, nombre_letras="Tukey", referencia=None):
    """Distribución de los datos de cada grupo (caja = 50 % central, línea = mediana,
    punteada = promedio) con las letras encima."""
    d = datos.dropna(subset=[variable])
    if d.empty:
        return None
    orden = d.groupby("Grupo")[variable].mean().sort_values(ascending=False).index.tolist()
    mapa = dict(zip(letras["Grupo"], letras["Letras"])) if letras is not None and not letras.empty else {}
    fig = go.Figure()
    for g in orden:
        serie = d.loc[d["Grupo"] == g, variable]
        color = COLOR_CONTROL if _es_control(g) else COLOR_PRINCIPAL
        fig.add_trace(go.Box(y=serie, name=str(g), boxmean=True, marker_color=color,
                             line_color=color, fillcolor="rgba(0,0,0,0)", boxpoints="all",
                             jitter=0.35, pointpos=0, marker=dict(size=6, opacity=0.55),
                             hovertemplate=f"<b>{g}</b><br>%{{y:.2f}} {u}<extra></extra>"))
    tope = d[variable].max()
    for g in orden:
        if mapa.get(g):
            fig.add_annotation(x=str(g), y=tope, text=f"<b>{mapa[g]}</b>", showarrow=False,
                               yshift=18, font=dict(size=16 * escala))
    sub = "Caja: 50 % central · línea: mediana · punteada: promedio · puntos: cada dato"
    if referencia is not None:
        medias = d.groupby("Grupo")[variable].mean()
        patron = _valor_patron(medias.index, medias.values, referencia)
        if patron is not None:
            _linea_patron(fig, patron, u)
            tope = max(tope, patron)
            sub += " · línea naranja: promedio del patrón"
    if mapa:
        sub += f" · letras: {nombre_letras}"
    if subtitulo:
        sub += f"<br>{subtitulo}"
    nombre = "Germinación" if variable == "Germinó" else variable
    fig = _estilo(fig, escala, f"<b>{titulo}</b><br><sub>{sub}</sub>", eje_x, f"{nombre} ({u})")
    fig.update_yaxes(range=[0, tope * 1.15 if tope > 0 else 1])
    return fig


def grafico_barras_grupos_letras(desc, letras, variable, u, eje_x, titulo, subtitulo="",
                                 escala=1.0, nombre_letras="Tukey"):
    """Barras del promedio de cada grupo, coloreadas según sus letras: las barras con las
    mismas letras tienen el mismo color. El control lleva rayas."""
    if desc is None or desc.empty or letras is None or letras.empty:
        return None
    d = desc.sort_values("Media", ascending=False).reset_index(drop=True)
    mapa = dict(zip(letras["Grupo"].astype(str), letras["Letras"]))
    d["Letras"] = d["Grupo"].astype(str).map(mapa).fillna("")
    combos = list(dict.fromkeys(d["Letras"]))
    paleta = paleta_aleatoria(len(combos))
    color_combo = {c: paleta[i % len(paleta)] for i, c in enumerate(combos)}
    de = d["Desviación estándar"].fillna(0)
    etiquetas = {g: f"<b>{g}</b><br>{m:.1f} {u}" for g, m in zip(d["Grupo"], d["Media"])}
    fig = go.Figure()
    for combo in combos:
        sub = d[d["Letras"] == combo]
        fig.add_trace(go.Bar(
            x=[etiquetas[g] for g in sub["Grupo"]], y=sub["Media"],
            name=f"Letras «{combo}»", marker_color=color_combo[combo],
            marker_pattern_shape=["/" if _es_control(g) else "" for g in sub["Grupo"]],
            marker_line=dict(color=color_combo[combo], width=1.5),
            error_y=dict(type="data", array=de[sub.index].values, visible=True, thickness=1.4,
                         width=6, color="rgba(150,150,150,0.95)"),
            customdata=np.stack([sub["n"], de[sub.index], sub["Letras"]], axis=1),
            hovertemplate=("<b>%{x}</b><br>Promedio: %{y:.2f} " + u + "<br>DE: %{customdata[1]:.2f} "
                           + u + "<br>n = %{customdata[0]}<br>Letras: %{customdata[2]}<extra></extra>")))
    tope = float((d["Media"] + de).max())
    for g, m, e, combo in zip(d["Grupo"], d["Media"], de, d["Letras"]):
        fig.add_annotation(x=etiquetas[g], y=m + e, yshift=16, showarrow=False, text=f"<b>{combo}</b>",
                           font=dict(size=20 * escala, color=color_combo[combo]))
    sub_txt = (f"Barra: promedio · línea: ± desviación estándar · letras de {nombre_letras} encima · "
               "mismo color = mismas letras · grupos que comparten alguna letra NO difieren")
    if any(_es_control(g) for g in d["Grupo"]):
        sub_txt += " · barra con rayas: control"
    if subtitulo:
        sub_txt += f"<br>{subtitulo}"
    nombre = "Germinación" if variable == "Germinó" else variable
    fig.update_layout(
        title=f"<b>{titulo}</b><br><sub>{sub_txt}</sub>",
        barmode="overlay", bargap=0.3,
        xaxis=dict(title=eje_x, type="category", categoryorder="array",
                   categoryarray=[etiquetas[g] for g in d["Grupo"]], tickangle=0, automargin=True),
        yaxis=dict(title=f"{nombre} promedio ({u})", range=[0, tope * 1.2 if tope > 0 else 1],
                   gridcolor="rgba(128,128,128,0.18)"),
        legend=dict(title=f"Grupos de {nombre_letras}"), height=520,
    )
    return aplicar_tipografia(fig, escala)


def tabla_letras_grupos(letras):
    """Para cada letra, qué grupos la llevan (esos grupos no difieren entre sí)."""
    if letras is None or letras.empty:
        return pd.DataFrame()
    ordenado = letras.sort_values("Media", ascending=False)
    todas = sorted({c for l in ordenado["Letras"] for c in str(l)})
    filas = []
    for c in todas:
        grupos = [str(g) for g, l in zip(ordenado["Grupo"], ordenado["Letras"]) if c in str(l)]
        filas.append({"Letra": c, "Grupos que la llevan (no difieren entre sí)": " · ".join(grupos),
                      "Cuántos": len(grupos)})
    return pd.DataFrame(filas)


def grafico_pares_cluster(tabla_pares, letras, u, titulo, subtitulo="", escala=1.0,
                          nombre_prueba="Tukey", col_margen="DHS"):
    """Gráfica tipo 'cluster' (forest plot) de las diferencias por pares: una línea
    horizontal por comparación con su intervalo de confianza simultáneo. Si la línea
    no cruza el cero, los dos grupos de ese par difieren significativamente."""
    if tabla_pares is None or tabla_pares.empty:
        return None

    mapa_letras = (dict(zip(letras["Grupo"], letras["Letras"]))
                  if letras is not None and not letras.empty else {})

    filas = []
    for _, f in tabla_pares.iterrows():
        diferencia = f["Media 1"] - f["Media 2"]
        margen = f[col_margen]
        la = mapa_letras.get(f["Grupo 1"], "")
        lb = mapa_letras.get(f["Grupo 2"], "")
        etiqueta = (f["Grupo 1"] + (f" ({la})" if la else "") + "  −  " +
                    f["Grupo 2"] + (f" ({lb})" if lb else ""))
        filas.append({
            "Par": etiqueta, "Diferencia": diferencia, "Margen": margen,
            "Inferior": diferencia - margen, "Superior": diferencia + margen,
            "Significativo": f["Resultado"] == SIG, "p": f.get("p ajustada", f.get("p-valor")),
        })
    d = pd.DataFrame(filas).sort_values("Diferencia").reset_index(drop=True)

    colores = ["#e34948" if s else "#8a8984" for s in d["Significativo"]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=d["Diferencia"], y=d["Par"], mode="markers",
        marker=dict(size=12, color=colores, line=dict(color="#333", width=1), symbol="diamond"),
        error_x=dict(type="data", symmetric=False,
                     array=(d["Superior"] - d["Diferencia"]).values,
                     arrayminus=(d["Diferencia"] - d["Inferior"]).values,
                     thickness=2.2, width=6, color="rgba(140,140,140,0.95)"),
        customdata=np.stack([d["Inferior"], d["Superior"], d["p"].fillna(np.nan),
                             np.where(d["Significativo"], "Sí difieren", "No difieren")], axis=1),
        hovertemplate=("<b>%{y}</b><br>Diferencia de promedios: %{x:.3f} " + u +
                       "<br>IC simultáneo: [%{customdata[0]:.3f}, %{customdata[1]:.3f}] " + u +
                       "<br>%{customdata[3]} (p = %{customdata[2]:.4g})<extra></extra>"),
        showlegend=False,
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="#9a9a9a", line_width=1.5)
    sub = (f"Cada línea: diferencia de promedios A − B ± margen de {nombre_prueba} (IC simultáneo)"
           "<br><span style='color:#e34948'>◆ rojo</span>: sí difieren (la línea no cruza el 0) · "
           "◆ gris: no difieren (la línea cruza el 0)")
    if mapa_letras:
        sub += " · entre paréntesis: letra de cada grupo"
    if subtitulo:
        sub += f"<br>{subtitulo}"

    fig.update_layout(
        title=f"<b>{titulo}</b><br><sub>{sub}</sub>",
        xaxis_title=f"Diferencia de promedios, A − B ({u})",
        yaxis_title="Par de grupos comparado",
        xaxis=dict(zeroline=False, gridcolor="rgba(128,128,128,0.18)"),
        yaxis=dict(type="category", automargin=True),
        showlegend=False,
        margin=dict(t=40, l=160, b=60),
    )
    altura = max(400, 170 + 34 * len(d))
    fig.update_layout(height=altura)
    return aplicar_tipografia(fig, escala)


def _forma_bowley(b, n):
    if n < 4 or pd.isna(b):
        return "Pocos datos (n < 4)"
    if abs(b) < 0.1:
        return "Simétrica"
    grado = "ligeramente" if abs(b) < 0.3 else "muy"
    lado = "hacia valores altos" if b > 0 else "hacia valores bajos"
    return f"{grado.capitalize()} sesgada {lado}"


def tabla_cuartiles(datos, variable, factor=1.5):
    filas = []
    for g, sub in datos.groupby("Grupo"):
        x = pd.to_numeric(sub[variable], errors="coerce").dropna().astype(float)
        n = len(x)
        if n == 0:
            continue
        q1, med, q3 = x.quantile([0.25, 0.5, 0.75]).tolist()
        iqr = q3 - q1
        lim_inf, lim_sup = q1 - factor * iqr, q3 + factor * iqr
        dentro = x[(x >= lim_inf) & (x <= lim_sup)]
        bowley = (q3 + q1 - 2 * med) / iqr if iqr > 0 else np.nan
        filas.append({
            "Grupo": str(g), "n": n, "Mínimo": x.min(), "Q1 (25 %)": q1, "Mediana (Q2)": med,
            "Q3 (75 %)": q3, "Máximo": x.max(), "IQR (Q3 − Q1)": iqr,
            "Límite inferior": lim_inf, "Límite superior": lim_sup,
            "Atípicos bajos": int((x < lim_inf).sum()), "Atípicos altos": int((x > lim_sup).sum()),
            "Promedio": x.mean(), "Asimetría de Bowley": bowley,
            "Forma de la distribución": _forma_bowley(bowley, n),
            "_bigote_inf": dentro.min() if len(dentro) else q1,
            "_bigote_sup": dentro.max() if len(dentro) else q3,
        })
    t = pd.DataFrame(filas)
    if t.empty:
        return t
    return t.sort_values("Mediana (Q2)", ascending=False).reset_index(drop=True)


def diagnostico_cuartiles(tc, factor=1.5):
    validos = tc[(tc["n"] >= 4) & (tc["IQR (Q3 − Q1)"] > 0)]
    salida = {"razon_iqr": np.nan, "iqr_max": None, "iqr_min": None,
              "sesgados": [], "atipicos": int(tc["Atípicos bajos"].sum() + tc["Atípicos altos"].sum()),
              "grupos_validos": len(validos)}
    if len(validos) >= 2:
        mx = validos.loc[validos["IQR (Q3 − Q1)"].idxmax()]
        mn = validos.loc[validos["IQR (Q3 − Q1)"].idxmin()]
        salida.update(razon_iqr=mx["IQR (Q3 − Q1)"] / mn["IQR (Q3 − Q1)"],
                      iqr_max=(mx["Grupo"], mx["IQR (Q3 − Q1)"]),
                      iqr_min=(mn["Grupo"], mn["IQR (Q3 − Q1)"]))
    salida["sesgados"] = validos.loc[validos["Asimetría de Bowley"].abs() >= 0.3, "Grupo"].tolist()
    return salida


def pasos_cuartil(valores, p):
    x = np.sort(np.asarray(valores, dtype=float))
    n = len(x)
    pos = 1 + (n - 1) * p
    baja = int(math.floor(pos))
    frac = pos - baja
    v_baja = x[baja - 1]
    v_alta = x[min(baja, n - 1)]
    return pos, baja, frac, v_baja, v_alta, v_baja + frac * (v_alta - v_baja)


def grafico_cuartiles(tc, datos, variable, u, eje_x, titulo, subtitulo="", escala=1.0, factor=1.5):
    if tc is None or tc.empty:
        return None
    colores = paleta_aleatoria(len(tc))
    fig = go.Figure()
    for i, f in tc.iterrows():
        g = f["Grupo"]
        color = colores[i % len(colores)]
        fig.add_trace(go.Box(
            x=[g], q1=[f["Q1 (25 %)"]], median=[f["Mediana (Q2)"]], q3=[f["Q3 (75 %)"]],
            lowerfence=[f["_bigote_inf"]], upperfence=[f["_bigote_sup"]], mean=[f["Promedio"]],
            name=g, marker_color=color, line=dict(color=color, width=2), boxmean=True,
            boxpoints=False, width=0.55, showlegend=False,
            hovertemplate=(f"<b>{g}</b> (n = {f['n']})<br>"
                           f"Q3: {f['Q3 (75 %)']:.2f} {u}<br>Mediana: {f['Mediana (Q2)']:.2f} {u}<br>"
                           f"Q1: {f['Q1 (25 %)']:.2f} {u}<br>IQR: {f['IQR (Q3 − Q1)']:.2f} {u}<br>"
                           f"Promedio: {f['Promedio']:.2f} {u}<extra></extra>"),
        ))
        x = pd.to_numeric(datos.loc[datos["Grupo"].astype(str) == g, variable], errors="coerce").dropna()
        fuera = x[(x < f["Límite inferior"]) | (x > f["Límite superior"])]
        if len(fuera):
            fig.add_trace(go.Scatter(
                x=[g] * len(fuera), y=fuera, mode="markers", showlegend=False,
                marker=dict(color="#e34948", size=8, symbol="x", opacity=0.75),
                hovertemplate=f"<b>{g}</b><br>Atípico: %{{y:.2f}} {u}<extra></extra>",
            ))
    sub = (f"Caja: de Q1 a Q3 (50 % central) · línea: mediana · punteada: promedio · "
           f"bigotes: último dato dentro de Q1 − {factor:g}·IQR y Q3 + {factor:g}·IQR · ✕ rojo: atípico")
    if subtitulo:
        sub += f"<br>{subtitulo}"
    nombre = "Germinación" if variable == "Germinó" else variable
    fig = _estilo(fig, escala, f"<b>{titulo}</b><br><sub>{sub}</sub>", eje_x, f"{nombre} ({u})")
    fig.update_layout(margin=dict(t=120))
    return fig


def _rgba(hex_color, alfa):
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alfa})"


def grafico_dispersion_grupos(datos, variable, u, eje_x, titulo, subtitulo="", escala=1.0,
                              unidad_txt="cajas"):
    """Cada dato de cada grupo alrededor de su promedio: la franja es ± 1 DE y la línea
    punteada de cada punto a su promedio es la desviación que entra en la varianza."""
    d = datos.dropna(subset=[variable]).copy()
    if d.empty:
        return None
    resumen = (d.groupby("Grupo")[variable].agg(["mean", "std", "var", "count"])
               .sort_values("mean", ascending=False))
    grupos = resumen.index.tolist()
    colores = paleta_aleatoria(len(grupos))
    fig = go.Figure()
    for i, g in enumerate(grupos):
        color = COLOR_CONTROL if _es_control(g) else colores[i % len(colores)]
        media, de = resumen.loc[g, "mean"], resumen.loc[g, "std"]
        de = 0.0 if pd.isna(de) else de
        var = resumen.loc[g, "var"]
        n = int(resumen.loc[g, "count"])
        fig.add_shape(type="rect", x0=i - 0.32, x1=i + 0.32, y0=media - de, y1=media + de,
                      fillcolor=_rgba(color, 0.16), line=dict(width=0), layer="below")
        fig.add_shape(type="line", x0=i - 0.36, x1=i + 0.36, y0=media, y1=media,
                      line=dict(color=color, width=3))
        sub = d[d["Grupo"] == g].sort_values(variable)
        m = len(sub)
        xs = [i + (-0.22 + 0.44 * j / (m - 1) if m > 1 else 0) for j in range(m)]
        if m <= 40:
            lx, ly = [], []
            for x, y in zip(xs, sub[variable]):
                lx += [x, x, None]
                ly += [media, y, None]
            fig.add_trace(go.Scatter(x=lx, y=ly, mode="lines", hoverinfo="skip", showlegend=False,
                                     line=dict(color=color, width=1, dash="dot")))
        etiquetas = (sub["Corrida"].astype(str).str.replace(r" \| rep ", " r", regex=True)
                     if "Corrida" in sub else pd.Series([""] * m))
        desv = sub[variable] - media
        fig.add_trace(go.Scatter(
            x=xs, y=sub[variable], mode="markers", name=str(g), showlegend=False,
            marker=dict(size=10 if m <= 40 else 5, color=color, opacity=1 if m <= 40 else 0.5,
                        line=dict(color="white", width=1 if m <= 40 else 0)),
            customdata=np.stack([etiquetas, desv, desv ** 2], axis=1),
            hovertemplate=(f"<b>{g}</b><br>%{{customdata[0]}}<br>Valor: %{{y:.2f}} {u}"
                           f"<br>Desviación (x − promedio): %{{customdata[1]:.2f}} {u}"
                           f"<br>Desviación²: %{{customdata[2]:.2f}}<extra></extra>")))
        fig.add_trace(go.Scatter(
            x=[i], y=[media], mode="markers", showlegend=False,
            marker=dict(size=1, color=color, opacity=0),
            hovertemplate=(f"<b>{g}</b><br>n = {n} {unidad_txt}<br>Promedio: {media:.2f} {u}"
                           f"<br>DE: {de:.2f} {u}<br>Varianza: {0 if pd.isna(var) else var:.2f}"
                           "<extra></extra>")))
    sub_txt = ("Puntos: cada dato · línea gruesa: promedio · franja: ± 1 desviación estándar · "
               "punteadas: distancia de cada dato a su promedio (lo que se eleva al cuadrado en la varianza)")
    if d.groupby("Grupo").size().max() > 40:
        sub_txt += " · en grupos con más de 40 datos no se dibujan las punteadas"
    if subtitulo:
        sub_txt += f"<br>{subtitulo}"
    nombre = "Germinación" if variable == "Germinó" else variable
    fig.update_layout(
        title=f"<b>{titulo}</b><br><sub>{sub_txt}</sub>",
        xaxis=dict(title=eje_x, tickmode="array", tickvals=list(range(len(grupos))),
                   ticktext=[f"{g}<br><span style='font-size:0.85em'>DE {0 if pd.isna(resumen.loc[g, 'std']) else resumen.loc[g, 'std']:.1f} · n {int(resumen.loc[g, 'count'])}</span>"
                             for g in grupos], tickangle=0, range=[-0.6, len(grupos) - 0.4],
                   showgrid=False, zeroline=False),
        yaxis=dict(title=f"{nombre} ({u})", gridcolor="rgba(128,128,128,0.18)", zeroline=False),
        showlegend=False, height=520,
    )
    return aplicar_tipografia(fig, escala)


def grafico_intervalos_lsd(anova, letras, u, eje_x, titulo, subtitulo="", escala=1.0, alfa=0.05):
    """Promedio de cada grupo con su intervalo de comparación LSD (± LSD/2). Si los
    intervalos de dos grupos no se tocan, la prueba LSD dice que sus promedios difieren."""
    if anova is None:
        return None
    med = anova["medias"].sort_values("Media", ascending=False).reset_index(drop=True)
    t_crit = stats.t.ppf(1 - alfa / 2, anova["GL error"])
    med["semi"] = t_crit * np.sqrt(anova["CM error"] / (2 * med["n"]))
    mapa = dict(zip(letras["Grupo"], letras["Letras"])) if letras is not None and not letras.empty else {}
    letras_unicas = sorted({c for l in mapa.values() for c in l})
    paleta = paleta_aleatoria(max(len(letras_unicas), 1))
    color_letra = {c: paleta[i % len(paleta)] for i, c in enumerate(letras_unicas)}
    fig = go.Figure()
    for _, f in med.iterrows():
        g = f["Grupo"]
        let = mapa.get(g, "")
        color = COLOR_CONTROL if _es_control(g) else color_letra.get(let[:1], COLOR_PRINCIPAL)
        fig.add_trace(go.Scatter(
            x=[f["Media"]], y=[g], mode="markers+text", showlegend=False,
            marker=dict(size=14, color=color, symbol="circle", line=dict(color="white", width=1.5)),
            error_x=dict(type="data", array=[f["semi"]], thickness=6, width=0,
                         color=_rgba(color, 0.55)),
            text=[f"  {let}"], textposition="middle right", textfont=dict(size=15, color=color),
            hovertemplate=(f"<b>{g}</b><br>Promedio: {f['Media']:.2f} {u}<br>n = {int(f['n'])}"
                           f"<br>Intervalo LSD: {f['Media'] - f['semi']:.2f} a {f['Media'] + f['semi']:.2f} {u}"
                           f"<br>Letras: {let}<extra></extra>")))
    iguales = med["n"].nunique() == 1
    sub = ("Barra: promedio ± LSD/2 · si las barras de dos grupos no se tocan, sus promedios difieren · "
           "mismo color y letra = no difieren")
    if not iguales:
        sub += " · con n distintos la regla es aproximada; la tabla de arriba es la exacta"
    if subtitulo:
        sub += f"<br>{subtitulo}"
    fig.update_layout(
        title=f"<b>{titulo}</b><br><sub>{sub}</sub>",
        xaxis=dict(title=f"Promedio ({u})", gridcolor="rgba(128,128,128,0.18)", zeroline=False),
        yaxis=dict(title=eje_x, autorange="reversed", automargin=True),
        height=max(360, 140 + 52 * len(med)),
    )
    return aplicar_tipografia(fig, escala)


def grafico_barras_pares(tabla_pares, u, titulo, subtitulo="", escala=1.0,
                         nombre_prueba="LSD", col_margen="LSD"):
    """Una barra por par de grupos: su largo es la diferencia entre sus promedios y la
    marca negra es la LSD del par. Si la barra pasa la marca, los grupos difieren."""
    if tabla_pares is None or tabla_pares.empty:
        return None
    filas = []
    for _, f in tabla_pares.iterrows():
        a, b, ma, mb = f["Grupo 1"], f["Grupo 2"], f["Media 1"], f["Media 2"]
        if mb > ma:
            a, b, ma, mb = b, a, mb, ma
        filas.append({"Par": f"{a}  >  {b}", "Dif": ma - mb, "Margen": f[col_margen],
                      "Sig": f["Resultado"] == SIG,
                      "p": f.get("p-valor", f.get("p ajustada", np.nan))})
    d = pd.DataFrame(filas).sort_values("Dif", ascending=True).reset_index(drop=True)
    verde, gris = "#1baf7a", "#8a8984"
    colores = [verde if sg else gris for sg in d["Sig"]]
    textos = [f"{x:.1f} {u}  {'> ' if sg else '≤ '}{m:.1f}  →  {'sí difieren' if sg else 'no difieren'}"
              for x, m, sg in zip(d["Dif"], d["Margen"], d["Sig"])]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=d["Dif"], y=d["Par"], orientation="h", marker_color=colores, showlegend=False,
        customdata=np.stack([d["Margen"], d["p"]], axis=1),
        hovertemplate=(f"<b>%{{y}}</b><br>Diferencia: %{{x:.2f}} {u}<br>{nombre_prueba} del par: "
                       f"%{{customdata[0]:.2f}} {u}<br>p = %{{customdata[1]:.4f}}<extra></extra>")))
    for ancho, color in ((6, "#222222"), (2.5, "#f2f2f2")):
        fig.add_trace(go.Scatter(
            x=d["Margen"], y=d["Par"], mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(symbol="line-ns", size=26, line=dict(width=ancho, color=color))))
    tope = float(max(d["Dif"].max(), d["Margen"].max()))
    fig.add_trace(go.Scatter(
        x=np.maximum(d["Dif"], d["Margen"]) + tope * 0.03, y=d["Par"], mode="text", text=textos,
        textposition="middle right", showlegend=False, hoverinfo="skip", cliponaxis=False,
        textfont=dict(color=[verde if sg else "#b4b2a9" for sg in d["Sig"]])))
    sub = (f"Barra: cuánto más mide el primer grupo que el segundo ({u}) · marca blanca y negra: la "
           f"{nombre_prueba}, la diferencia mínima para que cuente · si la barra pasa la marca "
           "(verde), los grupos sí difieren; si no la alcanza (gris), no difieren")
    if subtitulo:
        sub += f"<br>{subtitulo}"
    fig.update_layout(
        title=f"<b>{titulo}</b><br><sub>{sub}</sub>",
        xaxis=dict(title=f"Diferencia entre promedios ({u})", range=[0, tope * 1.8],
                   gridcolor="rgba(128,128,128,0.18)", zeroline=False),
        yaxis=dict(title="", automargin=True),
        height=max(320, 150 + 38 * len(d)), bargap=0.35,
    )
    return aplicar_tipografia(fig, escala)


def correlacion_raiz_tallo(df, columna_grupo, semilla_color=0, subtitulo_filtros="",
                           escala_fuente=1.0, etiqueta_eje=None):
    """Dispersión semilla por semilla de Raíz vs Tallo, coloreada por grupo, para ver
    si una semilla que crece más de raíz también crece más de tallo."""
    datos = df.dropna(subset=["Raíz", "Tallo"]).copy()
    if datos.empty:
        return None
    datos[columna_grupo] = datos[columna_grupo].astype(str)
    colores = paleta_aleatoria(max(datos[columna_grupo].nunique(), 3), semilla_color)

    fig = px.scatter(
        datos, x="Raíz", y="Tallo", color=columna_grupo,
        color_discrete_sequence=colores, opacity=0.5,
        hover_data={c: True for c in ["Hoja", "Corrida", "No"] if c in datos.columns},
        trendline="ols" if HAY_STATSMODELS else None,
        title=("Correlación entre longitud de raíz y de tallo, por semilla" +
              (f"<br><sub>{subtitulo_filtros}</sub>" if subtitulo_filtros else "")),
    )
    fig.update_traces(marker=dict(size=5), selector=dict(mode="markers"))
    fig.update_traces(line=dict(width=3), opacity=1, selector=dict(mode="lines"))
    fig.update_traces(line=dict(width=2), selector=dict(mode="lines"))
    fig.update_layout(
        xaxis_title="Raíz (mm)", yaxis_title="Tallo (mm)",
        legend_title=etiqueta_eje or columna_grupo, margin=dict(t=90),
    )
    return aplicar_tipografia(fig, escala_fuente)


def bloque_explicacion(que_responde, como_leer):
    with _caja():
        c1, c2 = st.columns(2)
        c1.markdown(f"**¿Qué responde?**\n\n{que_responde}")
        c2.markdown(f"**¿Cómo se lee?**\n\n{como_leer}")


# ---------------------------------------------------------------------------
# Exportación: reporte y gráficas (se dibujan en el navegador)
# ---------------------------------------------------------------------------

NOMBRES_FIGURAS = {
    "res_graf": "Promedio por grupo con letras",
    "desc_dispersion": "Datos de cada grupo alrededor de su promedio",
    "anova_cuartiles": "Cuartiles por grupo",
    "tk_cluster": "Tukey: diferencias entre pares",
    "tk_barras": "Tukey: promedio de cada grupo con sus letras",
    "lsd_intervalos": "LSD: intervalos de comparación",
    "lsd_pares": "LSD: qué pares difieren",
    "mas_raiz_tallo": "Raíz y tallo por grupo",
    "mas_germinacion": "Germinaron vs no germinaron",
    "mas_correlacion": "Correlación entre raíz y tallo",
    "mas_corridas": "Comparación entre cajas",
}

_TOKEN_MARKDOWN = re.compile(r"\*\*(.+?)\*\*")


def _nombre_figura(clave, fig):
    if clave in NOMBRES_FIGURAS:
        return NOMBRES_FIGURAS[clave]
    texto = str(fig.layout.title.text or clave).split("<br>")[0]
    return re.sub(r"<[^>]+>", "", texto).strip() or clave


def _archivo_seguro(texto):
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()[:60] or "grafica"


def _esc(texto):
    t = str(texto).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _TOKEN_MARKDOWN.sub(r"<b>\1</b>", t)


def _celda_txt(columna, valor, dec=3):
    if valor is None or (isinstance(valor, (float, np.floating)) and np.isnan(valor)):
        return ""
    if isinstance(valor, (bool, np.bool_)):
        return "Sí" if valor else "No"
    if isinstance(valor, (int, np.integer)):
        return str(int(valor))
    if isinstance(valor, (float, np.floating)):
        return f"{valor:.4f}" if _es_columna_p(columna) else f"{valor:.{dec}f}"
    return str(valor)


def _tabla_html(df):
    cab = "".join(f"<th>{_esc(c)}</th>" for c in df.columns)
    filas = "".join("<tr>" + "".join(f"<td>{_esc(_celda_txt(c, v))}</td>" for c, v in zip(df.columns, fila))
                    + "</tr>" for fila in df.itertuples(index=False))
    return f"<table><thead><tr>{cab}</tr></thead><tbody>{filas}</tbody></table>"


def _fig_para_exportar(fig, ancho=1200):
    f = go.Figure(fig)
    f.update_layout(template="plotly_white", paper_bgcolor="white", plot_bgcolor="white")
    alto = int(fig.layout.height or 560)
    return {"fig": json.loads(f.to_json()), "w": ancho, "h": alto}


CSS_DESCARGAS = """
*{box-sizing:border-box}
body{font-family:Arial,Helvetica,sans-serif;margin:0;background:#fff;color:#222;font-size:14px}
.barra{position:sticky;top:0;z-index:5;background:#f3f5f9;border-bottom:1px solid #d8dde6;
  padding:10px 14px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.barra button,.una button{border:1px solid #2a78d6;background:#2a78d6;color:#fff;border-radius:6px;
  padding:7px 12px;font-size:13px;cursor:pointer}
.barra button.sec,.una button{background:#fff;color:#2a78d6}
.barra button:disabled{opacity:.5;cursor:wait}
.estado{font-size:13px;color:#555;margin-left:6px}
.ayuda{background:#fff8e6;border:1px solid #f0d58c;border-radius:6px;padding:8px 12px;margin:12px 18px;font-size:13px}
.vista{padding:6px 22px 30px}
h1{font-size:22px;color:#1f4e8c;margin:14px 0 2px}
.sub{color:#666;font-size:12.5px;margin:0 0 12px}
h2{font-size:16px;color:#1f4e8c;margin:20px 0 6px;border-bottom:1px solid #dfe5ee;padding-bottom:3px}
h3{font-size:14px;margin:10px 0 6px}
p{margin:4px 0 6px;line-height:1.45}
.nota{color:#666;font-size:12px}
ul{margin:4px 0 8px 18px;padding:0}
table{border-collapse:collapse;width:100%;font-size:12px;margin:6px 0 10px}
th{background:#2a78d6;color:#fff;padding:4px 6px;text-align:left;font-weight:600}
td{border:1px solid #d7dce5;padding:3px 6px}
tr:nth-child(even) td{background:#f3f6fb}
table.kv td:first-child{font-weight:600;width:30%}
figure{margin:10px 0 14px;page-break-inside:avoid;break-inside:avoid}
figure img{width:100%;border:1px solid #e3e7ee}
figcaption{font-weight:600;font-size:13px;margin-bottom:4px}
.pagina{margin:18px 0 26px}
.pagina img{width:100%;border:1px solid #e3e7ee}
.una{display:flex;gap:6px;margin-top:6px}
.oculto{display:none}
@media print{
  .barra,.ayuda,.una{display:none !important}
  body.modo-reporte #graficas{display:none}
  body.modo-graficas #reporte{display:none}
  .pagina{page-break-after:always;break-after:page;margin:0}
  .pagina:last-child{page-break-after:auto;break-after:auto}
  figure img,.pagina img{border:none}
}
@page{size:letter;margin:12mm}
"""

JS_DESCARGAS = """
const IMGS = {};
const estado = document.getElementById('estado');
const botones = () => document.querySelectorAll('.barra button, .una button');
function bloquear(si){ botones().forEach(b => b.disabled = si); }
async function imagen(i, fmt){
  const f = FIGS[i];
  if (fmt === 'png' && IMGS[i]) return IMGS[i];
  return Plotly.toImage(f.fig, {format: fmt, width: f.w, height: f.h, scale: 2});
}
function bajar(url, nombre){
  const a = document.createElement('a'); a.href = url; a.download = nombre;
  document.body.appendChild(a); a.click(); a.remove();
}
const espera = ms => new Promise(r => setTimeout(r, ms));
async function una(i, fmt){
  const url = await imagen(i, fmt);
  bajar(url, String(i + 1).padStart(2, '0') + '_' + FIGS[i].archivo + (fmt === 'jpeg' ? '.jpg' : '.png'));
}
async function todas(fmt){
  bloquear(true);
  for (let i = 0; i < FIGS.length; i++){
    estado.textContent = 'Descargando ' + (i + 1) + ' de ' + FIGS.length + '…';
    await una(i, fmt); await espera(450);
  }
  estado.textContent = 'Listo: ' + FIGS.length + ' imágenes descargadas.';
  bloquear(false);
}
function imprimir(modo){
  document.body.className = 'modo-' + modo;
  estado.textContent = 'En la ventana que se abre, elige “Guardar como PDF” en Destino.';
  setTimeout(() => window.print(), 150);
}
async function preparar(){
  if (typeof Plotly === 'undefined'){ estado.textContent = 'No se pudo cargar el dibujador de gráficas.'; return; }
  bloquear(true);
  for (let i = 0; i < FIGS.length; i++){
    estado.textContent = 'Preparando gráfica ' + (i + 1) + ' de ' + FIGS.length + '…';
    try {
      IMGS[i] = await imagen(i, 'png');
      document.querySelectorAll('[data-img="' + i + '"]').forEach(im => im.src = IMGS[i]);
    } catch (e) { console.log(e); }
  }
  estado.textContent = 'Listo. Elige qué descargar.';
  bloquear(false);
}
preparar();
"""


def html_descargas(titulo, subtitulo, secciones, figuras, con_barra=True):
    """Página autocontenida que dibuja las gráficas en el navegador (plotly.js local, sin
    internet ni programas extra) y permite descargarlas en PNG/JPG o guardar en PDF."""
    import plotly.offline as po
    indice = {id(f): i for i, (_, f) in enumerate(figuras)}
    datos = []
    for nombre, f in figuras:
        d = _fig_para_exportar(f)
        d.update(nombre=nombre, archivo=_archivo_seguro(nombre))
        datos.append(d)

    partes = [f"<h1>{_esc(titulo)}</h1><p class='sub'>{_esc(subtitulo)}</p>"]
    for nombre_sec, bloques in secciones:
        partes.append(f"<h2>{_esc(nombre_sec)}</h2>")
        for b in bloques:
            tipo = b[0]
            if tipo == "p":
                partes.append(f"<p>{_esc(b[1])}</p>")
            elif tipo == "nota":
                partes.append(f"<p class='nota'>{_esc(b[1])}</p>")
            elif tipo == "lista":
                partes.append("<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in b[1]) + "</ul>")
            elif tipo == "kv":
                partes.append("<table class='kv'><tbody>" + "".join(
                    f"<tr><td>{_esc(k)}</td><td>{_esc(v)}</td></tr>" for k, v in b[1]) + "</tbody></table>")
            elif tipo == "tabla" and b[1] is not None and not b[1].empty:
                partes.append(_tabla_html(b[1]))
            elif tipo == "fig":
                i = indice.get(id(b[2]))
                if i is None:
                    d = _fig_para_exportar(b[2]); d.update(nombre=b[1], archivo=_archivo_seguro(b[1]))
                    datos.append(d); i = len(datos) - 1
                partes.append(f"<figure><figcaption>{_esc(b[1])}</figcaption><img data-img='{i}' alt=''></figure>")
    reporte = "".join(partes)

    graf = [f"<h1>{_esc(titulo.replace('Reporte', 'Gráficas'))}</h1><p class='sub'>{_esc(subtitulo)}</p>"]
    for i, d in enumerate(datos[:len(figuras)]):
        graf.append(f"<div class='pagina'><h3>{i + 1}. {_esc(d['nombre'])}</h3><img data-img='{i}' alt=''>"
                    f"<div class='una'><button onclick=\"una({i},'png')\">PNG</button>"
                    f"<button onclick=\"una({i},'jpeg')\">JPG</button></div></div>")
    graficas = "".join(graf)

    barra = ""
    if con_barra:
        barra = ("<div class='barra'>"
                 "<button onclick=\"imprimir('reporte')\">📄 Reporte en PDF</button>"
                 "<button onclick=\"imprimir('graficas')\">🖼️ Gráficas en PDF</button>"
                 "<button class='sec' onclick=\"todas('png')\">Todas las gráficas en PNG</button>"
                 "<button class='sec' onclick=\"todas('jpeg')\">Todas las gráficas en JPG</button>"
                 "<span class='estado' id='estado'>Cargando…</span></div>"
                 "<div class='ayuda'><b>PDF:</b> se abre la ventana de impresión; en <b>Destino</b> "
                 "elige <b>Guardar como PDF</b> y pulsa <b>Guardar</b>. <b>PNG/JPG:</b> se descargan "
                 "directo a tu carpeta de Descargas (si el navegador pregunta por varias descargas, "
                 "permítelas). Cada gráfica también tiene sus propios botones abajo.</div>")
    figs_js = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            f"<title>{_esc(titulo)}</title><style>{CSS_DESCARGAS}</style></head><body class='modo-reporte'>"
            f"{barra}<div class='vista'><section id='reporte'>{reporte}</section>"
            f"<section id='graficas'><hr>{graficas}</section></div>"
            f"<script>{po.get_plotlyjs()}</script>"
            f"<script>const FIGS = {figs_js};</script><script>{JS_DESCARGAS}</script></body></html>")


def mostrar_html(html, alto=900):
    if hasattr(st, "iframe"):
        try:
            return st.iframe(html, height=alto)
        except TypeError:
            pass
    import streamlit.components.v1 as components
    return components.html(html, height=alto, scrolling=True)


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Dashboard de semillas · BioGrow", page_icon="🌱", layout="wide")
    _bloquear_traduccion_automatica()
    _FIGURAS.clear()
    st.title("🌱 Panel estadístico de germinación de semillas")
    st.caption("Proyecto BioGrow · Promedio, desviación estándar, varianza, ANOVA, "
               "prueba de Tukey y prueba LSD, calculados según el archivo que carga.")

    # ================================================================== 1. archivos
    st.sidebar.header("1 · Archivos")
    subidos = st.sidebar.file_uploader(
        "Carga uno o varios Excel (.xlsx)", type=["xlsx"], accept_multiple_files=True,
        help="El programa revisa cada hoja y detecta solo qué tipo de experimento contiene.",
    )
    en_carpeta = encontrar_excels()
    usar_carpeta = st.sidebar.checkbox(
        f"Usar también los Excel de la carpeta del programa ({len(en_carpeta)})",
        value=not subidos, disabled=not en_carpeta,
    )
    fuentes = {}
    if usar_carpeta:
        for ruta in en_carpeta:
            fuentes[ruta.name] = ruta.read_bytes()
    for archivo in subidos or []:
        fuentes[archivo.name] = archivo.getvalue()

    if not fuentes:
        st.info("**Para empezar:** carga uno o más archivos de Excel en el panel de la "
                "izquierda (sección 1 · Archivos). El programa detecta el tipo de experimento "
                "y prepara los análisis automáticamente.")
        with _caja():
            st.markdown(
                "**Formatos que reconoce**\n\n"
                "- **Tiempo de tratamiento por fecha:** hojas 'Datos-B/R (fecha)' con bloques "
                "T-1M, T-1N… y controles T-01…T-05.\n"
                "- **Tiempo 30 s por variedad:** bloques 'Experimento 1, 2, 3' con columnas "
                "'Raíz [mm]' y 'Tallo [mm]'.\n"
                "- **Temperatura del tratamiento:** bloques 'M1 - T35' (muestra 1 a 35 °C), "
                "longitudes en cm.")
        st.stop()

    df_todo, advertencias = _cargar(tuple(sorted(fuentes.items())))
    if df_todo.empty:
        st.error("Los archivos se leyeron, pero no se encontró ningún bloque de datos reconocible.")
        for a in advertencias: st.write("•", a)
        st.stop()

    # ================================================================== 2. experimento
    st.sidebar.header("2 · Experimento")
    resumen_archivos = (df_todo.groupby(["Archivo", "Tipo de experimento"])
                        .agg(Hojas=("Hoja", "nunique"), Cajas=("Corrida", "nunique"),
                             Semillas=("No", "size")).reset_index())
    tipos = [t for t in CONFIG_TIPO if t in set(df_todo["Tipo de experimento"])]
    if len(tipos) > 1:
        tipos_sel = st.sidebar.multiselect(
            "Tipos de experimento a analizar (detectados)", tipos, default=tipos,
            help="Por defecto se analizan juntos todos los archivos que cargaste. Si mezclas tipos "
            "distintos, usa 'Comparar por' (por ejemplo Variedad o Archivo) para no juntar "
            "grupos que no son comparables.")
    else:
        tipos_sel = tipos
        st.sidebar.caption(f"Tipo de experimento detectado: **{tipos[0]}**")
    if not tipos_sel:
        st.warning("Selecciona al menos un tipo de experimento en '2 · Experimento'.")
        st.stop()
    archivos_tipo = resumen_archivos.loc[resumen_archivos["Tipo de experimento"].isin(tipos_sel),
                                         "Archivo"].drop_duplicates().tolist()
    sel_archivos = st.sidebar.multiselect("Archivos a analizar", archivos_tipo, default=archivos_tipo)
    if not sel_archivos:
        st.warning("Selecciona al menos un archivo en '2 · Experimento'.")
        st.stop()
    df = df_todo[df_todo["Archivo"].isin(sel_archivos)
                 & df_todo["Tipo de experimento"].isin(tipos_sel)].copy()
    tipos_sel = [t for t in tipos_sel if t in set(df["Tipo de experimento"])]
    tipo = " + ".join(tipos_sel)
    mezcla = len(tipos_sel) > 1
    if mezcla:
        dims_union = []
        for t in tipos_sel:
            dims_union += [x for x in CONFIG_TIPO[t]["dims"] if x not in dims_union]
        dims_union += [x for x in ("Variedad", "Archivo") if x not in dims_union]
        config = {
            "dims": dims_union,
            "default": list(CONFIG_TIPO[tipos_sel[0]]["default"]),
            "descripcion": " ".join(CONFIG_TIPO[t]["descripcion"] for t in tipos_sel),
            "pregunta": " / ".join(CONFIG_TIPO[t]["pregunta"] for t in tipos_sel),
        }
    else:
        config = CONFIG_TIPO[tipos_sel[0]]
    advertencias = [a for a in advertencias if any(a.startswith(f) for f in sel_archivos)]

    if TIPO_TEMPERATURA in tipos_sel:
        es_temp = df["Tipo de experimento"] == TIPO_TEMPERATURA
        max_germ = int(df[es_temp].groupby("Corrida")["Germinó"].sum().max())
        n_plantilla = int(df.loc[es_temp, "No"].max())
        sembradas = st.sidebar.number_input(
            "Semillas sembradas por caja" + (" (archivos de temperatura)" if mezcla else ""),
            min_value=1, max_value=n_plantilla, value=n_plantilla, step=1,
            help=f"La plantilla tiene {n_plantilla} filas y ninguna caja pasa de {max_germ} "
            "semillas germinadas. Si se sembraron menos, las filas sobrantes cuentan como "
            "'no germinó' y bajan el % de germinación.")
        if sembradas < n_plantilla:
            df = df[~es_temp | (df["No"] <= sembradas)].copy()

    if df["Color"].isin(["B", "R"]).any():
        with st.sidebar.expander("Nombres de las variedades"):
            nombre_b = st.text_input("Hojas 'Datos-B'", "PBB-DH-183")
            nombre_r = st.text_input("Hojas 'Datos-R' / 'Datos-Rosa'", "H-392 A")
    else:
        nombre_b, nombre_r = "PBB-DH-183", "H-392 A"
    df = variedad_por_color(df, nombre_blanca=nombre_b, nombre_rosa=nombre_r)

    # ================================================================== 3. qué analizar
    st.sidebar.header("3 · Qué analizar")
    variable = st.sidebar.selectbox(
        "Variable", ["Raíz", "Tallo", "Germinó"],
        format_func=lambda v: {"Raíz": "Longitud de raíz (mm)", "Tallo": "Longitud de tallo (mm)",
                               "Germinó": "Germinación (%)"}[v])
    u, u2, nombre_var = _unidades(variable)

    etiquetas = {
        "Temperatura": "Temperatura del tratamiento",
        "Tratamiento": "Tiempo de tratamiento",
        "Clase nombre": "Parte expuesta (Embrión / Endospermo / Patrón)",
        "Variedad": "Variedad de maíz",
        "Condición": "Condición del bloque",
        "Tirada": "Tirada / experimento",
        "Bloque": "Bloque",
        "Hoja": "Fecha / hoja",
        "Archivo": "Archivo",
        "Corrida": "Caja (bloque + réplica)",
    }
    dims_tipo = [x for x in config["dims"] if df[x].nunique() >= 2] or config["default"]
    dims_tipo += [x for x in ["Corrida"] if x not in dims_tipo]
    dimensiones = st.sidebar.multiselect(
        "Comparar por", dims_tipo,
        default=[x for x in config["default"] if x in dims_tipo] or dims_tipo[:1],
        format_func=lambda x: etiquetas.get(x, x), key=f"dims_{'|'.join(tipos_sel)}",
        help="Define los grupos que se comparan. Si eliges dos, se combinan "
        "(p. ej. 'Tiempo + Parte expuesta').")

    unidad = st.sidebar.radio(
        "Cada dato del análisis es…",
        ["Una caja (promedio de sus semillas) — recomendado", "Una semilla"],
        disabled=variable == "Germinó",
        help="Las semillas de una misma caja recibieron el tratamiento juntas, así que la "
        "réplica real es la caja. Con 'una semilla', los grados de libertad crecen mucho y "
        "las pruebas encuentran diferencias que no son reales.")
    por_caja = True if variable == "Germinó" else unidad.startswith("Una caja")
    if variable == "Germinó":
        st.sidebar.caption("La germinación se calcula como % de semillas germinadas en cada caja.")
    unidad_txt = "cajas" if por_caja else "semillas"

    alfa = 0.05 if st.sidebar.radio("Nivel de significancia (α)", ["5 % (0.05)", "1 % (0.01)"],
                                    horizontal=True).startswith("5") else 0.01
    letras_de = st.sidebar.radio("Letras en las gráficas", ["Tukey", "LSD"], horizontal=True)

    dims_ef = list(dimensiones) or list(config["default"])
    if por_caja and "Corrida" in dims_ef:
        st.sidebar.warning("Con 'cada dato es una caja', comparar por caja deja un solo dato por grupo; se ignora.")
        dims_ef.remove("Corrida")
        dims_ef = dims_ef or list(config["default"])
    agrupacion_texto = " + ".join(etiquetas.get(x, x) for x in dims_ef)

    # ================================================================== 4. filtros
    st.sidebar.header("4 · Filtros (opcional)")

    def orden_trat(x):
        m = re.search(r"\d+(?:\.\d+)?", str(x))
        return (0, float(m.group()), str(x)) if m else (1, 0.0, str(x))

    def filtro(etiqueta, col, orden=None, **kw):
        vals = df[col].dropna().unique().tolist()
        vals = sorted(vals, key=orden) if orden else sorted(vals, key=str)
        if len(vals) < 2:
            return []
        return st.sidebar.multiselect(etiqueta, vals, **kw)

    f_var = filtro("Variedad", "Variedad")
    f_clase = filtro("Tipo de caja", "Clase nombre")
    f_temp = filtro("Temperatura", "Temperatura", orden=orden_trat)
    f_trat = filtro("Tiempo de tratamiento", "Tratamiento", orden=orden_trat)
    f_cond = filtro("Condición del bloque", "Condición")
    f_tirada = filtro("Tirada / experimento / muestra", "Tirada")

    def filtrar(base):
        s = base
        if f_var: s = s[s["Variedad"].isin(f_var)]
        if f_clase: s = s[s["Clase nombre"].isin(f_clase)]
        if f_temp: s = s[s["Temperatura"].isin(f_temp)]
        if f_trat: s = s[s["Tratamiento"].isin(f_trat)]
        if f_cond: s = s[s["Condición"].isin(f_cond)]
        if f_tirada: s = s[s["Tirada"].isin(f_tirada)]
        return s

    partes = []
    for nombre, valores in [("Variedad", f_var),
                            ("Tipo de caja", f_clase), ("Temp.", f_temp), ("Tiempo", f_trat),
                            ("Condición", f_cond), ("Tirada", f_tirada)]:
        if valores:
            partes.append(f"{nombre}: " + ", ".join(map(str, valores)))
    texto_filtros = " | ".join(partes) if partes else "Sin filtros (todos los datos)"

    # ================================================================== 5. descartes
    st.sidebar.header("5 · Descartes y correcciones")
    sugeridas_cm = hojas_probables_cm(df)
    hojas_cm = st.sidebar.multiselect(
        "Hojas medidas en cm (convertir a mm)",
        sorted(df.loc[df["Unidad original"] == "mm", "Hoja"].unique()),
        help="Los archivos con la nota 'Longitud dada en cm' se convierten solos. Marca aquí "
        "las hojas en cm que no lo indican."
        + (f" Probables por sus valores: {', '.join(sugeridas_cm)}." if sugeridas_cm else ""))
    if hojas_cm:
        m = df["Hoja"].isin(hojas_cm)
        df.loc[m, ["Raíz", "Tallo"]] = df.loc[m, ["Raíz", "Tallo"]] * 10

    op = {"cajas_vacias": st.sidebar.checkbox(
        "Excluir cajas vacías (no realizadas)", value=True,
        help="Cajas sin ninguna longitud registrada. En los archivos son bloques de plantilla "
        "capturados con Germinó = 0; si se incluyen cuentan como 0 % de germinación.")}
    if variable in ("Raíz", "Tallo"):
        kw_ng = dict(help="Excluirlas: el promedio describe solo a las semillas que crecieron. "
                     "Incluirlas: cada semilla no germinada entra con 0 mm y la varianza aumenta. "
                     "Elige una opción para poder analizar raíz o tallo.",
                     key=f"no_germ_{variable}")
        try:
            ng = st.sidebar.radio("Semillas que no germinaron",
                                  ["Excluirlas del promedio", "Incluirlas con longitud 0"],
                                  index=None, **kw_ng)
        except TypeError:
            ng = st.sidebar.radio("Semillas que no germinaron",
                                  ["(elige una opción)", "Excluirlas del promedio",
                                   "Incluirlas con longitud 0"], **kw_ng)
            ng = None if ng.startswith("(") else ng
        if ng is None:
            st.sidebar.warning("Elige qué hacer con las semillas que no germinaron.")
            op["no_germinadas"] = None
        else:
            op["no_germinadas"] = "excluir" if ng.startswith("Excluir") else "incluir"
        op["ceros_germinadas"] = st.sidebar.checkbox(
            f"Excluir germinadas con {variable.lower()} = 0",
            help=(f"Semillas marcadas como germinadas pero con {variable.lower()} = 0: salen del promedio."
                  + (" En el % de germinación cuentan como no germinadas (no salió la raíz)."
                     if variable == "Raíz" else "")))
        serie = pd.to_numeric(filtrar(df)[variable], errors="coerce")
        serie = serie[serie > 0]
        if not serie.empty and st.sidebar.checkbox("Excluir valores fuera de un rango"):
            op["rango"] = st.sidebar.slider(f"Rango válido de {variable.lower()} (mm)", 0,
                                            int(np.ceil(serie.max())), (0, int(np.ceil(serie.max()))))
        op["atipicos"] = st.sidebar.checkbox(
            "Excluir valores atípicos de cada grupo",
            help="Quita valores fuera de Q1 − k·IQR y Q3 + k·IQR dentro de su grupo.")
        if op["atipicos"]:
            op["factor_iqr"] = st.sidebar.select_slider("k (regla k × IQR)", [1.5, 2.0, 3.0], value=1.5)

    # ================================================================== etiquetas y apariencia
    with st.sidebar.expander("Condiciones del experimento y tamaño de letra"):
        flujo = st.slider("Flujo (L/min)", 0, 10, 0)
        tipo_gas = "Atmosférico"
        escala = st.slider("Tamaño de letra de las gráficas", 0.8, 2.0, 1.0, 0.1)
    condiciones = f"Flujo {flujo} L/min · Gas {tipo_gas}"

    st.sidebar.header("6 · Colores de las gráficas")
    if "semilla_color" not in st.session_state:
        st.session_state.semilla_color = None
    b_azar, b_orig = st.sidebar.columns(2)
    if b_azar.button("🎨 Al azar", key="btn_colores", help="Genera una combinación nueva de "
                     "colores para todas las gráficas. Púlsalo las veces que quieras."):
        st.session_state.semilla_color = random.randint(1, 10 ** 9)
    if b_orig.button("↺ Originales", key="btn_colores_orig", help="Vuelve a los colores originales.",
                     disabled=st.session_state.semilla_color is None):
        st.session_state.semilla_color = None
    establecer_colores(st.session_state.semilla_color)
    st.sidebar.markdown(
        "".join(f"<span style='display:inline-block;width:22px;height:14px;margin-right:3px;"
                f"border-radius:3px;background:{c}'></span>" for c in PALETA[:8]),
        unsafe_allow_html=True)
    st.sidebar.caption("El control (patrón) sigue en gris y en la gráfica de cluster el rojo "
                       "siempre marca los pares que sí difieren.")

    df_filtrado = filtrar(df).copy()
    df_filtrado["Grupo"] = construir_grupo(df_filtrado, dims_ef)

    if "descartes_manuales" not in st.session_state:
        st.session_state.descartes_manuales = {}
        st.session_state.version_editor = 0
    manuales = st.session_state.descartes_manuales

    # ================================================================== encabezado
    with _caja():
        c1, c2, c3, c4 = st.columns([1.3, 1.2, 1, 1.2])
        c1.markdown(f"**Experimento**\n\n{tipo}")
        c2.markdown("**Archivos**\n\n" + "<br>".join(sel_archivos), unsafe_allow_html=True)
        c3.markdown(f"**Variable**\n\n{'Germinación (%)' if variable == 'Germinó' else f'{variable} (mm)'}")
        c4.markdown(f"**Se compara por**\n\n{agrupacion_texto}")
        st.caption(f"**Pregunta del experimento:** {config['pregunta']}  ·  **Filtros:** "
                   f"{texto_filtros}  ·  **α** = {alfa}  ·  **Cada dato es:** una "
                   f"{'caja' if por_caja else 'semilla'}")

    if variable in ("Raíz", "Tallo") and op.get("no_germinadas") is None:
        st.info(f"**Falta un paso para analizar {variable.lower()}:** en el panel izquierdo, "
                "sección **5 · Descartes y correcciones**, elige qué hacer con las **semillas que "
                "no germinaron**:\n\n"
                "- **Excluirlas del promedio:** el promedio describe solo a las semillas que "
                "crecieron.\n"
                f"- **Incluirlas con longitud 0:** cada semilla no germinada cuenta como 0 mm de "
                f"{variable.lower()}, así que el promedio mezcla cuánto creció con cuántas germinaron.")
        st.stop()

    zona_metricas = st.container()
    tabs = st.tabs(["📌 Resumen", "📊 Promedio, DE y varianza", "🧮 ANOVA", "🔠 Tukey",
                    "🔡 LSD", "🧹 Descartes", "📈 Más gráficas", "📥 Descargas"])
    (t_res, t_desc, t_anova, t_tukey, t_lsd, t_desc_m, t_graf, t_pdf) = tabs

    # ================================================================== descartes semilla por semilla
    _, reg_auto = aplicar_descartes(df_filtrado, variable, op)
    motivo_auto = reg_auto.drop_duplicates("ID semilla").set_index("ID semilla")["Motivo"]
    with t_desc_m:
        st.subheader("Descartes")
        bloque_explicacion(
            "Qué datos se quitaron del análisis y por qué. Hay dos tipos: se quita la semilla "
            "completa (deja de contar también en el % de germinación) o solo su valor de raíz "
            "o tallo (sigue contando como semilla sembrada).",
            "Las reglas automáticas se eligen en el panel izquierdo (sección 5). Abajo puedes "
            "marcar semillas una por una aunque su valor no sea cero, con un motivo.")
        st.markdown("#### Descartar semillas específicas")
        st.caption("Ordena por Raíz o Tallo con un clic en el encabezado para encontrar valores "
                   "extremos. Marca la casilla 'Descartar' y pulsa 'Aplicar descartes'.")
        vista = df_filtrado[["ID semilla", "Hoja", "Grupo", "Bloque", "Réplica", "No",
                             "Germinó", "Raíz", "Tallo"]].copy()
        vista.insert(0, "Descartar", vista["ID semilla"].isin(manuales.keys()))
        vista["Ya descartada por"] = vista["ID semilla"].map(motivo_auto).fillna("")
        vista = vista.rename(columns={"No": "Semilla n.º", "Raíz": "Raíz (mm)", "Tallo": "Tallo (mm)",
                                      "Germinó": "Germinó (1 = sí)"}).set_index("ID semilla")
        with st.form("form_descartes"):
            motivo = st.text_input("Motivo para las semillas que marques ahora", value="Descarte manual")
            kw_editor = dict(key=f"editor_{st.session_state.version_editor}", hide_index=True,
                             disabled=[c for c in vista.columns if c != "Descartar"], height=330,
                             column_config={"Descartar": st.column_config.CheckboxColumn("Descartar")})
            try:
                editado = st.data_editor(vista, width="stretch", **kw_editor)
            except TypeError:
                editado = st.data_editor(vista, use_container_width=True, **kw_editor)
            b1, b2 = st.columns(2)
            aplicar = b1.form_submit_button("Aplicar descartes", type="primary")
            limpiar = b2.form_submit_button("Quitar todos los descartes manuales")
        if aplicar:
            desmarcadas = set(editado.index[~editado["Descartar"]])
            nuevos = {k: v for k, v in manuales.items() if k not in desmarcadas}
            for k in editado.index[editado["Descartar"]]:
                nuevos.setdefault(k, motivo.strip() or "Descarte manual")
            st.session_state.descartes_manuales = nuevos
            st.session_state.version_editor += 1
            st.rerun()
        if limpiar:
            st.session_state.descartes_manuales = {}
            st.session_state.version_editor += 1
            st.rerun()

    op["manuales"] = manuales
    df_semilla, registro = aplicar_descartes(df_filtrado, variable, op)

    if por_caja:
        df_an = agregar_por_unidad(df_semilla, variable, COLUMNAS_CAJA + dims_ef)
    else:
        df_an = df_semilla.dropna(subset=[variable]).copy()

    def ref_patron(hoja=None):
        r = df[df["Clase"] == "S"].copy()
        if hoja is not None: r = r[r["Hoja"] == hoja]
        if f_var: r = r[r["Variedad"].isin(f_var)]
        if r.empty:
            return None
        r["Grupo"] = "Patrón"
        r, _ = aplicar_descartes(r, variable, op)
        if r.empty:
            return None
        if por_caja:
            r = agregar_por_unidad(r, variable)
        return descriptivos_serie(r[variable])

    # métricas generales (se muestran arriba de las pestañas)
    m1, m2, m3, m4, m5, m6 = zona_metricas.columns(6)
    m1.metric("Semillas analizadas", f"{len(df_semilla):,}")
    m2.metric("Cajas", df_semilla["Corrida"].nunique())
    m3.metric("Grupos comparados", df_an["Grupo"].nunique() if not df_an.empty else 0)
    m4.metric(f"Datos ({unidad_txt})", len(df_an))
    m5.metric("% germinación global", f"{df_semilla[columna_germinacion(df_semilla)].mean() * 100:.1f} %"
              if df_semilla["Germinó"].notna().any() else "—")
    m6.metric("Registros descartados", len(registro))

    if df_an.empty:
        zona_metricas.warning("No quedan datos con los filtros y descartes actuales.")
        st.stop()

    res = pruebas_requeridas(df_an, variable, alfa)
    anova, tk, ls = res["anova"], res["tukey"], res["lsd"]
    desc = tabla_descriptivos(df_an, "Grupo", variable, alfa)

    factor_q = op.get("factor_iqr", 1.5)
    datos_q_semilla = None if variable == "Germinó" else df_semilla.dropna(subset=[variable])
    tc_base = tabla_cuartiles(datos_q_semilla if datos_q_semilla is not None else df_an, variable, factor_q)
    diag_base = diagnostico_cuartiles(tc_base, factor_q) if not tc_base.empty else None

    avisos = []
    pocos = df_an.groupby("Grupo").size()
    pocos = pocos[pocos < 3]
    if len(pocos):
        avisos.append(f"Grupos con menos de 3 {unidad_txt}: " +
                      ", ".join(f"{g} (n = {n})" for g, n in pocos.items()) +
                      ". Con tan pocos datos las pruebas solo detectan diferencias grandes; "
                      "un grupo con 1 dato no entra al ANOVA.")
    if not por_caja:
        avisos.append("Cada dato es una semilla: los grados de libertad del error son "
                      "semillas − grupos y las pruebas tienden a encontrar diferencias que no "
                      "son reales. Para el reporte usa 'una caja'.")
    if mezcla and not ({"Archivo", "Variedad", "Hoja"} & set(dims_ef)):
        avisos.append("Estás analizando juntos experimentos de distinto tipo (" + tipo + "). Los grupos "
                      "mezclan cajas de experimentos diferentes; para compararlos por separado agrega "
                      "'Variedad' o 'Archivo' en 'Comparar por'.")
    if (TIPO_TIEMPO in tipos_sel and "Tratamiento" in dims_ef and df_an["Hoja"].nunique() > 1
            and "Hoja" not in dims_ef):
        avisos.append("Estás juntando varias fechas y cada fecha probó tiempos distintos: una "
                      "diferencia podría deberse a la fecha y no al tiempo. Agrega 'Fecha / hoja' "
                      "en 'Comparar por' para separarlas.")
    if diag_base and pd.notna(diag_base["razon_iqr"]) and diag_base["razon_iqr"] > 2:
        g_max, v_max = diag_base["iqr_max"]
        g_min, v_min = diag_base["iqr_min"]
        avisos.append(f"La dispersión de los grupos es muy distinta: el rango intercuartílico de "
                      f"{g_max} ({v_max:.2f} {u}) es {diag_base['razon_iqr']:.1f} veces el de {g_min} "
                      f"({v_min:.2f} {u}). Interpreta Tukey y LSD con cuidado; detalle en "
                      "'🧮 ANOVA → Análisis por cuartiles'.")
    if diag_base and diag_base["atipicos"] and variable != "Germinó" and not op.get("atipicos"):
        avisos.append(f"Hay {diag_base['atipicos']} valor(es) atípico(s) según los cuartiles de su grupo. "
                      "Revísalos en '🧮 ANOVA → Análisis por cuartiles' y, si corresponde, quítalos con "
                      "'Excluir valores atípicos de cada grupo' (sección 5).")
    if anova and not anova["significativo"] and not ls.empty and (ls["Resultado"] == SIG).any():
        avisos.append("La LSD marca diferencias aunque el ANOVA no fue significativo; por el "
                      "criterio de Fisher esas diferencias no deben reportarse.")

    subt_graf = f"{texto_filtros} · {condiciones}"

    # ================================================================== RESUMEN
    with t_res:
        if anova is None:
            st.warning(f"Con los filtros actuales, '{agrupacion_texto}' no forma al menos 2 grupos "
                       f"con 2 o más {unidad_txt}. Cambia 'Comparar por' o quita filtros.")
        else:
            signo = ">" if anova["F calculada"] > anova["F crítica"] else "≤"
            frase_f = (f"F calculada = {anova['F calculada']:.3f} {signo} F crítica = "
                       f"{anova['F crítica']:.3f} · GL = {anova['GL entre']} y {anova['GL error']} · "
                       f"p = {anova['p-valor']:.4f}")
            if anova["significativo"]:
                st.success(f"### ✔ Sí hay diferencias significativas en {nombre_var.lower()} entre los grupos\n{frase_f}")
            else:
                st.info(f"### ✘ No hay diferencias significativas en {nombre_var.lower()} entre los grupos\n{frase_f}")

            c_izq, c_der = st.columns([1.05, 1])
            with c_izq:
                st.markdown(f"#### Ranking de grupos (α = {alfa})")
                _tabla(tabla_ranking(desc, res["letras_tukey"], res["letras_lsd"], u,
                                       germinacion_por_grupo(df_semilla)))
                st.caption("Grupos que comparten una letra **no** difieren entre sí. Tukey es la "
                           "prueba más estricta; LSD separa más grupos. % germinación: semillas "
                           "germinadas / semillas sembradas en cada grupo.")
            with c_der:
                st.markdown(f"#### ¿Qué grupos difieren? (Tukey, α = {alfa})")
                frases = pares_significativos(tk, u)
                if frases:
                    for f in frases:
                        st.markdown(f"- {f}")
                else:
                    st.markdown("- Ningún par de grupos difiere según Tukey.")
                if not ls.empty:
                    n_lsd = int((ls["Resultado"] == SIG).sum())
                    st.caption(f"La prueba LSD encuentra {n_lsd} par(es) distintos; Tukey, "
                               f"{len(frases)}. Detalle en las pestañas Tukey y LSD.")

        st.markdown("#### Gráfica")
        g1, g2, g3 = st.columns([1.2, 1.2, 1])
        tipo_graf = g1.radio("Tipo", ["Barras: promedio con letras", "Cajas: distribución de los datos"],
                             horizontal=True, key="tipo_graf")
        dispersion = g2.selectbox("Línea de error (solo barras)",
                                  ["Desviación estándar", "Error estándar (SEM)", "IC 95% de la media"])
        usar_ref = g3.checkbox("Mostrar línea del patrón (control)", value=True,
                               help="Línea horizontal con el promedio del control, para ver qué "
                               "tratamientos quedan por arriba o por abajo de él.")

        def dibujar(datos_g, r_g, clave, titulo, hoja_ref=None):
            if r_g["anova"] is None:
                st.info("Sin grupos suficientes para comparar.")
                return
            let = r_g["letras_tukey"] if letras_de == "Tukey" else r_g["letras_lsd"]
            ref = (ref_patron(hoja_ref) or {}) if usar_ref else None
            if tipo_graf.startswith("Barras"):
                d_g = tabla_descriptivos(datos_g, "Grupo", variable, alfa)
                fig = grafico_barras_letras(d_g, let, variable, u, agrupacion_texto, titulo,
                                            subt_graf, dispersion, ref, escala, letras_de)
            else:
                fig = grafico_cajas_letras(datos_g, variable, let, u, agrupacion_texto, titulo,
                                           subt_graf, escala, letras_de, ref)
            if fig is not None:
                _grafica(fig, clave)

        dibujar(df_an, res, "res_graf", f"{nombre_var} por {agrupacion_texto.lower()}")

        if avisos:
            st.markdown("#### Avisos para interpretar los resultados")
            for a in avisos:
                st.warning(a)

        if anova:
            st.markdown("#### Texto para el reporte")
            st.text_area("Puedes copiarlo y ajustarlo", texto_reporte(
                variable, u, agrupacion_texto, unidad_txt, anova, tk, alfa, desc),
                height=150, label_visibility="collapsed")

    # ================================================================== DESCRIPTIVOS
    with t_desc:
        st.subheader("Promedio, desviación estándar y varianza por grupo")
        bloque_explicacion(
            f"Cuánto midió en promedio cada grupo y qué tan dispersos están sus datos. "
            f"Cada dato es una {'caja' if por_caja else 'semilla'}.",
            "**Promedio:** valor típico del grupo. **Desviación estándar (DE):** cuánto se "
            "alejan los datos del promedio, en las mismas unidades. **Varianza:** la DE al "
            "cuadrado; es la que usa el ANOVA. **CV:** DE como % del promedio.")
        d = desc.copy()
        d["GL (n − 1)"] = d["n"] - 1
        d = d.rename(columns={"Media": f"Promedio ({u})", "Desviación estándar": f"Desviación estándar ({u})",
                              "Varianza": f"Varianza ({u2})", "SEM": f"Error estándar ({u})",
                              "CV %": "CV (%)", "Mínimo": f"Mínimo ({u})", "Mediana": f"Mediana ({u})",
                              "Máximo": f"Máximo ({u})", "n": f"n ({unidad_txt})"})
        cols = ["Grupo", f"n ({unidad_txt})", f"Promedio ({u})", f"Desviación estándar ({u})",
                f"Varianza ({u2})", "GL (n − 1)", f"Error estándar ({u})", "CV (%)",
                f"Mínimo ({u})", f"Mediana ({u})", f"Máximo ({u})"]
        if por_caja:
            sem_g = df_an.groupby("Grupo")["Semillas con dato"].sum().rename("Semillas usadas")
            d = d.merge(sem_g, left_on="Grupo", right_index=True, how="left")
            cols.insert(2, "Semillas usadas")
        _tabla(_fmt(d[[c for c in cols if c in d.columns]]))
        st.latex(r"\bar{x}=\frac{\sum x_i}{n}\qquad s^2=\frac{\sum (x_i-\bar{x})^2}{n-1}"
                 r"\qquad s=\sqrt{s^2}\qquad CV=\frac{s}{\bar{x}}\times 100")
        st.caption("La varianza y la desviación estándar son muestrales: se divide entre n − 1, "
                   "que son sus grados de libertad.")
        st.markdown("#### ¿De dónde sale la desviación estándar de cada grupo?")
        st.caption("Cada punto es un dato del análisis (una caja o una semilla). La línea gruesa es "
                   "el promedio del grupo y la franja abarca ± 1 desviación estándar. Las líneas "
                   "punteadas son la distancia de cada dato a su promedio: esas distancias, elevadas "
                   "al cuadrado y divididas entre n − 1, son la varianza. Un grupo con puntos muy "
                   "separados tiene una franja ancha y una varianza grande.")
        fig = grafico_dispersion_grupos(df_an, variable, u, agrupacion_texto,
                                        f"Datos de cada grupo alrededor de su promedio — {nombre_var.lower()}",
                                        subt_graf, escala, unidad_txt)
        if fig is not None:
            _grafica(fig, "desc_dispersion")

    # ================================================================== ANOVA
    with t_anova:
        st.subheader(f"ANOVA de una vía (α = {alfa})")
        bloque_explicacion(
            "¿Al menos un grupo tiene un promedio distinto de los demás? No dice cuál; eso lo "
            "dicen Tukey y LSD.",
            "Compara la variación **entre** los promedios de los grupos con la variación "
            "**dentro** de cada grupo. Si **F calculada > F crítica** (o p < α), hay diferencia "
            "significativa.")
        if anova is None:
            st.info("Se necesitan al menos 2 grupos con 2 o más datos.")
        else:
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("F calculada", f"{anova['F calculada']:.3f}")
            k2.metric(f"F crítica (α = {alfa})", f"{anova['F crítica']:.3f}")
            k3.metric("GL entre grupos", anova["GL entre"])
            k4.metric("GL del error", anova["GL error"])
            k5.metric("p-valor", f"{anova['p-valor']:.4f}")
            signo = ">" if anova["F calculada"] > anova["F crítica"] else "≤"
            texto = (f"**{anova['F calculada']:.3f} {signo} {anova['F crítica']:.3f}** → ")
            if anova["significativo"]:
                st.success(texto + "**sí hay diferencia significativa** entre al menos dos grupos.")
            else:
                st.info(texto + "**no hay diferencia significativa** entre los grupos.")
            st.markdown("#### Tabla del ANOVA")
            _tabla(_fmt(tabla_anova_clara(anova, u2)))
            st.caption(f"SC = suma de cuadrados · CM = cuadrado medio (SC ÷ GL) · F crítica con "
                       f"α = {alfa}, {anova['GL entre']} y {anova['GL error']} GL. "
                       f"GL entre grupos = k − 1 = {anova['k']} − 1 = {anova['GL entre']} · "
                       f"GL del error = N − k = {anova['n total']} − {anova['k']} = {anova['GL error']} · "
                       f"GL total = N − 1 = {anova['GL total']}  (k = grupos, N = datos). "
                       f"η² = {anova['efecto']['η² (eta cuadrada)']:.3f}: proporción de la variación "
                       "explicada por los grupos.")

            with st.expander("Ver el cálculo paso a paso"):
                med = anova["medias"].copy()
                gran = (med["n"] * med["Media"]).sum() / med["n"].sum()
                med["Promedio − promedio general"] = med["Media"] - gran
                med[f"n × (diferencia)² ({u2})"] = med["n"] * med["Promedio − promedio general"] ** 2
                med[f"Σ(x − promedio)² ({u2})"] = (med["n"] - 1) * med["Varianza"]
                med = med.rename(columns={"Media": f"Promedio ({u})", "Varianza": f"Varianza ({u2})"})
                _tabla(_fmt(med))
                st.markdown(
                    f"1. **Promedio general** de los {anova['n total']} datos = {gran:.3f} {u}\n"
                    f"2. **SC entre grupos** = suma de n × (promedio − promedio general)² = "
                    f"**{anova['SC entre']:.3f}**\n"
                    f"3. **SC del error** = suma de Σ(x − promedio)² de cada grupo = **{anova['SC error']:.3f}**\n"
                    f"4. **CM entre** = SC entre ÷ GL entre = {anova['SC entre']:.3f} ÷ {anova['GL entre']} = "
                    f"**{anova['CM entre']:.3f}**\n"
                    f"5. **CM del error** = SC error ÷ GL error = {anova['SC error']:.3f} ÷ {anova['GL error']} = "
                    f"**{anova['CM error']:.3f}**\n"
                    f"6. **F calculada** = CM entre ÷ CM error = **{anova['F calculada']:.3f}**\n"
                    f"7. **F crítica** = valor de tablas F con α = {alfa}, {anova['GL entre']} y "
                    f"{anova['GL error']} GL = **{anova['F crítica']:.3f}**")

        st.markdown("---")
        st.markdown("### Análisis por cuartiles")
        bloque_explicacion(
            "Cómo se reparten los datos dentro de cada grupo, sin depender del promedio: dónde está "
            "el 50 % central, si la distribución está cargada hacia un lado y qué valores son "
            "atípicos. Sirve para revisar que los grupos sean comparables antes de leer el ANOVA, "
            "Tukey y LSD.",
            "Se ordenan los datos de menor a mayor y se parten en cuatro partes iguales. "
            "**Q1** deja abajo al 25 % de los datos, la **mediana (Q2)** al 50 % y **Q3** al 75 %. "
            "**IQR = Q3 − Q1** es el ancho del 50 % central. Un dato es **atípico** si queda por "
            f"debajo de Q1 − {factor_q:g}·IQR o por encima de Q3 + {factor_q:g}·IQR (regla de Tukey).")

        if datos_q_semilla is not None and por_caja:
            nivel_q = st.radio(
                "Calcular los cuartiles sobre…",
                ["Las semillas de cada grupo (recomendado)", "Los promedios de caja (datos del ANOVA)"],
                horizontal=True, key="nivel_q",
                help="Con semillas cada grupo tiene decenas de datos y los cuartiles describen bien "
                "la distribución; es el mismo nivel que usa 'Excluir valores atípicos'. Con promedios "
                "de caja suele haber 3 a 5 datos por grupo, muy pocos para que los cuartiles sean "
                "estables.")
            usar_semillas = nivel_q.startswith("Las semillas")
        else:
            usar_semillas = datos_q_semilla is not None
        datos_q = datos_q_semilla if usar_semillas else df_an
        nivel_txt = "semillas" if usar_semillas else unidad_txt
        tc = tabla_cuartiles(datos_q, variable, factor_q)

        if tc.empty:
            st.info("No hay datos para calcular cuartiles.")
        else:
            diag = diagnostico_cuartiles(tc, factor_q)
            st.caption(f"Cuartiles calculados sobre {nivel_txt}, por grupo. Método de interpolación "
                       "lineal, el mismo que usa Excel con =CUARTIL.INC().")
            vista_q = tc.drop(columns=["_bigote_inf", "_bigote_sup"]).rename(columns={
                "n": f"n ({nivel_txt})", "Mínimo": f"Mínimo ({u})", "Q1 (25 %)": f"Q1 ({u})",
                "Mediana (Q2)": f"Mediana ({u})", "Q3 (75 %)": f"Q3 ({u})", "Máximo": f"Máximo ({u})",
                "IQR (Q3 − Q1)": f"IQR ({u})", "Límite inferior": f"Límite inferior ({u})",
                "Límite superior": f"Límite superior ({u})", "Promedio": f"Promedio ({u})"})
            _tabla(_fmt(vista_q))

            fig_q = grafico_cuartiles(tc, datos_q, variable, u, agrupacion_texto,
                                      f"Cuartiles de {nombre_var.lower()} por {agrupacion_texto.lower()}",
                                      subt_graf, escala, factor_q)
            if fig_q is not None:
                _grafica(fig_q, "anova_cuartiles")

            st.markdown("#### ¿Qué dicen los cuartiles de estos datos?")
            d1, d2, d3 = st.columns(3)
            with d1:
                with _caja():
                    st.markdown("**1 · Dispersión entre grupos**")
                    if pd.isna(diag["razon_iqr"]):
                        st.write("Se necesitan al menos 2 grupos con 4 o más datos para compararla.")
                    else:
                        g_max, v_max = diag["iqr_max"]
                        g_min, v_min = diag["iqr_min"]
                        ok = diag["razon_iqr"] <= 2
                        st.markdown(
                            f"IQR mayor: **{g_max}** ({v_max:.2f} {u})  \nIQR menor: **{g_min}** "
                            f"({v_min:.2f} {u})  \nRazón: **{diag['razon_iqr']:.2f}**")
                        (st.success if ok else st.warning)(
                            "Dispersión parecida entre grupos (razón ≤ 2)." if ok else
                            "Dispersión muy distinta (razón > 2): un grupo es mucho más variable que "
                            "otro; Tukey y LSD usan una sola varianza para todos, así que interpreta "
                            "con cuidado.")
            with d2:
                with _caja():
                    st.markdown("**2 · Forma (simetría)**")
                    if diag["sesgados"]:
                        st.warning("Muy sesgados: " + ", ".join(diag["sesgados"]) +
                                   ". En esos grupos la mediana representa mejor al grupo que el promedio.")
                    elif diag["grupos_validos"]:
                        st.success("Ningún grupo está muy sesgado: el promedio es un buen resumen.")
                    else:
                        st.write("Se necesitan grupos con 4 o más datos.")
                    st.caption("Asimetría de Bowley = (Q3 + Q1 − 2·Mediana) ÷ IQR. Cerca de 0: "
                               "simétrica; |valor| ≥ 0.3: muy sesgada.")
            with d3:
                with _caja():
                    st.markdown("**3 · Valores atípicos**")
                    if diag["atipicos"]:
                        st.warning(f"{diag['atipicos']} dato(s) fuera de los límites (✕ rojas en la gráfica).")
                        if variable != "Germinó" and not op.get("atipicos"):
                            st.caption("Puedes quitarlos con 'Excluir valores atípicos de cada grupo' "
                                       "(sección 5); usa exactamente estos límites.")
                    else:
                        st.success("Ningún dato queda fuera de los límites.")

            with st.expander("Ver cómo se calculan Q1, mediana y Q3 de un grupo"):
                g_sel = st.selectbox("Grupo", tc["Grupo"].tolist(), key="q_grupo")
                vals = np.sort(pd.to_numeric(datos_q.loc[datos_q["Grupo"].astype(str) == g_sel, variable],
                                             errors="coerce").dropna().astype(float).values)
                n_q = len(vals)
                lista = ", ".join(f"{v:.2f}" for v in vals) if n_q <= 60 else (
                    ", ".join(f"{v:.2f}" for v in vals[:25]) + ", … , " +
                    ", ".join(f"{v:.2f}" for v in vals[-25:]))
                st.markdown(f"**1. Ordenar los {n_q} datos de menor a mayor ({u}):**")
                st.code(lista, language=None)
                st.markdown("**2. Posición de cada cuartil:** posición = 1 + (n − 1) × p, con "
                            "p = 0.25, 0.50 y 0.75. Si la posición no es entera, se interpola entre "
                            "los dos datos vecinos.")
                renglones = []
                for nombre_q, p in [("Q1", 0.25), ("Mediana", 0.5), ("Q3", 0.75)]:
                    pos, baja, frac, vb, va, val = pasos_cuartil(vals, p)
                    renglones.append(
                        f"- **{nombre_q}:** posición = 1 + ({n_q} − 1) × {p} = {pos:.2f} → dato {baja} "
                        f"({vb:.2f}) + {frac:.2f} × (dato {min(baja + 1, n_q)} − dato {baja}) = "
                        f"{vb:.2f} + {frac:.2f} × ({va:.2f} − {vb:.2f}) = **{val:.2f} {u}**")
                st.markdown("\n".join(renglones))
                f_g = tc.loc[tc["Grupo"] == g_sel].iloc[0]
                st.markdown(
                    f"**3. IQR** = Q3 − Q1 = {f_g['Q3 (75 %)']:.2f} − {f_g['Q1 (25 %)']:.2f} = "
                    f"**{f_g['IQR (Q3 − Q1)']:.2f} {u}**\n\n"
                    f"**4. Límites de atípicos:** Q1 − {factor_q:g} × IQR = **{f_g['Límite inferior']:.2f}** · "
                    f"Q3 + {factor_q:g} × IQR = **{f_g['Límite superior']:.2f}** → "
                    f"{f_g['Atípicos bajos'] + f_g['Atípicos altos']} dato(s) fuera.\n\n"
                    f"**5. Asimetría de Bowley** = ({f_g['Q3 (75 %)']:.2f} + {f_g['Q1 (25 %)']:.2f} − 2 × "
                    f"{f_g['Mediana (Q2)']:.2f}) ÷ {f_g['IQR (Q3 − Q1)']:.2f} = "
                    + (f"**{f_g['Asimetría de Bowley']:.3f}** → {f_g['Forma de la distribución']}"
                       if pd.notna(f_g["Asimetría de Bowley"]) else "no se puede calcular (IQR = 0)"))

    # ================================================================== TUKEY
    with t_tukey:
        st.subheader(f"Prueba de Tukey (α = {alfa})")
        bloque_explicacion(
            "¿Cuáles pares de grupos difieren? Compara todos contra todos y controla el error de "
            "hacer muchas comparaciones a la vez, por eso es estricta.",
            "Para cada par: si **|A − B| > DHS** (o, lo mismo, **q calculada > q crítica**), "
            "los dos grupos difieren. Las letras resumen la tabla: misma letra = no difieren.")
        if tk.empty:
            st.info("Se necesitan al menos 2 grupos con 2 o más datos.")
        else:
            q_crit = tk["q crítica"].iloc[0]
            k1, k2, k3, k4 = st.columns(4)
            k1.metric(f"q crítica (α = {alfa})", f"{q_crit:.3f}")
            k2.metric("k (grupos)", anova["k"])
            k3.metric("GL del error", anova["GL error"])
            k4.metric(f"CM del error ({u2})", f"{anova['CM error']:.3f}")
            st.latex(r"DHS = q_{crít}\sqrt{\frac{CM_{error}}{2}\left(\frac{1}{n_A}+\frac{1}{n_B}\right)}"
                     r"\qquad q_{calc}=\frac{|\bar{x}_A-\bar{x}_B|}{\sqrt{\frac{CM_{error}}{2}\left(\frac{1}{n_A}+\frac{1}{n_B}\right)}}")
            solo = st.checkbox("Mostrar solo los pares que difieren", key="tk_sig")
            v = tk[tk["Resultado"] == SIG] if solo else tk
            _tabla(_fmt(tabla_tukey_clara(v, u)))

            c1, c2 = st.columns([1, 1.3])
            with c1:
                st.markdown("#### Letras de Tukey")
                let = res["letras_tukey"].rename(columns={"Media": f"Promedio ({u})"})
                _tabla(_fmt(let))
            with c2:
                st.markdown("#### Cálculo paso a paso de un par")
                pares = [f"{a}  vs  {b}" for a, b in zip(tk["Grupo 1"], tk["Grupo 2"])]
                elegido = st.selectbox("Par", pares, key="tk_par")
                f = tk.iloc[pares.index(elegido)]
                cme = anova["CM error"]
                ee = math.sqrt(cme / 2 * (1 / f["n1"] + 1 / f["n2"]))
                st.markdown(
                    f"- |A − B| = |{f['Media 1']:.3f} − {f['Media 2']:.3f}| = **{f['|Diferencia|']:.3f} {u}**\n"
                    f"- Error = √({cme:.3f} ÷ 2 × (1/{f['n1']} + 1/{f['n2']})) = **{ee:.3f}**\n"
                    f"- q calculada = {f['|Diferencia|']:.3f} ÷ {ee:.3f} = **{f['q calculada']:.3f}**\n"
                    f"- q crítica (α = {alfa}; k = {anova['k']}; GL = {anova['GL error']}) = **{q_crit:.3f}**\n"
                    f"- DHS = {q_crit:.3f} × {ee:.3f} = **{f['DHS']:.3f} {u}**\n"
                    f"- **Conclusión:** {f['Comparación |dif| vs DHS']} → "
                    f"{'los grupos **sí difieren**' if f['Resultado'] == SIG else 'los grupos **no difieren**'}")
            st.markdown("#### Gráfica de cluster: diferencias entre pares (estilo Tukey simultáneo)")
            st.caption("Cada línea es un par de grupos. El punto es la diferencia de sus promedios "
                       "y la barra horizontal es su intervalo de confianza simultáneo del 95 %. "
                       "Si la línea no cruza la línea punteada del cero, esos dos grupos difieren.")
            fig = grafico_pares_cluster(v, res["letras_tukey"], u,
                                        f"{nombre_var} — diferencias de Tukey por {agrupacion_texto.lower()}",
                                        subt_graf, escala, "Tukey", "DHS")
            if fig is not None:
                _grafica(fig, "tk_cluster")

            st.markdown("#### Gráfica de barras: promedio de cada grupo con sus letras de Tukey")
            st.caption("Complementa a la gráfica de cluster: aquella muestra cada par, esta muestra cada "
                       "grupo. Cada barra es el promedio de un grupo y encima lleva sus letras. **Las "
                       "barras del mismo color tienen las mismas letras.** Dos grupos que comparten "
                       "alguna letra no difieren; si no comparten ninguna, sí difieren. La tabla de "
                       "abajo dice qué grupos lleva cada letra.")
            fig = grafico_barras_grupos_letras(desc, res["letras_tukey"], variable, u, agrupacion_texto,
                                               f"{nombre_var} por {agrupacion_texto.lower()} — grupos de Tukey",
                                               subt_graf, escala, "Tukey")
            if fig is not None:
                _grafica(fig, "tk_barras")
                _tabla(tabla_letras_grupos(res["letras_tukey"]))

    # ================================================================== LSD
    with t_lsd:
        st.subheader(f"Prueba LSD de Fisher (α = {alfa})")
        bloque_explicacion(
            "¿Cuáles pares de grupos difieren? Igual que Tukey, pero sin corregir por hacer muchas "
            "comparaciones: es más sensible y separa más grupos.",
            "Para cada par: si **|A − B| > LSD** (o **t calculada > t crítica**), los grupos "
            "difieren. Solo se interpreta si el ANOVA fue significativo (criterio de Fisher).")
        if ls.empty:
            st.info("Se necesitan al menos 2 grupos con 2 o más datos.")
        else:
            t_crit = ls["t crítica"].iloc[0]
            k1, k2, k3 = st.columns(3)
            k1.metric(f"t crítica (α/2 = {alfa / 2:g})", f"{t_crit:.3f}")
            k2.metric("GL del error", anova["GL error"])
            k3.metric(f"CM del error ({u2})", f"{anova['CM error']:.3f}")
            st.latex(r"LSD = t_{crít}\sqrt{CM_{error}\left(\frac{1}{n_A}+\frac{1}{n_B}\right)}"
                     r"\qquad t_{calc}=\frac{|\bar{x}_A-\bar{x}_B|}{\sqrt{CM_{error}\left(\frac{1}{n_A}+\frac{1}{n_B}\right)}}")
            if not anova["significativo"]:
                st.warning("El ANOVA no fue significativo: por el criterio de Fisher, las diferencias "
                           "que marque la LSD no deben reportarse como significativas.")
            solo = st.checkbox("Mostrar solo los pares que difieren", key="lsd_sig")
            v = ls[ls["Resultado"] == SIG] if solo else ls
            _tabla(_fmt(tabla_lsd_clara(v, u)))

            c1, c2 = st.columns([1, 1.3])
            with c1:
                st.markdown("#### Letras: Tukey vs LSD")
                comp = res["letras_tukey"].rename(columns={"Letras": "Letras Tukey", "Media": f"Promedio ({u})"})
                comp["Letras LSD"] = comp["Grupo"].map(dict(zip(res["letras_lsd"]["Grupo"], res["letras_lsd"]["Letras"])))
                _tabla(_fmt(comp))
            with c2:
                st.markdown("#### Cálculo paso a paso de un par")
                pares = [f"{a}  vs  {b}" for a, b in zip(ls["Grupo 1"], ls["Grupo 2"])]
                elegido = st.selectbox("Par", pares, key="lsd_par")
                f = ls.iloc[pares.index(elegido)]
                cme = anova["CM error"]
                ee = math.sqrt(cme * (1 / f["n1"] + 1 / f["n2"]))
                st.markdown(
                    f"- |A − B| = |{f['Media 1']:.3f} − {f['Media 2']:.3f}| = **{f['|Diferencia|']:.3f} {u}**\n"
                    f"- Error = √({cme:.3f} × (1/{f['n1']} + 1/{f['n2']})) = **{ee:.3f}**\n"
                    f"- t calculada = {f['|Diferencia|']:.3f} ÷ {ee:.3f} = **{f['t calculada']:.3f}**\n"
                    f"- t crítica (α/2 = {alfa / 2:g}; GL = {anova['GL error']}) = **{t_crit:.3f}**\n"
                    f"- LSD = {t_crit:.3f} × {ee:.3f} = **{f['LSD']:.3f} {u}**\n"
                    f"- **Conclusión:** {f['Comparación |dif| vs LSD']} → "
                    f"{'los grupos **sí difieren**' if f['Resultado'] == SIG else 'los grupos **no difieren**'}")
            st.markdown("#### Intervalos de comparación LSD")
            st.caption("Cada punto es el promedio de un grupo y su barra mide la mitad de la LSD hacia "
                       "cada lado. Regla de lectura: si las barras de dos grupos **no se tocan**, la LSD "
                       "dice que esos promedios son distintos; si se enciman, no difieren. El color y la "
                       "letra junto al punto agrupan a los que no difieren.")
            fig = grafico_intervalos_lsd(anova, res["letras_lsd"], u, agrupacion_texto,
                                         f"{nombre_var} — intervalos LSD por {agrupacion_texto.lower()}",
                                         subt_graf, escala, alfa)
            if fig is not None:
                _grafica(fig, "lsd_intervalos")
            st.markdown("#### ¿Qué pares de grupos difieren?")
            st.caption("Cada barra es un par de grupos y mide cuántos mm más midió el primero que el "
                       "segundo. La marca blanca con borde negro sobre cada barra es la LSD: la diferencia mínima "
                       "para que la prueba la considere real. **Si la barra pasa la marca, es verde y "
                       "los grupos sí difieren; si se queda antes, es gris y no difieren.**")
            fig = grafico_barras_pares(ls, u, f"{nombre_var} — ¿qué pares difieren según LSD?",
                                       subt_graf, escala, "LSD", "LSD")
            if fig is not None:
                _grafica(fig, "lsd_pares")


    # ================================================================== DESCARTES (registro)
    with t_desc_m:
        st.markdown("#### Registro de lo que se descartó")
        reglas = [f"Cajas vacías: {'se excluyen' if op.get('cajas_vacias') else 'se incluyen'}"]
        if variable in ("Raíz", "Tallo"):
            reglas.append(f"No germinadas: {'se excluyen' if op.get('no_germinadas') == 'excluir' else 'entran con 0 mm'}")
            if op.get("ceros_germinadas"): reglas.append(f"Germinadas con {variable.lower()} = 0: se excluyen")
            if op.get("rango"): reglas.append(f"Rango válido: {op['rango'][0]}–{op['rango'][1]} mm")
            if op.get("atipicos"): reglas.append(f"Atípicos: regla {op.get('factor_iqr', 1.5):g} × IQR por grupo")
        if hojas_cm: reglas.append("Convertidas de cm a mm: " + ", ".join(hojas_cm))
        if manuales: reglas.append(f"Semillas descartadas a mano: {len(manuales)}")
        st.caption(" · ".join(reglas))
        if registro.empty:
            st.write("No se descartó ningún dato.")
        else:
            resumen = (registro.groupby(["Motivo", "Efecto"]).size()
                       .reset_index(name="Registros").sort_values("Registros", ascending=False))
            _tabla(resumen)
            st.markdown("**Descartes por grupo**")
            _tabla(registro.pivot_table(index="Grupo", columns="Motivo", values="ID semilla",
                                        aggfunc="count", fill_value=0).reset_index())
            with st.expander("Ver cada semilla descartada"):
                _tabla(registro.drop(columns=["ID semilla"]), height=280)
            st.download_button("⬇️ Descargar registro de descartes (CSV)",
                               registro.to_csv(index=False).encode("utf-8-sig"),
                               file_name="registro_descartes.csv", mime="text/csv")

    # ================================================================== MÁS GRÁFICAS
    with t_graf:
        st.subheader("Más gráficas")
        bloque_explicacion(
            "Otras formas de ver los mismos datos: comparar raíz contra tallo, ver cuántas "
            "semillas germinaron y revisar si alguna caja se comporta distinto al resto de su "
            "grupo.",
            "Todas usan los filtros y descartes del panel izquierdo. Son interactivas: pasa el "
            "cursor sobre un punto o barra para ver el detalle, haz zoom arrastrando el mouse y "
            "haz clic en la leyenda para mostrar u ocultar una serie.")

        ambos = df_filtrado.copy()
        for v_ in ("Raíz", "Tallo"):
            ambos = aplicar_descartes(ambos, v_, {**op, "atipicos": False, "rango": None})[0]

        st.markdown("#### 1 · Raíz y tallo juntos, por grupo")
        st.caption("Compara, grupo por grupo, cuánto creció la raíz contra cuánto creció el "
                   "tallo (cada uno con su color). Si una barra es mucho más alta que la otra en un grupo, el "
                   "tratamiento favoreció más a esa parte de la plántula.")
        disp_rt = st.selectbox("Dispersión de esta gráfica", ["Desviación estándar", "Error estándar (SEM)"],
                               key="disp_rt")
        fig = raiz_vs_tallo(ambos, "Grupo", disp_rt, 0, subt_graf, escala,
                            etiqueta_eje=agrupacion_texto, mostrar_valores=True)
        if fig is not None:
            _grafica(fig, "mas_raiz_tallo")

        st.markdown("#### 2 · Germinaron vs no germinaron")
        st.caption("Cuántas semillas de cada grupo germinaron (color) y cuántas no (gris), en número "
                   "y en porcentaje. Útil para distinguir si un tratamiento afecta más la "
                   "germinación en sí o el crecimiento de las semillas que sí germinan.")
        fig = conteo_germinacion(df_semilla, "Grupo", 0, True, subtitulo_filtros=subt_graf,
                                 escala_fuente=escala, etiqueta_eje=agrupacion_texto)
        if fig is not None:
            _grafica(fig, "mas_germinacion")

        st.markdown("#### 3 · Correlación entre raíz y tallo (cada punto es una semilla)")
        st.caption("Si los puntos suben de izquierda a derecha, las semillas con raíz más larga "
                   "también tienden a tener tallo más largo dentro del mismo grupo. Cada color es "
                   "un grupo distinto y la línea es su tendencia general.")
        fig = correlacion_raiz_tallo(ambos, "Grupo", 0, subt_graf, escala, etiqueta_eje=agrupacion_texto)
        if fig is not None:
            _grafica(fig, "mas_correlacion")
        else:
            st.info("No hay semillas con raíz y tallo registrados a la vez para graficar.")

        st.markdown("#### 4 · Comparación entre cajas (corridas)")
        st.caption("Cada punto es una caja (la réplica real del experimento), con su propio "
                   "promedio y dispersión. Sirve para detectar si una caja en particular se aleja "
                   "mucho de las demás de su mismo grupo, lo que puede indicar un problema puntual "
                   "(contaminación, error de registro, etc.).")
        disp_cr = st.selectbox("Dispersión de esta gráfica", ["Desviación estándar", "Error estándar (SEM)"],
                               key="disp_cr")
        fig = comparacion_corridas(df_semilla, variable, "Grupo", disp_cr, None, 0,
                                   subt_graf, escala_fuente=escala, etiqueta_eje=agrupacion_texto)
        if fig is not None:
            _grafica(fig, "mas_corridas")

    # ================================================================== DESCARGAS
    with t_pdf:
        st.subheader("Descargas")
        st.caption("Todo se genera con la configuración actual del panel izquierdo: archivos, "
                   "variable, 'Comparar por', filtros, descartes, α y colores.")

        figuras = [(_nombre_figura(k, f), f) for k, f in _FIGURAS.items()]
        firma = hashlib.md5(repr((
            tipo, sel_archivos, variable, dims_ef, texto_filtros, alfa, por_caja, letras_de,
            condiciones, escala, sorted((k, str(v)) for k, v in op.items()), hojas_cm,
            len(df_an), round(float(df_an[variable].sum()), 6), [n for n, _ in figuras],
            st.session_state.get("semilla_color"),
        )).encode("utf-8")).hexdigest()
        marca = datetime.now().strftime("%Y-%m-%d_%H%M")

        def secciones_reporte():
            s = []
            datos = [("Experimento", tipo), ("Archivos", ", ".join(sel_archivos)),
                     ("Variable", f"{nombre_var} ({u})"), ("Se compara por", agrupacion_texto),
                     ("Cada dato es", f"una {'caja (promedio de sus semillas)' if por_caja else 'semilla'}"),
                     ("Nivel de significancia", f"α = {alfa}"), ("Filtros", texto_filtros),
                     ("Condiciones", condiciones), ("Pregunta del experimento", config["pregunta"])]
            metricas = [("Semillas analizadas", f"{len(df_semilla):,}"),
                        ("Cajas", str(df_semilla["Corrida"].nunique())),
                        ("Grupos comparados", str(df_an["Grupo"].nunique())),
                        (f"Datos del análisis ({unidad_txt})", str(len(df_an))),
                        ("Germinación global", f"{df_semilla[columna_germinacion(df_semilla)].mean() * 100:.1f} %"
                         if df_semilla["Germinó"].notna().any() else "—"),
                        ("Registros descartados", str(len(registro)))]
            s.append(("1. Datos del análisis", [("kv", datos), ("kv", metricas)]))

            bloques = [("tabla", tabla_correcciones(op, variable, hojas_cm, manuales, registro,
                                                    df_semilla, advertencias))]
            if registro.empty:
                bloques.append(("p", "No se descartó ningún dato."))
            else:
                bloques.append(("p", "**Descartes por grupo:**"))
                bloques.append(("tabla", registro.pivot_table(index="Grupo", columns="Motivo", values="ID semilla",
                                                              aggfunc="count", fill_value=0).reset_index()))
            bloques.append(("nota", "Cuando se quita solo el valor de la variable, la semilla sigue contando "
                                    "en el % de germinación; cuando se quita la semilla completa, deja de contar."))
            s.append(("2. Descartes y correcciones aplicados", bloques))

            if anova is None:
                s.append(("2. Resultado del ANOVA", [("p", f"Con la configuración actual, '{agrupacion_texto}' "
                                                          "no forma al menos 2 grupos con 2 o más datos.")]))
            else:
                signo = ">" if anova["F calculada"] > anova["F crítica"] else "≤"
                conclusion = ("**Sí hay diferencias significativas** entre los grupos." if anova["significativo"]
                              else "**No hay diferencias significativas** entre los grupos.")
                t_an = tabla_anova_clara(anova, u2).drop(columns=["F calc. vs F crít."], errors="ignore")
                s.append(("2. Resultado del ANOVA", [
                    ("p", f"{conclusion} F calculada = {anova['F calculada']:.3f} {signo} F crítica = "
                          f"{anova['F crítica']:.3f}; GL = {anova['GL entre']} y {anova['GL error']}; "
                          f"p = {anova['p-valor']:.4f}; α = {alfa}."),
                    ("tabla", t_an),
                    ("nota", f"GL entre grupos = k − 1 = {anova['GL entre']} · GL del error = N − k = "
                             f"{anova['GL error']} · η² = {anova['efecto']['η² (eta cuadrada)']:.3f} "
                             "(proporción de la variación explicada por los grupos)."),
                ]))

                frases = pares_significativos(tk, u) or ["Ningún par de grupos difiere según Tukey."]
                bloques = [("tabla", tabla_ranking(desc, res["letras_tukey"], res["letras_lsd"], u,
                                       germinacion_por_grupo(df_semilla))),
                           ("nota", "Grupos que comparten una letra no difieren entre sí. Tukey es la "
                                    "prueba más estricta; LSD separa más grupos."),
                           ("p", f"**Pares que difieren según Tukey (α = {alfa}):**"), ("lista", frases)]
                for clave in ("res_graf",):
                    if clave in _FIGURAS:
                        bloques.append(("fig", NOMBRES_FIGURAS[clave], _FIGURAS[clave]))
                s.append(("3. Ranking de grupos y letras", bloques))

            d_rep = desc[["Grupo", "n", "Media", "Desviación estándar", "Varianza", "SEM", "CV %"]].rename(columns={
                "n": f"n ({unidad_txt})", "Media": f"Promedio ({u})", "Desviación estándar": f"DE ({u})",
                "Varianza": f"Varianza ({u2})", "SEM": f"Error estándar ({u})", "CV %": "CV (%)"})
            s.append(("4. Promedio, desviación estándar y varianza", [
                ("tabla", d_rep),
                ("nota", "Varianza y desviación estándar muestrales (se divide entre n − 1).")]))

            if not tk.empty:
                t_tk = tabla_tukey_clara(tk, u)
                cols_tk = [c for c in t_tk.columns if c in (
                    "Grupo A", "Grupo B", "Conclusión", f"|A − B| ({u})", f"DHS ({u})",
                    "q calculada", "q crítica", "p ajustada")]
                bloques = [("p", f"q crítica = {tk['q crítica'].iloc[0]:.3f} (α = {alfa}; k = {anova['k']}; "
                                 f"GL del error = {anova['GL error']}). Dos grupos difieren si |A − B| > DHS."),
                           ("tabla", t_tk[cols_tk])]
                if "tk_cluster" in _FIGURAS:
                    bloques.append(("fig", NOMBRES_FIGURAS["tk_cluster"], _FIGURAS["tk_cluster"]))
                if "tk_barras" in _FIGURAS:
                    bloques.append(("fig", NOMBRES_FIGURAS["tk_barras"], _FIGURAS["tk_barras"]))
                    bloques.append(("nota", "Si la línea de un par no cruza el cero, esos dos grupos difieren."))
                s.append(("5. Prueba de Tukey", bloques))

            if not tc.empty:
                dg = diagnostico_cuartiles(tc, factor_q)
                t_q = tc[["Grupo", "n", "Q1 (25 %)", "Mediana (Q2)", "Q3 (75 %)", "IQR (Q3 − Q1)",
                          "Límite inferior", "Límite superior"]].copy()
                t_q["Atípicos"] = tc["Atípicos bajos"] + tc["Atípicos altos"]
                t_q["Forma"] = tc["Forma de la distribución"]
                lineas = []
                if pd.notna(dg["razon_iqr"]):
                    lineas.append(f"Dispersión: el IQR mayor ({dg['iqr_max'][0]}, {dg['iqr_max'][1]:.2f} {u}) es "
                                  f"{dg['razon_iqr']:.2f} veces el menor ({dg['iqr_min'][0]}, "
                                  f"{dg['iqr_min'][1]:.2f} {u}): "
                                  + ("dispersión parecida entre grupos." if dg["razon_iqr"] <= 2 else
                                     "dispersión muy distinta; interpretar Tukey y LSD con cuidado."))
                lineas.append("Forma: " + ("muy sesgados " + ", ".join(dg["sesgados"]) +
                                           "; en ellos la mediana representa mejor al grupo."
                                           if dg["sesgados"] else "ningún grupo está muy sesgado."))
                lineas.append(f"Atípicos: {dg['atipicos']} dato(s) fuera de Q1 − {factor_q:g}·IQR y "
                              f"Q3 + {factor_q:g}·IQR.")
                bloques = [("p", f"Cuartiles calculados sobre {nivel_txt} (interpolación lineal, igual que "
                                 "=CUARTIL.INC de Excel)."), ("tabla", t_q), ("lista", lineas)]
                if "anova_cuartiles" in _FIGURAS:
                    bloques.append(("fig", NOMBRES_FIGURAS["anova_cuartiles"], _FIGURAS["anova_cuartiles"]))
                s.append(("6. Análisis por cuartiles", bloques))

            if avisos:
                s.append(("Avisos para interpretar los resultados", [("lista", avisos)]))
            if anova:
                s.append(("Texto para el reporte", [
                    ("p", texto_reporte(variable, u, agrupacion_texto, unidad_txt, anova, tk, alfa, desc))]))
            return [(f"{i}. " + re.sub(r"^\d+\.\s*", "", t), b) for i, (t, b) in enumerate(s, 1)]

        st.markdown(
            "Todo se arma **dentro de tu navegador**: no necesitas instalar nada ni estar conectado "
            "a internet. Pulsa el botón y aparecerá un panel con los botones de descarga.")
        b1, b2 = st.columns([1, 1])
        if b1.button("Preparar descargas", type="primary", key="btn_preparar", disabled=not figuras):
            st.session_state["panel_descargas"] = firma
        abierto = st.session_state.get("panel_descargas")
        if abierto and b2.button("Cerrar el panel", key="btn_cerrar_panel"):
            st.session_state.pop("panel_descargas", None)
            abierto = None
        if abierto and abierto != firma:
            st.info("Cambiaste la configuración: pulsa **Preparar descargas** otra vez para usar los "
                    "datos actuales.")
        elif abierto:
            titulo_rep = f"Reporte BioGrow · {nombre_var} por {agrupacion_texto.lower()}"
            subt_rep = f"{tipo} · generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            html = html_descargas(titulo_rep, subt_rep, secciones_reporte(), figuras)
            with _caja():
                st.markdown(
                    "**Cómo descargar:**\n"
                    "- **📄 Reporte en PDF** y **🖼️ Gráficas en PDF:** se abre la ventana de impresión; "
                    "en *Destino* elige **Guardar como PDF** y pulsa *Guardar*.\n"
                    "- **PNG / JPG:** las imágenes se descargan directo a tu carpeta de Descargas. "
                    "Si el navegador pregunta si permites varias descargas, acepta.\n"
                    "- Cada gráfica del panel también tiene sus botones **PNG** y **JPG**.")
            mostrar_html(html, alto=950)
            st.download_button("⬇️ Guardar este panel como archivo (.html)", html.encode("utf-8"),
                               file_name=f"reporte_y_graficas_biogrow_{marca}.html", mime="text/html",
                               key="dl_html",
                               help="Por si quieres generar los PDF o imágenes después: ábrelo con "
                               "doble clic y tiene los mismos botones. Funciona sin internet.")
        with st.expander("Qué incluye el reporte"):
            st.markdown(
                "- Datos del análisis y métricas generales\n"
                "- Resultado y tabla del ANOVA\n"
                "- Ranking con letras de Tukey y LSD, y pares que difieren\n"
                "- Promedio, desviación estándar y varianza\n"
                "- Prueba de Tukey con sus gráficas\n"
                "- Análisis por cuartiles\n"
                "- Descartes, avisos y texto para el reporte\n\n"
                f"Las **{len(figuras)} gráficas** del dashboard se pueden bajar por separado: "
                + ", ".join(n for n, _ in figuras) + ".")


def _ejecutar():
    main()
    return None


if __name__ == "__main__":
    _basura = _ejecutar()
    del _basura