"""Recolector v2 de Diamante."""
import calendar
import fcntl
import hashlib
import ipaddress
import json
import re
import signal
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.robotparser
import zlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import trafilatura

from db import BASE_DIR, ahora_utc, conectar

# ----------------------------- Configuración -----------------------------
FUENTES = [
    {"nombre": "larazon", "feed": "https://larazon.bo/feed/", "dominios": ["larazon.bo"]},
    {"nombre": "opinion", "feed": "https://www.opinion.com.bo/rss/", "dominios": ["opinion.com.bo"],
     "habilitada": False},
]
USER_AGENT = "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}
TIMEOUT_S = 30
DESCARGA_MAX_S = 60
MAX_DESCARGAS_POR_EJECUCION = 10
TIEMPO_MAXIMO_S = 360
PAUSA_ENTRE_DESCARGAS_S = 2
MIN_CHARS = 200
MAX_BYTES_HTML = 4 * 1024 * 1024
MAX_BYTES_FEED = 3 * 1024 * 1024
MAX_BYTES_ROBOTS = 512 * 1024
MAX_REDIRECCIONES = 3
MAX_URL_LEN = 2048
PUERTOS_OK = (None, 80, 443)
PARAMS_RASTREO = {"fbclid", "gclid", "mc_cid", "mc_eid"}

REVISION_OK_S = 12 * 3600
VENTANA_REVISION_S = 3 * 86400
ESPERA_FALLO_S = 1800
MAX_INTENTOS_FALLO = 8
ESPERA_SIN_TEXTO_S = 6 * 3600
MAX_INTENTOS_SIN_TEXTO = 4
REVISION_ROBOTS_S = 24 * 3600
ABANDONO = "9999-12-31T00:00:00Z"
MAX_CANDIDATAS_VENCIDAS = 50

DETENER = False
_ROBOTS = {}

class ErrorDescarga(Exception):
    pass

def _al_terminar(signum, frame):
    global DETENER
    DETENER = True
    print("Señal de parada recibida: termino la noticia actual y salgo.")

def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def ahora_str():
    return iso(datetime.now(timezone.utc))

def en_segundos(n):
    return iso(datetime.now(timezone.utc) + timedelta(seconds=n))

def canonicalizar_url(url):
    p = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not (k.lower().startswith("utm_") or k.lower() in PARAMS_RASTREO)]
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(query), ""))

