"""
Build Orchestrator for Yulya Studio V2.
Coordinates code generation, per-project locking, incremental preservation,
transactional snapshots, and static validation rollback (Sections 21, 32, 34).
"""

import re
import json
import time
import asyncio
import secrets
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from google import genai
from google.genai import types
from google.genai.errors import APIError

from backend.app.core.config import settings
from backend.app.core.logging import logger, log_event
from backend.app.core.errors import AppError, ErrorCategory
from backend.app.database import repositories
from backend.app.models.schemas import BuildStage, BuildProgressEvent
from backend.app.models.registry import (
    get_code_fallback_candidates,
    get_default_code_model
)
from backend.app.projects import service
from backend.app.projects.manifest import load_manifest, merge_manifest_updates
from backend.app.projects.sanitizer import resolve_project_path
from backend.app.ai.tools.build_tools import record_build_state


# Per-project execution locks: (user_id, slug) -> asyncio.Lock
PROJECT_LOCKS: Dict[Tuple[int, str], asyncio.Lock] = {}

# Subscribers for real-time build events: (user_id, slug) -> set of asyncio.Queue
BUILD_EVENT_SUBSCRIBERS: Dict[Tuple[int, str], set] = {}

CODING_AGENT_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "game_coding_agent.md"


def get_project_lock(user_id: int, slug: str) -> asyncio.Lock:
    key = (int(user_id), slug.lower())
    if key not in PROJECT_LOCKS:
        PROJECT_LOCKS[key] = asyncio.Lock()
    return PROJECT_LOCKS[key]


def subscribe_to_build_events(user_id: int, slug: str, queue: asyncio.Queue) -> None:
    key = (int(user_id), slug.lower())
    if key not in BUILD_EVENT_SUBSCRIBERS:
        BUILD_EVENT_SUBSCRIBERS[key] = set()
    BUILD_EVENT_SUBSCRIBERS[key].add(queue)


def unsubscribe_from_build_events(user_id: int, slug: str, queue: asyncio.Queue) -> None:
    key = (int(user_id), slug.lower())
    if key in BUILD_EVENT_SUBSCRIBERS:
        BUILD_EVENT_SUBSCRIBERS[key].discard(queue)
        if not BUILD_EVENT_SUBSCRIBERS[key]:
            del BUILD_EVENT_SUBSCRIBERS[key]


async def broadcast_build_event(user_id: int, slug: str, event: BuildProgressEvent) -> None:
    key = (int(user_id), slug.lower())
    queues = list(BUILD_EVENT_SUBSCRIBERS.get(key, []))
    for q in queues:
        try:
            q.put_nowait(event.model_dump())
        except Exception:
            pass


def _load_coding_prompt() -> str:
    if CODING_AGENT_PROMPT_PATH.exists():
        return CODING_AGENT_PROMPT_PATH.read_text(encoding="utf-8")
    return "You are the Game Coding Agent. Output JSON with summary, changes, files, manifest_updates."


