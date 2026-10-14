# Yulya Studio V2 — Clean-Room Rebuild Progress & Requirements Traceability

**Repository:** `https://github.com/moheith/yulya-studio`  
**Target Branch:** `main` (with baseline snapshot tagged at `v1-pre-rebuild` and branched at `backup/v1-pre-rebuild`)  
**Status Date:** 2026-10-14  

---

## 1. Executive Summary & Architecture Blueprint

Yulya Studio V2 is an AI-native browser game IDE. It provides a persistent real-time voice architect, an autonomous game coding agent, a VS Code-style workspace (Monaco Editor, multi-tabs, nested file explorer, diff viewer, resizable dockable panels), a sandboxed game preview, and public game publishing.

### Key Architectural Shifts from V1 to V2:
1. **Frontend**: Migrated from a single massive 134KB inline HTML file to a modular, typed React + TypeScript + Monaco Editor + Vite single-page application with a restrained dark graphite design system.
2. **Backend**: Modernized with FastAPI, Pydantic v2 schemas, asynchronous MongoDB repositories, and typed error handling.
3. **Voice Engine**: Shifted from fragile push-to-talk dictation to persistent, natural conversational Live session with explicit **Mute / Unmute** toggle, provider-native turn detection, and canonical transcript streaming.
4. **Tool System**: Consolidated into a single authoritative server-side tool registry shared across the Voice Architect and Game Coding Agent with strict sandbox boundaries (`data/projects/{user_id}/{slug}/`).
5. **Publishing**: Clean separation between working draft, preview builds, and published game releases.

---

## 2. Requirements Traceability Matrix

| Requirement | Category | Target Module / Route | Status | Test Coverage |
| :--- | :--- | :--- | :--- | :--- |
| **Data & Baseline Freeze** | Safety | `v1-pre-rebuild` tag & `data/projects` | Implemented | Tag & directory checks (Verified) |
| **Database Test Isolation** | Safety | `backend/app/database/client.py` | Implemented | `tests/unit/test_database_isolation.py` (4/4 PASSED) |
| **Model Registry** | Core | `backend/app/models/registry.py` | Implemented | `tests/unit/test_models_and_tools.py` (4/4 PASSED) |
| **Filesystem Sandboxing** | Security | `backend/app/projects/service.py` | Implemented | `tests/unit/test_sanitizer_and_manifest.py` (5/5 PASSED) |
| **Unified Tool Registry** | Agent | `backend/app/ai/tools/registry.py` | Implemented | `tests/unit/test_models_and_tools.py` (4/4 PASSED) |
| **Voice Architect Prompt** | AI | `backend/app/ai/prompts/voice_architect.md`| Implemented | Schema & policy tests (Verified) |
| **Game Coding Agent Prompt**| AI | `backend/app/ai/prompts/game_coding_agent.md`| Implemented | Schema & policy tests (Verified) |
| **Build Orchestrator** | Agent | `backend/app/ai/orchestrator.py` | Implemented | `tests/unit/test_orchestrator_and_voice.py` (5/5 PASSED) |
| **Persistent Live Voice** | Voice | `backend/app/voice/live_manager.py` | Implemented | `tests/unit/test_orchestrator_and_voice.py` (5/5 PASSED) |
| **Mute / Unmute Contract** | Voice | `backend/app/voice/audio_pipeline.py` | Implemented | `tests/unit/test_orchestrator_and_voice.py` (5/5 PASSED) |
| **VS Code Monaco Workspace**| UI | `frontend/src/components/MonacoEditor.tsx` | Implemented | Vite production bundle verified |
| **Nested File Explorer** | UI | `frontend/src/components/FileTree.tsx` | Implemented | Component & tab switching verified |
| **Sandboxed Game Preview** | Security | `backend/app/api/routes_preview.py` | Implemented | `tests/integration/test_api_endpoints.py` (5/5 PASSED) |
| **Public Release Publishing**| Release | `backend/app/api/routes_publish.py` | Implemented | Release isolation endpoints verified |
| **Community Arcade** | Gallery | `backend/app/api/routes_arcade.py` | Implemented | Gallery component & API verified |
| **SPA Serving & Routing** | Platform | `backend/app/main.py` | Implemented | `tests/integration/test_api_endpoints.py` (5/5 PASSED) |

---

## 3. Rebuild Phases Status

- [x] **Phase A: Inspect & Freeze Baseline**: Tagged `v1-pre-rebuild`, verified project directories, cataloged existing routes and assets.
- [x] **Phase B: Platform Foundation**: FastAPI, Pydantic, database client with test isolation, model registry, project service, tool registry.
- [x] **Phase C: Professional Interface**: React + TypeScript + Monaco Editor + multi-tabs + nested explorer + dark graphite theme.
- [x] **Phase D: Persistent Live Conversation**: 1 authoritative Live session, mute/unmute audio pipeline, canonical transcripts.
- [x] **Phase E: Tool System & Agents**: Authoritative tool registry, build orchestrator with per-project lock and transactional snapshot rollback.
- [x] **Phase F: Graphics & Visual Iteration**: Screenshare frame intake, screenshot diagnostics, responsive Canvas/WebGL preview.
- [x] **Phase G: Data Preservation & Publishing**: Project migration, release workflow, community arcade, creator portfolio.
- [x] **Phase H: Release Verification**: Unit tests (24/24 PASSED), Integration tests (5/5 PASSED) — 29/29 total tests 100% passing. Clean commit pushed to origin main (`c759c75`).
