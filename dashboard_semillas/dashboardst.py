
from __future__ import annotations

import math
import re
import zipfile
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



PATRON_TITULO = re.compile(r"^\s*T\s*[-–]\s*0*(\d+)\s*([MNmn]?)\s*$")

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
    (16, 5): {"par": 45, "impar": 30},  
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


def _segundos_tratamiento(dia, mes, tirada):
    regla = TRATAMIENTOS_POR_FECHA.get((dia, mes))

    if regla is None:
        return 75 if tirada % 2 == 0 else 45

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
    titulos = []
    for (fila, col), valor in celdas.items():
        if isinstance(valor, str):
            coincidencia = PATRON_TITULO.match(valor.strip())
            if coincidencia:
                tirada = int(coincidencia.group(1))
                letra = coincidencia.group(2)
                titulos.append((fila, col, tirada, letra, valor.strip()))

    titulos.sort()  

    registros = []
    contador_replica = {} 

    for fila_titulo, col_bloque, tirada, letra, titulo_texto in titulos:
        codigo_clase, nombre_clase = _datos_clase(letra)
        segundos = _segundos_tratamiento(dia, mes, tirada)

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

def cargar_datos(ruta_excel: str | Path):
    ruta_excel = Path(ruta_excel)
    advertencias = []
    todos = []

    with zipfile.ZipFile(ruta_excel) as zf:
        cadenas = _leer_cadenas_compartidas(zf)
        for nombre_hoja, ruta_hoja in _mapa_hojas(zf):
            celdas = _leer_celdas(zf, ruta_hoja, cadenas)

            if _es_formato_tiempo(celdas):
                registros = _extraer_hoja_tiempo(nombre_hoja, celdas, advertencias)
            else:
                registros = _extraer_bloques_de_hoja(nombre_hoja, celdas, advertencias)

            todos.extend(registros)

    df = pd.DataFrame(todos)

    if df.empty:
        return df, advertencias

    return _postprocesar(df), advertencias


def _postprocesar(df):
    for columna in ["Raíz", "Tallo", "Germinó", "Tratamiento (s)"]:
        df[columna] = pd.to_numeric(df[columna], errors="coerce")

    df["Tratamiento"] = df["Tratamiento (s)"].apply(
        lambda s: f"{int(s)} s" if pd.notna(s) else "Sin definir"
    )
    df["Estado germinación"] = df["Germinó"].map({1: "Germinó", 0: "No germinó"})

    df["Corrida"] = (
        df["Color"].astype(str) + " | " + df["Bloque"].astype(str)
        + " | rep " + df["Réplica"].astype(str)
        + " | " + df["Hoja"].astype(str)
    )
    return df


def cargar_varios(rutas):
   
    marcos = []
    advertencias = []

    for ruta in rutas:
        ruta = Path(ruta)
        try:
            df_parcial, avisos = cargar_datos(ruta)
        except Exception as error:  
            advertencias.append(f"No se pudo leer {ruta.name}: {error}")
            continue

        advertencias.extend(f"{ruta.name}: {a}" for a in avisos)

        if not df_parcial.empty:
            df_parcial = df_parcial.copy()
            df_parcial["Archivo"] = ruta.name
            marcos.append(df_parcial)

    if not marcos:
        return pd.DataFrame(), advertencias

    df = pd.concat(marcos, ignore_index=True)
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
                "Tratamiento (s)": SEGUNDOS_TIEMPO30,
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
                "Raíz": 0.0,
                "Tallo": 0.0,
                "Germinó": 0,
                "Tratamiento (s)": SEGUNDOS_TIEMPO30,
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


def descriptivos_serie(serie):
    valores = pd.to_numeric(serie, errors="coerce").dropna()
    n = len(valores)

    base = {
        "n": n, "Media": np.nan, "Desviación estándar": np.nan,
        "Varianza": np.nan, "SEM": np.nan, "Q1": np.nan, "Mediana": np.nan,
        "Q3": np.nan, "IQR": np.nan, "Mínimo": np.nan, "Máximo": np.nan,
        "Atípicos (IQR)": 0,
    }
    if n == 0:
        return base

    sd = valores.std(ddof=1) if n > 1 else 0.0
    var = valores.var(ddof=1) if n > 1 else 0.0
    sem = sd / math.sqrt(n) if n > 0 else np.nan

    q1 = valores.quantile(0.25)
    q3 = valores.quantile(0.75)
    iqr = q3 - q1
    lim_inf = q1 - 1.5 * iqr
    lim_sup = q3 + 1.5 * iqr
    atipicos = int(((valores < lim_inf) | (valores > lim_sup)).sum())

    base.update({
        "Media": valores.mean(), "Desviación estándar": sd, "Varianza": var,
        "SEM": sem, "Q1": q1, "Mediana": valores.quantile(0.5), "Q3": q3,
        "IQR": iqr, "Mínimo": valores.min(), "Máximo": valores.max(),
        "Atípicos (IQR)": atipicos,
    })
    return base


def tabla_descriptivos(df, columna_grupo, variable):
    filas = []
    for nombre, sub in df.groupby(columna_grupo, dropna=False):
        est = descriptivos_serie(sub[variable])
        fila = {"Grupo": str(nombre)}
        fila.update(est)
        filas.append(fila)

    salida = pd.DataFrame(filas)
    if salida.empty:
        return salida
    return salida.sort_values("Media", ascending=False).reset_index(drop=True)



# ANOVA


