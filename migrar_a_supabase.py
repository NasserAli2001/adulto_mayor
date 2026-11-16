"""Copia los datos del archivo local acompana.db a la base de datos de Supabase.

Uso (con DATABASE_URL puesta en el .env):   python migrar_a_supabase.py
Se puede repetir sin duplicar datos. Si la nube ya tiene OTROS datos, se detiene sin tocar nada.
"""
import os
import sqlite3
import sys

import db

if not db.USAR_PG:
    sys.exit("Falta DATABASE_URL en el archivo .env: sin ella no hay base de datos en la nube a la que copiar.")
if not os.path.exists(db.DB_FILE):
    sys.exit(f"No se encontró el archivo local {db.DB_FILE}. Ejecute este script en la carpeta del proyecto.")

origen = sqlite3.connect(db.DB_FILE)
origen.row_factory = sqlite3.Row
locales = {(r["id"], r["email"]) for r in origen.execute("SELECT id, email FROM usuarios")}

db.crear_esquema()  # solo las tablas: las cuentas iniciales NO se crean antes de copiar
en_la_nube = {(r["id"], r["email"]) for r in db._consultar("SELECT id, email FROM usuarios")}
if not en_la_nube <= locales:
    sys.exit("La base de datos en la nube ya tiene cuentas que no están en su archivo local. Por seguridad "
             "no se copió nada. Use una base de Supabase vacía para migrar.")

for tabla in db.TABLAS:
    try:
        filas = [dict(r) for r in origen.execute(f"SELECT * FROM {tabla}")]
    except sqlite3.OperationalError:
        continue  # esa tabla no existía en la base local
    destino = db._columnas(tabla)
    for f in filas:
        if tabla == "usuarios" and f.get("foto") and os.path.exists(f["foto"]):
            f["foto"] = db._foto_base64(f["foto"])[0] or ""  # las fotos guardadas como archivo pasan a la base
        cols = [c for c in f if c in destino]
        sql = (f"INSERT INTO {tabla}({', '.join(cols)}) VALUES({', '.join('?' for _ in cols)}) "
               "ON CONFLICT DO NOTHING")
        db._ejecutar(sql, [f[c] for c in cols])
    if tabla != "vinculos" and filas:  # que los números automáticos sigan después del último id copiado
        db._ejecutar(f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), (SELECT MAX(id) FROM {tabla}))")
    print(f"{tabla}: {len(filas)} filas copiadas")
db.init_db()  # si faltara alguna cuenta de administración, se crea ahora
print("Listo. Los datos locales ya están en Supabase.")
