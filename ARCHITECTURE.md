# Arquitectura del Proyecto Diamante v2.0

## 1. Filosofía Principal
El proyecto es **Data-Centric**, no AI-Centric. La inteligencia del sistema reside en la estructura de los datos, la trazabilidad y el código determinista (Python). El LLM local (Qwen 1.5B) es un "extractor especializado" (texto a JSON), y el LLM en la nube (DeepSeek/Gemini) es un "editor final". Ninguno tiene autoridad sobre la base de datos.

## 2. Stack Tecnológico (Fase 0 Validada)
*   **Hardware:** Realme 8 Pro (Snapdragon 720G, 8GB RAM, sin root).
*   **Entorno:** Termux (instalado oficialmente desde **F-Droid**, no GitHub, para asegurar firmas y actualizaciones). Uso de `termux-api` y `termux-job-scheduler`.
*   **Lenguaje:** Python 3.14.10.
*   **Base de Datos:** SQLite (modo WAL, `synchronous=NORMAL`). Archivo: `diamante.db`.
*   **Librerías Locales:** `trafilatura` (limpieza HTML), `rapidfuzz` (deduplicación), `regex`/diccionarios (NER, en lugar de spaCy).
*   **Programación de Tareas:** `termux-job-scheduler`. **Nota crítica:** Android impone un mínimo de 15 minutos (900,000 ms) para tareas periódicas en segundo plano. No se pueden programar ticks de 1 minuto.
*   **LLM Local:** Qwen 1.5B Q4 (GGUF) vía `llama.cpp` (Uso exclusivo: extracción estructurada a JSON).
*   **LLM Nube:** Cliente HTTP propio (sin LiteLLM) hacia DeepSeek/Gemini con contabilidad de tokens.

## 3. El Pipeline (Flujo de Datos)
1.  **Ingesta (Recolector):** Descarga RSS/HTML/PDFs. Extrae texto limpio con `trafilatura`. Guarda originales y hashes.
2.  **Deduplicación:** `rapidfuzz` compara títulos y cuerpos para evitar procesar la misma noticia múltiples veces. Conserva el registro de procedencia (quién publicó primero).
3.  **Extracción Determinista:** Python puro (`regex`) extrae fechas, números de decretos e instituciones bolivianas (Aduana, BCB, INE) usando un diccionario propio (gazetteer).
4.  **Extracción Semántica:** Qwen 1.5B recibe fragmentos cortos y devuelve JSON estricto con hechos (sujeto, verbo, objeto, cita literal).
5.  **Validación (El Guardián):** Python verifica que la cita literal exista en el texto. Si el LLM alucinó una cifra o fecha, se descarta.
6.  **Almacenamiento:** Todo va a SQLite. Máquina de estados para las tareas (`pendiente`, `running`, `completed`, `failed`).
7.  **Generación de Informe:** Un script empaqueta los hechos JSON validados y los envía a la nube. El prompt exige que cada párrafo cite un ID de hecho (`[F123]`).
8.  **Distribución:** El informe final (Markdown) se envía por Telegram como archivo `.md` (evitando el límite de 4096 caracteres).

## 4. Reglas de Seguridad Críticas
*   **Aislamiento del LLM:** Qwen no tiene acceso a internet, ni a la base de datos, ni a claves API. Solo recibe texto y devuelve JSON.
*   **Anti-Prompt Injection:** Las noticias se tratan como "datos no confiables". Nunca se ejecutan instrucciones que vengan dentro del texto de una noticia.
*   **Validación Estricta:** El JSON del LLM se valida con Pydantic. Python inyecta los metadatos (URL, fuente, fecha de captura), el LLM no puede inventarlos.