def anova_una_via(df, variable, columna_grupo, alfa=0.05):
   
    grupos = []
    for nombre, sub in df.groupby(columna_grupo, dropna=False):
        valores = pd.to_numeric(sub[variable], errors="coerce").dropna()
        if len(valores) >= 2:
            grupos.append((str(nombre), valores))

    k = len(grupos)
    if k < 2:
        return None

    n_total = sum(len(v) for _, v in grupos)
    gran_media = np.concatenate([v.values for _, v in grupos]).mean()

    sc_entre = sum(len(v) * (v.mean() - gran_media) ** 2 for _, v in grupos)
    sc_dentro = sum(((v - v.mean()) ** 2).sum() for _, v in grupos)
    sc_total = sc_entre + sc_dentro

    gl_entre = k - 1
    gl_dentro = n_total - k
    gl_total = n_total - 1

    if gl_dentro <= 0:
        return None

    cm_entre = sc_entre / gl_entre
    cm_dentro = sc_dentro / gl_dentro

    f_calc = cm_entre / cm_dentro if cm_dentro > 0 else np.inf
    f_crit = stats.f.ppf(1 - alfa, gl_entre, gl_dentro)
    p_valor = stats.f.sf(f_calc, gl_entre, gl_dentro)

    significativo = f_calc > f_crit
    veredicto = "Diferencia significativa" if significativo else "Sin diferencia significativa"

    tabla = pd.DataFrame([
        {
            "Fuente": "Entre grupos (tratamiento)", "Suma de cuadrados": sc_entre,
            "GL": gl_entre, "Cuadrado medio": cm_entre, "F calculada": f_calc,
            f"F crítica ({int(alfa*100)}%)": f_crit, "p-valor": p_valor,
            "Resultado": veredicto,
        },
        {
            "Fuente": "Dentro de grupos (error)", "Suma de cuadrados": sc_dentro,
            "GL": gl_dentro, "Cuadrado medio": cm_dentro, "F calculada": np.nan,
            f"F crítica ({int(alfa*100)}%)": np.nan, "p-valor": np.nan, "Resultado": "",
        },
        {
            "Fuente": "Total", "Suma de cuadrados": sc_total, "GL": gl_total,
            "Cuadrado medio": np.nan, "F calculada": np.nan,
            f"F crítica ({int(alfa*100)}%)": np.nan, "p-valor": np.nan, "Resultado": "",
        },
    ])

    medias = pd.DataFrame([
        {"Grupo": nombre, "n": len(v), "Media": v.mean()} for nombre, v in grupos
    ])

    return {
        "tabla": tabla, "medias": medias, "CM error": cm_dentro,
        "GL error": gl_dentro, "GL entre": gl_entre, "k": k, "n total": n_total,
        "F calculada": f_calc, "F crítica": f_crit, "p-valor": p_valor,
        "significativo": significativo, "alfa": alfa,
    }


# Tukey HSD

def tukey_hsd(anova):
    if anova is None:
        return pd.DataFrame()

    medias = anova["medias"]
    cm_error = anova["CM error"]
    gl_error = anova["GL error"]
    k = anova["k"]
    alfa = anova["alfa"]

    if len(medias) < 2 or cm_error <= 0 or gl_error <= 0:
        return pd.DataFrame()

    q_crit = stats.studentized_range.ppf(1 - alfa, k, gl_error)
    filas = []

    for (_, g1), (_, g2) in combinations(medias.iterrows(), 2):
        diferencia = abs(g1["Media"] - g2["Media"])
        error = math.sqrt((cm_error / 2) * (1 / g1["n"] + 1 / g2["n"]))
        q_calc = diferencia / error if error > 0 else np.inf
        p_aj = stats.studentized_range.sf(q_calc, k, gl_error)
        signif = q_calc > q_crit

        filas.append({
            "Grupo 1": g1["Grupo"], "Grupo 2": g2["Grupo"],
            "n1": int(g1["n"]), "n2": int(g2["n"]),
            "Media 1": g1["Media"], "Media 2": g2["Media"],
            "Diferencia": diferencia, "q calculada": q_calc,
            f"q crítica ({int(alfa*100)}%)": q_crit, "GL error": gl_error,
            "p ajustada": p_aj,
            "Resultado": "Diferencia significativa" if signif else "Sin diferencia significativa",
        })

    return pd.DataFrame(filas).sort_values("Diferencia", ascending=False).reset_index(drop=True)


# LSD 

def lsd(anova):
    if anova is None:
        return pd.DataFrame()

    medias = anova["medias"]
    cm_error = anova["CM error"]
    gl_error = anova["GL error"]
    alfa = anova["alfa"]

    if len(medias) < 2 or cm_error <= 0 or gl_error <= 0:
        return pd.DataFrame()

    t_crit = stats.t.ppf(1 - alfa / 2, gl_error)
    filas = []

    for (_, g1), (_, g2) in combinations(medias.iterrows(), 2):
        diferencia = abs(g1["Media"] - g2["Media"])
        error = math.sqrt(cm_error * (1 / g1["n"] + 1 / g2["n"]))
        t_calc = diferencia / error if error > 0 else np.inf
        p_valor = 2 * stats.t.sf(t_calc, gl_error)
        lsd_valor = t_crit * error
        signif = diferencia > lsd_valor

        filas.append({
            "Grupo 1": g1["Grupo"], "Grupo 2": g2["Grupo"],
            "n1": int(g1["n"]), "n2": int(g2["n"]),
            "Media 1": g1["Media"], "Media 2": g2["Media"],
            "Diferencia": diferencia, "LSD": lsd_valor,
            "t calculada": t_calc, f"t crítica ({int(alfa*100)}%)": t_crit,
            "GL error": gl_error, "p-valor": p_valor,
            "Resultado": "Diferencia significativa" if signif else "Sin diferencia significativa",
        })

    return pd.DataFrame(filas).sort_values("Diferencia", ascending=False).reset_index(drop=True)


