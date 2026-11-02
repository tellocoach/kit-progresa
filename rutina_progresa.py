#!/usr/bin/env python3
"""Rutina Progresa: lee los expedientes de las alumnas y arma el resumen del coach.

La rutina de Claude solo descarga archivos de Drive y corre este script.
Todo el calculo vive aqui para que cada semana salga igual y gaste pocos tokens.

Subcomandos:
  decodificar <json_guardado> <salida.xlsx>
      Convierte la descarga del conector de Drive (JSON con base64) en un .xlsx.
  analizar --alumnas alumnas.json --respuestas respuestas.txt --salida DIR
      Lee cada expediente y escribe en DIR: maestra.csv, telegram.html,
      push.txt e informe.txt.
  telegram --mensaje DIR/telegram.html --enlace URL
      Manda el resumen al chat del coach. Usa TELEGRAM_BOT_TOKEN y
      TELEGRAM_CHAT_ID del entorno y nunca los imprime.

Celdas de la plantilla (cambia aqui si tu plantilla es distinta):
"""
import argparse
import base64
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

# ---------------------------------------------------------------- configuracion
CONFIG = {
    "hoja_intro": "INTRO \U0001F4D6",
    "hoja_revisiones": "REVISIONES INTEGRALES \U0001F525",
    "intro": {"nombre": "E6", "correo": "E7", "peso": "E8", "mesociclo": "E14"},
    "fecha_inicio": "D11",
    "semanas": 12,
    "fila_semana_1": 27,      # la semana k empieza en 27 + 19*(k-1)
    "paso_semana": 19,
    "sesiones_por_semana": 6,
    "bloques_sesion": [2, 21, 40, 59, 78, 97],  # columna donde empieza cada sesion en MC1..MC12
    "umbral_dias_sin_registrar": 5,   # dias sin pasos, sueno ni check-in para avisar
    # Sistema de pagos en INTRO: fechas de cada pago y la casilla de "pagado" debajo.
    "pagos": {"tipo": "B35", "cantidad": "C35",
              "fechas": ["C37", "D37", "E37"], "pagado": ["C38", "D38", "E38"]},
    "dias_aviso_pago": 7,             # avisar cuando el siguiente pago esta a 7 dias o menos
    "dias_aviso_renovacion": 7,       # avisar cuando el mesociclo termina en 7 dias o menos
    "apego_min": 0.90,
    "apego_max": 1.10,
    "formato_fecha_formulario": "dmy",  # Google Forms en Mexico: 2/11/2026 = 2 de noviembre
    "zona_horaria_horas": -6,           # America/Mexico_City, sin horario de verano
}

# Palabras clave. "dol*" = cualquier palabra que empiece con "dol" (dolor, dolía, dolían).
# "!" al inicio = cuenta aunque haya un "no" antes ("no me abandone").
ROJO = ["mal", "dol*", "duel*", "lesion*", "lastim*", "enferm*", "mare*", "vomit*",
        "fiebre", "diarre*", "nause*", "malestar*", "inflam*", "molesti*", "desmay*",
        "fractur*", "esguince*", "torced*"]
NARANJA = ["desanimad*", "sin ganas", "cansad*", "agotad*", "no pude", "no he podido",
           "estres*", "ansie*", "ansios*", "triste*", "desmotivad*", "flojera",
           "mas o menos", "regular", "me cuesta", "!abandon*"]
AJUSTE = ["cambiar", "cambiame", "cambio", "quitar", "quita", "quitame", "quitarme",
          "agrega", "agregar", "agregame", "ajuste", "ajustar", "sustituir", "mover"]
NEGACIONES = {"no", "sin", "ningun", "ninguna", "ninguno", "cero", "nada"}

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
ORDEN = {"ROJO": 0, "NARANJA": 1, "VERDE": 2}
ICONO = {"ROJO": "\U0001F534", "NARANJA": "\U0001F7E0", "VERDE": "\U0001F7E2"}


# ---------------------------------------------------------------- utilidades
def sin_acentos(texto):
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def palabras(texto):
    return re.findall(r"[a-z0-9]+", sin_acentos(texto))


def busca(texto, lista):
    """Devuelve las expresiones de la lista que aparecen sin una negacion justo antes."""
    w = palabras(texto)
    hallados = []
    for expr in lista:
        ignora_negacion = expr.startswith("!")
        e = expr.lstrip("!").split()
        for i in range(len(w) - len(e) + 1):
            coincide = all(
                w[i + j].startswith(t[:-1]) if t.endswith("*") else w[i + j] == t
                for j, t in enumerate(e))
            if coincide and (ignora_negacion or not (NEGACIONES & set(w[max(0, i - 3):i]))):
                hallados.append(expr)
                break
    return hallados


def celda(ref):
    m = re.match(r"([A-Z]+)(\d+)", ref)
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return int(m.group(2)), col


def ahora():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=CONFIG["zona_horaria_horas"]))).replace(tzinfo=None)


