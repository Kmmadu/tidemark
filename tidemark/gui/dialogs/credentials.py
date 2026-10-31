"""Credentials dialog: backend in use, set-backend, change passphrase."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from tidemark.store.credentials import (
    CredentialStoreFactory,
    EncryptedFileStore,
    StaticPassphraseProvider,
    WrongPassphrase,
    probe_keyring,
)
from tidemark.store.db import Database
from tidemark.store.paths import Paths


class CredentialsDialog(QDialog):
    def __init__(self, db: Database, paths: Paths, parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._paths = paths
        self.setWindowTitle("Credentials")
        self.resize(520, 260)

        factory = CredentialStoreFactory(paths.config_dir, db)
        self._backend = QComboBox()
        self._backend.addItems(["keyring", "file"])
        self._backend.setCurrentText(factory.get_configured_backend()
                                     if factory.get_configured_backend() != "unset"
                                     else "keyring")

        keyring_usable, reason = probe_keyring()
        self._status = QLabel(
            f"keyring usable now: {'yes' if keyring_usable else 'no'} ({reason})")
        self._status.setObjectName("muted")

        self._save = QPushButton("Save backend")
        self._save.clicked.connect(self._on_save_backend)
        self._change_pw = QPushButton("Change file passphrase…")
        self._change_pw.clicked.connect(self._on_change_passphrase)

        form = QFormLayout()
        form.addRow("Backend:", self._backend)
        form.addRow(self._status)
        form.addRow(self._save)
        form.addRow(self._change_pw)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_save_backend(self) -> None:
        factory = CredentialStoreFactory(self._paths.config_dir, self._db)
        factory.set_backend(self._backend.currentText())
        QMessageBox.information(self, "Saved", "Backend preference saved.")

    def _on_change_passphrase(self) -> None:
        import getpass
        file_path = self._paths.config_dir / "credentials.enc"
        if not file_path.exists():
            QMessageBox.warning(self, "No file store",
                                "No file store exists to change.")
            return
        old = getpass.getpass("Current passphrase: ")
        new1 = getpass.getpass("New passphrase: ")
        new2 = getpass.getpass("Confirm new passphrase: ")
        if new1 != new2:
            QMessageBox.warning(self, "Mismatch", "Passphrases do not match.")
            return
        store = EncryptedFileStore(file_path, StaticPassphraseProvider(old))
        try:
            store.rekey(StaticPassphraseProvider(old), StaticPassphraseProvider(new1))
        except WrongPassphrase:
            QMessageBox.warning(self, "Wrong passphrase", "Current passphrase is incorrect.")
            return
        QMessageBox.information(self, "Done", "Passphrase changed.")
