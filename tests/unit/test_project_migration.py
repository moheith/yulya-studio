"""
Unit tests for Project Migration Tool (Section 6).
Verifies:
1. Read-only inventory produces correct file hashes and sizes without mutating source.
2. Dry-run mode produces reports without writing files.
3. Live migration copies files accurately, verifies SHA-256 hashes, and creates project_manifest.json.
4. Unsupported file extensions are flagged in warnings/errors.
5. Idempotent re-runs recognize up-to-date state without duplicate operations.
6. Rollback cleanly restores prior state.
"""

import pytest
import os
import shutil
from pathlib import Path
from backend.app.projects.migration import ProjectMigrator, compute_file_sha256
from backend.app.projects.manifest import MANIFEST_FILENAME, load_manifest


@pytest.fixture
def migration_fixture(tmp_path):
    """Sets up a temporary legacy source directory and destination directory."""
    src_base = tmp_path / "legacy_projects"
    dst_base = tmp_path / "v2_projects"

    # Create a legacy project: user 12345, slug "space-shooter"
    proj_dir = src_base / "12345" / "space-shooter"
    proj_dir.mkdir(parents=True, exist_ok=True)

    # Write files
    (proj_dir / "index.html").write_text("<!DOCTYPE html><html><body>Canvas</body></html>", encoding="utf-8")
    (proj_dir / "style.css").write_text("body { margin: 0; background: #000; }", encoding="utf-8")
    (proj_dir / "app.js").write_text("console.log('Space shooter loaded');", encoding="utf-8")
    (proj_dir / "unsupported.exe").write_text("binary-mock", encoding="utf-8")

    yield src_base, dst_base


def test_inventory_read_only(migration_fixture):
    src_base, dst_base = migration_fixture
    migrator = ProjectMigrator(source_base_dir=src_base, dest_base_dir=dst_base)

    reports = migrator.inventory_projects()
    assert len(reports) == 1
    rep = reports[0]

    assert rep.user_id == 12345
    assert rep.slug == "space-shooter"
    assert rep.status == "INVENTORIED"
    assert len(rep.files) == 4  # index.html, style.css, app.js, unsupported.exe

    # Ensure destination was not created in inventory mode
    assert not dst_base.exists()

    # Check sha256 computation
    js_item = next(f for f in rep.files if f.relative_path == "app.js")
    assert js_item.source_sha256 == compute_file_sha256(src_base / "12345" / "space-shooter" / "app.js")
    assert js_item.is_valid_extension is True

    # Check invalid extension detection
    exe_item = next(f for f in rep.files if f.relative_path == "unsupported.exe")
    assert exe_item.is_valid_extension is False
    assert len(rep.warnings) > 0


def test_dry_run_mode(migration_fixture):
    src_base, dst_base = migration_fixture
    migrator = ProjectMigrator(source_base_dir=src_base, dest_base_dir=dst_base)

    reports = migrator.run_migration(dry_run=True)
    assert len(reports) == 1
    assert reports[0].status == "DRY_RUN_PENDING"

    # Destination directory must not exist after dry run
    assert not dst_base.exists()


def test_live_migration_and_hash_verification(migration_fixture):
    src_base, dst_base = migration_fixture
    migrator = ProjectMigrator(source_base_dir=src_base, dest_base_dir=dst_base)

    # Execute live migration
    reports = migrator.run_migration(dry_run=False)
    assert len(reports) == 1
    rep = reports[0]
    assert rep.status == "MIGRATED"
    assert rep.manifest_created is True

    dest_proj = dst_base / "12345" / "space-shooter"
    assert dest_proj.exists()
    assert (dest_proj / "index.html").exists()
    assert (dest_proj / "style.css").exists()
    assert (dest_proj / "app.js").exists()
    assert not (dest_proj / "unsupported.exe").exists()  # filtered out by allowlist

    # Verify SHA-256 match
    for item in rep.files:
        if item.is_valid_extension:
            assert item.dest_sha256 == item.source_sha256

    # Verify project_manifest.json created
    manifest = load_manifest(dest_proj)
    assert manifest["slug"] == "space-shooter"
    assert manifest["title"] == "Space Shooter"


def test_migration_idempotency(migration_fixture):
    src_base, dst_base = migration_fixture
    migrator = ProjectMigrator(source_base_dir=src_base, dest_base_dir=dst_base)

    # 1. First live run
    reports_1 = migrator.run_migration(dry_run=False)
    assert reports_1[0].status == "MIGRATED"

    # 2. Dry run after migration should detect UP_TO_DATE
    reports_2 = migrator.run_migration(dry_run=True)
    assert reports_2[0].status == "UP_TO_DATE"


def test_migration_rollback(migration_fixture):
    src_base, dst_base = migration_fixture
    migrator = ProjectMigrator(source_base_dir=src_base, dest_base_dir=dst_base)

    # Run live migration
    reports = migrator.run_migration(dry_run=False)
    assert reports[0].status == "MIGRATED"
    dest_proj = dst_base / "12345" / "space-shooter"
    assert dest_proj.exists()

    # Trigger rollback
    rolled_back = migrator.rollback_project(12345, "space-shooter")
    assert rolled_back is True
    assert not dest_proj.exists()
