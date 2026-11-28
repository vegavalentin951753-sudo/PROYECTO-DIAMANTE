# Procedimiento: primera escritura controlada (Módulo 2.3)

Fecha: 2026-11-27. **No ejecutar nada de esto sin Go explícito.**
Probado solo en sandbox (Python 3.12, modelo falso). En Termux (Python 3.14.10) está **sin probar**.

Etiquetas: **[LECTURA]** no cambia nada · **[ARCHIVO]** crea un archivo nuevo fuera de la base · **[MODIFICA BASE]** escribe en `diamante.db`.
Ningún comando de este documento borra ni sobrescribe la base (`backup` y `exportar` se niegan a pisar archivos).
Si algo sale distinto a lo esperado: **detente y pega la salida completa, errores incluidos.**

## 0. Preparar el repo (primero el parche 2.2, aparte)

```bash
cd <carpeta donde está db.py>      # si no sabes cuál: find ~ -maxdepth 3 -name db.py
git status --short                 # [LECTURA]
python -m unittest test_extractor_json test_extractor_21 test_extractor_22
```
Esperado: `Ran 78 tests ... OK`. Si no: **STOP**.

Commit del 2.2 (ya está en tu código, sin commit):
```bash
git diff --stat a1c4163 -- extractor_json.py     # [LECTURA] debe mostrar solo cambios del 2.2
git add extractor_json.py test_extractor_22.py
git commit -m "extractor: parche defensivo 2.2 (Bug A): strict=False y rescate de hechos completos"
```

## 1. Copiar la entrega y verificar hashes

Copia estos 6 archivos a la carpeta de `db.py` (scp por el puerto 8022, o `termux-setup-storage` y `cp ~/storage/downloads/...`):
`db_setup.py extractor_json.py diagnostico_db.py test_extractor_json.py test_extractor_23.py test_db_setup_v4.py`

```bash
sha256sum db_setup.py extractor_json.py diagnostico_db.py test_extractor_json.py test_extractor_23.py test_db_setup_v4.py | cut -c1-16,65-
```
Los 16 primeros caracteres deben ser, en ese orden:
```
ac5a2bdeabaf0e5a  db_setup.py
a12e7d42f5a42960  extractor_json.py
53c65382e857059a  diagnostico_db.py
29f5ecbe15b1b380  test_extractor_json.py
b68ca397511310ba  test_extractor_23.py
93a0efd3cba8203c  test_db_setup_v4.py
```
Si uno no coincide: **STOP** (archivo truncado o editado).

## 2. Tests en el teléfono (usan bases temporales, no la real)

```bash
python -m unittest test_extractor_json test_extractor_21 test_extractor_22 test_extractor_23 test_db_setup_v4
```
Esperado: `Ran 153 tests ... OK`. Luego **los 42 del recolector** (el cambio de `db_setup.py` los puede afectar):
```bash
grep -n "user_version\|VERSION_ESQUEMA\|db_setup" *.py | grep -v "^test_db_setup_v4\|^test_extractor_23\|^diagnostico_db\|^db_setup"   # [LECTURA]
python -m unittest discover -p "test_*.py"
```
Esperado: todo `OK` (153 + los 42 del recolector). **STOP** si el recolector falla o si algún módulo compara `user_version == 3`.

## 3. Identificar la base real [LECTURA]

```bash
python diagnostico_db.py base
```
Muestra la ruta exacta que usa `db.py` (carpeta de `db.py` + `diamante.db`), tamaño, `-wal`, `user_version`, conteos y **otros `diamante*.db*` del HOME** (los viejos que no se usan).
Esperado ahora: `user_version=3`, índice `FALTA`, `hechos=0`. **STOP** si la ruta no es la que esperas o `hechos` ≠ 0.

## 4. Comprobar las 3 versiones [LECTURA]

```bash
python diagnostico_db.py version 244 243 231
python diagnostico_db.py auditar 244 243 231
```
Revisa título, URL y comienzo del texto: deben ser las noticias esperadas. Esperado: `hechos ya guardados: 0` y `AUDITORIA: sin problemas`. **STOP** si alguna dice `NO EXISTE` o no es la noticia.

