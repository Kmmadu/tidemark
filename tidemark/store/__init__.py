"""Tidemark store — SQLite, git-backed configs, XDG paths, importer, credentials."""

from tidemark.store.credentials import (
    CredentialNotFound,
    CredentialStore,
    CredentialStoreError,
    CredentialStoreFactory,
    CredentialStoreUnavailable,
    EncryptedFileStore,
    FilePassphraseProvider,
    InteractivePassphraseProvider,
    KeyringStore,
    PassphraseProvider,
    StaticPassphraseProvider,
    WrongPassphrase,
    passphrase_provider_from_env,
    probe_keyring,
)
from tidemark.store.db import Database, migrate
from tidemark.store.git_repo import (
    ConfigRepo,
    ConfigRepoError,
    ConfigRepoLockError,
)
from tidemark.store.git_repo import (
    InvalidDeviceNameError as ConfigRepoInvalidDeviceNameError,
)
from tidemark.store.importer import import_legacy_yaml
from tidemark.store.paths import Paths, default_paths
from tidemark.store.repositories import (
    DeviceRepo,
    InvalidDeviceNameError,
    RunRepo,
    SettingsRepo,
    SnapshotRepo,
)
from tidemark.store.restore_attempts import (
    AttemptOutcome,
    RestoreAttempt,
    RestoreAttemptsRepo,
)
from tidemark.store.service import backup_and_persist

__all__ = [
    "AttemptOutcome",
    "ConfigRepo",
    "ConfigRepoError",
    "ConfigRepoInvalidDeviceNameError",
    "ConfigRepoLockError",
    "CredentialNotFound",
    "CredentialStore",
    "CredentialStoreError",
    "CredentialStoreFactory",
    "CredentialStoreUnavailable",
    "Database",
    "DeviceRepo",
    "EncryptedFileStore",
    "FilePassphraseProvider",
    "InteractivePassphraseProvider",
    "InvalidDeviceNameError",
    "KeyringStore",
    "PassphraseProvider",
    "Paths",
    "RestoreAttempt",
    "RestoreAttemptsRepo",
    "RunRepo",
    "SettingsRepo",
    "SnapshotRepo",
    "StaticPassphraseProvider",
    "WrongPassphrase",
    "backup_and_persist",
    "default_paths",
    "import_legacy_yaml",
    "migrate",
    "passphrase_provider_from_env",
    "probe_keyring",
]
