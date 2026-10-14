"""
Project Manifest Manager for Yulya Studio V2.
Maintains persistent project memory in project_manifest.json (Section 31).
Preserves architectural decisions, game systems, and controls across incremental builds.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


MANIFEST_FILENAME = "project_manifest.json"

DEFAULT_MANIFEST: Dict[str, Any] = {
    "schema_version": "2.0.0",
    "slug": "",
    "title": "",
    "genre": "arcade",
    "engine": "canvas2d",
    "entrypoint": "index.html",
    "systems": ["movement", "collision", "score", "game_loop"],
    "controls": ["keyboard_arrows_wasd", "spacebar"],
    "design_decisions": [],
    "known_bugs": [],
    "creator_preferences": {},
    "build_number": 1,
    "last_successful_build": 1,
    "build_status": "READY",
    "created_at": "",
    "updated_at": ""
}


def load_manifest(project_dir: Path) -> Dict[str, Any]:
    """Loads project_manifest.json or returns default template."""
    manifest_file = project_dir / "project_manifest.json"
    if manifest_file.exists():
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                res = dict(DEFAULT_MANIFEST)
                res.update(data)
                return res
        except Exception:
            pass
    return dict(DEFAULT_MANIFEST)


def save_manifest(project_dir: Path, manifest_data: Dict[str, Any]) -> None:
    """Saves updated project_manifest.json with updated timestamps."""
    manifest_file = project_dir / "project_manifest.json"
    now_iso = datetime.now(timezone.utc).isoformat()
    if not manifest_data.get("created_at"):
        manifest_data["created_at"] = now_iso
    manifest_data["updated_at"] = now_iso
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)


def merge_manifest_updates(project_dir: Path, updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Safely merges incremental updates into project_manifest.json.
    Preserves existing game systems, controls, and design decisions.
    """
    current = load_manifest(project_dir)

    # Merge engine if specified
    if updates.get("engine"):
        current["engine"] = updates["engine"]

    # Merge genre if specified
    if updates.get("genre"):
        current["genre"] = updates["genre"]

    if updates.get("title"):
        current["title"] = updates["title"]

    if updates.get("description"):
        current["description"] = updates["description"]

    # Merge systems (additive union, handles both strings and dicts)
    new_systems = updates.get("systems", [])
    if isinstance(new_systems, list):
        current_systems = list(current.get("systems", []))
        for sys_item in new_systems:
            if isinstance(sys_item, dict):
                sys_id = sys_item.get("id")
                idx = next((i for i, x in enumerate(current_systems) if isinstance(x, dict) and x.get("id") == sys_id), None)
                if idx is not None:
                    current_systems[idx] = sys_item
                else:
                    current_systems.append(sys_item)
            elif sys_item not in current_systems:
                current_systems.append(sys_item)
        current["systems"] = current_systems

    # Merge controls (supports dict of key -> action or list)
    new_controls = updates.get("controls")
    if isinstance(new_controls, dict):
        current_controls = current.get("controls")
        if not isinstance(current_controls, dict):
            current_controls = {}
        current_controls.update(new_controls)
        current["controls"] = current_controls
    elif isinstance(new_controls, list):
        current_controls = current.get("controls")
        if not isinstance(current_controls, list):
            current_controls = []
        for c in new_controls:
            if c not in current_controls:
                current_controls.append(c)
        current["controls"] = current_controls

    # Append new design decisions
    new_decisions = updates.get("design_decisions", [])
    if isinstance(new_decisions, list):
        current_decisions = current.get("design_decisions", [])
        for d in new_decisions:
            if d and d not in current_decisions:
                current_decisions.append(d)
        current["design_decisions"] = current_decisions

    # Update known bugs
    if "known_bugs" in updates and isinstance(updates["known_bugs"], list):
        current["known_bugs"] = updates["known_bugs"]

    save_manifest(project_dir, current)
    return current
