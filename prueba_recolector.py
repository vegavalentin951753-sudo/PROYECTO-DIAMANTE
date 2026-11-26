"""Pruebas del recolector v2 contra un servidor local falso. No toca diamante.db ni internet.
Uso:  python3 prueba_recolector.py      (imprime PASS/FAIL por comprobación)"""
import contextlib, io, re, socket, sqlite3, sys, tempfile, threading, time, types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --- Si faltan feedparser/trafilatura (sandbox), se simulan; en el teléfono se usan las reales ---
try:
    import feedparser  # noqa
except ImportError:
    import email.utils, xml.etree.ElementTree as ET
    fp = types.ModuleType("feedparser")
    def _parse(datos):
        try:
            raiz = ET.fromstring(datos)
        except ET.ParseError:
            return types.SimpleNamespace(entries=[], bozo=1)
        ents = []
        for it in raiz.iter("item"):
            e = {"title": it.findtext("title") or "", "link": it.findtext("link") or ""}
            if it.findtext("pubDate"):
                e["published_parsed"] = email.utils.parsedate(it.findtext("pubDate"))
            ents.append(e)
        return types.SimpleNamespace(entries=ents, bozo=0)
    fp.parse = _parse
    sys.modules["feedparser"] = fp
try:
    import trafilatura  # noqa
except ImportError:
    sys.modules["trafilatura"] = types.ModuleType("trafilatura")

import db_setup
import recolector

def _extraer(html, **kw):                       # extractor determinista: probamos NUESTRA lógica, no trafilatura
    if "BOOM" in html:
        raise RuntimeError("boom")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
recolector.trafilatura.extract = _extraer
FUENTES_REALES = list(recolector.FUENTES)

# ------------------------------ servidor falso ------------------------------
HITS, RUTAS = [], {}
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_GET(self):
        ruta = self.path.split("?")[0]
        HITS.append(ruta)
        r = RUTAS.get(ruta, (404, "text/html", b"nada", {}))
        if r == "RESET":
            self.request.shutdown(socket.SHUT_RDWR); return
        if r == "DRIP":
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
            try:
                for _ in range(100):
                    self.wfile.write(b"x"); self.wfile.flush(); time.sleep(0.3)
            except Exception:
                pass
            return
        st, ct, cuerpo, hd = r
        self.send_response(st); self.send_header("Content-Type", ct)
        if not hd.get("__sin_largo__"):
            self.send_header("Content-Length", str(len(cuerpo)))
        for k, v in hd.items():
            if k != "__sin_largo__": self.send_header(k, v)
        self.end_headers(); self.wfile.write(cuerpo)
class Srv(ThreadingHTTPServer):
    daemon_threads = True
    def handle_error(self, *a): pass
srv = Srv(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://localhost:{PORT}"

# ------------------------------ utilidades ------------------------------
TMP = Path(tempfile.mkdtemp(prefix="diamante_prueba_"))
DB = TMP / "t.db"
def conexion():
    c = sqlite3.connect(DB, timeout=30); c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); return c
recolector.conectar = conexion
recolector.BASE_DIR = TMP
recolector.PAUSA_ENTRE_DESCARGAS_S = 0
recolector.PUERTOS_OK = (None, 80, 443, PORT)

FALLOS = []
def check(nombre, cond, detalle=""):
    print(("PASS  " if cond else "FAIL  ") + nombre + ("" if cond else f"   <-- {detalle}"))
    if not cond: FALLOS.append(nombre)

TEXTO = "Texto de prueba sobre la economía de Bolivia y el comercio exterior. " * 6
def art(t=TEXTO): return (200, "text/html; charset=utf-8", f"<html><body><p>{t}</p></body></html>".encode(), {})
def rss(rutas):
    it = "".join(f"<item><title>N{i}</title><link>{BASE}{r}</link><pubDate>Tue, 24 Nov 2026 12:00:00 +0000</pubDate></item>"
                 for i, r in enumerate(rutas))
    return (200, "application/rss+xml", f"<?xml version='1.0'?><rss><channel>{it}</channel></rss>".encode(), {})
