# Registro de Decisiones Arquitectónicas (ADR)

## [2026-11-24] - Fase 0: Python 3.14 y Dependencias
*   **Problema:** `spaCy` falló al compilar en Python 3.14 (Android ARM64) por falta de wheels precompiladas de `numpy` y `blis`.
*   **Decisión:** Se descarta `spaCy` para el MVP-1. Se usará `regex` nativo de Python y diccionarios propios (gazetteers) para instituciones bolivianas.
*   **Problema 2:** `lxml` falló al compilar.
*   **Solución:** Se instalaron los paquetes de sistema `libxml2` y `libxslt` mediante `pkg`, y luego `python-lxml`.

## [2026-11-24] - Eliminación del "Agente Crítico" LLM
*   **Decisión:** No usar un modelo local para revisar lo que escribió otro modelo.
*   **Razón:** Un modelo de 1.5B revisando a otro de 1.5B tiene los mismos sesgos y alucinaciones. Se reemplaza por validación determinista en Python (comprobar que las cifras y citas existan literalmente en el texto original).

## [2026-11-24] - Uso de `termux-job-scheduler`
*   **Decisión:** No usar `cron` de Termux.
*   **Razón:** Android mata los procesos de `cron` cuando cierra la app. `termux-job-scheduler` usa el API nativo de Android (JobScheduler), que sobrevive en segundo plano.

## [2026-11-24] - Longitud de los Informes
*   **Decisión:** Los informes no tendrán una longitud fija de 2000 palabras.
*   **Razón:** Si hay pocos hechos, el modelo rellenará con "paja" o inventará relaciones. La longitud será proporcional a la cantidad de hechos validados disponibles.

## [2026-11-24] - Enrutador de Nube
*   **Decisión:** No usar `LiteLLM`.
*   **Razón:** Tiene demasiadas dependencias pesadas para Termux. Se usará la librería nativa `urllib` o `httpx` para hacer peticiones HTTP directas a las APIs, con lógica de reintentos propia.

## [2026-11-24] - Migración a F-Droid (Firmas y Estabilidad)
*   **Problema:** El Termux instalado desde GitHub tenía una firma de depuración ("debug") que impedía la actualización automática y bloqueaba la integración con `Termux:API`.
*   **Decisión:** Desinstalar Termux de GitHub e instalar la versión oficial de **F-Droid**, junto con `Termux:API` (también de F-Droid).
*   **Consecuencia:** Se restableció la base de datos desde un backup (`diamante_backup.db`) y se reconfiguró el acceso SSH (puerto 8022). El entorno ahora es 100% estable y seguro.

## [2026-11-24] - Límite de Frecuencia en `termux-job-scheduler`
*   **Problema:** Se intentó programar un "tick" de prueba cada 60,000 ms (1 minuto). El sistema respondió forzando el intervalo a 900,000 ms (15 minutos).
*   **Decisión:** Aceptar la restricción de Android. Los "ticks" del sistema (Despachador) se programarán con un mínimo de 15 a 30 minutos. Para tareas que requieran inmediatez, se dependerá del flujo manual o de la nube.

## [2026-11-24] - Creación Exitosa del Esquema SQLite
*   **Decisión:** Se implementó el script `db_setup.py` para crear las tablas `documentos`, `hechos` y `tareas`. 
*   **Detalle técnico:** Se utilizó el comando `cat << 'EOF'` en Termux para evitar errores de indentación de Termius (el editor `nano` pegaba el código en una sola línea). Se habilitó el modo WAL y `synchronous=NORMAL` para balancear velocidad y durabilidad.
## [2026-11-24] - Módulo 1 (Recolector) validado en el teléfono
* Hecho: 10 noticias reales de La Razón guardadas; la segunda corrida dio 0 nuevas y 10 ya conocidas (idempotencia por URL verificada en el teléfono).
* Problema: el feed respondió HTTP 403 con el User-Agent propio.
* Decisión: usar el User-Agent de Chrome en Android para leer feeds. Riesgo: sortea un bloqueo del sitio. Mitigación: uso personal, máx. 10 descargas por tick, pausa de 2 s, sin redistribuir texto.
* Pendiente: revisar robots.txt y términos de La Razón; trafilatura.fetch_url usa su propio User-Agent (unificar si hace falta).
## [2026-11-24] - Esquema v2
* documentos (una fila por URL) separado de versiones (una por texto distinto) + crudos (HTML comprimido); hechos cuelga de version_id.
* Fechas en UTC ISO 8601 con Z; ON CONFLICT DO NOTHING en vez de INSERT OR IGNORE; tope de 10 descargas y 6 min por tick; candado de ejecución; tabla ejecuciones como latido.
## [2026-11-25] - Validación de Ingesta y Limitaciones de Plataforma
* Se confirma el funcionamiento del Recolector v2 en hardware real (Realme 8 Pro/Termux).
* Se adopta la política de "Fail Closed" para robots.txt, verificada en pruebas unitarias y reales.
* Se acepta la limitación de suspensión de procesos de Android (Doze) como riesgo conocido para la MVP. Los ticks nocturnos pueden demorarse significativamente (>1h). No se implementan soluciones complejas de Wakelock hasta validar la utilidad real de los datos nocturnos.
* La fuente "Opinión" permanece deshabilitada técnicamente pese a cumplir requisitos de robots.txt, aguardando aprobación legal explícita.
* Se autoriza el inicio de la Fase 0 (Integración LLM Local) dado que la capa de datos estructurada es estable.
## [2026-11-25] - Convención de fechas y husos horarios