def fecha_iso(st):
    if not st:
        return None
    return datetime.fromtimestamp(calendar.timegm(st), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def normalizar_texto(texto):
    return unicodedata.normalize("NFC", texto)

def hash_texto(texto):
    compacto = re.sub(r"\s+", " ", texto).strip()
    return hashlib.sha256(compacto.encode("utf-8")).hexdigest()

def decodificar(datos, charset):
    try:
        return datos.decode(charset or "utf-8", "replace")
    except LookupError:
        return datos.decode("utf-8", "replace")

def describir_error(ex):
    if isinstance(ex, urllib.error.HTTPError):
        return f"HTTP {ex.code}"
    return f"{type(ex).__name__}: {ex}"[:300]

def url_valida(url, dominios):
    if not url or len(url) > MAX_URL_LEN:
        return False, "vacía o demasiado larga"
    if re.search(r"[\s\x00-\x1f\x7f]", url):
        return False, "contiene espacios o caracteres de control"
    try:
        p = urlsplit(url)
    except ValueError:
        return False, "mal formada"
    if p.scheme not in ("http", "https"):
        return False, f"esquema no permitido ({p.scheme or 'ninguno'})"
    if p.username is not None or p.password is not None:
        return False, "lleva usuario o clave"
    host = (p.hostname or "").lower()
    if not host:
        return False, "sin dominio"
    puerto = p.port
    if puerto not in PUERTOS_OK:
        return False, f"puerto no permitido ({puerto})"
    try:
        ipaddress.ip_address(host)
        return False, "IP literal no permitida"
    except ValueError:
        pass
    if not any(host == d or host.endswith("." + d) for d in dominios):
        return False, f"dominio fuera de la lista ({host})"
    return True, ""

class _Redirecciones(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECCIONES
    def __init__(self, dominios, comprobar_robots):
        self.dominios = dominios
        self.comprobar_robots = comprobar_robots
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok, motivo = url_valida(newurl, self.dominios)
        if not ok:
            raise ErrorDescarga(f"redirección rechazada ({motivo})")
        if self.comprobar_robots and robots_estado(newurl, self.dominios) != "permitido":
            raise ErrorDescarga("redirección rechazada (robots.txt del destino)")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def _leer_limitado(r, max_bytes):
    partes, total, limite_t = [], 0, time.monotonic() + DESCARGA_MAX_S
    leer = getattr(r, "read1", r.read)
    while True:
        trozo = leer(16384)
        if not trozo:
            break
        total += len(trozo)
        if total > max_bytes:
            raise ErrorDescarga(f"respuesta mayor de {max_bytes} bytes")
        if time.monotonic() > limite_t:
            raise ErrorDescarga(f"descarga más lenta que {DESCARGA_MAX_S} s")
        partes.append(trozo)
    return b"".join(partes)

def descargar(url, dominios, max_bytes, solo_texto=False, comprobar_robots=True):
    ok, motivo = url_valida(url, dominios)
    if not ok:
        raise ErrorDescarga(f"URL rechazada ({motivo})")
    opener = urllib.request.build_opener(_Redirecciones(dominios, comprobar_robots))
    req = urllib.request.Request(url, headers=HEADERS)
    with opener.open(req, timeout=TIMEOUT_S) as r:
        if solo_texto:
            tipo = r.headers.get_content_type()
            if not (tipo.startswith("text/") or tipo == "application/xhtml+xml"):
                raise ErrorDescarga(f"tipo de contenido no admitido ({tipo})")
        largo = r.headers.get("Content-Length")
        if largo and largo.isdigit() and int(largo) > max_bytes:
            raise ErrorDescarga(f"Content-Length {largo} mayor de {max_bytes} bytes")
        datos = _leer_limitado(r, max_bytes)
        return datos, r.headers.get_content_charset()

def _leer_robots(base, dominios):
    rp = urllib.robotparser.RobotFileParser()
    try:
        datos, charset = descargar(base + "/robots.txt", dominios, MAX_BYTES_ROBOTS, comprobar_robots=False)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            rp.allow_all = True
        elif e.code in (401, 403):
            rp.disallow_all = True
            print(f"  ! robots.txt de {base} respondió {e.code}: se trata como prohibido")
        else:
            print(f"  ! robots.txt de {base} respondió {e.code}: no se descarga nada en este tick")
            return None
        return rp
    except Exception as e:
        print(f"  ! no pude leer robots.txt de {base} ({describir_error(e)}): no se descarga nada en este tick")
        return None
    rp.parse(decodificar(datos, charset).splitlines())
    rp.modified()
    return rp

def robots_estado(url, dominios):
    p = urlsplit(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _ROBOTS:
        _ROBOTS[base] = _leer_robots(base, dominios)
    rp = _ROBOTS[base]
    if rp is None:
        return "no_disponible"
    return "permitido" if rp.can_fetch(USER_AGENT, url) else "prohibido"

def proxima_revision(estado, intentos):
    if estado == "ok":
        return en_segundos(REVISION_OK_S)
    if estado == "bloqueado_robots":
        return en_segundos(REVISION_ROBOTS_S)
    if estado == "descarga_fallida":
        base, tope = ESPERA_FALLO_S, MAX_INTENTOS_FALLO
    else:
        base, tope = ESPERA_SIN_TEXTO_S, MAX_INTENTOS_SIN_TEXTO
    if intentos >= tope:
        return ABANDONO
    return en_segundos(base * 2 ** (intentos - 1))

def escribir_estado(conn, d, estado, error=None):
    previo = conn.execute(
        "SELECT estado, intentos FROM documentos WHERE url_canonica = ?", (d["url_canonica"],)
    ).fetchone()
    if previo is not None and previo["estado"] == "ok" and estado != "ok":
        estado, intentos, prox = "ok", previo["intentos"], en_segundos(REVISION_OK_S)
    else:
        if estado == "ok":
            intentos = 0
        elif estado == "bloqueado_robots":
            intentos = previo["intentos"] if previo else 0
        else:
            intentos = (previo["intentos"] if previo else 0) + 1
        prox = proxima_revision(estado, intentos)
    ahora = ahora_str()
    conn.execute(
        """INSERT INTO documentos
               (url_canonica, url_original, fuente, titulo, fecha_publicacion, primera_captura,
                estado, intentos, ultima_revision, proxima_revision, ultimo_error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(url_canonica) DO UPDATE SET
               estado = excluded.estado,
               intentos = excluded.intentos,
               ultima_revision = excluded.ultima_revision,
               proxima_revision = excluded.proxima_revision,
               ultimo_error = excluded.ultimo_error""",
        (d["url_canonica"], d["url_original"], d["fuente"], d["titulo"], d["fecha_publicacion"],
         ahora, estado, intentos, ahora, prox, error),
    )
    return conn.execute("SELECT id FROM documentos WHERE url_canonica = ?", (d["url_canonica"],)).fetchone()["id"]

def guardar_version(conn, d, html, texto):
    h = hash_texto(texto)
    with conn:
        doc_id = escribir_estado(conn, d, "ok")
        es_copia = conn.execute(
            "SELECT 1 FROM versiones WHERE hash_texto = ? AND documento_id <> ? LIMIT 1", (h, doc_id)
        ).fetchone() is not None
        cur = conn.execute(
            """INSERT INTO versiones (documento_id, hash_texto, texto_limpio, fecha_captura)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(documento_id, hash_texto) DO NOTHING""",
            (doc_id, h, texto, ahora_utc()),
        )
        if cur.rowcount == 0:
            return "sin_cambios"
        conn.execute(
            "INSERT INTO crudos (version_id, html_zlib) VALUES (?, ?)",
            (cur.lastrowid, zlib.compress(html.encode("utf-8", "replace"), 6)),
        )
        n_versiones = conn.execute(
            "SELECT COUNT(*) FROM versiones WHERE documento_id = ?", (doc_id,)
        ).fetchone()[0]
    if n_versiones > 1:
        return "version_nueva"
    return "nueva_copia" if es_copia else "nueva"

def procesar_documento(conn, d, dominios, presupuesto):
    r = robots_estado(d["url_original"], dominios)
    if r == "no_disponible":
        return "robots_no_disponible"
    if r == "prohibido":
        with conn:
            escribir_estado(conn, d, "bloqueado_robots", "robots.txt lo prohíbe")
        return "robots"
    presupuesto["descargas"] += 1
    try:
        datos, charset = descargar(d["url_original"], dominios, MAX_BYTES_HTML, solo_texto=True)
    except Exception as ex:
        with conn:
            escribir_estado(conn, d, "descarga_fallida", describir_error(ex))
        return "fallida"
    html = decodificar(datos, charset)
    texto = trafilatura.extract(html, include_comments=False, favor_precision=True)
    texto = normalizar_texto(texto).strip() if texto else ""
    if len(texto) < MIN_CHARS:
        with conn:
            escribir_estado(conn, d, "sin_texto", f"texto de {len(texto)} caracteres")
        return "sin_texto"
    return guardar_version(conn, d, html, texto)

def registrar_excepcion(conn, d, ex):
    print(f"  ! error en {d['url_original']}: {describir_error(ex)}")
    try:
        with conn:
            escribir_estado(conn, d, "descarga_fallida", "excepción: " + describir_error(ex))
    except Exception as ex2:
        print(f"  ! no pude registrar el fallo: {describir_error(ex2)}")
    return "error"

def nuevo_contador():
    return {"nuevas": 0, "copias": 0, "versiones_nuevas": 0, "sin_cambios": 0, "conocidas": 0,
            "sin_texto": 0, "robots": 0, "robots_no_disponible": 0, "fallidas": 0, "errores": 0,
            "invalidas": 0, "pendientes": 0, "error_feed": None}

RESULTADO_A_CONTADOR = {
    "nueva": "nuevas", "nueva_copia": "nuevas", "version_nueva": "versiones_nuevas",
    "sin_cambios": "sin_cambios", "sin_texto": "sin_texto", "robots": "robots",
    "robots_no_disponible": "robots_no_disponible", "fallida": "fallidas", "error": "errores",
}

def leer_feed(fuente):
    estado = robots_estado(fuente["feed"], fuente["dominios"])
    if estado != "permitido":
        raise RuntimeError(f"robots.txt: el feed está {estado}")
    datos, _ = descargar(fuente["feed"], fuente["dominios"], MAX_BYTES_FEED)
    feed = feedparser.parse(datos)
    if not feed.entries:
        raise RuntimeError(f"el feed no trae entradas (bozo={getattr(feed, 'bozo', None)})")
    return list(feed.entries)

def documentos_vencidos(conn, fuente, c):
    corte = iso(datetime.now(timezone.utc) - timedelta(seconds=VENTANA_REVISION_S))
    filas = conn.execute(
        """SELECT url_canonica, url_original, fuente, titulo, fecha_publicacion
             FROM documentos
            WHERE fuente = ?
              AND (proxima_revision IS NULL OR proxima_revision <= ?)
              AND (estado <> 'ok' OR primera_captura >= ?)
            ORDER BY COALESCE(proxima_revision, '') ASC, id ASC
            LIMIT ?""",
        (fuente["nombre"], ahora_str(), corte, MAX_CANDIDATAS_VENCIDAS),
    ).fetchall()
    res = []
    for f in filas:
        d = dict(f)
        if url_valida(d["url_original"], fuente["dominios"])[0]:
            res.append(d)
        else:
            c["invalidas"] += 1
    return res

def preparar_fuente(conn, fuente, c):
    try:
        entradas = leer_feed(fuente)
    except Exception as ex:
        c["error_feed"] = describir_error(ex)
        return []
    entradas.sort(key=lambda e: e.get("published_parsed") or time.gmtime(0), reverse=True)
    nuevas, vistas = [], set()
    for e in entradas:
        try:
            url = (e.get("link") or "").strip()
            ok, motivo = url_valida(url, fuente["dominios"])
            if not ok:
                c["invalidas"] += 1
                print(f"  ! enlace rechazado ({motivo}): {url[:120]}")
                continue
            url_can = canonicalizar_url(url)
            if url_can in vistas:
                continue
            vistas.add(url_can)
            if conn.execute("SELECT 1 FROM documentos WHERE url_canonica = ?", (url_can,)).fetchone():
                c["conocidas"] += 1
                continue
            nuevas.append({
                "url_canonica": url_can, "url_original": url, "fuente": fuente["nombre"],
                "titulo": (e.get("title") or "").strip() or None,
                "fecha_publicacion": fecha_iso(e.get("published_parsed") or e.get("updated_parsed")),
            })
        except Exception as ex:
            c["errores"] += 1
            print(f"  ! entrada descartada ({describir_error(ex)})")
    return nuevas + documentos_vencidos(conn, fuente, c)

def ejecutar_descargas(conn, fuentes, colas, contadores, t0):
    presupuesto = {"descargas": 0}
    dominios = {f["nombre"]: f["dominios"] for f in fuentes}
    pausa_pendiente, seguir = False, True
    while seguir and any(colas.values()):
        for nombre, cola in colas.items():
            if not cola:
                continue
            if (DETENER or presupuesto["descargas"] >= MAX_DESCARGAS_POR_EJECUCION
                    or (time.monotonic() - t0) > TIEMPO_MAXIMO_S):
                seguir = False
                break
            if pausa_pendiente:
                time.sleep(PAUSA_ENTRE_DESCARGAS_S)
                pausa_pendiente = False
            d = cola.pop(0)
            antes = presupuesto["descargas"]
            try:
                r = procesar_documento(conn, d, dominios[nombre], presupuesto)
            except Exception as ex:
                r = registrar_excepcion(conn, d, ex)
            c = contadores[nombre]
            c[RESULTADO_A_CONTADOR[r]] += 1
            if r == "nueva_copia":
                c["copias"] += 1
            if presupuesto["descargas"] > antes:
                pausa_pendiente = True
    for nombre, cola in colas.items():
        contadores[nombre]["pendientes"] = len(cola)
    return presupuesto["descargas"]

def imprimir_resumen(nombre, c):
    if c["error_feed"]:
        print(f"[{nombre}] ERROR leyendo el feed: {c['error_feed']}")
        return
    print(f"[{nombre}] {c['nuevas']} noticias nuevas guardadas, {c['conocidas']} ya conocidas en el feed")
    extra = [f"{c[k]} {txt}" for k, txt in (
        ("copias", "con texto idéntico a otra (guardadas igual)"),
        ("versiones_nuevas", "versiones nuevas"),
        ("sin_cambios", "revisadas sin cambios"),
        ("sin_texto", "sin texto útil"),
        ("robots", "bloqueadas por robots.txt"),
        ("robots_no_disponible", "sin descargar (robots.txt no disponible)"),
        ("fallidas", "descargas fallidas (se reintentan con espera)"),
        ("errores", "con error"),
        ("invalidas", "URLs rechazadas"),
        ("pendientes", "pendientes para el próximo tick"),
    ) if c[k]]
    if extra:
        print("    " + ", ".join(extra))

def tomar_lock():
    f = open(BASE_DIR / "recolector.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f

def main():
    lock = tomar_lock()
    if lock is None:
        print("Ya hay un recolector en ejecución; salgo.")
        return 0
    signal.signal(signal.SIGTERM, _al_terminar)
    t0 = time.monotonic()
    conn = conectar()
    with conn:
        conn.execute(
            "UPDATE ejecuciones SET estado = 'interrumpida', fin = ? WHERE modulo = 'recolector' AND estado = 'running'",
            (ahora_utc(),),
        )
        ej_id = conn.execute(
            "INSERT INTO ejecuciones (modulo, inicio, estado) VALUES ('recolector', ?, 'running')", (ahora_utc(),)
        ).lastrowid

    fuentes = [f for f in FUENTES if f.get("habilitada", True)]
    apagadas = [f["nombre"] for f in FUENTES if not f.get("habilitada", True)]
    if apagadas:
        print("Fuentes deshabilitadas:", ", ".join(apagadas))
    resumen, estado = {}, "interrumpida"
    try:
        contadores, colas = {}, {}
        for fuente in fuentes:
            if DETENER:
                break
            contadores[fuente["nombre"]] = nuevo_contador()
            colas[fuente["nombre"]] = preparar_fuente(conn, fuente, contadores[fuente["nombre"]])
        ejecutar_descargas(conn, fuentes, colas, contadores, t0)
        for nombre, c in contadores.items():
            resumen[nombre] = c
            imprimir_resumen(nombre, c)
        hubo_error = any(c["error_feed"] for c in contadores.values())
        estado = "error" if hubo_error else ("interrumpida" if DETENER else "ok")
    except Exception as ex:
        estado = "error"
        resumen["excepcion"] = f"{type(ex).__name__}: {ex}"
        print("ERROR inesperado:", resumen["excepcion"])
    finally:
        with conn:
            conn.execute(
                "UPDATE ejecuciones SET fin = ?, estado = ?, resumen = ? WHERE id = ?",
                (ahora_utc(), estado, json.dumps(resumen, ensure_ascii=False), ej_id),
            )
        conn.close()
    return 0 if estado == "ok" else 1

if __name__ == "__main__":
    sys.exit(main())