def a_fecha(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, (int, float)) and 20000 < v < 80000:  # numero de serie de hoja de calculo
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(v))
    if isinstance(v, str):
        for f in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                return dt.datetime.strptime(v.strip(), f).date()
            except ValueError:
                pass
    return None


def a_horas(v):
    if isinstance(v, dt.time):
        return v.hour + v.minute / 60
    if isinstance(v, dt.timedelta):
        return v.total_seconds() / 3600
    if isinstance(v, dt.datetime):
        return v.hour + v.minute / 60
    if isinstance(v, (int, float)):
        return v * 24 if v < 1 else float(v)
    return None


def num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ".").strip())
        except ValueError:
            return None
    return None


def promedio(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def miles(n):
    return f"{n:,.0f}".replace(",", " ")


def fecha_corta(d):
    return f"{d.day} {MESES[d.month - 1]}"


def nombre_bonito(carpeta, intro_nombre):
    base = re.sub(r"^\s*\d+\s*[.)-]?\s*", "", carpeta or "").strip() or (intro_nombre or "")
    return " ".join(p.capitalize() for p in base.split())


# ---------------------------------------------------------------- lectura del expediente
class Hoja:
    """Lee una pestana una sola vez en modo rapido y responde celdas por (fila, columna)."""

    def __init__(self, wb, nombre, max_fila, max_col):
        self.filas = []
        if nombre in wb.sheetnames:
            self.filas = [list(r) for r in wb[nombre].iter_rows(
                min_row=1, max_row=max_fila, max_col=max_col, values_only=True)]

    def v(self, fila, col):
        if 0 < fila <= len(self.filas) and 0 < col <= len(self.filas[fila - 1]):
            return self.filas[fila - 1][col - 1]
        return None

    def ref(self, r):
        return self.v(*celda(r))


def lee_expediente(ruta):
    import openpyxl
    wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    intro = Hoja(wb, CONFIG["hoja_intro"], 40, 12)
    rev = Hoja(wb, CONFIG["hoja_revisiones"], 260, 26)
    pagos = []
    for ref_fecha, ref_pagado in zip(CONFIG["pagos"]["fechas"], CONFIG["pagos"]["pagado"]):
        fecha = a_fecha(intro.ref(ref_fecha))
        if fecha and fecha.year >= 2000:  # una fecha vacia sale como 1900 por la formula +30
            pagado = intro.ref(ref_pagado)
            pagos.append({"fecha": fecha, "pagado": pagado if isinstance(pagado, bool) else None})
    exp = {
        "pagos": pagos,
        "tipo_pago": intro.ref(CONFIG["pagos"]["tipo"]),
        "cantidad": num(intro.ref(CONFIG["pagos"]["cantidad"])),
        "nombre": intro.ref(CONFIG["intro"]["nombre"]),
        "correo": intro.ref(CONFIG["intro"]["correo"]),
        "peso_inicial": num(intro.ref(CONFIG["intro"]["peso"])),
        "mesociclo": str(intro.ref(CONFIG["intro"]["mesociclo"]) or "").replace("#", "").strip() or None,
        "inicio": a_fecha(rev.ref(CONFIG["fecha_inicio"])),
        "semanas": [],
    }
    for k in range(1, CONFIG["semanas"] + 1):
        b = CONFIG["fila_semana_1"] + CONFIG["paso_semana"] * (k - 1)
        kcal = num(rev.v(b + 6, 7))
        sem = {
            "k": k,
            "kcal": kcal,
            "carbs": num(rev.v(b + 8, 7)),
            "prot": num(rev.v(b + 10, 7)),
            "grasas": num(rev.v(b + 12, 7)),
            "peso": num(rev.v(b + 14, 7)),
            "apego": num(rev.v(b + 16, 9)) if kcal is not None else None,
            "pasos": [num(rev.v(b + 6 + d, 16)) for d in range(7)],
            "sueno": [a_horas(rev.v(b + 6 + d, 18)) for d in range(7)],
            "sesiones": 0, "animo": [], "rpe": [], "notas": [],
        }
        mc = Hoja(wb, f"MC{k}", 228, 115)
        for s in CONFIG["bloques_sesion"]:
            hubo = False
            for e in range(10):
                for j in range(5):
                    fila = 17 + 22 * e + j
                    if mc.v(fila, s + 10) not in (None, "") or mc.v(fila, s + 11) not in (None, ""):
                        hubo = True
                    nota = mc.v(fila, s + 14)
                    if isinstance(nota, str) and nota.strip():
                        sem["notas"].append(nota.strip())
            if hubo:
                sem["sesiones"] += 1
                sem["animo"].append(num(mc.v(7, s + 12)))
                sem["rpe"].append(num(mc.v(8, s + 12)))
        exp["semanas"].append(sem)
    wb.close()
    return exp


# ---------------------------------------------------------------- formulario
def lee_respuestas(ruta):
    """Lee la salida de read_file_content (texto o JSON) de la hoja de respuestas."""
    aviso = None
    if not ruta or not os.path.exists(ruta):
        return [], [], "sin hoja de respuestas"
    texto = open(ruta, encoding="utf-8").read()
    if texto.lstrip().startswith("{"):
        try:
            texto = json.loads(texto).get("fileContent", texto)
        except json.JSONDecodeError:
            pass
    texto = texto.replace("\\n", "\n") if "\n" not in texto else texto
    filas = []
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea.startswith("|"):
            if filas and linea.startswith("###"):
                break
            continue
        celdas = [re.sub(r"\\([_&*\\|])", r"\1", c).strip() for c in linea.strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in celdas if c):
            continue
        if not any(celdas):
            continue
        filas.append(celdas)
    if not filas:
        return [], [], "hoja de respuestas vacía o ilegible"
    cabecera, datos = filas[0], filas[1:]
    m = re.search(r"Table Range:\s*[A-Z]+\d+:[A-Z]+(\d+)", texto)
    if m and int(m.group(1)) - 1 > len(datos):
        aviso = f"la hoja de respuestas tiene {int(m.group(1)) - 1} filas y solo se leyeron {len(datos)}"
    return cabecera, datos, aviso


def fecha_respuesta(v):
    v = (v or "").strip()
    fmt = "%d/%m/%Y" if CONFIG["formato_fecha_formulario"] == "dmy" else "%m/%d/%Y"
    for f in (fmt + " %H:%M:%S", fmt + " %H:%M", fmt, "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(v, f)
        except ValueError:
            pass
    return None


def interpreta_respuestas(cabecera, datos):
    cab = [sin_acentos(c) for c in cabecera]
    i_fecha = next((i for i, c in enumerate(cab) if "marca temporal" in c or "timestamp" in c), 0)
    i_correo = next((i for i, c in enumerate(cab) if "correo" in c or "email" in c), None)
    i_nombre = next((i for i, c in enumerate(cab) if "nombre" in c), None)
    i_peso = next((i for i, c in enumerate(cab) if "peso" in c), None)
    i_dolor = [i for i, c in enumerate(cab) if "dolor" in c]
    i_ajuste = [i for i, c in enumerate(cab) if "ajuste" in c or "cambi" in c]
    respuestas = []
    for fila in datos:
        fila = fila + [""] * (len(cabecera) - len(fila))
        textos = [fila[i] for i in range(len(fila)) if i not in (i_fecha, i_correo, i_nombre, i_peso)]
        otros = [fila[i] for i in range(len(fila))
                 if i not in (i_fecha, i_correo, i_nombre, i_peso) and i not in i_ajuste]
        ajustes = []
        for i in i_ajuste:
            v = sin_acentos(fila[i]).strip()
            if v and not re.match(r"^no\b", v):
                tema = ("dieta" if re.search(r"dieta|alimenta|comida|nutri", cab[i])
                        else "rutina" if re.search(r"rutina|entren|ejercicio", cab[i]) else "")
                ajustes.append((f"pide ajuste de {tema}" if tema else "pide ajuste", fila[i]))
        respuestas.append({
            "fecha": fecha_respuesta(fila[i_fecha]),
            "correo": (fila[i_correo] if i_correo is not None else "").strip().lower(),
            "nombre": fila[i_nombre] if i_nombre is not None else "",
            "peso": num(fila[i_peso]) if i_peso is not None else None,
            "dolor_si": any(sin_acentos(fila[i]).startswith("si") for i in i_dolor),
            "texto": " | ".join(t for t in textos if t),
            "texto_otros": " | ".join(t for t in otros if t),
            "ajustes": ajustes,
            "asignada": False,
        })
    return respuestas


def es_de(resp, exp, carpeta):
    correo = (exp.get("correo") or "").strip().lower()
    if correo and resp["correo"] and resp["correo"] == correo:
        return "correo"
    tok = set(palabras(resp["nombre"]))
    if len(tok) >= 2:
        for referencia in (exp.get("nombre"), carpeta):
            if tok <= set(palabras(referencia)):
                return "nombre"
    return None


# ---------------------------------------------------------------- analisis
def evalua(sem, checkin, dias_sin, es_actual, hay_formulario):
    """Semaforo de una semana. Devuelve color, categorias para Telegram y motivo detallado."""
    rojo, naranja, cats, detalle, cats_ck = [], [], [], [], []
    textos = [("nota de serie", n) for n in sem["notas"]]
    if checkin:
        textos.append(("check-in", checkin["texto"]))
        for etiqueta, respuesta in checkin.get("ajustes", []):
            cats.append(etiqueta)
            cats_ck.append(etiqueta)
            detalle.append(f"check-in, {etiqueta}: «{respuesta[:70]}»")
        if checkin["dolor_si"]:
            rojo.append("dolor reportado")
            cats_ck.append("dolor reportado")
            detalle.append("check-in: indicó que sí hay dolor")
    for fuente, t in textos:
        r = busca(t, ROJO)
        if r:
            rojo.append("dolor o malestar reportado")
            if fuente == "check-in":
                cats_ck.append("dolor o malestar reportado")
            detalle.append(f"{fuente}: «{t[:70]}»")
        n = busca(t, NARANJA)
        if n:
            naranja.append("cansancio o desánimo")
            if fuente == "check-in":
                cats_ck.append("cansancio o desánimo")
            detalle.append(f"{fuente}: «{t[:70]}»")
        if busca(checkin["texto_otros"] if fuente == "check-in" else t, AJUSTE):
            cats.append("pide ajuste")
            if fuente == "check-in":
                cats_ck.append("pide ajuste")
            detalle.append(f"ajuste pedido en {fuente}: «{t[:70]}»")
    animos = [a for a in sem["animo"] if a is not None]
    if animos and min(animos) <= 5:
        rojo.append(f"ánimo {min(animos):g}/10")
    elif animos and min(animos) <= 6:
        naranja.append(f"ánimo {min(animos):g}/10")
    if sem["apego"] is not None and not (CONFIG["apego_min"] <= sem["apego"] <= CONFIG["apego_max"]):
        naranja.append(f"apego {sem['apego'] * 100:.0f} %")
    if es_actual and dias_sin is not None and dias_sin >= CONFIG["umbral_dias_sin_registrar"]:
        naranja.append(f"sin registrar {dias_sin} días")
    if es_actual and hay_formulario and not checkin:
        naranja.append("sin check-in")
    color = "ROJO" if rojo else "NARANJA" if naranja else "VERDE"
    cats = list(dict.fromkeys(rojo + naranja + cats))
    return color, cats, detalle, list(dict.fromkeys(cats_ck))


def analiza_alumna(item, respuestas, hoy, hay_formulario):
    exp = lee_expediente(item["xlsx"])
    nombre = nombre_bonito(item.get("carpeta"), exp["nombre"])
    inicio = exp["inicio"]
    if inicio:
        actual = (hoy - inicio).days // 7 + 1
        semanas_log = range(1, max(0, min(actual, CONFIG["semanas"])) + 1)
    else:
        actual = None
        con_datos = [s["k"] for s in exp["semanas"]
                     if s["kcal"] is not None or s["sesiones"] or any(p is not None for p in s["pasos"])]
        semanas_log = con_datos[-1:] if con_datos else [1]

    mias = []
    for r in respuestas:
        via = es_de(r, exp, item.get("carpeta"))
        if via:
            r["asignada"] = True
            mias.append(dict(r, via=via))
    mias.sort(key=lambda r: r["fecha"] or dt.datetime.min)

    # ultimo dia con actividad: pasos, sueno o un check-in. Las series no traen fecha.
    ultimo = None
    if inicio:
        for s in exp["semanas"]:
            for d in range(7):
                if s["pasos"][d] is not None or s["sueno"][d] is not None:
                    dia = inicio + dt.timedelta(days=7 * (s["k"] - 1) + d)
                    if dia <= hoy and (ultimo is None or dia > ultimo):
                        ultimo = dia
    for r in mias:
        if r["fecha"] and r["fecha"].date() <= hoy and (ultimo is None or r["fecha"].date() > ultimo):
            ultimo = r["fecha"].date()
    if ultimo:
        dias_sin, sin_nada = (hoy - ultimo).days, False
    elif inicio and inicio <= hoy:
        dias_sin, sin_nada = (hoy - inicio).days, True  # nada registrado desde que empezo
    else:
        dias_sin, sin_nada = None, False
    futuras = [s["k"] for s in exp["semanas"] if s["sesiones"] and (actual is None or s["k"] > actual)]

    # pagos y renovacion
    pendientes = [p for p in exp["pagos"] if p["pagado"] is not True]
    vencido = next((p["fecha"] for p in pendientes if p["fecha"] < hoy and p["pagado"] is False), None)
    proximo = next((p["fecha"] for p in sorted(pendientes, key=lambda p: p["fecha"]) if p["fecha"] >= hoy), None)
    fin_meso = inicio + dt.timedelta(days=7 * CONFIG["semanas"] - 1) if inicio else None
    pago = {
        "vencido": vencido, "proximo": proximo, "fin_meso": fin_meso,
        "cantidad": exp["cantidad"], "tipo": exp["tipo_pago"],
        "avisa_pago": bool(vencido) or (proximo is not None and (proximo - hoy).days <= CONFIG["dias_aviso_pago"]),
        "avisa_renovacion": fin_meso is not None and (fin_meso - hoy).days <= CONFIG["dias_aviso_renovacion"],
    }

    # check-in de "esta semana" = la respuesta mas reciente de los ultimos 7 dias
    recientes = [r for r in mias if r["fecha"] and 0 <= (hoy - r["fecha"].date()).days <= 7]

    filas = []
    for k in semanas_log:
        sem = exp["semanas"][k - 1]
        es_actual = (actual is None) or (k == actual)
        ini = inicio + dt.timedelta(days=7 * (k - 1)) if inicio else None
        fin = ini + dt.timedelta(days=6) if ini else None
        if es_actual:
            checkin = recientes[-1] if recientes else None
        else:
            checkins = [r for r in mias if r["fecha"] and ini <= r["fecha"].date() <= fin + dt.timedelta(days=1)]
            checkin = checkins[-1] if checkins else None
        # Si la semana apenas empieza (menos de 3 dias), se evalua junto con la anterior
        # para no perder lo que paso la semana pasada.
        prev = exp["semanas"][k - 2] if (es_actual and ini and k >= 2) else None
        usa_prev = bool(prev) and (hoy - ini).days + 1 < 3
        ev = dict(sem)
        if usa_prev:
            ev["notas"] = prev["notas"] + sem["notas"]
            ev["animo"] = prev["animo"] + sem["animo"]
            ev["rpe"] = prev["rpe"] + sem["rpe"]
            for campo in ("apego", "kcal"):
                if ev[campo] is None:
                    ev[campo] = prev[campo]
        color, cats, detalle, cats_ck = evalua(ev, checkin, dias_sin if es_actual else None, es_actual, hay_formulario)

        pesos = [exp["semanas"][j]["peso"] for j in range(k) if exp["semanas"][j]["peso"] is not None]
        peso = sem["peso"] if sem["peso"] is not None else (checkin["peso"] if checkin and checkin.get("peso") else None)
        peso_ref = pesos[-1] if peso is None and pesos else peso
        cambio = (peso_ref - exp["peso_inicial"]) if (peso_ref is not None and exp["peso_inicial"]) else None

        faltan = []
        if es_actual:
            if not inicio:
                faltan.append("fecha de inicio (D11)")
            else:
                transcurridos = min(7, max(0, (hoy - ini).days + 1))
                sin_pasos = sum(1 for d in range(transcurridos) if sem["pasos"][d] is None)
                sin_sueno = sum(1 for d in range(transcurridos) if sem["sueno"][d] is None)
                if sin_pasos:
                    faltan.append(f"pasos de {sin_pasos} día(s)")
                if sin_sueno:
                    faltan.append(f"sueño de {sin_sueno} día(s)")
            if sem["kcal"] is None:
                faltan.append("calorías de la semana")
            if sem["peso"] is None:
                faltan.append("peso semanal")
            if futuras:
                detalle.append("hay sesiones registradas en pestañas de semanas futuras: " +
                               ", ".join(f"MC{k2}" for k2 in futuras))
        if checkin and checkin["via"] == "nombre":
            detalle.append("check-in emparejado por nombre (el correo no coincide con INTRO)")

        filas.append({
            "alumna": nombre, "semana": k, "actual": es_actual, "ini": ini, "fin": fin,
            "color": color, "cats": cats, "detalle": detalle, "cats_ck": cats_ck,
            "mesociclo": exp["mesociclo"], "sesiones": sem["sesiones"],
            "sesiones_prev": prev["sesiones"] if prev else None,
            "animo": promedio(ev["animo"]), "rpe": promedio(ev["rpe"]),
            "apego": ev["apego"], "kcal": ev["kcal"], "peso": peso_ref,
            "apego_de_prev": usa_prev and sem["apego"] is None and ev["apego"] is not None,
            "peso_inicial": exp["peso_inicial"], "cambio": cambio,
            "pasos": promedio(sem["pasos"]), "sueno": promedio(sem["sueno"]),
            "checkin": checkin, "dias_sin": dias_sin if es_actual else None,
            "faltan": faltan, "url": item.get("url", ""), "sin_inicio": inicio is None,
            "futuras": futuras if es_actual else [],
            "sin_nada": sin_nada if es_actual else False,
            "pago": pago if es_actual else None,
        })
    return filas


# ---------------------------------------------------------------- salidas
def escribe_csv(filas, ruta, generado):
    cab = ["Semana", "Fechas", "Alumna", "Semáforo", "Motivo", "Mesociclo", "Sesiones",
           "Ánimo prom.", "RPE prom.", "Apego %", "Kcal prom.", "Peso", "Cambio vs inicio (kg)",
           "Pasos/día", "Sueño h/día", "Check-in", "Días sin registrar", "Faltan",
           "Próximo pago", "Fin de mesociclo", "Archivo", "Generado"]
    fmt = lambda v, d=1: "" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cab)
        for r in filas:
            ck = r["checkin"]
            w.writerow([
                r["semana"] if not r["sin_inicio"] else "sin fecha de inicio",
                f"{r['ini']:%Y-%m-%d} a {r['fin']:%Y-%m-%d}" if r["ini"] else "",
                r["alumna"], r["color"],
                "; ".join(r["cats"] + r["detalle"]) or "todo en orden",
                r["mesociclo"] or "", r["sesiones"],
                fmt(r["animo"]), fmt(r["rpe"]),
                "" if r["apego"] is None else f"{r['apego'] * 100:.0f}",
                fmt(r["kcal"], 0), fmt(r["peso"]), fmt(r["cambio"]),
                fmt(r["pasos"], 0), fmt(r["sueno"]),
                (f"sí, {ck['fecha']:%Y-%m-%d}" if ck and ck["fecha"] else "sí") if ck else "no",
                "" if r["dias_sin"] is None else r["dias_sin"],
                ", ".join(r["faltan"]),
                texto_pago(r["pago"]) if r["pago"] else "",
                f"{r['pago']['fin_meso']:%Y-%m-%d}" if r["pago"] and r["pago"]["fin_meso"] else "",
                r["url"], generado,
            ])
    return cab


def texto_pago(p):
    if p["vencido"]:
        return f"vencido desde {p['vencido']:%Y-%m-%d}"
    if p["proximo"]:
        return f"{p['proximo']:%Y-%m-%d}"
    return ""


def linea_pago(p, hoy):
    """Una linea corta para Telegram, o None si no hay nada que avisar."""
    partes = []
    monto = f" · ${miles(p['cantidad'])}" if p["cantidad"] else ""
    if p["vencido"]:
        partes.append(f"pago vencido desde el {fecha_corta(p['vencido'])}{monto}")
    elif p["avisa_pago"]:
        dias = (p["proximo"] - hoy).days
        cuando = "hoy" if dias == 0 else "mañana" if dias == 1 else f"en {dias} días"
        partes.append(f"pago el {fecha_corta(p['proximo'])} ({cuando}){monto}")
    if p["avisa_renovacion"]:
        dias = (p["fin_meso"] - hoy).days
        cuando = (f"terminó el {fecha_corta(p['fin_meso'])}" if dias < 0
                  else f"termina el {fecha_corta(p['fin_meso'])} ({'hoy' if dias == 0 else f'en {dias} días'})")
        partes.append(f"su mesociclo {cuando}: toca renovar")
    return " · ".join(partes) or None


def bloque_alumna(r):
    e = html.escape
    sem = f"Semana {r['semana']}" if not r["sin_inicio"] else "sin fecha de inicio"
    meso = f"Meso {r['mesociclo']} · " if r["mesociclo"] else ""
    lineas = [f"{ICONO[r['color']]} <b>{e(r['alumna'])}</b> · {meso}{sem}"]
    entreno = f"{r['sesiones']} de {CONFIG['sesiones_por_semana']} esta semana"
    if r["sesiones_prev"] is not None:
        entreno += f" · la pasada {r['sesiones_prev']} de {CONFIG['sesiones_por_semana']}"
    if r["animo"] is not None:
        entreno += f" · ánimo {r['animo']:.0f}/10"
    if r["rpe"] is not None:
        entreno += f" · RPE {r['rpe']:.0f}"
    lineas.append(f"\U0001F3CB️ Entreno: {entreno}")
    if r["apego"] is not None:
        de = " (semana pasada)" if r.get("apego_de_prev") else ""
        lineas.append(f"\U0001F37D️ Apego{de}: {r['apego'] * 100:.0f} % (meta 90–110 %)" +
                      (f" · {miles(r['kcal'])} kcal" if r["kcal"] else ""))
    if r["peso"] is not None:
        if r["peso_inicial"] and r["cambio"] is not None:
            lineas.append(f"⚖️ Peso: {r['peso_inicial']:.1f} → {r['peso']:.1f} kg ({r['cambio']:+.1f})")
        else:
            lineas.append(f"⚖️ Peso: {r['peso']:.1f} kg")
    elif r["peso_inicial"]:
        lineas.append(f"⚖️ Peso inicial: {r['peso_inicial']:.1f} kg · sin peso de esta semana")
    partes = []
    if r["pasos"] is not None:
        partes.append(f"\U0001F463 Pasos: {miles(r['pasos'])}/día")
    if r["sueno"] is not None:
        partes.append(f"\U0001F634 Sueño: {r['sueno']:.1f} h")
    if partes:
        lineas.append(" · ".join(partes))
    ck = r["checkin"]
    if ck:
        txt = f"sí, {fecha_corta(ck['fecha'])}" if ck["fecha"] else "sí"
        extra = r["cats_ck"]
        lineas.append("\U0001F4DD Check-in: " + " · ".join([txt] + extra))
    else:
        lineas.append("\U0001F4DD Check-in: no llegó")
    otros = [c for c in r["cats"] if c.startswith(("sin registrar", "apego", "ánimo "))]
    if otros:
        lineas.append("\U0001F440 Ojo: " + ", ".join(otros))
    if r["faltan"]:
        lineas.append("⚠️ Faltan: " + ", ".join(r["faltan"]))
    if r["futuras"]:
        lineas.append("ℹ️ Registró en " + ", ".join(f"MC{k}" for k in r["futuras"]) + " (semana futura)")
    if r["pago"]:
        p = r["pago"]
        if p["vencido"] or p["proximo"] or p["fin_meso"]:
            datos = []
            if p["vencido"]:
                datos.append(f"vencido desde el {fecha_corta(p['vencido'])}")
            elif p["proximo"]:
                datos.append(f"próximo pago {fecha_corta(p['proximo'])}")
            if p["fin_meso"]:
                datos.append(f"termina mesociclo {fecha_corta(p['fin_meso'])}")
            lineas.append("\U0001F4B3 " + " · ".join(datos))
    return "\n".join(lineas)


def escribe_inactividad(actuales, hoy, ruta):
    """Mensaje corto solo con las alumnas que llevan N dias o mas sin registrar.
    Si nadie esta inactiva, el archivo queda vacio y `telegram` no manda nada."""
    umbral = CONFIG["umbral_dias_sin_registrar"]
    inactivas = sorted([r for r in actuales if r["dias_sin"] is not None and r["dias_sin"] >= umbral],
                       key=lambda r: -r["dias_sin"])
    if not inactivas:
        open(ruta, "w", encoding="utf-8").write("")
        return 0
    partes = [f"\U0001F6A8 <b>Aviso de inactividad</b> — {DIAS[hoy.weekday()]} {fecha_corta(hoy)}",
              f"{len(inactivas)} alumna{'s' if len(inactivas) != 1 else ''} con {umbral} días o más sin registrar", ""]
    for r in inactivas:
        motivo = "sin registros desde que empezó" if r["sin_nada"] else "sin pasos, sueño ni check-in"
        enlace = f' · <a href="{html.escape(r["url"], quote=True)}">abrir</a>' if r["url"] else ""
        partes.append(f"⏳ <b>{html.escape(r['alumna'])}</b>: {r['dias_sin']} días, {motivo}{enlace}")
    open(ruta, "w", encoding="utf-8").write("\n".join(partes))
    return len(inactivas)


def escribe_telegram(actuales, sin_asignar, hoy, ruta):
    cuenta = {c: sum(1 for r in actuales if r["color"] == c) for c in ORDEN}
    n = len(actuales)
    partes = [
        f"\U0001F4CB <b>Control del coach</b> — {DIAS[hoy.weekday()]} {fecha_corta(hoy)}",
        f"{n} alumna{'s' if n != 1 else ''} · resumen de la semana",
        "",
        f"{ICONO['ROJO']} {cuenta['ROJO']}   {ICONO['NARANJA']} {cuenta['NARANJA']}   {ICONO['VERDE']} {cuenta['VERDE']}",
    ]
    prioridad = [r for r in actuales if r["color"] != "VERDE"]
    if prioridad:
        partes += ["", "\U0001F3AF <b>Atiende primero</b>"]
        for i, r in enumerate(prioridad, 1):
            partes.append(f"{i}. {html.escape(r['alumna'])}: " + (", ".join(r["cats"][:3]) or "revisar"))
    detalladas = actuales if n <= 6 else prioridad
    for r in detalladas:
        partes += ["", bloque_alumna(r)]
    if n > 6:
        verdes = [r["alumna"] for r in actuales if r["color"] == "VERDE"]
        if verdes:
            partes += ["", f"{ICONO['VERDE']} <b>En orden:</b> " + html.escape(", ".join(verdes))]
    avisos_pago = [(r, linea_pago(r["pago"], hoy)) for r in actuales if r["pago"]]
    avisos_pago = [(r, t) for r, t in avisos_pago if t]
    if avisos_pago:
        partes += ["", "\U0001F4B3 <b>Pagos y renovaciones</b>"]
        for r, t in avisos_pago:
            partes.append(f"· {html.escape(r['alumna'])}: {html.escape(t)}")
    if sin_asignar:
        partes += ["", "❔ <b>Check-in sin asignar</b>"]
        for r in sin_asignar:
            cuando = fecha_corta(r["fecha"]) if r["fecha"] else "sin fecha"
            partes.append(f"· {html.escape(r['correo'] or r['nombre'] or 'sin correo')} ({cuando})")
        partes.append("Pide el nombre completo en el formulario o revisa el correo en INTRO.")
    partes += ["", '\U0001F4CE <a href="{{ENLACE}}">Abrir hoja maestra</a>']
    open(ruta, "w", encoding="utf-8").write("\n".join(partes))
    return cuenta


def cmd_analizar(a):
    hoy = dt.date.fromisoformat(a.hoy) if a.hoy else ahora().date()
    generado = f"{ahora():%Y-%m-%d %H:%M}"
    alumnas = json.load(open(a.alumnas, encoding="utf-8"))
    cabecera, datos, aviso = lee_respuestas(a.respuestas)
    respuestas = interpreta_respuestas(cabecera, datos) if cabecera else []
    hay_formulario = bool(cabecera)
    filas, errores = [], []
    for item in alumnas:
        try:
            filas += analiza_alumna(item, respuestas, hoy, hay_formulario)
        except Exception as ex:  # una alumna rota no tumba a las demas
            errores.append(f"{item.get('carpeta')}: {type(ex).__name__}: {ex}")
    filas.sort(key=lambda r: (-(r["semana"] or 0), ORDEN[r["color"]], r["alumna"]))
    actuales = sorted([r for r in filas if r["actual"]], key=lambda r: (ORDEN[r["color"]], r["alumna"]))
    sin_asignar = [r for r in respuestas if not r["asignada"]
                   and r["fecha"] and (hoy - r["fecha"].date()).days <= 7]
    os.makedirs(a.salida, exist_ok=True)
    escribe_csv(filas, os.path.join(a.salida, "maestra.csv"), generado)
    cuenta = escribe_telegram(actuales, sin_asignar, hoy, os.path.join(a.salida, "telegram.html"))
    n_inactivas = escribe_inactividad(actuales, hoy, os.path.join(a.salida, "inactividad.html"))
    push = (f"Control del coach: {ICONO['ROJO']} {cuenta['ROJO']} · {ICONO['NARANJA']} {cuenta['NARANJA']}"
            f" · {ICONO['VERDE']} {cuenta['VERDE']}. Detalle en Telegram.")
    open(os.path.join(a.salida, "push.txt"), "w", encoding="utf-8").write(push)
    informe = [f"alumnas leídas: {len(alumnas) - len(errores)} de {len(alumnas)}",
               f"filas en la bitácora: {len(filas)}",
               f"respuestas del formulario: {len(respuestas)} ({len(respuestas) - sum(r['asignada'] for r in respuestas)} sin asignar)",
               "colores esta semana: " + ", ".join(f"{c} {n}" for c, n in cuenta.items()),
               f"inactivas ({CONFIG['umbral_dias_sin_registrar']}+ días sin registrar): {n_inactivas}",
               "avisos de pago o renovación: " + str(sum(1 for r in actuales if r["pago"] and linea_pago(r["pago"], hoy)))]
    if aviso:
        informe.append("AVISO: " + aviso)
    informe += ["ERROR " + e for e in errores]
    for r in actuales:
        informe.append(f"{r['alumna']}: {r['color']} · " + ("; ".join(r["cats"]) or "en orden"))
    open(os.path.join(a.salida, "informe.txt"), "w", encoding="utf-8").write("\n".join(informe))
    print("\n".join(informe))


# ---------------------------------------------------------------- telegram y decodificar
def cmd_telegram(a):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("telegram omitido: faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        return 0
    texto = open(a.mensaje, encoding="utf-8").read().replace("{{ENLACE}}", html.escape(a.enlace, quote=True))
    if not texto.strip():
        print("telegram: nada que enviar")
        return 0
    trozos, actual = [], ""
    for linea in texto.split("\n"):
        if len(actual) + len(linea) + 1 > 3900:
            trozos.append(actual)
            actual = ""
        actual += ("\n" if actual else "") + linea
    trozos.append(actual)
    for i, trozo in enumerate(trozos, 1):
        datos = urllib.parse.urlencode({"chat_id": chat, "text": trozo, "parse_mode": "HTML",
                                        "disable_web_page_preview": "true"}).encode()
        try:
            with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", datos, timeout=30) as resp:
                r = json.load(resp)
        except Exception as ex:
            msg = str(ex).replace(token, "***")
            print(f"telegram error en mensaje {i}/{len(trozos)}: {msg}")
            return 1
        if not r.get("ok"):
            print(f"telegram error en mensaje {i}/{len(trozos)}: {r.get('description')}")
            return 1
    print(f"telegram ok ({len(trozos)} mensaje{'s' if len(trozos) > 1 else ''})")
    return 0


def cmd_decodificar(a):
    texto = open(a.origen, encoding="utf-8").read().strip()
    contenido = json.loads(texto)["content"] if texto.startswith("{") else texto
    open(a.destino, "wb").write(base64.b64decode(contenido))
    print(f"{a.destino}: {os.path.getsize(a.destino)} bytes")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decodificar")
    d.add_argument("origen")
    d.add_argument("destino")
    an = sub.add_parser("analizar")
    an.add_argument("--alumnas", required=True)
    an.add_argument("--respuestas")
    an.add_argument("--salida", required=True)
    an.add_argument("--hoy", help="AAAA-MM-DD, solo para pruebas")
    t = sub.add_parser("telegram")
    t.add_argument("--mensaje", required=True)
    t.add_argument("--enlace", required=True)
    a = p.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    return {"decodificar": cmd_decodificar, "analizar": cmd_analizar, "telegram": cmd_telegram}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