## 5. Backup antes de migrar [ARCHIVO]

```bash
mkdir -p ~/diamante_backups
python diagnostico_db.py backup ~/diamante_backups/pre_v4_20261127.db
```
Esperado: `VERIFICACION: OK`, `integrity_check de la copia: ok`, conteos iguales. **STOP** si dice `FALLO`.
Copia el archivo **fuera del teléfono** (scp -P 8022 desde tu PC). Comprueba que la copia se lee:
```bash
python diagnostico_db.py --db ~/diamante_backups/pre_v4_20261127.db base   # [LECTURA]
```
No uses `cp diamante.db`: con WAL los datos recientes viven en `-wal` y la copia saldría incompleta.

## 6. Migrar a esquema v4 [MODIFICA BASE: solo el esquema, ninguna fila]

```bash
python db_setup.py
python diagnostico_db.py base      # [LECTURA]
```
Esperado: `Migrado a esquema v4 (...ninguna fila modificada)`, `integrity_check=ok`, luego `user_version=4` e índice `PRESENTE`.
- `database is locked`: el tick del recolector está escribiendo; espera 1 min y repite (es seguro).
- `NO se migró a v4 ... filas repetidas`: **STOP**, no se cambió nada; pega la salida.
Backup limpio previo a escribir:
```bash
python diagnostico_db.py backup ~/diamante_backups/pre_escritura_20261127.db
```

## 7. Texto exacto de la versión [ARCHIVO]

```bash
mkdir -p ~/diamante_export
V=244
python diagnostico_db.py exportar $V ~/diamante_export/v$V.txt
```
Usa **siempre la misma variable `$V`** en los pasos 7 a 11: el extractor no puede comprobar que el texto sea de esa versión (riesgo conocido, ver Pendientes).

## 8. Comprobación sin escritura (usa el modelo)

```bash
termux-battery-status | grep -E "temperature|percentage"
python extractor_json.py --input ~/diamante_export/v$V.txt --dry-run 2>&1 | tee -a ~/diamante_export/dry_v$V.log
termux-battery-status | grep -E "temperature|percentage"
```
Esperado: `[dry-run] ... (nada escrito)`. Para v244 el dry-run anterior dio 4 aceptados / 0 rechazados; si ahora difiere, **STOP** y averigua por qué (¿otro texto de entrada?). Si la temperatura pasa de lo habitual (~31 °C) o sube mucho, deja enfriar.

## 9. Primera persistencia, solo v244 [MODIFICA BASE]

```bash
python extractor_json.py --input ~/diamante_export/v$V.txt --guardar --version-id $V 2>&1 | tee -a ~/diamante_export/guardar_v$V.log; echo "codigo=${PIPESTATUS[0]}"
```
Esperado (si coincide con el dry-run): `codigo=0` y una línea como
`Resumen [guardar]: ... aceptados=4 rechazados=0 errores=0 (proceso=0 guardado=0) filas_insertadas=4 (validadas=4 rechazadas=0) omitidas_por_duplicado=0 ...`

Cómo leer el resumen: `aceptados/rechazados` es lo que opinó el Guardian; **`filas_insertadas` es lo que SQLite escribió de verdad**; `omitidas_por_duplicado` ya existían; `rechazados_sin_registro` no tenían forma de objeto y no se guardan.
Con `errores=0` debe cumplirse: `filas_insertadas + omitidas_por_duplicado = aceptados + rechazados − rechazados_sin_registro`.

| codigo | significa | qué hacer |
|---|---|---|
| 0 | todo bien | seguir |
| 4 | base sin índice v4; no se llamó al modelo | repetir el paso 6 |
| 3 | todos los fragmentos fallaron | leer `ERROR:`; `guardado_fallo ... FOREIGN KEY` = `version_id` inexistente → paso 4 |
| 5 | algún fragmento no se guardó, el resto sí | pegar la salida; se puede reintentar (es idempotente) |
| 1 | entrada ilegible o ruta inexistente | revisar el nombre del archivo |

