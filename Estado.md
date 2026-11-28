# ESTADO (2026-11-27, hora local Bolivia; registros técnicos en UTC)

## 1. Estado actual verificado (Realme 8 Pro / Termux)
- **Entorno:** Termux oficial (F-Droid), Python 3.14.10, SQLite 3.54.1, modo WAL.
- **Tests:** 153/153 OK en Termux (`test_extractor_json`, `test_extractor_21`, `test_extractor_22`, `test_extractor_23`, `test_db_setup_v4`) en 13.627s sobre bases temporales. Recolector v2 con 42/42 pruebas previas en verde y sin colisiones con `user_version=4`.
- **Base de producción (`~/diamante/diamante.db`):**
  - Migrada atómicamente de esquema v3 a **v4** (`user_version=4`, índice único `ux_hechos_identidad` presente, `integrity_check=ok`, ninguna fila previa modificada).
  - Conteo previo base: `documentos=333`, `versiones=347`, `crudos=347`, `ejecuciones=235`, `tareas=0`.
- **Backups externos verificados (`VACUUM INTO`, copiados fuera del teléfono vía `scp`):**
  - Pre-v4: `pre_v4_20261127.db` (`integrity_check=ok`, conteos idénticos).
  - Post-v4 / pre-escritura: `pre_escritura_20261127.db` (`integrity_check=ok`, conteos idénticos).
- **Primera escritura real (`--guardar`) e idempotencia:**
  - `v244`: `6` hechos guardados (`4` validados, `2` rechazados). 2.ª corrida idempotente (`filas_insertadas=0`, `omitidas_por_duplicado=6`).
  - `v243`: `7` hechos guardados (`5` validados, `2` rechazados). 2.ª corrida idempotente (`filas_insertadas=0`, `omitidas_por_duplicado=7`).
  - `v231`: `7` hechos guardados (`2` validados, `5` rechazados). 2.ª corrida idempotente (`filas_insertadas=0`, `omitidas_por_duplicado=7`).
  - **Auditoría global (`244`, `243`, `231`):** `20` hechos (`11` validados, `9` rechazados), `0` duplicados, `0` citas validadas ausentes del texto, `0` estados contradictorios, `AUDITORIA: sin problemas`.
- **Métricas Paso 14 y parámetros del extractor:**
  - `salida_recuperada=0`, `json_invalido=0`, `fragmentos_en_tope(5)=0`; máximo `208/384` tokens generados y máximo `3` hechos/fragmento; `cita_literal` máx. `300` chars.
  - **Decisión:** mantener `MAX_TOKENS_LLM=384`, `MAX_HECHOS_POR_FRAGMENTO=5`, `HILOS_LLM=2`, `SCHEMA_COMO_TEXTO=False` y sin tope adicional de `cita_literal`.
- **LLM local:** `llama-completion` + `Qwen2.5-1.5B-Instruct` (`q4_k_m.gguf`, ~1117 MB), temperatura en corridas `28.5–33.7 °C`.
- **Ingesta:** Recolector v2 activo con `termux-job-scheduler` (900000 ms), `robots.txt` fail-closed, La Razón estable; Opinión deshabilitada.

## 2. Últimos cambios y commits (`main`)
- `4ccaea3`: parche defensivo 2.2 (Bug A: `strict=False` y rescate de hechos completos).
- `4d7736a`: entrega Persistencia 2.3 (`db_setup.py`, `extractor_json.py`, `diagnostico_db.py`, `test_extractor_json.py`, `test_extractor_23.py`, `test_db_setup_v4.py`).
- `4abc271`: actualización y estandarización de `.md` (`Arquitectura.md`, `Decisiones.md`, `Estado.md`, `PROCEDIMIENTO_PRIMERA_ESCRITURA.md`, `Contexto_tecnico.md`).

## 3. Pendientes técnicos ordenados por prioridad
1. **Cerrar el vínculo texto ↔ `version_id` (prioridad 1):** impedir en código que un texto se guarde bajo un `version_id` que no le corresponde antes de ampliar `--guardar`.
2. **Observaciones técnicas acotadas (D):**
   - Verificar la definición exacta del índice `ux_hechos_identidad` (no solo nombre y propiedad `UNIQUE`).
   - Reforzar la verificación de `backup` o ajustar su mensaje para reflejar exactamente lo que comprueba.
3. **`bcb_adapter.py`:** resolver las 5 decisiones de diseño pendientes (tabla destino, idempotencia, hash de archivo, reloj, ubicación del módulo) e implementar primero con fixtures JSON.
4. **Higiene y alcance futuro:** revisar términos legales de La Razón y Opinión si se amplían diarios; inventariar otras series (BCB, INE, Gaceta, Aduana, SIN). Nube, Telegram, informes y Opinión siguen fuera de alcance por ahora.

## 4. Próximo ciclo de trabajo
1. Auditoría independiente de continuidad sobre `vegavalentin951753-sudo/PROYECTO-DIAMANTE` (`main`).
2. Diseño, implementación y pruebas del cierre del vínculo texto ↔ `version_id` + observaciones D.
3. Diseño e implementación de `bcb_adapter.py` con fixtures antes de tocar datos reales.