def fuente(feed="/feed", nombre="t1"):
    return {"nombre": nombre, "feed": BASE + feed, "dominios": ["localhost"]}

def nueva_bd(fuentes=None, robots=(404, "text/plain", b"", {})):
    DB.unlink(missing_ok=True)
    for ext in ("-wal", "-shm"): Path(str(DB) + ext).unlink(missing_ok=True)
    c = conexion(); c.executescript(db_setup.ESQUEMA); c.commit(); c.close()
    HITS.clear(); RUTAS.clear(); RUTAS["/robots.txt"] = robots
    recolector.FUENTES = fuentes or [fuente()]
    recolector.MAX_BYTES_HTML = 4 * 1024 * 1024
    recolector.DESCARGA_MAX_S = 60

def correr():
    recolector._ROBOTS.clear(); recolector.DETENER = False
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = recolector.main()
    return rc, buf.getvalue()

def fila(ruta):
    c = conexion(); r = c.execute("SELECT * FROM documentos WHERE url_original LIKE ?", ("%" + ruta,)).fetchone(); c.close(); return r
def n(sql, *p):
    c = conexion(); v = c.execute(sql, p).fetchone()[0]; c.close(); return v
def vencer():
    c = conexion(); c.execute("UPDATE documentos SET proxima_revision='2000-01-01T00:00:00Z' WHERE proxima_revision < '9999'"); c.commit(); c.close()
def hits(ruta): return HITS.count(ruta)
ahora = recolector.ahora_str

# =============================== PRUEBAS ===============================
print("\n== 1. Versionado (hallazgo: los 'ok' nunca se volvían a descargar) ==")
nueva_bd(); RUTAS["/feed"] = rss(["/a1"]); RUTAS["/a1"] = art(TEXTO + " V1")
correr()
check("1a primera corrida guarda 1 documento y 1 versión", n("select count(*) from documentos") == 1 and n("select count(*) from versiones") == 1)
correr()
check("1b si no toca revisar, NO se vuelve a descargar", hits("/a1") == 1, f"hits={hits('/a1')}")
vencer(); correr()
check("1c al tocar revisar con texto igual: se descarga y no crea versión", hits("/a1") == 2 and n("select count(*) from versiones") == 1)
RUTAS["/a1"] = art(TEXTO + " V2 MODIFICADO"); vencer(); correr()
check("1d texto modificado crea versión 2 (y su crudo)", n("select count(*) from versiones") == 2 and n("select count(*) from crudos") == 2)
vencer(); correr()
check("1e otra revisión sin cambios no duplica", n("select count(*) from versiones") == 2)
RUTAS["/a1"] = (500, "text/html", b"error", {}); vencer(); correr()
f = fila("/a1")
check("1f revisión fallida NO degrada un documento guardado", f["estado"] == "ok" and f["ultimo_error"] == "HTTP 500" and n("select count(*) from versiones") == 2, dict(f))

print("\n== 2. robots.txt falla cerrado ==")
for nombre, rob in (("500", (500, "text/plain", b"", {})), ("conexión cortada", "RESET"), ("403", (403, "text/plain", b"", {})),
                    ("Disallow del feed", (200, "text/plain", b"User-agent: *\nDisallow: /feed\n", {}))):
    nueva_bd(robots=rob); RUTAS["/feed"] = rss(["/a2"]); RUTAS["/a2"] = art()
    rc, out = correr()
    check(f"2 robots {nombre}: no se descarga ni el feed ni artículos", hits("/feed") == 0 and hits("/a2") == 0 and rc == 1, f"hits={HITS}")
