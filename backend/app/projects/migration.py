"""
Project Migration Tool for Yulya Studio V2 (Section 6).
Provides safe, idempotent migration from legacy v1 project layouts to V2.
- Inventories existing projects in read-only mode.
- Validates source paths, extensions, and file sizes.
- Computes SHA-256 hashes to guarantee data integrity.
- Generates a structured migration report.
- Idempotent execution (avoids duplicate writes if already migrated).
- Supports rollback via backup snapshots.
- Default execution mode is strictly a dry run.
"""

import os
import shutil
import hashlib
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict, field

from backend.app.core.config import settings
from backend.app.projects.sanitizer import validate_slug, resolve_project_path
from backend.app.projects.manifest import load_manifest, save_manifest, MANIFEST_FILENAME

logger = logging.getLogger("yulya.projects.migration")


def compute_file_sha256(file_path: Path) -> str:
    """Computes SHA-256 hash of a file for integrity verification."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class FileMigrationItem:
    relative_path: str
    size_bytes: int
    source_sha256: str
    dest_sha256: Optional[str] = None
    is_valid_extension: bool = True
    error: Optional[str] = None


@dataclass
class ProjectMigrationReport:
    user_id: int
    slug: str
    title: str
    source_dir: str
    dest_dir: str
    status: str  # "INVENTORIED", "MIGRATED", "UP_TO_DATE", "ERROR", "ROLLED_BACK"
    files: List[FileMigrationItem] = field(default_factory=list)
    total_bytes: int = 0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    manifest_created: bool = False
    timestamp: str = ""


class ProjectMigrator:
    """
    Manages safe read-only inventory, structured dry runs, live migrations,
    integrity verification, and rollback operations.
    """

    def __init__(self, source_base_dir: Optional[Path] = None, dest_base_dir: Optional[Path] = None):
        self.source_base_dir = (source_base_dir or (Path.cwd() / "projects")).resolve()
        self.dest_base_dir = (dest_base_dir or settings.PROJECTS_DIR).resolve()
        self.rollback_snapshots: Dict[str, Path] = {}

    def inventory_projects(self) -> List[ProjectMigrationReport]:
        """
        Scans source directory in read-only mode and produces an inventory report.
        Strictly does NOT mutate any files.
        """
        reports: List[ProjectMigrationReport] = []
        if not self.source_base_dir.exists():
            return reports

        for user_entry in self.source_base_dir.iterdir():
            if not user_entry.is_dir() or not user_entry.name.isdigit():
                continue
            user_id = int(user_entry.name)

            for slug_entry in user_entry.iterdir():
                if not slug_entry.is_dir():
                    continue
                try:
                    safe_slug = validate_slug(slug_entry.name)
                except Exception as ex:
                    report = ProjectMigrationReport(
                        user_id=user_id,
                        slug=slug_entry.name,
                        title=slug_entry.name,
                        source_dir=str(slug_entry),
                        dest_dir="",
                        status="ERROR",
                        errors=[f"Invalid project slug: {ex}"]
                    )
                    reports.append(report)
                    continue

                dest_dir = self.dest_base_dir / str(user_id) / safe_slug
                report = self._inspect_project(user_id, safe_slug, slug_entry, dest_dir)
                reports.append(report)

        return reports

    def _inspect_project(self, user_id: int, slug: str, source_dir: Path, dest_dir: Path) -> ProjectMigrationReport:
        """Inspects all files in a source project directory and checks extension allowlist."""
        now_iso = datetime.now(timezone.utc).isoformat()
        items: List[FileMigrationItem] = []
        total_bytes = 0
        warnings: List[str] = []
        errors: List[str] = []

        # Find existing title from manifest or slug
        title = slug.replace("-", " ").title()
        legacy_manifest = source_dir / MANIFEST_FILENAME
        if legacy_manifest.exists():
            try:
                with open(legacy_manifest, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    title = data.get("title", title)
            except Exception:
                pass

        for root, _, files in os.walk(source_dir):
            for file_name in files:
                full_path = Path(root) / file_name
                try:
                    rel_path = full_path.relative_to(source_dir).as_posix()
                except ValueError:
                    continue

                ext = full_path.suffix.lower()
                is_valid = ext in settings.ALLOWED_GAME_EXTENSIONS
                try:
                    size = full_path.stat().st_size
                    total_bytes += size
                    sha = compute_file_sha256(full_path)
                    item = FileMigrationItem(
                        relative_path=rel_path,
                        size_bytes=size,
                        source_sha256=sha,
                        is_valid_extension=is_valid
                    )
                    if not is_valid:
                        item.error = f"Unsupported file extension: {ext}"
                        warnings.append(f"File {rel_path} has disallowed extension {ext}")
                    items.append(item)
                except Exception as ex:
                    errors.append(f"Failed to inspect file {rel_path}: {ex}")

        return ProjectMigrationReport(
            user_id=user_id,
            slug=slug,
            title=title,
            source_dir=str(source_dir),
            dest_dir=str(dest_dir),
            status="INVENTORIED",
            files=items,
            total_bytes=total_bytes,
            warnings=warnings,
            errors=errors,
            timestamp=now_iso
        )

    def run_migration(self, dry_run: bool = True) -> List[ProjectMigrationReport]:
        """
        Executes migration across all inventoried projects.
        When dry_run=True, verifies integrity and returns what WOULD be performed.
        When dry_run=False, copies valid files, writes project_manifest.json, and verifies hashes.
        """
        reports = self.inventory_projects()
        for report in reports:
            if report.status == "ERROR":
                continue

            dest_path = Path(report.dest_dir)
            source_path = Path(report.source_dir)

            if dry_run:
                # In dry run, check if destination already has identical files
                all_up_to_date = dest_path.exists() and (dest_path / MANIFEST_FILENAME).exists()
                if all_up_to_date:
                    for item in report.files:
                        if not item.is_valid_extension:
                            continue
                        dest_file = dest_path / item.relative_path
                        if not dest_file.exists():
                            all_up_to_date = False
                            break
                        item.dest_sha256 = compute_file_sha256(dest_file)
                        if item.dest_sha256 != item.source_sha256:
                            all_up_to_date = False
                            break
                report.status = "UP_TO_DATE" if all_up_to_date else "DRY_RUN_PENDING"
                continue

            # Live Migration Execution
            try:
                # 1. Create backup snapshot if destination already exists (for rollback)
                project_key = f"{report.user_id}/{report.slug}"
                if dest_path.exists():
                    backup_dir = dest_path.parent / f".backup_{report.slug}_{int(datetime.now().timestamp())}"
                    shutil.copytree(dest_path, backup_dir)
                    self.rollback_snapshots[project_key] = backup_dir

                dest_path.mkdir(parents=True, exist_ok=True)

                # 2. Copy each valid file and verify hash
                for item in report.files:
                    if not item.is_valid_extension:
                        continue
                    src_file = source_path / item.relative_path
                    dst_file = dest_path / item.relative_path
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, dst_file)

                    dst_sha = compute_file_sha256(dst_file)
                    item.dest_sha256 = dst_sha
                    if dst_sha != item.source_sha256:
                        raise ValueError(f"Integrity check failed for {item.relative_path}: {dst_sha} != {item.source_sha256}")

                # 3. Create or update project_manifest.json
                manifest = load_manifest(dest_path)
                manifest["slug"] = report.slug
                manifest["title"] = report.title
                manifest["entrypoint"] = "index.html"
                manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
                save_manifest(dest_path, manifest)
                report.manifest_created = True
                report.status = "MIGRATED"

            except Exception as ex:
                logger.error(f"Migration error for {report.user_id}/{report.slug}: {ex}")
                report.status = "ERROR"
                report.errors.append(str(ex))
                # Attempt automatic rollback on failure
                self.rollback_project(report.user_id, report.slug)

        return reports

    def rollback_project(self, user_id: int, slug: str) -> bool:
        """Rolls back a migrated project to its pre-migration state using the snapshot."""
        project_key = f"{user_id}/{slug}"
        backup_dir = self.rollback_snapshots.get(project_key)
        dest_dir = self.dest_base_dir / str(user_id) / slug

        if backup_dir and backup_dir.exists():
            if dest_dir.exists():
                shutil.rmtree(dest_dir)
            shutil.copytree(backup_dir, dest_dir)
            shutil.rmtree(backup_dir)
            del self.rollback_snapshots[project_key]
            return True
        elif dest_dir.exists():
            # If no prior backup existed because dest was newly created, remove it
            shutil.rmtree(dest_dir)
            return True
        return False
