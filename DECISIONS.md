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