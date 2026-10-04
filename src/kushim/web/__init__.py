"""Web-Recherche (Logik ohne Netzwerk): Prüfer, Bereinigung, Wikipedia-Anbieter, Ablauf mit Vorschau und Freigabe.

Der eigentliche Abruf wird von außen als Funktion hineingereicht (`fetch`). Das Netz-Modul dafür (net/web.py) gibt es erst
nach ausdrücklicher Freigabe des Nutzers (siehe docs/tools-plan.md). Bis dahin ist `web.search` "nicht verfügbar".
"""
