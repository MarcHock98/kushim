"""Claude über die Claude CLI des angemeldeten Nutzers (Modus C). Plan: docs/claude-cli-plan.md.

kushim speichert keine Zugangsdaten und braucht keinen API-Schlüssel: Es nutzt die Anmeldung des Nutzers in der CLI.
Alles, was hier nach außen geht, läuft über Vorschau und Freigabe; Claudes Text ist `Untrusted` und löst nie eine Aktion aus.
"""
