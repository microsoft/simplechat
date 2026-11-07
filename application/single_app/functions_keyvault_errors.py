# functions_keyvault_errors.py
"""Safe diagnostics for Key Vault operations without provider exception text."""


def key_vault_operation_error(operation, error):
    status_code = getattr(error, "status_code", None)
    if status_code == 403:
        return (
            f"key_vault_{operation}_forbidden",
            f"Key Vault denied {operation} access. Grant the app's selected managed identity "
            "Key Vault Secrets Officer on this vault, or equivalent secret permissions, "
            "and check the vault's network restrictions.",
        )
    if status_code == 401:
        return (
            "key_vault_authentication_failed",
            "Key Vault authentication failed. Check the selected managed identity and vault configuration.",
        )
    return (
        f"key_vault_{operation}_failed",
        f"Key Vault {operation} failed. Check the selected identity, vault permissions, "
        "network connectivity, and server diagnostics.",
    )


class KeyVaultSecretStorageError(RuntimeError):
    """A secret was not confirmed stored; callers may expose only public_message."""

    def __init__(self, error):
        self.code, self.public_message = key_vault_operation_error("write", error)
        super().__init__(self.public_message)