nueva_bd(robots=(404, "text/plain", b"", {})); RUTAS["/feed"] = rss(["/a2"]); RUTAS["/a2"] = art()
correr()
check("2 robots 404 (no existe): se permite", hits("/a2") == 1 and n("select count(*) from versiones") == 1)
nueva_bd(robots=(200, "text/plain", b"User-agent: *\nDisallow: /a2\n", {})); RUTAS["/feed"] = rss(["/a2"]); RUTAS["/a2"] = art()
correr(); f = fila("/a2")
check("2 Disallow de un artículo: no se descarga y queda bloqueado_robots", hits("/a2") == 0 and f["estado"] == "bloqueado_robots")
check("2 ...pero NO es terminal: se reevalúa en ~24 h", "2026" in f["proxima_revision"] and f["proxima_revision"] > ahora(), dict(f))
RUTAS["/robots.txt"] = (404, "text/plain", b"", {}); vencer(); correr()
check("2 ...si robots.txt cambia, se recupera y se guarda", fila("/a2")["estado"] == "ok" and n("select count(*) from versiones") == 1)

print("\n== 3. Reintentos: todo fallo cuenta, con espera y tope ==")
nueva_bd(); RUTAS["/feed"] = rss(["/a3", "/a4", "/a5"])
RUTAS["/a3"] = (500, "text/html", b"x", {}); RUTAS["/a4"] = "RESET"; RUTAS["/a5"] = art(TEXTO + " BOOM")
correr()
check("3a HTTP 500 cuenta intento y guarda el motivo", fila("/a3")["intentos"] == 1 and fila("/a3")["ultimo_error"] == "HTTP 500", dict(fila("/a3")))
check("3b conexión cortada (excepción) cuenta intento", fila("/a4") is not None and fila("/a4")["intentos"] == 1 and fila("/a4")["estado"] == "descarga_fallida", fila("/a4") and dict(fila("/a4")))
check("3c excepción interna (extractor) cuenta intento", fila("/a5") is not None and fila("/a5")["intentos"] == 1 and "excepción" in (fila("/a5")["ultimo_error"] or ""), fila("/a5") and dict(fila("/a5")))
check("3d espera creciente: no se reintenta antes de tiempo", fila("/a3")["proxima_revision"] > ahora())
h0 = hits("/a3"); correr()
check("3e segunda corrida inmediata no reintenta", hits("/a3") == h0)
for _ in range(10):
    vencer(); correr()
f = fila("/a3")
check("3f tras 8 fallos se abandona (proxima_revision=9999) y deja de pedirse",
      f["intentos"] == recolector.MAX_INTENTOS_FALLO and f["proxima_revision"] == recolector.ABANDONO and hits("/a3") == recolector.MAX_INTENTOS_FALLO,
      f"intentos={f['intentos']} hits={hits('/a3')}")

print("\n== 4. Estados no terminales de golpe ==")
nueva_bd(); RUTAS["/feed"] = rss(["/a6"]); RUTAS["/a6"] = art("corto")
correr(); f = fila("/a6")
check("4a sin_texto cuenta intento y programa revisión", f["estado"] == "sin_texto" and f["intentos"] == 1 and f["proxima_revision"] > ahora())
RUTAS["/a6"] = art(); vencer(); correr()
check("4b si el sitio arregla el texto, el documento se recupera", fila("/a6")["estado"] == "ok" and n("select count(*) from versiones") == 1)
nueva_bd(); RUTAS["/feed"] = rss(["/a7"]); RUTAS["/a7"] = art("corto")
for _ in range(6): correr(); vencer()
check("4c sin_texto se abandona tras 4 intentos", fila("/a7")["proxima_revision"] == recolector.ABANDONO and fila("/a7")["intentos"] == 4, dict(fila("/a7")))

print("\n== 5. Validación de URLs, redirecciones y límites ==")
malos = ["ftp://localhost/x", f"http://user:pw@localhost:{PORT}/x", f"http://127.0.0.1:{PORT}/x", "http://evil.example/x",
         "javascript:alert(1)", f"{BASE}/" + "a" * 3000, "http://localhost:9/x", f"{BASE}/con espacio"]
