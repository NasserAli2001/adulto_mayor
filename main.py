import os

import flet as ft

import db
from ui import App

_bd_lista = False  # la base de datos se prepara una sola vez, aunque entren varias personas


def main(page: ft.Page):
    global _bd_lista
    if not _bd_lista:
        try:
            db.init_db()
            _bd_lista = True
        except Exception as ex:
            page.bgcolor = "#F4F6FA"
            page.add(ft.Text("No se pudo iniciar Acompaña+", size=26, weight=ft.FontWeight.BOLD, color="#B71C1C"),
                     ft.Text(str(ex), size=18, color="#1A1A1A", selectable=True))
            return
    App(page)


if os.environ.get("MODO_WEB") == "1":
    # Para compartirla por la web: la app corre en el servidor y las personas la abren con el navegador
    ft.run(main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0", port=int(os.environ.get("PORT", "8550")))
else:
    ft.run(main)