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