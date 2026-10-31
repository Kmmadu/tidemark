"""Restore wizard gating: Finish enabled only for matching token; ack required."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from tidemark.core import engine as engine_mod
from tidemark.core.credentials import Credentials
from tidemark.core.driver import FetchResult
from tidemark.core.models import Device
from tidemark.core.profiles import ProfileRegistry
from tidemark.gui.wizard.restore_wizard import RestoreWizard
from tidemark.store.db import Database, migrate
from tidemark.store.git_repo import ConfigRepo
from tidemark.store.paths import Paths
from tidemark.store.repositories import DeviceRepo
from tidemark.store.service import backup_and_persist


def _seeded(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    migrate(db)
    repo = ConfigRepo(tmp_path / "configs")
    device = DeviceRepo(db).add(Device(
        name="core", host="10.0.0.1", port=22,
        profile_id="cisco_ios", credential_ref="default",
    ))
    profile = ProfileRegistry().get("cisco_ios")
    for text in ("hostname r1\n",
                 "hostname r1\ninterface Gi0/1\n ip address 10.0.0.1 255.255.255.0\n"):
        with patch.object(engine_mod.Driver, "fetch",
                          return_value=FetchResult(text=text)):
            backup_and_persist(device, profile, Credentials("u", "p"),
                               db, repo, retries=0)
    paths = Paths(config_dir=tmp_path, data_dir=tmp_path, state_dir=tmp_path)
    paths.ensure_dirs()
    return db, paths, device


def test_confirm_page_requires_exact_token(tmp_path: Path, qapp) -> None:
    """The confirm page accepts only the exact token set on it.

    This is a widget-level test: it does not depend on QWizard's page
    navigation. The wizard's own navigation is exercised in the manual
    acceptance test and in ``test_demo_smoke.py``.
    """
    db, paths, device = _seeded(tmp_path)
    wizard = RestoreWizard(db, paths, device)

    # Force the wizard to compute the plan by simulating what
    # ``_on_page_changed`` does when entering the plan page, without
    # depending on QWizard.next() internals.
    wizard._rebuild_plan_and_token()  # noqa: SLF001 - test introspection
    plan = wizard._holder.get("plan")  # noqa: SLF001
    assert plan is not None, "plan should be computed from seeded snapshots"

    wizard._plan_page.rebuild()  # noqa: SLF001 - ensure checkboxes exist
    for cb in wizard._plan_page._ack.values():  # noqa: SLF001
        cb.setChecked(True)

    # Confirm page gating.
    wizard._confirm_page._typed.setText("wrong")  # noqa: SLF001
    assert not wizard._confirm_page.isComplete()  # noqa: SLF001
    wizard._confirm_page._typed.setText(plan.confirm_token)  # noqa: SLF001
    assert wizard._confirm_page.isComplete()  # noqa: SLF001