# Letras de Tukey (compact letter display)

def letras_tukey(anova, comparaciones_df):
    if anova is None or comparaciones_df is None or comparaciones_df.empty:
        return pd.DataFrame()

    medias = anova["medias"].sort_values("Media", ascending=False).reset_index(drop=True)
    grupos = medias["Grupo"].tolist()
    if len(grupos) < 2:
        return pd.DataFrame()

   
    distinto = {}
    for _, fila in comparaciones_df.iterrows():
        es_distinto = fila["Resultado"] == "Diferencia significativa"
        distinto[(fila["Grupo 1"], fila["Grupo 2"])] = es_distinto
        distinto[(fila["Grupo 2"], fila["Grupo 1"])] = es_distinto

    def difieren(a, b):
        return distinto.get((a, b), False)

    columnas = [] 
    for grupo in grupos:
        colocado = False
        for columna in columnas:
            if all(not difieren(grupo, otro) for otro in columna):
                columna.add(grupo)
                colocado = True
        if not colocado:
            columnas.append({grupo})


    finales = []
    for columna in columnas:
        if not any(columna < otra for otra in columnas if columna is not otra):
            if columna not in finales:
                finales.append(columna)

    abecedario = "abcdefghijklmnopqrstuvwxyz"
    letras_por_grupo = {g: "" for g in grupos}
    for indice, columna in enumerate(finales):
        letra = abecedario[indice] if indice < len(abecedario) else f"[{indice+1}]"
        for grupo in grupos:
            if grupo in columna:
                letras_por_grupo[grupo] += letra

    salida = medias.copy()
    salida["Letras"] = salida["Grupo"].map(letras_por_grupo)
    return salida[["Grupo", "n", "Media", "Letras"]]


import colorsys
import random


def paleta_aleatoria(n, semilla=0):
    if n <= 0:
        return ["#4C78A8"]

    rng = random.Random(semilla)
    desfase = rng.random()
    colores = []

    for i in range(n):
        tono = (desfase + i / n + rng.uniform(-0.03, 0.03)) % 1.0
        saturacion = rng.uniform(0.55, 0.85)
        brillo = rng.uniform(0.70, 0.95)
        r, g, b = colorsys.hsv_to_rgb(tono, saturacion, brillo)
        colores.append(f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}")

    return colores


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
    return resumen["Desviación estándar"], None, "desviación estándar", "Desviación estándar"


# GRÁFICO INTEGRADO DE LETRAS DE TUKEY  (pieza central)