nueva_bd(); RUTAS["/a8"] = art()
it = "".join(f"<item><title>m</title><link>{u}</link></item>" for u in malos) + f"<item><title>ok</title><link>{BASE}/a8</link></item>"
RUTAS["/feed"] = (200, "application/rss+xml", f"<rss><channel>{it}</channel></rss>".encode(), {})
rc, out = correr()
check("5a URLs peligrosas del feed se rechazan (8) y la buena se guarda", n("select count(*) from documentos") == 1 and "8 URLs rechazadas" in out, out)
check("5b el servidor no recibió ninguna petición a las malas", set(HITS) <= {"/robots.txt", "/feed", "/a8"}, HITS)
nueva_bd(robots=(200, "text/plain", b"User-agent: *\nDisallow: /privado\n", {}))
RUTAS["/feed"] = rss(["/r1", "/r2", "/r3", "/r4", "/b1", "/b2", "/b3", "/dr", "/pdf", "/sl"])
RUTAS["/r1"] = (302, "text/html", b"", {"Location": "http://evil.example/x"})
RUTAS["/r2"] = (302, "text/html", b"", {"Location": "/c1"}); RUTAS["/c1"] = (302, "text/html", b"", {"Location": "/c2"})
RUTAS["/c2"] = (302, "text/html", b"", {"Location": "/c3"}); RUTAS["/c3"] = (302, "text/html", b"", {"Location": "/c4"})
RUTAS["/c4"] = art()
RUTAS["/r3"] = (302, "text/html", b"", {"Location": "/destino"}); RUTAS["/destino"] = art()
RUTAS["/r4"] = (302, "text/html", b"", {"Location": "/privado"}); RUTAS["/privado"] = art()
RUTAS["/b1"] = (200, "text/html", b"x" * 5000, {}); RUTAS["/b2"] = (200, "text/html", b"x" * 5000, {"__sin_largo__": True})
RUTAS["/pdf"] = (200, "application/pdf", b"%PDF" + b"x" * 300, {}); RUTAS["/sl"] = "DRIP"; RUTAS["/dr"] = art()
recolector.MAX_BYTES_HTML = 1000; recolector.DESCARGA_MAX_S = 1
t = time.monotonic(); correr(); dur = time.monotonic() - t
e = lambda r: (fila(r)["ultimo_error"] or "") if fila(r) else "SIN FILA"
check("5c redirección a dominio ajeno rechazada", "redirección rechazada" in e("/r1") and "evil" not in str(HITS), e("/r1"))
check("5d cadena de más de 3 redirecciones rechazada", fila("/r2")["estado"] == "descarga_fallida" and hits("/c4") == 0, e("/r2"))
check("5e redirección dentro del dominio y permitida se sigue", fila("/r3")["estado"] == "ok" and hits("/destino") == 1, e("/r3"))
check("5f redirección hacia zona prohibida por robots rechazada", "robots" in e("/r4") and hits("/privado") == 0, e("/r4"))
check("5g cuerpo demasiado grande (con Content-Length) rechazado", "mayor de" in e("/b1"), e("/b1"))
check("5h cuerpo demasiado grande (sin Content-Length) rechazado", "mayor de" in e("/b2"), e("/b2"))
check("5i tipo de contenido no HTML rechazado", "tipo de contenido" in e("/pdf"), e("/pdf"))
check("5j goteo lento cortado por plazo total", "más lenta" in e("/sl") and dur < 20, f"{e('/sl')} dur={dur:.1f}")

