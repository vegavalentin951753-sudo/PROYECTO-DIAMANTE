"""Ejecuta llama.cpp como proceso aparte, con tope de tiempo, y mide tiempos, velocidad y RAM.

Este módulo NO importa db ni toca SQLite: el LLM solo recibe un prompt (archivo temporal)
y devuelve texto por stdout. Lo usan test_llm.py y extractor_json.py.
"""
import json
import os
import re
import resource
import signal
import subprocess
import tempfile
import time
from pathlib import Path

HOME = Path.home()
DIR_BIN = Path(os.environ.get("LLAMA_BIN_DIR", HOME / "llama.cpp/build/bin"))
MODELO = Path(os.environ.get("DIAMANTE_MODELO", HOME / "modelos/qwen2.5-1.5b-instruct-q4_k_m.gguf"))
_CAPS = {}


def chatml(sistema, usuario):
    """Formato de chat de Qwen2.5 (ChatML), armado a mano porque usamos modo completion."""
    return (f"<|im_start|>system\n{sistema}<|im_end|>\n"
            f"<|im_start|>user\n{usuario}<|im_end|>\n"
            f"<|im_start|>assistant\n")


def _entorno_limpio():
    """Copia del entorno sin variables que parezcan claves: el LLM no debe verlas."""
    return {k: v for k, v in os.environ.items() if not re.search(r"KEY|TOKEN|SECRET|PASS", k, re.I)}


def encontrar_binario():
    if os.environ.get("LLAMA_BIN"):
        return Path(os.environ["LLAMA_BIN"])
    for nombre in ("llama-completion", "llama-cli"):      # llama-completion = modo de una sola respuesta
        p = DIR_BIN / nombre
        if p.exists():
            return p
    raise FileNotFoundError(f"No hay llama-completion ni llama-cli en {DIR_BIN}")


def capacidades(binario):
    """Lee --help y anota qué opciones soporta ESTA compilación (las opciones cambian entre versiones)."""
    clave = str(binario)
    if clave in _CAPS:
        return _CAPS[clave]
    try:
        r = subprocess.run([clave, "--help"], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL, env=_entorno_limpio())
        texto = (r.stdout or "") + (r.stderr or "")
    except Exception:
        texto = ""
    _CAPS[clave] = {
        "no_cnv": "-no-cnv" in texto,                 # desactiva el modo chat interactivo
        "perf": "--perf" in texto,                    # imprime tiempos al final
        "json_schema": "--json-schema" in texto,      # obliga a que la salida sea JSON válido
        "sin_eco": "--no-display-prompt" in texto,    # no repite el prompt en stdout
        "no_escape": "--no-escape" in texto,          # no tocar los \n literales del texto
        "ayuda_vacia": not texto,
    }
    return _CAPS[clave]


def leer_bateria():
    """Temperatura y % de batería vía Termux:API. None si no se puede leer."""
    try:
        r = subprocess.run(["termux-battery-status"], capture_output=True, text=True, timeout=15,
                           stdin=subprocess.DEVNULL)
        d = json.loads(r.stdout)
        return {"temp_c": d.get("temperature"), "pct": d.get("percentage"), "estado": d.get("status")}
    except Exception:
        return None


def esperar_enfriamiento(temp_max, espera_max_s=300, log=print):
    """Espera hasta que la batería baje de temp_max. Devuelve (lectura, ok). Sin lectura => ok."""
    t0 = time.monotonic()
    while True:
        b = leer_bateria()
        t = b.get("temp_c") if b else None
        if t is None or t < temp_max:
            return b, True
        if time.monotonic() - t0 > espera_max_s:
            return b, False
        log(f"  temperatura {t} °C >= {temp_max} °C; espero 30 s...")
        time.sleep(30)