## 10. Verificar contenido y duplicados [LECTURA]

```bash
python diagnostico_db.py hechos $V
python diagnostico_db.py auditar $V
python diagnostico_db.py base | grep "hechos por estado"
```
Esperado: los hechos mostrados coinciden con los del dry-run; `AUDITORIA: sin problemas` (0 duplicados, 0 citas validadas ausentes del texto de la versión, 0 estados contradictorios). **STOP** ante cualquier problema; **no borres nada**.

## 11. Demostrar idempotencia (repite el paso 9, vuelve a usar el modelo)

Mismo comando del paso 9. Esperado: `codigo=0`, `filas_insertadas=0 (validadas=0 rechazadas=0)` y `omitidas_por_duplicado=` igual al total anterior. Después, `auditar $V` y `base` deben dar **exactamente los mismos conteos** que en el paso 10. **STOP** si sube algún conteo.

## 12. Resto de versiones

Solo si 9–11 salieron bien, repite 7–11 con `V=243` y luego `V=231` (uno por vez, auditando cada uno).

## 13. Si una corrida se interrumpe (Ctrl-C, Android mata Termux, batería)

- Se guarda una transacción por fragmento: los fragmentos terminados quedan completos; nunca queda uno a medias.
- Comprueba con `auditar $V` y **repite el mismo comando**: lo ya guardado se omite y se completa el resto (probado en sandbox).
- `database is locked`: espera y repite. Disco: `df -h ~`.
- **No restaures ni borres la base por tu cuenta.** Si `auditar` marca `CITA VALIDADA NO ESTA EN EL TEXTO DE LA VERSION`, casi seguro se cruzaron texto y `version_id`: detente y pégame la salida; la restauración desde `~/diamante_backups/` se hace en una sesión aparte, con el job del recolector detenido (confirma con `termux-job-scheduler --help` cómo cancelarlo en tu versión).

## 14. Métricas a recoger (salen al final de cada corrida, en los `.log`)

No se cambia ningún parámetro antes de tener estos datos. Con 3 noticias (≤ 15 fragmentos) se puede **detectar** un problema, no descartarlo.

| Decisión | Métrica (línea `Metricas:`) | Criterio propuesto (opinión, no hecho) |
|---|---|---|
| `MAX_TOKENS_LLM` 384 → 512 | `gen_tokens_por_fragmento`, `salida_recuperada`, `json_invalido` | Subir solo si hay salidas recuperadas o JSON cortado. Coste: a ~11,6 t/s (tg32 medido con 2 hilos) 128 tokens más son ≤ ~11 s por fragmento que llegue al tope. Supuesto a verificar: llama.cpp puede informar n−1, por eso mira el máximo observado. |
| `MAX_HECHOS_POR_FRAGMENTO` 5 → 3 | `hechos_por_fragmento`, `fragmentos_en_tope(5)`, `veredicto_por_posicion` | Bajar solo si los hechos #4–#5 se rechazan claramente más que #1–#3 o los fragmentos al tope coinciden con truncados. Si casi ningún fragmento llega a 3, no hay efecto. |
| Tope de largo de `cita_literal` | `cita_literal_aceptada_chars` (p50/p90/max) | Plantearlo solo si p90/max son muy altos y esos fragmentos son los de más tokens. Verificar antes que `--json-schema` de tu llama.cpp soporta `maxLength`. |
| Mantener valores | todas sin señales | no tocar |

Más datos: `motivos_rechazo` (¿domina `sujeto_generico`?), `segundos_por_fragmento`, temperatura/batería antes y después, y `auditar` (largo de cita validada).

## Pendientes y no ejecutar todavía

- Verificar todo lo de arriba en Termux/Python 3.14.10.
- Decidir el vínculo texto↔`version_id` (ver `Decisiones.md`, 2026-11-27).
- No ejecutar: `--guardar` fuera de este orden, `bcb_adapter.py`, nube, Telegram, informes, Opinión.
