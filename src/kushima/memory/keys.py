"""Schlüsselverwaltung. Der Schlüssel liegt nie im Vault und nie auf dem NAS."""
from __future__ import annotations

import os
import secrets

import keyring

SERVICE = "kushima-vault"
LEGACY_SERVICE = "kushim-vault"          # Name vor der Umbenennung; bestehende Vaults behalten ihren Schlüssel


def get_or_create_key(vault_id: str, create: bool = False) -> str:
    """Liefert den Vault-Schlüssel (hex). Reihenfolge: Env-Variable, Credential Manager (neu, dann alt).

    Ein unter dem alten Namen gespeicherter Schlüssel wird unter dem neuen Namen zusätzlich abgelegt;
    der alte Eintrag bleibt als Rückfall bestehen und wird nie gelöscht.
    """
    env = os.environ.get("KUSHIMA_VAULT_KEY") or os.environ.get("KUSHIM_VAULT_KEY")
    if env:
        return env
    key = keyring.get_password(SERVICE, vault_id)
    if key:
        return key
    legacy = keyring.get_password(LEGACY_SERVICE, vault_id)
    if legacy:
        keyring.set_password(SERVICE, vault_id, legacy)
        return legacy
    if not create:
        raise KeyError(
            f"Kein Schlüssel für Vault {vault_id}. Mit `kushima key export` auf dem alten "
            "Rechner sichern und mit `kushima key import` importieren."
        )
    key = secrets.token_hex(32)
    keyring.set_password(SERVICE, vault_id, key)
    return key


def store_key(vault_id: str, key: str) -> None:
    keyring.set_password(SERVICE, vault_id, key)