def _vmhwm_kb(pid):
    """Pico de RAM residente (VmHWM) de un proceso, en KB. 0 si no se puede leer."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for linea in f:
                if linea.startswith("VmHWM:"):
                    return int(linea.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def _matar(p):
    try:
        os.killpg(p.pid, signal.SIGTERM)
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
    except ProcessLookupError:
        pass


def _parse_perf(err):
    """Extrae los tiempos que imprime llama.cpp en stderr (el formato exacto varía por versión)."""
    def tiempo(patron):
        m = re.search(patron, err)
        if not m:
            return None
        ms = float(m.group(1))
        n = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else None
        return ms, n

    out = {}
    carga = re.search(r"load time\s*=\s*([\d.]+)\s*ms", err)
    out["carga_ms"] = float(carga.group(1)) if carga else None
    pe = tiempo(r"prompt eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*(?:tokens|runs)")
    ge = tiempo(r"(?<!prompt )eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*(?:runs|tokens)")
    out["prompt_tokens"] = pe[1] if pe else None
    out["prompt_tps"] = round(pe[1] / (pe[0] / 1000), 2) if pe and pe[0] > 0 else None
    out["gen_tokens"] = ge[1] if ge else None
    out["gen_tps"] = round(ge[1] / (ge[0] / 1000), 2) if ge and ge[0] > 0 else None
    return out


def ejecutar(prompt, max_tokens=256, hilos=4, ctx=4096, timeout_s=300, json_schema=None):
    """Corre el modelo una vez. Nunca lanza por fallos del modelo: devuelve un dict con ok/timeout/etc."""
    binario = encontrar_binario()
    if not MODELO.exists():
        raise FileNotFoundError(f"Falta el modelo: {MODELO}")
    caps = capacidades(binario)

    with tempfile.TemporaryDirectory(prefix="diamante_llm_") as tmp:
        tmp = Path(tmp)
        f_prompt, f_out, f_err = tmp / "prompt.txt", tmp / "salida.txt", tmp / "stderr.txt"
        f_prompt.write_text(prompt, encoding="utf-8")

        cmd = [str(binario), "-m", str(MODELO), "-f", str(f_prompt), "-n", str(max_tokens),
               "-c", str(ctx), "-t", str(hilos), "--temp", "0"]
        for opcion, bandera in (("no_cnv", "-no-cnv"), ("perf", "--perf"),
                                ("sin_eco", "--no-display-prompt"), ("no_escape", "--no-escape")):
            if caps[opcion]:
                cmd.append(bandera)
        usa_esquema = bool(json_schema) and caps["json_schema"]
        if usa_esquema:
            cmd += ["--json-schema", json.dumps(json_schema, ensure_ascii=False)]

        pico_kb, timeout = 0, False
        t0 = time.monotonic()
        with open(f_out, "wb") as fo, open(f_err, "wb") as fe:
            p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe,
                                 start_new_session=True, env=_entorno_limpio())
            try:
                while p.poll() is None:
                    pico_kb = max(pico_kb, _vmhwm_kb(p.pid))
                    if time.monotonic() - t0 > timeout_s:
                        timeout = True
                        _matar(p)
                        break
                    time.sleep(0.25)
            finally:
                if p.poll() is None:          # Ctrl-C, SIGTERM o error nuestro: no dejar el modelo huérfano
                    _matar(p)
        rc = p.returncode
        dt = time.monotonic() - t0
        pico_kb = max(pico_kb, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)

        salida = f_out.read_text(encoding="utf-8", errors="replace")
        err = f_err.read_text(encoding="utf-8", errors="replace")

    return {
        "ok": rc == 0 and not timeout,
        "returncode": rc,
        "timeout": timeout,
        "matado_por_senal": rc is not None and rc < 0 and not timeout,   # -9 = SIGKILL (Android o falta de RAM)
        "segundos": round(dt, 2),
        "ram_pico_mb": round(pico_kb / 1024, 1),
        "salida": salida,
        "stderr_cola": err[-1500:],
        "perf": _parse_perf(err),
        "usa_esquema": usa_esquema,
        "comando": cmd[:cmd.index("-f")] + ["-f", "<prompt>"] + cmd[cmd.index("-f") + 2:],
    }
