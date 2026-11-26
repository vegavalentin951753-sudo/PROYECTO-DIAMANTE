"""Benchmark mínimo de llama.cpp en el teléfono. No toca la base de datos.

Mide: tiempo de carga, tokens/s del prompt y de la generación, pico de RAM y temperatura.
Uso:  python test_llm.py            (o con --hilos 2, --repeticiones 3, etc.)
"""
import argparse
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import llm_runner as R

BASE_DIR = Path(__file__).resolve().parent
SISTEMA = "Eres un asistente conciso. Responde en español."
PARRAFO = ("El banco central publicó el nuevo informe de comercio exterior con las cifras de importaciones "
           "y exportaciones del trimestre, y la aduana anunció cambios en los controles de frontera. ")


def correr(nombre, prompt, n_tokens, a, timeout_s):
    bat0, ok = R.esperar_enfriamiento(a.temp_max)
    if not ok:
        print(f"[{nombre}] ABORTO: el teléfono sigue a {bat0 and bat0.get('temp_c')} °C tras 5 min de espera.")
        return None
    r = R.ejecutar(prompt, max_tokens=n_tokens, hilos=a.hilos, ctx=4096, timeout_s=timeout_s)
    bat1 = R.leer_bateria()
    p = r["perf"]
    t0 = bat0 and bat0.get("temp_c")
    t1 = bat1 and bat1.get("temp_c")
    print(f"[{nombre}] {'ok' if r['ok'] else 'FALLO'} | total {r['segundos']} s | carga {p['carga_ms']} ms | "
          f"prompt {p['prompt_tokens']} tok @ {p['prompt_tps']} t/s | gen {p['gen_tokens']} tok @ {p['gen_tps']} t/s | "
          f"RAM pico {r['ram_pico_mb']} MB | temp {t0}→{t1} °C")
    if not r["ok"]:
        print(f"   returncode={r['returncode']} timeout={r['timeout']} matado_por_senal={r['matado_por_senal']}")
        if r["matado_por_senal"]:
            print("   Android pudo matar el proceso (Phantom Process Killer o falta de RAM). Pega el stderr.")
        print("   stderr (cola):", r["stderr_cola"][-600:])
    elif p["gen_tps"] is None:
        print("   No pude leer los tiempos del stderr. Pega esto tal cual:")
        print("   ", r["stderr_cola"][-600:])
    r["nombre"], r["temp_antes"], r["temp_despues"] = nombre, t0, t1
    return r


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))      # que el finally del runner mate al modelo
    ap = argparse.ArgumentParser()
    ap.add_argument("--hilos", type=int, default=4)
    ap.add_argument("--repeticiones", type=int, default=2)
    ap.add_argument("--temp-max", type=float, default=41.0, help="°C de batería; supuesto, ajustable")
    ap.add_argument("--pausa", type=int, default=20, help="segundos de pausa entre corridas")
    a = ap.parse_args()

    binario = R.encontrar_binario()
    print("Binario:", binario)
    print("Modelo :", R.MODELO, "(%.0f MB)" % (R.MODELO.stat().st_size / 1e6))
    print("Opciones detectadas:", R.capacidades(binario))
    print("Batería:", R.leer_bateria())

    corridas = []
    corridas.append(correr("A_carga", R.chatml(SISTEMA, "Hola"), 1, a, timeout_s=240))
    prompt_largo = R.chatml(SISTEMA, "Resume en una frase:\n" + PARRAFO * 5)
    for i in range(a.repeticiones):
        time.sleep(a.pausa)
        corridas.append(correr(f"B{i + 1}_rendimiento", prompt_largo, 64, a, timeout_s=300))

    hechas = [c for c in corridas if c]
    b = [c for c in hechas if c["nombre"].startswith("B")]
    criterios = [
        ("todas las corridas terminaron sin fallo ni timeout", len(hechas) == len(corridas) and all(c["ok"] for c in hechas)),
        ("tokens/s de prompt y de generación medidos", bool(b) and all(c["perf"]["gen_tps"] and c["perf"]["prompt_tps"] for c in b)),
        ("RAM pico medida (> 0)", bool(hechas) and all(c["ram_pico_mb"] > 0 for c in hechas)),
        ("temperatura medida antes y después", bool(hechas) and all(c["temp_antes"] is not None and c["temp_despues"] is not None for c in hechas)),
    ]
    print("\nCRITERIOS")
    for texto, cumple in criterios:
        print(" ", "PASA " if cumple else "FALLA", texto)

    ruta = BASE_DIR / ("bench_llm_%s.json" % datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    ruta.write_text(json.dumps({"hilos": a.hilos, "corridas": hechas}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("Detalle guardado en:", ruta)
    return 0 if all(c for _, c in criterios) else 1


if __name__ == "__main__":
    sys.exit(main())