async def execute_build_task(
    user_id: int,
    username: str,
    slug: str,
    prompt: str,
    requested_model: Optional[str] = None,
    source: str = "web_ide"
) -> Dict[str, Any]:
    """
    Authoritative build execution pipeline with per-project lock, incremental preservation,
    and snapshot-based transactional rollback.
    """
    if not prompt or not prompt.strip():
        raise AppError(ErrorCategory.INVALID_INPUT, "Build prompt cannot be empty.")

    lock = get_project_lock(user_id, slug)
    if lock.locked():
        raise AppError(
            ErrorCategory.CONFLICT,
            f"Another build is currently in progress for project '{slug}'. Please wait for it to complete.",
            status_code=409,
            recoverable=True
        )

    request_id = f"req_{int(time.time()*1000)}_{secrets.token_hex(4)}"
    build_id = f"bld_{int(time.time()*1000)}_{secrets.token_hex(4)}"

    async with lock:
        record_build_state(build_id, {
            "request_id": request_id,
            "build_id": build_id,
            "status": "ACCEPTED",
            "prompt": prompt,
            "started_at": time.time()
        })

        await broadcast_build_event(user_id, slug, BuildProgressEvent(
            event_id=f"evt_{int(time.time()*1000)}_1",
            request_id=request_id,
            build_id=build_id,
            stage=BuildStage.ACCEPTED,
            message="Build request accepted by orchestrator.",
            timestamp=time.time()
        ))

        # 1. Take in-memory snapshot for transactional rollback
        snapshot = service.create_snapshot(user_id, slug)
        project_dir = service.resolve_project_path(user_id, slug)
        manifest = load_manifest(project_dir)

        # 2. Resolve user's Google AI Studio API key
        api_key = await repositories.get_decrypted_user_api_key(user_id)
        if not api_key:
            raise AppError(
                ErrorCategory.AUTHENTICATION,
                "No Google AI Studio API key found. Please connect your API key in Settings.",
                status_code=400
            )

        # 3. Determine code model candidates via waterfall
        pref_model = requested_model or manifest.get("preferred_code_model")
        candidates = get_code_fallback_candidates(pref_model)

        # 4. Formulate context
        current_files = service.get_project_files(user_id, slug)
        files_context_str = json.dumps(current_files, indent=2)

        user_content = (
            f"PROJECT SLUG: {slug}\n"
            f"MANIFEST: {json.dumps(manifest, indent=2)}\n\n"
            f"CURRENT FILES:\n{files_context_str}\n\n"
            f"USER BUILD REQUEST:\n{prompt}\n\n"
            "REMEMBER: Preserve existing game mechanics! Output valid JSON only with keys: "
            "summary, changes (array of {file, search, replace}), files (complete content for new or rewritten files), manifest_updates."
        )

        system_instruction = _load_coding_prompt()

        await broadcast_build_event(user_id, slug, BuildProgressEvent(
            event_id=f"evt_{int(time.time()*1000)}_2",
            request_id=request_id,
            build_id=build_id,
            stage=BuildStage.PLANNING,
            message="Analyzing project files and planning modifications...",
            timestamp=time.time()
        ))

        # 5. Execute generation with model fallback
        genai_client = genai.Client(api_key=api_key)
        raw_response_text = None
        actual_model_used = None

        for candidate in candidates:
            try:
                log_event(f"Attempting code generation with {candidate.id}", channel="build", request_id=request_id)
                response = await asyncio.to_thread(
                    genai_client.models.generate_content,
                    model=candidate.id,
                    contents=user_content,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.2,
                        response_mime_type="application/json"
                    )
                )
                if response and hasattr(response, "text") and response.text:
                    raw_response_text = response.text
                    actual_model_used = candidate.id
                    break
            except APIError as ae:
                logger.warning(f"[CODE GEN API ERROR] Model {candidate.id} failed: {ae}")
                if ae.code in (429, 404, 500, 502, 503):
                    continue  # Fallback to next candidate
                raise AppError(ErrorCategory.PROVIDER_UNAVAILABLE, str(ae))
            except Exception as e:
                logger.warning(f"[CODE GEN ERROR] Model {candidate.id} failed: {e}")
                continue

        if not raw_response_text or not actual_model_used:
            raise AppError(
                ErrorCategory.PROVIDER_UNAVAILABLE,
                "All candidate code generation models failed to produce a response. Please try again later."
            )

        # 6. Parse structured response
        try:
            # Strip potential markdown code fences if model enclosed them
            clean_json = raw_response_text.strip()
            if clean_json.startswith("```json"):
                clean_json = clean_json[7:]
            if clean_json.startswith("```"):
                clean_json = clean_json[3:]
            if clean_json.endswith("```"):
                clean_json = clean_json[:-3]
            data = json.loads(clean_json.strip())
        except Exception as parse_err:
            raise AppError(
                ErrorCategory.INVALID_INPUT,
                f"Model response was not valid JSON: {parse_err}"
            )

        await broadcast_build_event(user_id, slug, BuildProgressEvent(
            event_id=f"evt_{int(time.time()*1000)}_3",
            request_id=request_id,
            build_id=build_id,
            stage=BuildStage.EDITING,
            message="Applying validated incremental code updates...",
            timestamp=time.time(),
            actual_model=actual_model_used
        ))

        # 7. Apply changes with transactional rollback protection
        modified_files: List[str] = []
        try:
            # A. Search-and-replace patches
            for change in data.get("changes", []):
                file_rel = change.get("file")
                search_str = change.get("search")
                replace_str = change.get("replace")
                if file_rel and search_str and replace_str is not None:
                    service.apply_patch(user_id, slug, file_rel, search_str, replace_str)
                    if file_rel not in modified_files:
                        modified_files.append(file_rel)

            # B. Full file writes / new files
            for file_rel, content in data.get("files", {}).items():
                if file_rel and content is not None:
                    service.write_project_file(user_id, slug, file_rel, content)
                    if file_rel not in modified_files:
                        modified_files.append(file_rel)

            # C. Update manifest memory
            if data.get("manifest_updates"):
                merge_manifest_updates(project_dir, data["manifest_updates"])

            # 8. Post-write validation gate (Preservation checks)
            # Check 1: index.html must exist
            if not (project_dir / "index.html").exists():
                raise AppError(ErrorCategory.BUILD_VALIDATION, "Primary entrypoint 'index.html' was deleted or missing.")

            # Check 2: Destructive shrinkage detection
            for mod_file in modified_files:
                target_path = service.resolve_file_path(project_dir, mod_file)
                if target_path.exists() and target_path.is_file():
                    new_line_count = len(target_path.read_text(encoding="utf-8").splitlines())
                    old_content = snapshot.get(mod_file, "")
                    old_line_count = len(old_content.splitlines()) if old_content else 0
                    if old_line_count >= 25 and new_line_count <= 5:
                        raise AppError(
                            ErrorCategory.BUILD_VALIDATION,
                            f"Destructive shrinkage detected in '{mod_file}' (shrunk from {old_line_count} to {new_line_count} lines)."
                        )

        except Exception as apply_err:
            logger.error(f"[BUILD ROLLBACK] Build {build_id} failed: {apply_err}. Restoring snapshot...")
            service.restore_snapshot(user_id, slug, snapshot)
            await broadcast_build_event(user_id, slug, BuildProgressEvent(
                event_id=f"evt_{int(time.time()*1000)}_fail",
                request_id=request_id,
                build_id=build_id,
                stage=BuildStage.FAILED,
                message=f"Build failed validation: {apply_err}. Changes rolled back.",
                timestamp=time.time(),
                error=str(apply_err)
            ))
            raise AppError(ErrorCategory.BUILD_VALIDATION, f"Build validation failure: {apply_err}")

        # 9. Update database project record
        all_current_files = list(service.get_project_files(user_id, slug).keys())
        await repositories.save_project(
            user_id=user_id,
            username=username,
            slug=slug,
            title=manifest.get("title", slug),
            description=manifest.get("description", ""),
            files=all_current_files,
            tags=manifest.get("tags", ["game", "canvas"])
        )

        summary = data.get("summary", "Game updated successfully.")
        res_payload = {
            "success": True,
            "request_id": request_id,
            "build_id": build_id,
            "summary": summary,
            "files_changed": modified_files,
            "actual_model": actual_model_used,
            "duration_ms": (time.time() - record_build_state.__name__.__len__()) * 1000
        }

        record_build_state(build_id, {
            "request_id": request_id,
            "build_id": build_id,
            "status": "SUCCEEDED",
            "summary": summary,
            "actual_model": actual_model_used,
            "files_changed": modified_files,
            "completed_at": time.time()
        })

        await broadcast_build_event(user_id, slug, BuildProgressEvent(
            event_id=f"evt_{int(time.time()*1000)}_done",
            request_id=request_id,
            build_id=build_id,
            stage=BuildStage.SUCCEEDED,
            message=summary,
            timestamp=time.time(),
            files_changed=modified_files,
            actual_model=actual_model_used
        ))

        return res_payload
