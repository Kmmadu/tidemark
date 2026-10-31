"""
QWizard for planning and applying a restore.

Pages:
  1. Select snapshot
  2. Plan & risk flags (checkbox per high flag)
  3. Options (allow_removals)
  4. Confirm (typed token)
  5. Progress
  6. Result

The wizard never applies without a matching token and acknowledgements, and
never saves startup-config without verifying the post-state first
(``apply_restore`` enforces this).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from tidemark.core.credentials import read_credentials
from tidemark.core.models import Device
from tidemark.core.profiles import ProfileRegistry
from tidemark.core.restore import (
    RestoreConfirmationError,
    RestoreError,
    RestoreModeError,
    RestorePlanStaleError,
    SnapshotIntegrityError,
    apply_restore,
    plan_restore,
)
from tidemark.core.restore_risk_ios import Severity
from tidemark.store.db import Database
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.paths import Paths
from tidemark.store.repositories import SnapshotRepo
from tidemark.store.restore_attempts import RestoreAttemptsRepo

# ── Page: select snapshot ──────────────────────────────────────────────────

class _SnapshotPage(QWizardPage):
    def __init__(self, db: Database, device: Device) -> None:
        super().__init__()
        self._db = db
        self._device = device
        self.setTitle("Select snapshot")
        self.setSubTitle(f"Choose a saved snapshot for {device.name}.")

        self._combo = QComboBox()
        for s in SnapshotRepo(db).list_for_device(device.id or 0, limit=200):
            if s.kind != "normal":
                continue
            self._combo.addItem(
                f"#{s.id} · {s.taken_at_utc.isoformat().replace('T', ' ')[:19]} "
                f"· {s.sha256[:8]}", s.id)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Snapshot:"))
        layout.addWidget(self._combo)

        ua = RestoreAttemptsRepo(db).last_unverified_for_device(device.id or 0)
        if ua is not None:
            warn = QLabel(
                f"Note: a previous restore on this device ended "
                f"{ua.outcome.value} at {ua.started_at_utc.isoformat()}. "
                f"You may want to inspect the device before restoring again.")
            warn.setStyleSheet("color: #b9770e;")
            warn.setWordWrap(True)
            layout.addWidget(warn)

    def selected_snapshot_id(self) -> int | None:
        return self._combo.currentData()


# ── Page: plan & risk flags ────────────────────────────────────────────────

class _PlanPage(QWizardPage):
    def __init__(self, db: Database, paths: Paths, device: Device,
                 plan_holder: dict) -> None:
        super().__init__()
        self._db = db
        self._paths = paths
        self._device = device
        self._holder = plan_holder
        self._ack: dict[str, QCheckBox] = {}
        self.setTitle("Plan & risk flags")
        self.setSubTitle("Review the plan. Tick every high-risk flag to continue.")

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setMinimumHeight(160)

        self._checks_container = QVBoxLayout()
        layout = QVBoxLayout(self)
        layout.addWidget(self._details)
        layout.addLayout(self._checks_container)

    def rebuild(self) -> None:
        while self._checks_container.count():
            item = self._checks_container.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._ack.clear()

        if "plan" in self._holder:
            plan = self._holder["plan"]
            self._details.setPlainText(_render_plan(plan))
            for flag in plan.risk_flags:
                if flag.severity is Severity.HIGH:
                    cb = QCheckBox(f"{flag.code}: {flag.message}")
                    cb.stateChanged.connect(lambda _state: self.completeChanged.emit())
                    self._checks_container.addWidget(cb)
                    self._ack[flag.code] = cb
        else:
            self._details.setPlainText(self._holder.get("error", ""))
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802 - Qt override
        if "plan" not in self._holder:
            return False
        return all(cb.isChecked() for cb in self._ack.values())

    def acknowledged(self) -> list[str]:
        return [code for code, cb in self._ack.items() if cb.isChecked()]


# ── Page: options ──────────────────────────────────────────────────────────

class _OptionsPage(QWizardPage):
    def __init__(self, holder: dict) -> None:
        super().__init__()
        self._holder = holder
        self.setTitle("Options")
        self.setSubTitle("Review restore behaviour.")

        self._allow_removals = QCheckBox(
            "Allow removals (lines in the current config not in the target "
            "will be removed with `no <line>`).")
        self._allow_removals.stateChanged.connect(self._on_change)

        note = QLabel(
            "Reload-in-N safety timer is deferred to a later milestone. "
            "Nothing is saved until the post-restore state has been verified.")
        note.setObjectName("muted")
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self._allow_removals)
        layout.addWidget(note)

    def _on_change(self) -> None:
        self._holder["allow_removals"] = self._allow_removals.isChecked()
        self.completeChanged.emit()


# ── Page: confirm ──────────────────────────────────────────────────────────

class _ConfirmPage(QWizardPage):
    def __init__(self, holder: dict) -> None:
        super().__init__()
        self._holder = holder
        self.setTitle("Confirm")
        self.setSubTitle("Type the exact token to enable Finish.")

        self._expected_label = QLabel("")
        self._expected_label.setStyleSheet(
            "font-family: monospace; font-weight: 600;")
        self._expected_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)

        self._typed = QLineEdit()
        self._typed.textChanged.connect(lambda _text: self.completeChanged.emit())

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Type this token exactly (case-sensitive):"))
        layout.addWidget(self._expected_label)
        layout.addWidget(self._typed)

    def set_token(self, token: str) -> None:
        self._holder["token"] = token
        self._expected_label.setText(token)
        self.completeChanged.emit()

    def isComplete(self) -> bool:  # noqa: N802 - Qt override
        return self._typed.text() == self._holder.get("token", "\0")


# ── Helpers ────────────────────────────────────────────────────────────────

def _render_plan(plan) -> str:  # noqa: ANN001 - RestorePlan without import cycle
    lines = [
        f"device      : {plan.device.name}",
        f"target      : snapshot #{plan.target_snapshot.id} "
        f"({plan.target_snapshot.taken_at_utc.isoformat()})",
        f"target sha  : {plan.target_sha256[:12]}…",
        f"current sha : {plan.current_sha256[:12]}…",
        f"plan hash   : {plan.plan_hash[:16]}…",
        f"status      : {plan.status}",
    ]
    if plan.status == "no_changes":
        lines.append("No changes are needed; Finish will close the wizard.")
    if plan.lines_skipped:
        lines.append(f"skipped non-replayable lines: {len(plan.lines_skipped)}")
    if plan.needs_manual_review:
        lines.append(f"lines needing manual review: {len(plan.needs_manual_review)}")
    return "\n".join(lines)


# ── Wizard ─────────────────────────────────────────────────────────────────

class RestoreWizard(QWizard):
    def __init__(self, db: Database, paths: Paths, device: Device,
                 parent=None) -> None:
        super().__init__(parent)
        self._db = db
        self._paths = paths
        self._device = device
        self._holder: dict = {}

        self.setWindowTitle(f"Restore — {device.name}")
        self.resize(760, 560)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)

        self._snapshot_page = _SnapshotPage(db, device)
        self._plan_page = _PlanPage(db, paths, device, self._holder)
        self._options_page = _OptionsPage(self._holder)
        self._confirm_page = _ConfirmPage(self._holder)

        self._progress_page = QWizardPage()
        self._progress_page.setTitle("Progress")
        self._progress_label = QLabel("Preparing…")
        QVBoxLayout(self._progress_page).addWidget(self._progress_label)

        self._result_page = QWizardPage()
        self._result_page.setTitle("Result")
        self._result_label = QLabel("")
        self._result_label.setWordWrap(True)
        QVBoxLayout(self._result_page).addWidget(self._result_label)

        self.addPage(self._snapshot_page)
        self.addPage(self._plan_page)
        self.addPage(self._options_page)
        self.addPage(self._confirm_page)
        self.addPage(self._progress_page)
        self.addPage(self._result_page)

        self.currentIdChanged.connect(self._on_page_changed)

    def _on_page_changed(self, page_id: int) -> None:
        current = self.page(page_id)
        if current is self._plan_page:
            self._rebuild_plan_and_token()
            self._plan_page.rebuild()
        elif current is self._options_page:
            self._rebuild_plan_and_token()
        elif current is self._confirm_page:
            self._rebuild_plan_and_token()
        elif current is self._progress_page:
            self._run_restore()

    def _rebuild_plan_and_token(self) -> None:
        snap_id = self._snapshot_page.selected_snapshot_id()
        if snap_id is None:
            self._holder.clear()
            self._holder["error"] = "No snapshot selected"
            return
        profiles = ProfileRegistry(
            user_profiles_dir=self._paths.user_profiles_dir)
        profile = profiles.get(self._device.profile_id)
        allow_removals = bool(self._holder.get("allow_removals", False))
        config_repo = ConfigRepo(self._paths.configs_git_dir)
        try:
            plan = plan_restore(
                self._device, profile, snap_id, self._db, config_repo,
                allow_removals=allow_removals,
            )
        except (RestoreModeError, RestoreError, RestoreConfirmationError,
                SnapshotIntegrityError) as exc:
            self._holder.clear()
            self._holder["error"] = str(exc)
            return
        self._holder["plan"] = plan
        self._holder["token"] = plan.confirm_token
        self._confirm_page.set_token(plan.confirm_token)

    def _run_restore(self) -> None:
        plan = self._holder.get("plan")
        if plan is None:
            self._result_label.setText("No plan to apply.")
            return
        if plan.status == "no_changes":
            self._result_label.setText(
                "No changes needed. Nothing was sent to the device.")
            return

        if getattr(plan.device, "custom_command", None) == "DEMO":
            self._result_label.setText(
                "Demo mode: the restore plan was computed but no SSH was sent.")
            return

        typed_token = self._confirm_page._typed.text()
        acknowledged = self._plan_page.acknowledged()
        credentials = read_credentials(prompt_device=self._device.name)
        config_repo = ConfigRepo(self._paths.configs_git_dir)

        def on_progress(msg: str) -> None:
            self._progress_label.setText(msg)

        try:
            outcome = apply_restore(
                plan, typed_token, acknowledged, credentials,
                self._db, config_repo, on_progress=on_progress,
            )
        except (RestoreConfirmationError, RestorePlanStaleError) as exc:
            self._result_label.setText(f"Refused: {exc}")
            return
        except RestoreError as exc:
            self._result_label.setText(
                f"Restore ended {exc}. If the device is unreachable, "
                f"reload it to roll back to the pre-restore startup-config.")
            return
        self._result_label.setText(f"Restore finished: {outcome.value}")
