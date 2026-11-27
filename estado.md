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

## Extractor Semántico (Módulo 2.1 + parche defensivo 2.2 - Cerrado 2026-11-26)
- **Estado:** CERRADO Y VALIDADO. Commit `a1c4163` (2.1) + parche defensivo Bug A sin commitear aún.
- **78/78 tests OK** en Termux (Python 3.14.10): 62 base + 7 del 2.1 + 9 del parche defensivo.
- **Comparación 2.1 vs original (válida, 3 noticias reales):**
  - v244: original 2 aceptados / 2.1 4 aceptados (recupera 2 válidos).
  - v243: original 1 error truncado / 2.1 0 errores + rechaza 3 falsos positivos de "Marka".
  - v231: original 1 error truncado / 2.1 0 errores + rechaza 2 falsos positivos.
  - **Veredicto: 2.1 gana.** Elimina truncados por fragmentación robusta, filtra sujetos fuera de cita, mejora tipo a `declaracion`.
- **Bug A (truncado por tope de tokens):** parche defensivo aplicado (`strict=False` + rescate de hechos completos antes del corte). No se reproduce en las 3 noticias con el 2.1, pero protege contra futuras noticias largas.
- **Bug B (falso positivo):** el 2.1 rechaza "Marka" por `sujeto_no_en_cita`. El test se conserva como contrato.
- **Aislamiento:** no importa `sqlite3` ni librerías de red.
- **`SCHEMA_COMO_TEXTO = False`.** `HILOS_LLM = 2`. `MAX_TOKENS_LLM = 384`. `MAX_HECHOS_POR_FRAGMENTO = 5`.
- **`--guardar` implementado pero NO ejecutado contra la BD real todavía.**

## Fuentes estructuradas / BCB
- Se confirmó que una serie pública del BCB corresponde a tipo de cambio USD/BOB.
- Formato observado: JSON con campos `variable`, `unidad`, `datos[]`, y dentro `Fecha`, `Valor`.
- Contrato de `bcb_adapter.py` aprobado; pendiente definir 5 puntos de diseño antes de programar.
- Útil, pero demasiado angosto para ser la única fuente institucional (conservar esta observación del estado anterior).

## Pendiente
- Cerrar 5 decisiones de diseño de `bcb_adapter.py` e implementarlo.
- Primera corrida controlada con `--guardar` y validar inserción en tabla `hechos`.
- Revisar términos legales de La Razón y Opinión manualmente si se desea ampliar diarios.
- Más adelante: inventariar otras series BCB, INE, Gaceta, Aduana, SIN.

## Siguiente
1. Primera corrida `--guardar` controlada sobre v244, v243, v231 (ya validadas en dry-run).
2. Higiene de BDs: `~/diamante.db` (raíz) → renombrar a `.old_esquema_viejo`. `~/repo_github/diamante.db` → confirmar `.gitignore`. `~/diamante_backup_20261126/` → conservar.
3. Fix UX `--input`: si parece ruta (empieza con `/`, `./`, `~/`, `../` o termina en `.txt/.md/.json/.html`) y no existe → `FileNotFoundError`, no procesar como texto.
4. Decidir (con datos post-`--guardar`): subir `MAX_TOKENS_LLM` a 512, bajar `MAX_HECHOS_POR_FRAGMENTO` a 3, o limitar `maxLength` de `cita_literal` en schema.
5. `bcb_adapter.py` (5 decisiones de diseño pendientes).

## Fuera de alcance por ahora
- Nube.
- Telegram.
- Informes finales.
- Comercialización.
- Habilitación de Opinión.
