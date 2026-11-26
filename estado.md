# ESTADO (2026-11-26, hora local Bolivia; registros técnicos en UTC)

## Probado en el teléfono
- Termux oficial desde F-Droid, Python 3.14.10, Realme 8 Pro.
- Esquema SQLite v3 migrado correctamente.
- Recolector v2 instalado y compilado.
- 42/42 pruebas automáticas del recolector pasan en el teléfono.
- Corrida real contra La Razón estable:
  - idempotencia verificada;
  - versionado funcional;
  - robots.txt fail-closed funcionando;
  - tope global de 10 descargas respetado;
  - 0 documentos con `proxima_revision NULL`.
- `termux-job-scheduler` tiene job periódico de 900000 ms para `tick.sh`.
- Limitación conocida: Android/Doze produce huecos largos nocturnos; mediana ~17 min, máximo observado ~606 min.

## Fase 0: LLM local
- `llama.cpp` compilado en Termux ARM64.
- Binario usable: `llama-completion`.
- Modelo descargado y verificado:
  - `Qwen2.5-1.5B-Instruct`
  - archivo: `qwen2.5-1.5b-instruct-q4_k_m.gguf`
  - tamaño: ~1117 MB
  - firma GGUF verificada.
- Benchmark `test_llm.py`:
  - todas las corridas OK;
  - RAM pico ~2048 MB;
  - temperatura estable ~30.3–30.9 °C;
  - opciones detectadas: `no_cnv`, `perf`, `json_schema`, `sin_eco`, `no_escape`.
- `llama-bench`:
  - 2 hilos: pp128 ~30.32 t/s, tg32 ~11.57 t/s;
  - 4 hilos: pp128 ~32.02 t/s, tg32 ~9.77 t/s;
  - 6 hilos: pp128 ~36.14 t/s, tg32 ~10.18 t/s.
- Decisión técnica: para generación usar `-t 2`, porque mejora tg32 en este Snapdragon 720G.

## Extractor Semántico (Módulo 2.1 - Cerrado el 2026-11-26)
- **Estado:** MÓDULO 2.1 CERRADO Y VALIDADO (commit `a1c4163` en `main`).
- `extractor_json.py` y `test_extractor_21.py` probados en Termux (Python 3.14.10).
- **69/69 tests pasan en el teléfono** usando `unittest` (62 anteriores + 7 nuevos del Módulo 2.1).
- **Aislamiento verificado:** no importa `sqlite3` ni librerías de red.
- **Afinación 2.1 aplicada:**
  - Fragmentación sin cortar palabras (`_corte_seguro` + `_cortar_largo`).
  - Prompt endurecido con 3 reglas explícitas de sujeto.
  - Guardián ampliado con `sujeto_generico` y `sujeto_no_en_cita`.
- **Decisión de diseño:** `SCHEMA_COMO_TEXTO = False` (validado en hardware real; `llm_runner` serializa internamente).
- **Modo seguro:** El script asume `--dry-run` por defecto. El flag `--guardar` está implementado pero no se ha ejecutado contra la BD real.

## Fuentes estructuradas / BCB
- Se confirmó que una serie pública del BCB corresponde a tipo de cambio USD/BOB.
- Formato observado: JSON con campos `variable`, `unidad`, `datos[]`, y dentro `Fecha`, `Valor`.
- Contrato de `bcb_adapter.py` aprobado; pendiente definir 5 puntos de diseño antes de programar.
- Útil, pero demasiado angosto para ser la única fuente institucional (conservar esta observación del estado anterior).

## Pendiente
- Ejecutar demo `--dry-run` post-2.1 contra texto real de la BD para medir calidad (aceptados vs rechazados).
- Cerrar 5 decisiones de diseño de `bcb_adapter.py` e implementarlo.
- Primera corrida controlada con `--guardar` y validar inserción en tabla `hechos`.
- Revisar términos legales de La Razón y Opinión manualmente si se desea ampliar diarios.
- Más adelante: inventariar otras series BCB, INE, Gaceta, Aduana, SIN.

## Siguiente
1. Demo `--dry-run` contra texto real de la BD para medir calidad post-2.1.
2. Diseñar e implementar `bcb_adapter.py`.
3. Primera corrida con `--guardar` y validar inserción en tabla `hechos`.

## Fuera de alcance por ahora
- Nube.
- Telegram.
- Informes finales.
- Comercialización.
- Habilitación de Opinión.
