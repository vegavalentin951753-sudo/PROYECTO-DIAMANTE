# ESTADO (2026-11-25, hora local Bolivia; registros técnicos en UTC)

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

## Extractor Semántico (Fase 0 - Validado en hardware real)
- **Estado:** FUNCIONAL Y VALIDADO (versión 1.0).
- `extractor_json.py` escrito y probado en Termux (Python 3.14.10).
- 62/62 tests pasan en el teléfono usando `unittest` (sin necesidad de instalar `pytest`).
- **Aislamiento verificado:** no importa `sqlite3` ni librerías de red.
- **Prueba con Qwen real:** exitosa. El modelo extrajo hechos y el Guardián validó las citas literales y las cifras.
- **Decisión de diseño:** `SCHEMA_COMO_TEXTO = False` para evitar el doble `json.dumps` (llm_runner ya lo hace).
- **Modo seguro:** El script asume `--dry-run` por defecto. El flag `--guardar` está implementado pero no se ha ejecutado contra la BD real.
- **Limitaciones detectadas:** El LLM a veces extrae sujetos genéricos ("la institución") y el fragmentador corta a mitad de palabra. Requiere ajuste (Módulo 2.1).

## Fuentes estructuradas / BCB
- Se confirmó que una serie pública del BCB corresponde a tipo de cambio USD/BOB.
- Formato observado: JSON con campos `variable`, `unidad`, `datos[]`, y dentro `Fecha`, `Valor`.
- Útil, pero demasiado angosto para ser la única fuente institucional.
- Decisión provisional: posponer `bcb_adapter.py` hasta cerrar extractor JSON.

## Pendiente
- Corregir/compilar `extractor_json.py`.
- Ejecutar pruebas offline del Guardián.
- Ejecutar una demo LLM controlada sin guardar en BD.
- Pedir a Sonnet pruebas reales del extractor, no solo código.
- Revisar términos legales de La Razón y Opinión manualmente si se desea ampliar diarios.
- Más adelante: inventariar otras series BCB, INE, Gaceta, Aduana, SIN.

## Siguiente
- Validar extractor en sandbox/teléfono.
- Solo después: integración cautious con tabla `hechos`.
- Después: adaptador BCB para series estructuradas.

## Fuera de alcance por ahora
- Nube.
- Telegram.
- Informes finales.
- Comercialización.
- Habilitación de Opinión.
- Scraping agresivo de instituciones.