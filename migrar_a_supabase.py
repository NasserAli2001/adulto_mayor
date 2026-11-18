"""Herramientas para la base de datos en la nube (Supabase).

  python migrar_a_supabase.py                    copia los datos de su archivo local acompana.db a Supabase
  python migrar_a_supabase.py --borrar-respaldo  borra las copias *_v1 que deja la conversión a 30 tablas

Necesita la línea DATABASE_URL en el archivo .env. Se puede repetir sin duplicar datos. Si la base de la nube
ya tiene OTROS datos, se detiene sin tocar nada.
"""
import os
import sqlite3
import subprocess
import sys

import db

AQUI = os.path.dirname(os.path.abspath(__file__))

if "--borrar-respaldo" in sys.argv:
    borradas = db.borrar_respaldo_v1()
    sys.exit("Copias borradas: " + ", ".join(borradas) if borradas else "No hay copias de seguridad que borrar.")

if not db.USAR_PG:
    sys.exit("Falta DATABASE_URL en el archivo .env: sin ella no hay base de datos en la nube a la que copiar.")
if not os.path.exists(db.DB_FILE):
    sys.exit(f"No se encontró el archivo local {db.DB_FILE}. Ejecute este script en la carpeta del proyecto.")

origen = sqlite3.connect(db.DB_FILE)
origen.row_factory = sqlite3.Row
columnas_locales = {r[1] for r in origen.execute("PRAGMA table_info(usuarios)")}
if "nombre" in columnas_locales:  # su archivo local todavía tiene las 5 tablas: se convierte primero (en local)
    origen.close()
    print("Convirtiendo primero su archivo local a la estructura de 30 tablas...")
    sin_nube = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    r = subprocess.run([sys.executable, "-c", "import db; db.crear_esquema()"], cwd=AQUI, env=sin_nube)
    if r.returncode:
        sys.exit("No se pudo convertir el archivo local. No se copió nada.")
    origen = sqlite3.connect(db.DB_FILE)
    origen.row_factory = sqlite3.Row


def filas_locales(tabla):
    try:
        return [dict(r) for r in origen.execute(f"SELECT * FROM {tabla}")]
    except sqlite3.OperationalError:
        return []


db.crear_esquema(sembrar=False)  # solo las tablas: nada se crea antes de copiar
copias, columnas = {}, {}
for tabla in db.TABLAS:
    if tabla == "meta":
        continue
    locales = filas_locales(tabla)
    destino = db._columnas(tabla)
    cols = sorted(set(locales[0]) & destino) if locales else sorted(destino)
    en_nube = {tuple(f[c] for c in cols) for f in db._consultar(f"SELECT {', '.join(cols)} FROM {tabla}")}
    if not en_nube <= {tuple(f[c] for c in cols) for f in locales}:
        sys.exit(f"La base de datos en la nube ya tiene datos en «{tabla}» que no están en su archivo local. "
                 "Por seguridad no se copió nada. Use una base de Supabase vacía para migrar.")
    copias[tabla], columnas[tabla] = locales, cols

for tabla, locales in copias.items():
    cols = columnas[tabla]
    for f in locales:
        sql = f"INSERT INTO {tabla}({', '.join(cols)}) VALUES({', '.join('?' for _ in cols)}) ON CONFLICT DO NOTHING"
        db._ejecutar(sql, [f[c] for c in cols])
    if locales:
        print(f"{tabla}: {len(locales)} filas copiadas")
with db._transaccion() as tx:
    db._reajustar_secuencias(tx)  # que los números automáticos sigan después del último id copiado
db.sembrar_catalogos()
db.init_db()  # si faltara alguna cuenta de administración, se crea ahora
print("Listo. Los datos locales ya están en Supabase.")