nueva_bd(); RUTAS["/feed"] = rss(["/r5"]); RUTAS["/espejo"] = art()
RUTAS["/r5"] = (302, "text/html", b"", {"Location": f"http://127.0.0.1:{PORT}/espejo"})
correr()
check("5k redirección a una IP literal alcanzable: no se sigue", hits("/espejo") == 0, HITS)
nueva_bd(robots=(302, "text/plain", b"", {"Location": f"http://127.0.0.1:{PORT}/robots_espejo"}))
RUTAS["/robots_espejo"] = (200, "text/plain", b"", {}); RUTAS["/feed"] = rss(["/a9"]); RUTAS["/a9"] = art()
correr()
check("5l robots.txt que redirige fuera de la lista: no se sigue y no se descarga nada",
      hits("/robots_espejo") == 0 and hits("/feed") == 0 and hits("/a9") == 0, HITS)

print("\n== 6. Tope GLOBAL de 10 descargas, repartido entre fuentes ==")
A = [f"/A{i}" for i in range(8)]; B = [f"/B{i}" for i in range(8)]
nueva_bd([fuente("/feedA", "fa"), fuente("/feedB", "fb")])
RUTAS["/feedA"] = rss(A); RUTAS["/feedB"] = rss(B)
for r in A + B: RUTAS[r] = art(TEXTO + r)
rc, out = correr()
tot = sum(hits(r) for r in A + B)
check("6a una corrida con 2 fuentes descarga exactamente 10 páginas en total", tot == 10, f"tot={tot}")
check("6b reparto por turnos: 5 y 5", n("select count(*) from documentos where fuente='fa'") == 5 and n("select count(*) from documentos where fuente='fb'") == 5)
check("6c lo que sobra se informa como pendiente", "pendientes" in out, out)
correr()
check("6d la siguiente corrida completa el resto sin repetir ninguna", all(hits(r) == 1 for r in A + B), {r: hits(r) for r in A + B if hits(r) != 1})
check("6e Opinión existe y está deshabilitada; La Razón habilitada",
      {f["nombre"]: f.get("habilitada", True) for f in FUENTES_REALES} == {"larazon": True, "opinion": False}, FUENTES_REALES)

print("\n== 7. Migración db_setup v2 -> v3 ==")
M = TMP / "m.db"
c = sqlite3.connect(M); c.row_factory = sqlite3.Row; c.executescript(db_setup.ESQUEMA)
try:
    c.execute("DROP INDEX idx_documentos_revision")
    for col in ("ultima_revision", "proxima_revision", "ultimo_error"): c.execute(f"ALTER TABLE documentos DROP COLUMN {col}")
    c.execute("PRAGMA user_version=2")
    c.execute("INSERT INTO documentos (url_canonica,url_original,fuente,primera_captura,estado,intentos) VALUES ('u','u','x','2026-11-24T00:00:00Z','ok',0)")
    c.commit(); c.close()
    migrable = True
except sqlite3.OperationalError as ex:
    print("SKIP  este SQLite no soporta DROP COLUMN:", ex); migrable = False
if migrable:
    def con_m():
        k = sqlite3.connect(M); k.row_factory = sqlite3.Row; return k
    db_setup.conectar = con_m
    with contextlib.redirect_stdout(io.StringIO()) as o: rc1 = db_setup.main()
    k = con_m(); cols = {r[1] for r in k.execute("PRAGMA table_info(documentos)")}
    check("7a migra v2→v3 sin perder datos", rc1 == 0 and {"ultima_revision", "proxima_revision", "ultimo_error"} <= cols
          and k.execute("select count(*) from documentos").fetchone()[0] == 1 and k.execute("PRAGMA user_version").fetchone()[0] == 3)
    k.close()
    with contextlib.redirect_stdout(io.StringIO()): rc2 = db_setup.main()
    check("7b repetirla es inofensiva", rc2 == 0)

print("\n" + ("TODO PASA" if not FALLOS else f"FALLAN {len(FALLOS)}: " + "; ".join(FALLOS)))
sys.exit(1 if FALLOS else 0)
