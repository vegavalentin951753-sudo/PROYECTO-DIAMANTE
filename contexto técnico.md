**CONTEXTO TÉCNICO DEL SISTEMA EXISTENTE:**

1. **Interfaz del LLM (`llm_runner.py`):**
   - La función se llama así: `ejecutar(prompt, max_tokens=256, hilos=4, ctx=4096, timeout_s=300, json_schema=None)`
   - Retorna un diccionario (dict). No lanza excepciones por fallos del modelo. Las claves que devuelve incluyen: `ok` (bool), `salida` (str con el JSON crudo), `timeout` (bool), `err` (str), `gen_tokens` (int), `gen_tps` (float), etc.
   - Internamente, si se le pasa `json_schema`, `llm_runner` ya se encarga de pasarlo a `llama.cpp` usando el flag `--json-schema`.

2. **Base de Datos (`db.py` y Esquema):**
   - Para conectar: `import db; conn = db.conectar()` (ya maneja WAL, foreign_keys, etc.).
   - Para hora UTC: `from db import ahora_utc`.
   - **Tabla `hechos`:**
     - `id` (INTEGER PK)
     - `version_id` (INTEGER NOT NULL, FK a `versiones`)
     - `sujeto` (TEXT)
     - `accion` (TEXT)
     - `objeto` (TEXT)
     - `cita_literal` (TEXT NOT NULL) -> Debe ser exacta al texto original.
     - `tipo` (TEXT DEFAULT 'hecho', CHECK: 'hecho','declaracion','opinion','proyeccion')
     - `estado` (TEXT DEFAULT 'pendiente_validacion', CHECK: 'pendiente_validacion','validado','rechazado')
     - `motivo_rechazo` (TEXT)
     - `fecha_creacion` (TEXT NOT NULL) -> Usar `ahora_utc()`
   - **Nota para el script:** El script `extractor_json.py` NO debe importar `sqlite3` ni hacer consultas SQL. En el modo `--guardar`, debe usar `db.conectar()` y hacer un `INSERT` limpio, simulando la inserción o usando una BD de prueba (ej. `:memory:` o tmp_path en pytest).
## Módulo: Extractor Semántico (`extractor_json.py`)
- **Estado:** Funcional (v1.0), validado en Python 3.14.10 / Termux.
- **Interfaz:** `python extractor_json.py --input <archivo> --max-fragmentos N --version-id ID [--dry-run | --guardar]`
- **Salida:** Imprime un resumen en consola. Por defecto es `dry-run`. El flag `--guardar` requiere `--version-id`.
- **Aislamiento:** No importa `sqlite3` ni librerías de red. Usa `llm_runner.ejecutar()`.
- **Guardián:** Verifica cita literal en el texto y que las cifras coincidan. Los hechos inválidos se marcan como `estado='rechazado'` (no se borran).
- **Pruebas:** 62 tests en `test_extractor_json.py` (usando `unittest` estándar).
- **Configuración:** `SCHEMA_COMO_TEXTO = False` (porque `llm_runner` hace el `json.dumps`).