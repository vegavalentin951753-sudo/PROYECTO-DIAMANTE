"""Utilidades compartidas de Diamante: conexión a SQLite y hora en UTC.

Todos los módulos deben abrir la base con conectar(), porque varios PRAGMA
(foreign_keys, busy_timeout) valen solo para la conexión que los activa.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent   # la carpeta donde están los scripts
DB_PATH = BASE_DIR / "diamante.db"           # la base vive junto al código, sin importar el cwd


def ahora_utc():
    """Hora actual en UTC, formato ISO 8601 con 'Z' (ej. 2026-11-24T14:05:00Z)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conectar():
    conn = sqlite3.connect(DB_PATH, timeout=30)   # espera hasta 30 s si la base está ocupada
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")       # persistente en el archivo
    conn.execute("PRAGMA synchronous=NORMAL")     # por conexión
    conn.execute("PRAGMA foreign_keys=ON")        # por conexión
    return conn
