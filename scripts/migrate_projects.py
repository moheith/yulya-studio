#!/usr/bin/env python3
"""
CLI Migration Command for Yulya Studio V2 Projects (Section 6).
Usage:
    python scripts/migrate_projects.py --dry-run
    python scripts/migrate_projects.py --live
    python scripts/migrate_projects.py --inventory-only
    python scripts/migrate_projects.py --source ./projects --dest ./data/projects
"""

import sys
import argparse
import json
from pathlib import Path
from dataclasses import asdict

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.app.projects.migration import ProjectMigrator


def main():
    parser = argparse.ArgumentParser(description="Yulya Studio V2 Project Migration Tool")
    parser.add_argument("--source", type=str, default=None, help="Source directory containing legacy projects")
    parser.add_argument("--dest", type=str, default=None, help="Destination directory for V2 projects")
    parser.add_argument("--live", action="store_true", help="Perform live migration (default is dry-run)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Explicitly specify dry-run mode (default)")
    parser.add_argument("--inventory-only", action="store_true", help="Only inventory projects without running migration")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")

    args = parser.parse_args()

    src_dir = Path(args.source) if args.source else None
    dst_dir = Path(args.dest) if args.dest else None

    migrator = ProjectMigrator(source_base_dir=src_dir, dest_base_dir=dst_dir)

    print(f"[ProjectMigrator] Source: {migrator.source_base_dir}")
    print(f"[ProjectMigrator] Destination: {migrator.dest_base_dir}")

    if args.inventory_only:
        print("[ProjectMigrator] Running read-only inventory...")
        reports = migrator.inventory_projects()
    else:
        is_dry_run = not args.live
        mode_str = "DRY RUN (no files modified)" if is_dry_run else "LIVE MIGRATION"
        print(f"[ProjectMigrator] Executing in {mode_str} mode...")
        reports = migrator.run_migration(dry_run=is_dry_run)

    dict_reports = [asdict(r) for r in reports]

    if args.json:
        print(json.dumps(dict_reports, indent=2))
    else:
        print("\n" + "=" * 60)
        print(f"Migration Summary: {len(reports)} project(s) processed")
        print("=" * 60)
        for r in reports:
            print(f"- User: {r.user_id} | Slug: {r.slug} | Status: {r.status} | Files: {len(r.files)} | Bytes: {r.total_bytes}")
            if r.warnings:
                for w in r.warnings:
                    print(f"  [WARN] {w}")
            if r.errors:
                for e in r.errors:
                    print(f"  [ERROR] {e}")
        print("=" * 60)


if __name__ == "__main__":
    main()
