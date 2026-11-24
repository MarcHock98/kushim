"""Werkstatt (Stufe 2): Claude Code erweitert kushim in einem sichtbaren Fenster, nur nach Freigabe.

Dieses Paket liegt selbst unter einem geschützten Pfad (`schutz.GESCHUETZTE_ORDNER`): ein Werkstatt-Zweig darf es nie ändern.
"""
from .schutz import Datei, Ergebnis, Grund, pruefe, pruefe_commits

__all__ = ["Datei", "Ergebnis", "Grund", "pruefe", "pruefe_commits"]