* La base de datos y los logs técnicos usan UTC ISO 8601 con sufijo Z.
* La documentación humana del proyecto usa fecha local de Bolivia, salvo indicación contraria.
* Cuando exista discrepancia entre fecha local y UTC, se registrará ambas si es relevante.
* Motivo: evitar confusiones en ADRs, benchmarks y auditorías entre IAs con distintos relojes base.

## [2026-11-25] - Fase 0 LLM validada en hardware real

* Se confirma `llama.cpp` compilado en Termux ARM64.
* Se usa `llama-completion` como binario principal.
* Se valida Qwen2.5-1.5B-Instruct Q4_K_M GGUF, archivo `qwen2.5-1.5b-instruct-q4_k_m.gguf`, ~1117 MB.
* RAM pico observada: ~2048 MB.
* Temperatura observada: ~30.3–30.9 °C, sin throttling térmico evidente.
* Opciones soportadas detectadas: `--json-schema`, `--perf`, `-no-cnv`, `--no-display-prompt`, `--no-escape`.
* Benchmark `llama-bench` muestra que para generación de tokens, 2 hilos supera a 4 y 6 hilos en este dispositivo.
* Decisión: el extractor usará `-t 2` por defecto para generación, priorizando tg32 sobre pp128.

## [2026-11-25] - Extractor JSON en borrador, no aceptado

* Sonnet entregó un borrador de `extractor_json.py`.
* El diseño es coherente con la arquitectura Data-Centric:
  - LLM aislado vía `llm_runner`;
  - sin acceso a SQLite desde el proceso del modelo;
  - validación dura de `cita_literal`;
  - rechazo de cifras fuera de la cita;
  - manejo de JSON inválido/incompleto;
  - tareas con lease y reintentos.
* Sin embargo, no se acepta como estable todavía porque:
  - se detectó error de indentación en `main()`;
  - no se entregaron pruebas ejecutadas;
  - no se entregaron mutaciones;
  - no se validó contra el teléfono más allá del benchmark base.
* Regla operativa: no usar `--guardar` hasta pasar pruebas offline y demo controlada.

## [2026-11-25] - BCB: serie confirmada limitada a tipo de cambio

* Se inspeccionó una muestra JSON del BCB correspondiente al Gráfico Evolutivo.
* La serie observada es tipo de cambio en bolivianos por dólar estadounidense.
* Estructura mínima observada:
  - `variable`
  - `unidad`
  - `datos[]`
  - campos `Fecha` y `Valor`
* Decisión: BCB sigue siendo fuente institucional prioritaria, pero su adaptador se pospone.
* Razón: primero debe validarse el extractor semántico local; después se integrarán series estructuradas sin LLM.
## [2026-11-26] - Extractor validado en teléfono (Dry-Run)
*   **Hecho:** El `extractor_json.py` de Sonnet corrió con Qwen 1.5B real en el Realme 8 Pro. Se procesó un texto de la BD y se extrajeron 4 hechos válidos.
*   **Decisión sobre `unittest` vs `pytest`:** Se adopta `unittest` (librería estándar) para las pruebas del extractor. Evita depender de la red para instalar dependencias en Termux. `pytest` puede correrlos si se desea, pero no es obligatorio.
*   **Decisión sobre el esquema JSON:** `llm_runner.py` hace el `json.dumps` internamente. Por lo tanto, el extractor debe pasarle el diccionario (`SCHEMA_COMO_TEXTO = False`).
*   **Aislamiento Confirmado:** El script usa un import perezoso de `llm_runner`. Si no se va a usar el modelo, se puede importar el archivo sin que colapse.
*   **Pendiente de mejora:** Fragmentación por oraciones y prompt de sistema más estricto para evitar sujetos genéricos.