def grafico_letras_tukey(df, variable, columna_grupo, anova, letras,
                         dispersion="Desviación estándar", referencia=None,
                         subtitulo_filtros="", escala_fuente=1.0,
                         etiqueta_eje=None, semilla_color=0):
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
                f"<b>{g}</b><br>Letra Tukey: <b>{letra}</b><br>"
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

    try:
        from scipy import stats as _st
        q_crit = _st.studentized_range.ppf(1 - anova["alfa"], anova["k"], anova["GL error"])
    except Exception:
        q_crit = float("nan")

    nombre_eje = etiqueta_eje or columna_grupo

    titulo = (
        f"<b>Letras de Tukey — {variable} por {nombre_eje}</b><br>"
        f"<sub>Grupos que comparten letra NO difieren (α={anova['alfa']}) · "
        f"GL entre grupos={anova['GL entre']} · GL del error={anova['GL error']} · "
        f"F={anova['F calculada']:.2f} vs F crítica={anova['F crítica']:.2f} · "
        f"q crítica Tukey={q_crit:.3f}"
    )
    if subtitulo_filtros:
        titulo += f"<br>{subtitulo_filtros}"
    titulo += "</sub>"

    fig.update_layout(
        title=titulo,
        xaxis_title=nombre_eje,
        yaxis_title=f"{variable}",
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

    resumen["etiqueta_x"] = resumen["Corrida"].str.replace(r" \| rep ", " r", regex=True)

    fig = px.scatter(
        resumen, x="etiqueta_x", y="Media", color="Grupo",
        error_y=col_err,
        color_discrete_sequence=paleta_aleatoria(
            max(resumen["Grupo"].nunique(), 3), semilla_color),
        hover_data=["Corrida", "Grupo", "Media", "Desviación estándar", "SEM", "n"],
        title=(f"Comparación entre corridas — {variable} (media ± {etiqueta})" +
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
        xaxis_title="Corrida (bloque + réplica)",
        yaxis_title=f"Media de {variable} por corrida (± {etiqueta})",
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

    conteo["etiqueta"] = conteo["Semillas"].astype(str) + " (" + conteo["%"].astype(str) + "%)"

    fig = px.bar(
        conteo, x=columna_grupo, y="Semillas", color="Estado germinación",
        barmode="stack", text="etiqueta" if mostrar_valores else None,
        hover_data={columna_grupo: True, "Estado germinación": True,
                    "Semillas": True, "%": True, "Total": True},
        color_discrete_map={"Germinó": "#2E8B57", "No germinó": "#C0392B"},
        title=(f"Germinaron vs no germinaron por {etiqueta_eje or columna_grupo}" +
               (f"<br><sub>{subtitulo_filtros}</sub>" if subtitulo_filtros else "")),
    )
    if mostrar_valores:
        fig.update_traces(textposition="inside", textfont_size=11)


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
            t = f"{fila['Media']:.1f}"
            if col_txt is not None and pd.notna(fila[col_txt]):
                t += f"±{fila[col_txt]:.1f}"
            textos.append(t)

        fig.add_trace(go.Bar(
            x=datos["Grupo"], y=datos["Media"], name=variable,
            marker_color=colores[indice],
            error_y=dict(type="data", array=err_mas,
                         arrayminus=err_menos if err_menos is not None else None,
                         visible=True),
            text=textos, textposition="outside",
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
    fig.update_traces(cliponaxis=False, selector=dict(type="bar"))
    return aplicar_tipografia(fig, escala_fuente)

import random

import streamlit.components.v1 as components


CARPETA = Path(__file__).resolve().parent

def encontrar_excels():
    return sorted(p for p in CARPETA.glob("*.xlsx") if not p.name.startswith("~$"))


def redondear(df, decimales=4):
    salida = df.copy()
    for c in salida.select_dtypes(include="number").columns:
        salida[c] = salida[c].round(decimales)
    return salida


@st.cache_data(show_spinner="Leyendo los archivos de Excel…")
def _cargar(rutas_str, firmas):
    return cargar_varios(rutas_str)


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

    components.html(
        """
        <script>
        try {
            const doc = window.parent.document;
            doc.documentElement.setAttribute('translate', 'no');
            doc.documentElement.classList.add('notranslate');
            if (!doc.querySelector('meta[name="google"][content="notranslate"]')) {
                const meta = doc.createElement('meta');
                meta.name = 'google';
                meta.content = 'notranslate';
                doc.head.appendChild(meta);
            }
        } catch (e) { /* si el navegador lo impide, no pasa nada */ }
        </script>
        """,
        height=0,
    )


def main():
    st.set_page_config(page_title="Dashboard de semillas", layout="wide")
    _bloquear_traduccion_automatica()
    st.title("🌱 Dashboard estadístico de semillas")

    rutas = encontrar_excels()
    if not rutas:
        st.error(f"No hay ningún .xlsx en la carpeta del script ({CARPETA}). "
                 "Coloca los archivos de datos y recarga.")
        st.stop()

    firmas = tuple((p.name, p.stat().st_mtime) for p in rutas)
    df, advertencias = _cargar([str(p) for p in rutas], firmas)

    if df.empty:
        st.error("Los archivos se leyeron pero no se detectaron bloques de datos.")
        st.stop()

    st.caption("Archivos leídos: " + " · ".join(p.name for p in rutas))

    st.sidebar.header("⚙️ Configuración")

    st.sidebar.subheader("Variedades de maíz")
    st.sidebar.write("PBB-DH-183")
    st.sidebar.write("H-392 A")
    st.sidebar.write("CACAHUAZINTLE")
    st.sidebar.write("CRIOLLO")
    df = variedad_por_color(df)

    alfa = 0.05 if st.sidebar.radio(
        "Significancia (α) para Tukey y LSD", ["5% (0.05)", "1% (0.01)"]
    ).startswith("5") else 0.01

    variable = st.sidebar.selectbox("Variable de análisis", ["Raíz", "Tallo", "Germinó"])
    if "semilla_color" not in st.session_state:
        st.session_state.semilla_color = random.randint(0, 10_000)

    if st.sidebar.button("🎨 Cambiar colores"):
        st.session_state.semilla_color = random.randint(0, 10_000)

    semilla_color = st.session_state.semilla_color

    with st.sidebar.expander("🌡️ Condiciones experimentales"):
        flujo = st.slider("Flujo (L/min)", min_value=0, max_value=10, value=0, step=1)
        temperatura = st.number_input("Temperatura (°C)", value=25.0, step=0.5,
                                      format="%.1f")
        tipo_gas = st.selectbox(
            "Tipo de gas",
            ["Atmosférico", "Argón", "Helio", "Oxígeno", "Ambiente"],
        )

    condiciones = f"Flujo: {flujo} L/min · Temp: {temperatura:.1f} °C · Gas: {tipo_gas}"

    escala_fuente = st.sidebar.slider(
        "Tamaño de letra", min_value=0.8, max_value=2.0, value=1.0, step=0.1,
        help="Aumenta el tamaño de letra de las gráficas y de la página. "
        "1.0 = normal, 1.5 = 50% más grande.",
    )


    st.markdown(
        f"""
        <style>
        html, body, [class*="css"], .stMarkdown, .stText,
        div[data-testid="stMetricValue"], div[data-testid="stMetricLabel"],
        .stDataFrame, .stSelectbox, .stMultiSelect, .stRadio, .stCheckbox {{
            font-size: {escala_fuente}rem !important;
        }}
        h1 {{ font-size: {2.2 * escala_fuente}rem !important; }}
        h2 {{ font-size: {1.7 * escala_fuente}rem !important; }}
        h3 {{ font-size: {1.4 * escala_fuente}rem !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.header("🔎 Filtros (acotar datos)")
    st.sidebar.caption(
        "Los filtros REDUCEN qué datos entran al análisis (vacío = todo). "
        "Para elegir cómo AGRUPAR/comparar, usa la sección '📊 Comparar por' más abajo."
    )

    f_archivo = st.sidebar.multiselect(
        "Archivo de origen", sorted(df["Archivo"].unique()),
        help="Los datos provienen de varios Excel. Filtra por origen si quieres "
        "analizarlos por separado.",
    )
    f_var = st.sidebar.multiselect("Variedad", sorted(df["Variedad"].unique()))
    f_clase = st.sidebar.multiselect("Clase", ["Embrión", "Endospermo", "Patrón"])
    f_fecha = st.sidebar.multiselect("Fecha / sesión (elige 2 para contraste cara a cara)",
                                     sorted(df["Hoja"].unique()))
    f_trat = st.sidebar.multiselect(
        "Tratamiento (segundos)",
        sorted(df["Tratamiento"].unique(),
               key=lambda x: (0, int(re.search(r"\d+", x).group())) if re.search(r"\d+", x) else (1, x)),
        help="El tratamiento ya incluye la paridad (par/impar) según la fecha, "
        "por eso no hay un filtro de paridad aparte.",
    )
    f_tirada = st.sidebar.multiselect(
        "Tirada / experimento", sorted(df["Tirada"].unique()),
        help="Número de tirada (archivo de datos crudos) o de experimento "
        "(archivo de tiempo). 0 = bloques de control sin número.",
    )

    def filtrar(base):
        s = base
        if f_archivo: s = s[s["Archivo"].isin(f_archivo)]
        if f_var: s = s[s["Variedad"].isin(f_var)]
        if f_clase: s = s[s["Clase nombre"].isin(f_clase)]
        if f_fecha: s = s[s["Hoja"].isin(f_fecha)]
        if f_trat: s = s[s["Tratamiento"].isin(f_trat)]
        if f_tirada: s = s[s["Tirada"].isin(f_tirada)]
        return s

    df_filtrado = filtrar(df)

    partes_filtro = []
    if f_archivo: partes_filtro.append("Archivo: " + ", ".join(f_archivo))
    if f_var: partes_filtro.append("Variedad: " + ", ".join(f_var))
    if f_clase: partes_filtro.append("Clase: " + ", ".join(f_clase))
    if f_fecha: partes_filtro.append("Fecha: " + ", ".join(f_fecha))
    if f_trat: partes_filtro.append("Trat.: " + ", ".join(f_trat))
    if f_tirada: partes_filtro.append("Tirada: " + ", ".join(map(str, f_tirada)))
    subtitulo_filtros = "Filtros → " + " | ".join(partes_filtro) if partes_filtro else "Sin filtros (todos los datos)"
   
    subtitulo_filtros = subtitulo_filtros + "  ·  " + condiciones

 
    st.sidebar.header("📊 Comparar por (agrupar)")
    st.sidebar.caption("Define en qué grupos se divide el eje X de las gráficas y las pruebas.")
    etiquetas = {
        "Tratamiento": "Tratamiento (segundos)",
        "Clase nombre": "Clase (Embrión/Endospermo/Patrón)",
        "Variedad": "Variedad de semilla",
        "Tirada": "Tirada / experimento",
        "Bloque": "Bloque (ej. T-1M, Exp1-M)",
        "Hoja": "Fecha / sesión",
        "Archivo": "Archivo de origen",
        "Corrida": "Corrida (bloque+réplica)",
    }
    dimensiones = st.sidebar.multiselect(
        "Dimensiones (se combinan entre sí)", list(etiquetas.keys()),
        default=["Tratamiento"], format_func=lambda x: etiquetas[x],
        help="Elige una o varias. Ejemplo: Variedad + Clase compara "
        "Blanca-Embrión vs Rosa-Embrión, etc. Nota: no repitas aquí algo que ya "
        "fijaste en un filtro (si filtraste una sola variedad, agrupar por "
        "variedad no aporta).",
    )
    if not dimensiones:
        dimensiones = ["Tratamiento"]

    consolidar = st.sidebar.checkbox(
        "Consolidar réplicas (unir M o N de todas las tiradas)", value=False,
    )

    st.sidebar.header("🧹 Descartes")
    quitar_ng = st.sidebar.checkbox("Excluir no germinadas (Germinó=0)", value=False)
    quitar_ceros = st.sidebar.checkbox(f"Excluir ceros en {variable}", value=False)

    usar_rango, rango = False, None
    if variable in ("Raíz", "Tallo"):
        serie = pd.to_numeric(df_filtrado[variable], errors="coerce").dropna()
        if not serie.empty and int(serie.min()) < int(serie.max()):
            usar_rango = st.sidebar.checkbox("Descartar fuera de un rango", value=False)
            if usar_rango:
                rango = st.sidebar.slider(f"Rango válido de {variable}",
                                          int(serie.min()), int(serie.max()),
                                          (int(serie.min()), int(serie.max())))

    with st.sidebar.expander("Descartes manuales"):
        corr_excl = st.multiselect("Excluir corridas", sorted(df_filtrado["Corrida"].unique()))
        sem_excl = st.multiselect("Excluir números de semilla", list(range(1, 28)))

    def descartar(base):
        s = base
        if corr_excl: s = s[~s["Corrida"].isin(corr_excl)]
        if sem_excl: s = s[~s["No"].isin(sem_excl)]
        if quitar_ng and variable != "Germinó": s = s[s["Germinó"] == 1]
        if quitar_ceros: s = s[s[variable].notna() & (s[variable] != 0)]
        if usar_rango and rango: s = s[s[variable].notna() & (s[variable] >= rango[0]) & (s[variable] <= rango[1])]
        return s

    df_datos = descartar(df_filtrado).copy()

    dims_ef = list(dimensiones)
    if consolidar and "Corrida" in dims_ef:
        dims_ef.remove("Corrida")
        if not dims_ef: dims_ef = ["Clase nombre"]
    df_datos["Grupo"] = construir_grupo(df_datos, dims_ef)

  
    st.write(
        "**T**=tirada · **M**=embrión · **N**=endospermo · sin M/N (T-01…T-05)=**patrón**. "
        "El tratamiento (s) se asigna por fecha y paridad. Todo se recalcula con el "
        "panel lateral."
    )
    if advertencias:
        with st.expander(f"⚠️ Advertencias de lectura ({len(advertencias)})"):
            for a in advertencias: st.write("•", a)

    if df_datos.empty:
        st.warning("No quedan datos con los filtros y descartes actuales.")
        st.stop()

   
    anova = anova_una_via(df_datos, variable, "Grupo", alfa=alfa)
    tukey = tukey_hsd(anova) if anova else pd.DataFrame()
    tabla_lsd = lsd(anova) if anova else pd.DataFrame()
    letras = letras_tukey(anova, tukey) if anova else pd.DataFrame()
    letras_lsd = letras_tukey(anova, tabla_lsd) if anova else pd.DataFrame()

    letras_combinadas = pd.DataFrame()
    if not letras.empty:
        letras_combinadas = letras.rename(columns={"Letras": "Letras Tukey"}).copy()
        if not letras_lsd.empty:
            mapa_lsd = dict(zip(letras_lsd["Grupo"], letras_lsd["Letras"]))
            letras_combinadas["Letras LSD"] = letras_combinadas["Grupo"].map(mapa_lsd)

    def ref_patron(hoja=None):
        r = df[df["Clase"] == "S"]
        if hoja is not None: r = r[r["Hoja"] == hoja]
        if f_archivo: r = r[r["Archivo"].isin(f_archivo)]
        if f_var: r = r[r["Variedad"].isin(f_var)]
        if quitar_ng and variable != "Germinó": r = r[r["Germinó"] == 1]
        if quitar_ceros: r = r[r[variable].notna() & (r[variable] != 0)]
        return descriptivos_serie(r[variable])

   
    st.subheader("1. Datos en uso")

    agrupacion_texto = " + ".join(etiquetas[d] for d in dimensiones)
    st.info(
        f"**Variable:** {variable}  ·  **Agrupando por:** {agrupacion_texto}  ·  "
        f"**α:** {alfa}\n\n"
        f"**Condiciones:** {condiciones}\n\n{subtitulo_filtros}"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Semillas", len(df_datos))
    c2.metric("Corridas", df_datos["Corrida"].nunique())
    c3.metric("Grupos", df_datos["Grupo"].nunique())
    pg = df_datos["Germinó"].mean() * 100 if df_datos["Germinó"].notna().any() else 0
    c4.metric("% germinación", f"{pg:.1f}%")

  
    # GRÁFICO DE LETRAS DE TUKEY  
  
    st.subheader("2. Gráfico de letras de Tukey")

    dos_fechas = len(f_fecha) == 2

    usar_ref = st.checkbox("Mostrar referencia del patrón", value=True)

    st.caption(
        f"**Cómo leerlo:** cada caja es un grupo (mediana, cuartiles Q1–Q3 y "
        f"bigotes), ordenadas de mayor a menor media. La(s) letra(s) sobre cada "
        f"caja indican grupos homogéneos: si dos grupos comparten al menos una "
        f"letra **no** difieren significativamente (α={alfa}); si no comparten "
        f"ninguna, **sí** difieren. Los grupos con la misma letra comparten color. "
        f"El boxplot siempre muestra cuartiles (es su naturaleza); el control de "
        f"desviación/SEM está en la sección 3."
    )

  
    zona_aviso = st.container()
    zona_grafico = st.container()
    zona_tabla = st.container()

    CLAVE_GRAFICO_S2 = "grafico_seccion2"

    if anova is None:
        n_grupos = df_datos["Grupo"].nunique()

        utiles = []
        for clave, etiqueta in etiquetas.items():
            if clave in df_datos.columns and df_datos[clave].nunique() >= 2:
                utiles.append(f"**{etiqueta}** ({df_datos[clave].nunique()} niveles)")

        mensaje = (
            f"Con los filtros actuales, '{agrupacion_texto}' produce "
            f"**{n_grupos} grupo(s)**. El ANOVA y las pruebas post-hoc necesitan "
            f"al menos 2 grupos con 2 o más semillas cada uno."
        )
        if utiles:
            mensaje += (
                "\n\nEn los datos que tienes ahora, estas dimensiones sí dividen "
                "en varios grupos: " + " · ".join(utiles) +
                ". Cámbialas en '📊 Comparar por'."
            )
        else:
            mensaje += ("\n\nNinguna dimensión divide estos datos en varios grupos. "
                        "Quita algún filtro para incluir más datos.")

        with zona_aviso:
            st.warning(mensaje)

        figura_s2 = medias_por_grupo(
            df_datos, variable, "Grupo", "Desviación estándar",
            referencia=ref_patron() if usar_ref else None,
            mostrar_valores=True, grado_polinomio=0,
            semilla_color=semilla_color,
            subtitulo_filtros=subtitulo_filtros,
            escala_fuente=escala_fuente, etiqueta_eje=agrupacion_texto,
        )
        with zona_grafico:
            if figura_s2 is not None:
                st.plotly_chart(figura_s2, use_container_width=True,
                                key=CLAVE_GRAFICO_S2)
            else:
                st.info("Sin datos para graficar con los filtros actuales.")

        with zona_tabla:
            st.caption("La tabla de letras de Tukey requiere al menos 2 grupos.")

    elif dos_fechas:
        with zona_aviso:
            st.info("Contraste cara a cara: cada fecha con su propio ANOVA y letras de Tukey.")

        with zona_grafico:
            cols = st.columns(2)
            for indice, (columna, hoja) in enumerate(zip(cols, f_fecha)):
                with columna:
                    st.markdown(f"**{hoja}**")
                    sub = df_datos[df_datos["Hoja"] == hoja]
                    an_h = anova_una_via(sub, variable, "Grupo", alfa=alfa)

                    if an_h is None:
                        st.info("Sin grupos suficientes en esta fecha.")
                        continue

                    let_h = letras_tukey(an_h, tukey_hsd(an_h))
                    fig_h = grafico_letras_tukey(
                        sub, variable, "Grupo", an_h, let_h,
                        referencia=ref_patron(hoja) if usar_ref else None,
                        subtitulo_filtros=f"Fecha: {hoja}",
                        escala_fuente=escala_fuente,
                        etiqueta_eje=agrupacion_texto,
                    )
                    if fig_h is not None:
                        st.plotly_chart(fig_h, use_container_width=True,
                                        key=f"{CLAVE_GRAFICO_S2}_fecha_{indice}")
                    else:
                        st.info("Sin datos para esta fecha.")

        with zona_tabla:
            st.caption("En el contraste por fecha, cada panel tiene sus propias letras.")

    else:
        with zona_aviso:
            if letras.empty:
                st.info("No se pudieron calcular las letras de Tukey; se muestra la distribución.")
            else:
                st.caption(f"{anova['k']} grupos comparados · α = {alfa}")

        hoja_ref = f_fecha[0] if len(f_fecha) == 1 else None
        figura_s2 = grafico_letras_tukey(
            df_datos, variable, "Grupo", anova, letras,
            referencia=ref_patron(hoja_ref) if usar_ref else None,
            subtitulo_filtros=subtitulo_filtros,
            escala_fuente=escala_fuente,
            etiqueta_eje=agrupacion_texto,
        )
        with zona_grafico:
            if figura_s2 is not None:
                st.plotly_chart(figura_s2, use_container_width=True,
                                key=CLAVE_GRAFICO_S2)
            else:
                st.info("Sin datos para el gráfico de letras.")

        with zona_tabla:
            if not letras_combinadas.empty:
                st.markdown("**Comparación de métodos:** letras de Tukey vs LSD")
                st.dataframe(redondear(letras_combinadas), use_container_width=True, hide_index=True)
                st.caption(
                    "Tukey es más conservador (agrupa más); LSD es más sensible "
                    "(separa más). Si un par comparte letra en Tukey pero no en LSD, "
                    "la diferencia es pequeña pero detectable."
                )


    st.subheader("3. Otras gráficas")

    g1, g2 = st.columns(2)
    with g1:
        otra = st.selectbox(
            "Gráfica",
            ["Raíz y Tallo juntos", "Comparación entre corridas",
             "Medias por grupo", "Conteo de germinación"],
            help="'Raíz y Tallo juntos' muestra las dos mediciones a la vez, "
            "una barra de cada una por grupo.",
        )
    with g2:
        dispersion = st.selectbox(
            "Dispersión (barra de error)",
            ["Desviación estándar", "Error estándar (SEM)", "Cuartiles (IQR)"],
            help="Sustituye el bigote por SD, SEM o cuartiles en las gráficas que "
            "usan barras de error.",
        )

    g3, g4 = st.columns(2)
    with g3:
        mostrar_valores = st.checkbox("Valores sobre barras", value=True)
    with g4:
        grado = st.select_slider(
            "Ajuste polinomial (solo 'Medias por grupo')",
            options=[0, 1, 2, 3, 4], value=0,
        )

    orden_x = "Por media (descendente)"
    if otra == "Medias por grupo":
        orden_x = st.radio(
            "Orden del eje X",
            ["Por media (descendente)", "Por valor del eje (ascendente)"],
            horizontal=True,
            help="Usa 'Por valor del eje' cuando los grupos son números (ej. "
            "tratamiento en segundos: 30→45→60→75→120). Así el ajuste polinomial "
            "es interpretable como una tendencia real. 'Por media' solo ordena las "
            "barras de mayor a menor y la curva no representa una tendencia.",
        )
        if grado > 0 and orden_x == "Por media (descendente)":
            st.warning(
                "Con el eje ordenado 'por media', la curva roja solo sigue el orden "
                "de las barras y NO es una tendencia real. Para leer bien el ajuste "
                "polinomial, cambia a 'Por valor del eje' (funciona cuando los grupos "
                "son numéricos, como los segundos)."
            )

    sub = ""
    if anova:
        sub = (f"ANOVA F={anova['F calculada']:.2f} · F crítica={anova['F crítica']:.2f} · "
               f"GL entre={anova['GL entre']} · GL error={anova['GL error']}")

    ref_actual = ref_patron(f_fecha[0] if len(f_fecha) == 1 else None) if usar_ref else None

    if otra == "Comparación entre corridas":
        st.caption(
            "Cada punto es una corrida (bloque + réplica) con su media y la barra "
            "de error elegida (desviación estándar o SEM). Sirve para ver cómo se "
            "dispersan las corridas dentro de cada grupo y detectar corridas atípicas."
        )
        fig = comparacion_corridas(df_datos, variable, "Grupo", dispersion,
                                      ref_actual, semilla_color, subtitulo_filtros,
                                      escala_fuente=escala_fuente,
                                      etiqueta_eje=agrupacion_texto)
    elif otra == "Raíz y Tallo juntos":
        st.caption(
            "Dos barras por grupo: la media de **Raíz** y la de **Tallo**, con su "
            "barra de error. Permite ver si un tratamiento afecta igual a ambas "
            "mediciones o solo a una."
        )
        fig = raiz_vs_tallo(df_datos, "Grupo", dispersion, semilla_color,
                               subtitulo_filtros, escala_fuente,
                               etiqueta_eje=agrupacion_texto,
                               mostrar_valores=mostrar_valores)
    elif otra == "Conteo de germinación":
     
        base_pat = df[df["Clase"] == "S"]
        if f_archivo: base_pat = base_pat[base_pat["Archivo"].isin(f_archivo)]
        if f_var: base_pat = base_pat[base_pat["Variedad"].isin(f_var)]
        if len(f_fecha) == 1: base_pat = base_pat[base_pat["Hoja"] == f_fecha[0]]

        germ_pat = None
        if usar_ref and base_pat["Germinó"].notna().any():
            germ_pat = base_pat["Germinó"].mean() * 100

        if germ_pat is not None:
            st.caption(
                f"La línea dorada marca la tasa de germinación del **patrón "
                f"(control)**: {germ_pat:.1f}%. Sirve para ver qué grupos germinan "
                f"por encima o por debajo del control."
            )

        fig = conteo_germinacion(df_datos, "Grupo", semilla_color, mostrar_valores,
                                    subtitulo_filtros=subtitulo_filtros,
                                    escala_fuente=escala_fuente,
                                    etiqueta_eje=agrupacion_texto,
                                    germinacion_patron=germ_pat)
    else:
        fig = medias_por_grupo(df_datos, variable, "Grupo", dispersion, ref_actual,
                                  mostrar_valores, grado, semilla_color, sub,
                                  subtitulo_filtros=subtitulo_filtros, orden=orden_x,
                                  escala_fuente=escala_fuente,
                                  etiqueta_eje=agrupacion_texto)
    with st.container():
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, key=f"graf_seccion3_{otra}")
        else:
            st.info("Sin datos para esta gráfica.")

   
    st.subheader("4. Descriptivos por grupo")
    st.caption("n, promedio, mediana, desviación estándar, varianza y error estándar de la media (SEM).")
    _desc = tabla_descriptivos(df_datos, "Grupo", variable)
    _cols_desc = ["Grupo", "n", "Media", "Mediana", "Desviación estándar", "Varianza", "SEM"]
    _cols_desc = [c for c in _cols_desc if c in _desc.columns]
    st.dataframe(redondear(_desc[_cols_desc]),
                 use_container_width=True, hide_index=True)


    st.subheader(f"5. ANOVA de una vía (α = {alfa})")
    if variable == "Germinó":
        st.info("Con Germinó (1/0), el ANOVA compara proporciones de germinación.")

    if anova is None:
        st.info(
            "No se puede calcular el ANOVA con la agrupación actual "
            f"('{agrupacion_texto}' da un solo grupo). Elige otra dimensión en "
            "'📊 Comparar por' o amplía los filtros."
        )
    else:
        st.dataframe(redondear(anova["tabla"]), use_container_width=True, hide_index=True)

        if anova["significativo"]:
            st.success(f"F={anova['F calculada']:.3f} > F crítica={anova['F crítica']:.3f} "
                       f"(p={anova['p-valor']:.4g}). Hay diferencias significativas.")
        else:
            st.info(f"F={anova['F calculada']:.3f} ≤ F crítica={anova['F crítica']:.3f} "
                    f"(p={anova['p-valor']:.4g}). No hay diferencias significativas.")

    st.subheader(f"6. Post-hoc: Tukey HSD y LSD (α = {alfa})")
    tt, tl = st.tabs(["Tukey HSD", "LSD"])
    with tt:
        if tukey.empty:
            st.warning("No fue posible calcular Tukey.")
        else:
            solo = st.checkbox("Solo significativas", key="t_sig")
            v = tukey[tukey["Resultado"] == "Diferencia significativa"] if solo else tukey
            st.dataframe(redondear(v), use_container_width=True, hide_index=True)
    with tl:
        if tabla_lsd.empty:
            st.warning("No fue posible calcular LSD.")
        else:
            solo = st.checkbox("Solo significativas", key="l_sig")
            v = tabla_lsd[tabla_lsd["Resultado"] == "Diferencia significativa"] if solo else tabla_lsd
            st.dataframe(redondear(v), use_container_width=True, hide_index=True)

    with st.expander("Ver datos detallados en uso"):
        cols = ["Archivo", "Hoja", "Variedad", "Clase nombre", "Tirada", "Bloque",
                "Réplica", "Corrida", "No", "Tratamiento", "Tratamiento (s)", "Grupo",
                "Raíz", "Tallo", "Germinó", "Estado germinación"]
        cols = [c for c in cols if c in df_datos.columns]
        st.dataframe(df_datos[cols], use_container_width=True, hide_index=True)


def _ejecutar():
    main()
    return None


if __name__ == "__main__":
    _basura = _ejecutar()
    del _basura