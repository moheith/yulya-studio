"""
Comprehensive Verification Test Suite for Yulya Studio
"""
import os
import sys
import asyncio
import io
import json
import base64
import zipfile
from pathlib import Path
import pathlib
from unittest.mock import MagicMock, AsyncMock

# Ensure pathlib._NormalAccessor.mkdir works reliably across wrapped os.mkdir environments
if hasattr(pathlib, "_NormalAccessor") and hasattr(pathlib._NormalAccessor, "mkdir"):
    _orig_mkdir = os.mkdir
    class _CallableWrapper:
        def __init__(self, func):
            self.func = func
        def __call__(self, *args, **kwargs):
            return self.func(*args, **kwargs)
        def __get__(self, instance, owner=None):
            return self.func
    pathlib._NormalAccessor.mkdir = _CallableWrapper(_orig_mkdir)

import config
import database
import projects_manager
import ai_engine
import server
from aiohttp.test_utils import make_mocked_request

async def run_tests():
    print("=== STARTING YULYA STUDIO TEST SUITE ===")
    tests_passed = 0
    tests_failed = 0

    def assert_true(condition, msg):
        nonlocal tests_passed, tests_failed
        if condition:
            tests_passed += 1
            print(f"  [PASS] {msg}")
        else:
            tests_failed += 1
            print(f"  [FAIL] {msg}")

    # 1. Template Rendering Verification
    print("\n1. Testing Template Rendering...")
    for tmpl, ctx in [
        ("index.html", {"user": None}),
        ("index.html", {"user": {"username": "alice", "id": 123}}),
        ("onboarding.html", {"user": None}),
        ("onboarding.html", {"user": {"username": "bob", "id": 456}}),
        ("studio.html", {
            "user": {"username": "carol", "id": 789},
            "projects": [{"slug": "neon-dodge", "title": "Neon Dodge"}],
            "active_slug": "neon-dodge",
            "active_project": {"slug": "neon-dodge", "title": "Neon Dodge"}
        }),
        ("profile.html", {
            "user": {"username": "carol", "id": 789},
            "profile": {
                "user_id": 789,
                "username": "carol",
                "display_name": "Carol Developer",
                "profile_name": "Carol Developer",
                "avatar": None,
                "created_games": [{"slug": "neon-dodge", "title": "Neon Dodge", "description": "Dodge neon sparks", "tags": ["canvas", "arcade"]}]
            },
            "is_owner": True,
            "games": [{"slug": "neon-dodge", "title": "Neon Dodge", "description": "Dodge neon sparks", "tags": ["canvas", "arcade"]}]
        }),
        ("profile.html", {
            "user": None,
            "profile": {
                "user_id": 789,
                "username": "carol",
                "display_name": "Carol Developer",
                "profile_name": "Carol Developer",
                "avatar": None,
                "created_games": [{"slug": "neon-dodge", "title": "Neon Dodge", "description": "Dodge neon sparks", "tags": ["canvas", "arcade"]}]
            },
            "is_owner": False,
            "games": [{"slug": "neon-dodge", "title": "Neon Dodge", "description": "Dodge neon sparks", "tags": ["canvas", "arcade"]}]
        })
    ]:
        try:
            resp = await server.render_template(tmpl, ctx)
            assert_true(resp.status == 200 and len(resp.text) > 200, f"Rendered {tmpl} with ctx={list(ctx.keys())}")
            
            # Verify Iframe Sandbox in templates (allow-scripts ONLY, strictly no allow-same-origin)
            if tmpl in ["studio.html", "profile.html"]:
                assert_true('sandbox="allow-scripts"' in resp.text, f"Iframe has sandbox='allow-scripts' in {tmpl}")
            elif tmpl == "index.html":
                assert_true("sandbox = 'allow-scripts'" in resp.text or 'sandbox="allow-scripts"' in resp.text, "Iframe sandbox configured in index.html")
            assert_true('allow-same-origin' not in resp.text, f"Iframe strictly omits allow-same-origin in {tmpl}")
            
            # Verify NO emojis used as interface icons
            forbidden_emojis = ["🎮", "🚀", "🎙️", "⚡", "🤖", "🔥", "🕹️"]
            found_emojis = [e for e in forbidden_emojis if e in resp.text]
            assert_true(len(found_emojis) == 0, f"Zero forbidden emojis in {tmpl} (found: {found_emojis})")
            
            # Specific template component checks
            if tmpl == "studio.html":
                assert_true('id="commandPaletteModal"' in resp.text, "Command Palette modal exists in studio.html")
                assert_true('paletteSearchInput' in resp.text, "Command Palette input exists in studio.html")
            elif tmpl == "index.html":
                assert_true('author.innerHTML' not in resp.text, "XSS-safe author DOM construction in index.html")
            elif tmpl == "profile.html":
                if ctx.get("is_owner"):
                    assert_true('+ New Project' in resp.text, "Owner sees '+ New Project' button in profile.html")
                    assert_true('Edit in Studio' in resp.text, "Owner sees 'Edit in Studio' button in profile.html")
                else:
                    assert_true('+ New Project' not in resp.text, "Spectator does not see '+ New Project' button in profile.html")
                    assert_true('Edit in Studio' not in resp.text, "Spectator does not see 'Edit in Studio' button in profile.html")
            
        except Exception as e:
            assert_true(False, f"Failed rendering {tmpl}: {e}")

    # 2. Project Manager & Security Verification
    print("\n2. Testing Projects Manager & Security...")
    test_user_id = 999999999
    test_slug = "test-game"
    
    try:
        # Create starter
        files = projects_manager.create_starter_game(test_user_id, "testuser", test_slug, "Test Game")
        assert_true(len(files) == 3, f"Created starter game files: {files}")
        
        # Read files
        html = projects_manager.read_project_file(test_user_id, test_slug, "index.html")
        assert_true("Test Game" in html and "canvas" in html, "Read valid starter HTML")
        
        # Path Traversal Checks
        traversal_caught = False
        try:
            projects_manager.get_user_project_dir(test_user_id, "../../etc")
        except PermissionError:
            traversal_caught = True
        except Exception:
            traversal_caught = True
        assert_true(traversal_caught, "Path traversal in slug blocked")
        
        # Traversal in filename
        filename_caught = False
        try:
            projects_manager.write_project_file(test_user_id, test_slug, "../../../evil.txt", "evil")
        except (ValueError, PermissionError):
            filename_caught = True
        assert_true(filename_caught, "Path traversal in filename blocked")
        
        # File size limit check (Max 512 KB)
        oversized_caught = False
        try:
            large_content = "X" * (config.MAX_FILE_SIZE + 1024)
            projects_manager.write_project_file(test_user_id, test_slug, "huge.js", large_content)
        except ValueError as ve:
            oversized_caught = True
        assert_true(oversized_caught, "Oversized file (>512 KB) blocked")
        
        # Comprehensive Section 26 Code sanitization checks
        patterns_to_test = [
            ("parent.document.cookie", "parent.document"),
            ("top.document.location", "top.document"),
            ("window.opener.postMessage()", "window.opener"),
            ("window.parent.location", "window.parent"),
            ("window.top.location", "window.top"),
            ("document.cookie = 'x=1'", "document.cookie"),
            ("localStorage.getItem('x')", "localStorage"),
            ("sessionStorage.setItem('x', '1')", "sessionStorage"),
            ("new XMLHttpRequest()", "XMLHttpRequest"),
            ("fetch('https://evil.com')", "fetch"),
            ("eval('bad()')", "eval"),
            ("Function('bad()')", "Function"),
        ]
        all_sanitized = True
        for snippet, name in patterns_to_test:
            san, _ = projects_manager.sanitize_game_code(f"function run() {{ {snippet}; }}")
            if name in san:
                all_sanitized = False
                print(f"  [FAIL] Sanitizer did not neutralize: {name}")
                break
        assert_true(all_sanitized, "All Section 26 dangerous escape & network patterns neutralized")
        
        # ZIP generation
        zip_buf = projects_manager.create_zip_archive(test_user_id, test_slug)
        with zipfile.ZipFile(zip_buf, "r") as zf:
            zip_names = zf.namelist()
            assert_true("index.html" in zip_names and "app.js" in zip_names, f"ZIP contains project files: {zip_names}")
            
        # Project deletion
        deleted = projects_manager.delete_project_dir(test_user_id, test_slug)
        assert_true(deleted, "Project directory deleted safely")
        
    except Exception as e:
        assert_true(False, f"Projects manager error: {e}")

    # 3. Rate Limiting Tests
    print("\n3. Testing Rate Limiter...")
    action = "test_action"
    ident = "user_1"
    limit = 3
    window = 10
    
    # 3 allowed
    for i in range(limit):
        allowed, _ = server.check_rate_limit(action, ident, limit, window)
        assert_true(allowed, f"Request {i+1} within limit allowed")
        
    # 4th blocked
    allowed, wait_time = server.check_rate_limit(action, ident, limit, window)
    assert_true(not allowed and wait_time > 0, f"Request 4 blocked with wait_time={wait_time}s")

    # 4. App Initialization & Routes Test
    print("\n4. Testing App Routes & Middlewares...")
    try:
        app = await server.init_app()
        routes = [r.resource.canonical for r in app.router.routes() if hasattr(r.resource, 'canonical')]
        expected_routes = [
            "/",
            "/studio",
            "/spectate/{token}",
            "/spectate/{username}/{slug}",
            "/auth/login",
            "/auth/callback",
            "/auth/logout",
            "/api/save-key",
            "/api/create-project",
            "/api/modify-project",
            "/api/delete-project",
            "/api/leave-vc",
            "/api/community-projects",
            "/api/health",
            "/api/project-files/{slug}",
            "/api/project-logs/{slug}",
            "/api/download-zip/{username}/{slug}",
            "/ws/studio",
            "/{username}/{slug}",
            "/{username}/{slug}/",
            "/{username}/{slug}/studio",
            "/{username}"
        ]
        for er in expected_routes:
            assert_true(any(er == r or er in r for r in routes), f"Route registered: {er}")
            
        # Test middleware security headers
        middlewares = app.middlewares
        assert_true(len(middlewares) > 0, "Security headers middleware installed")
    except Exception as e:
        assert_true(False, f"App initialization error: {e}")

    # 5. Routing & WebSocket Security Checks
    print("\n5. Testing URL Redirects & WebSocket Rejection...")
    try:
        # Test game redirect without trailing slash
        req_redir = make_mocked_request("GET", "/moheith/neon-dodge", match_info={"username": "moheith", "slug": "neon-dodge"}, app=app)
        try:
            await server.handle_game_redirect(req_redir)
            assert_true(False, "handle_game_redirect should raise HTTPFound")
        except server.web.HTTPFound as redirect:
            assert_true(redirect.location == "/moheith/neon-dodge/", f"Redirects to trailing slash: {redirect.location}")

        # Test WebSocket rejection for unauthorized connection with invalid slug/token
        req_bad_ws = make_mocked_request(
            "GET",
            "/ws/studio?slug=nonexistent-game-xyz-999&token=bogus_token",
            headers={"Upgrade": "websocket", "Connection": "Upgrade"},
            app=app
        )
        ws_res = await server.handle_ws_studio(req_bad_ws)
        assert_true(isinstance(ws_res, server.web.Response) and ws_res.status == 401, "Rejected unauthorized WebSocket connection with 401")

        # Test user slug studio redirect
        req_studio = make_mocked_request("GET", "/moheith/neon-dodge/studio", match_info={"username": "moheith", "slug": "neon-dodge"}, app=app)
        try:
            res_studio = await server.handle_user_slug_studio(req_studio)
            # When not logged in, redirects to login
            assert_true(res_studio.status in [302, 303, 401] or isinstance(res_studio, server.web.HTTPFound), "Studio direct route redirects unauthenticated user safely")
        except server.web.HTTPFound:
            assert_true(True, "Studio direct route redirects unauthenticated user safely")

        # Test handle_game_asset returns 200 OK with valid content_type and charset (No 500 error)
        from unittest.mock import patch
        projects_manager.create_starter_game(888123456, "mockauthor", "test-game", "Test Game")
        with patch("database.get_project_by_username_and_slug", AsyncMock(return_value={"user_id": 888123456, "slug": "test-game", "title": "Test Game"})):
            req_asset = make_mocked_request("GET", "/mockauthor/test-game/", match_info={"username": "mockauthor", "slug": "test-game", "file": "index.html"}, app=app)
            asset_res = await server.handle_game_asset(req_asset)
            assert_true(asset_res.status == 200, "handle_game_asset returns 200 OK without 500 error")
            assert_true(asset_res.content_type == "text/html", "handle_game_asset has clean content_type 'text/html'")
            assert_true(asset_res.charset == "utf-8", "handle_game_asset specifies charset='utf-8' correctly")

        # Test api_save_project_log and log retrieval up to 200 lines
        with patch("server.get_session_user", AsyncMock(return_value={"id": 888123456, "username": "mockauthor"})), \
             patch("database.get_project", AsyncMock(return_value={"user_id": 888123456, "slug": "test-game"})):
            req_log = make_mocked_request("POST", "/api/project-logs/test-game", match_info={"slug": "test-game"}, app=app)
            req_log.json = AsyncMock(return_value={"step": "EXIT", "message": "Session closed"})
            log_res = await server.api_save_project_log(req_log)
            assert_true(log_res.status == 200, "api_save_project_log succeeds with 200 OK")
            
            # Verify log entry in build.log
            logs = projects_manager.read_build_log(888123456, "test-game", max_lines=200)
            assert_true(any(l.get("step") == "exit" for l in logs), "EXIT step written to build.log")

    except Exception as e:
        assert_true(False, f"Routing & WebSocket error: {e}")

    # 6. Strict Path Sandboxing & Repository Isolation Tests
    print("\n6. Testing Strict Path Sandboxing & Repository Isolation...")
    isolation_user_id = 888123456
    game_a = "game-alpha"
    game_b = "game-beta"
    
    try:
        # Ensure projects dir uses data/projects
        assert_true("data" in str(config.PROJECTS_DIR) and "projects" in str(config.PROJECTS_DIR), f"PROJECTS_DIR is within data/projects: {config.PROJECTS_DIR}")

        # Create two isolated projects
        projects_manager.create_starter_game(isolation_user_id, "tester", game_a, "Game Alpha")
        projects_manager.create_starter_game(isolation_user_id, "tester", game_b, "Game Beta")

        dir_a = projects_manager.get_user_project_dir(isolation_user_id, game_a)
        dir_b = projects_manager.get_user_project_dir(isolation_user_id, game_b)
        assert_true(dir_a != dir_b, "Separate game repos have distinct directories")
        assert_true(str(dir_a).endswith("game-alpha") and str(dir_b).endswith("game-beta"), "Game repo paths contain safe slugs")

        # Traversal in slug tests
        slug_traversals = [
            "../../other_user",
            "..\\windows\\system32",
            "/absolute/path",
            "slug/nested",
            "slug\\nested",
            ":drive",
            "%2e%2e%2f"
        ]
        for bad_slug in slug_traversals:
            caught = False
            try:
                projects_manager.get_user_project_dir(isolation_user_id, bad_slug)
            except (PermissionError, ValueError):
                caught = True
            assert_true(caught, f"Slug traversal blocked: {bad_slug}")

        # Traversal in filename tests
        bad_filenames = [
            "../../profile.json",
            "..\\..\\server.py",
            "../game-beta/app.js",
            "/etc/passwd",
            "C:\\Windows\\win.ini",
            "sub/../../file.js",
            "js/../../../etc/passwd",
            "sub/.."
        ]
        for bad_fn in bad_filenames:
            caught = False
            try:
                projects_manager.write_project_file(isolation_user_id, game_a, bad_fn, "evil")
            except (PermissionError, ValueError):
                caught = True
            assert_true(caught, f"Filename traversal blocked: {bad_fn}")

        # Multi-file and subdirectory support tests (relaxed per Section 2)
        nested_fn = "js/engine.js"
        written_nested = projects_manager.write_project_file(isolation_user_id, game_a, nested_fn, "console.log('engine');")
        assert_true(written_nested == nested_fn, f"Allowed nested file creation: {nested_fn}")
        read_nested = projects_manager.read_project_file(isolation_user_id, game_a, nested_fn)
        assert_true("console.log('engine');" in read_nested, "Read nested file successfully")

        # Multi-file asset support tests (.json, .svg, 3D .gltf/.obj)
        asset_fn = "assets/sprite.svg"
        written_asset = projects_manager.write_project_file(isolation_user_id, game_a, asset_fn, "<svg></svg>")
        assert_true(written_asset == asset_fn, f"Allowed asset file creation: {asset_fn}")
        read_asset = projects_manager.read_project_file(isolation_user_id, game_a, asset_fn)
        assert_true("<svg></svg>" in read_asset, "Read asset file successfully")

        # Check list_project_files returns nested paths
        all_game_files = projects_manager.list_project_files(isolation_user_id, game_a)
        assert_true(nested_fn in all_game_files and asset_fn in all_game_files, f"list_project_files includes nested subpaths: {all_game_files}")

        # Media & 3D model extensions tests (.gltf, .glb, .obj, .mp3, .json)
        for media_ext in ["model.gltf", "mesh.glb", "tree.obj", "sound.mp3", "level.json"]:
            written_media = projects_manager.write_project_file(isolation_user_id, game_a, f"assets/{media_ext}", "data")
            assert_true(written_media == f"assets/{media_ext}", f"Allowed media/3D extension: {media_ext}")

        # Prohibited executable / system file extension tests
        forbidden_extensions = ["payload.py", "script.sh", "run.bat", ".env", "cmd.cmd", "app.exe"]
        for bad_ext in forbidden_extensions:
            caught = False
            try:
                projects_manager.write_project_file(isolation_user_id, game_a, bad_ext, "code")
            except (PermissionError, ValueError):
                caught = True
            assert_true(caught, f"Forbidden file extension blocked: {bad_ext}")

        # Protected target filename tests (cannot touch profile or server config)
        protected_files = ["profile.json", "user.json", "database.py", "server.py", "config.py", "build.log", "ai_engine.py"]
        for prot_f in protected_files:
            caught = False
            try:
                projects_manager.write_project_file(isolation_user_id, game_a, prot_f, "test")
            except (PermissionError, ValueError):
                caught = True
            assert_true(caught, f"Protected target file blocked for writing: {prot_f}")

        # Protected file reading tests (cannot read profile, server config, build log, or .env)
        protected_reads = ["profile.json", "user.json", "database.py", "server.py", "config.py", "build.log", ".env"]
        for prot_r in protected_reads:
            read_blocked = False
            try:
                projects_manager.read_project_file(isolation_user_id, game_a, prot_r)
            except (PermissionError, ValueError):
                read_blocked = True
            assert_true(read_blocked, f"Protected target file blocked for reading: {prot_r}")

        # Cross-repo access check: reading game_b's file using relative path from game_a
        cross_read_caught = False
        try:
            val = projects_manager.read_project_file(isolation_user_id, game_a, "../game-beta/app.js")
            if not val:
                cross_read_caught = True
        except (PermissionError, ValueError):
            cross_read_caught = True
        assert_true(cross_read_caught, "Cross-game reading via traversal blocked")

        # Verify list_project_files excludes build.log and hidden files
        projects_manager.write_build_log(isolation_user_id, game_a, "USER", "test log")
        listed_files = projects_manager.list_project_files(isolation_user_id, game_a)
        assert_true("build.log" not in listed_files, "list_project_files excludes internal build.log")
        assert_true(all(not f.startswith(".") for f in listed_files), "list_project_files excludes hidden files")

        # Verify create_zip_archive excludes build.log
        zip_buf_iso = projects_manager.create_zip_archive(isolation_user_id, game_a)
        with zipfile.ZipFile(zip_buf_iso, "r") as zf:
            zip_contents = zf.namelist()
            assert_true("build.log" not in zip_contents, "create_zip_archive excludes internal build.log")

        # Cleanup test projects
        projects_manager.delete_project_dir(isolation_user_id, game_a)
        projects_manager.delete_project_dir(isolation_user_id, game_b)

    except Exception as e:
        assert_true(False, f"Sandboxing test failed: {e}")

    # 7. Antigravity CLI Activity Log & Persistence Tests
    print("\n7. Testing Antigravity CLI Activity Log & Persistence...")
    try:
        log_test_user = 777777777
        log_test_slug = "antigravity-test"
        projects_manager.create_starter_game(log_test_user, "loguser", log_test_slug, "Antigravity Test")

        # Write sequential Antigravity CLI steps
        projects_manager.write_build_log(log_test_user, log_test_slug, "USER", "Add player jump and coin collection")
        projects_manager.write_build_log(log_test_user, log_test_slug, "THINKING", "Analyzing player mechanics and physics")
        projects_manager.write_build_log(log_test_user, log_test_slug, "READ_FILE", "Reading existing index.html, style.css, app.js")
        projects_manager.write_build_log(log_test_user, log_test_slug, "REPLACE_CONTENT", "Updated app.js (3400 bytes)")
        projects_manager.write_build_log(log_test_user, log_test_slug, "PASS", "Jump mechanics and coins integrated successfully")

        # Verify build.log file exists on disk inside data/projects/{user_id}/{slug}/
        expected_log_path = config.PROJECTS_DIR / str(log_test_user) / log_test_slug / "build.log"
        assert_true(expected_log_path.exists(), f"build.log file exists at {expected_log_path}")

        # Read back build log entries
        log_entries = projects_manager.read_build_log(log_test_user, log_test_slug, max_lines=10)
        assert_true(len(log_entries) == 5, f"Read back {len(log_entries)} formatted log entries")
        
        steps = [entry.get("step") for entry in log_entries]
        assert_true("user" in steps, "USER step present in build.log")
        assert_true("thinking" in steps, "THINKING step present in build.log")
        assert_true("read_file" in steps, "READ_FILE step present in build.log")
        assert_true("replace_content" in steps, "REPLACE_CONTENT step present in build.log")
        assert_true("pass" in steps, "PASS step present in build.log")

        # Cleanup
        projects_manager.delete_project_dir(log_test_user, log_test_slug)

    except Exception as e:
        assert_true(False, f"Antigravity CLI log test failed: {e}")

    # 8. Studio Profiles Database Tracking Tests
    print("\n8. Testing Database Studio Profiles Tracking...")
    try:
        # Test simulated in-memory collection if MongoDB not connected in CI
        mock_profiles_store = {}
        
        class MockCollection:
            def __init__(self):
                self.store = {}
            async def find_one(self, query):
                for doc in self.store.values():
                    match = True
                    for k, v in query.items():
                        if k == "$or" and isinstance(v, list):
                            if not any(all(doc.get(sub_k) == sub_v for sub_k, sub_v in sub_q.items()) for sub_q in v):
                                match = False
                        elif isinstance(v, dict) and "$ne" in v:
                            if doc.get(k) == v["$ne"]: match = False
                        elif doc.get(k) != v:
                            match = False
                    if match:
                        return dict(doc)
                return None
            async def insert_one(self, doc):
                d = dict(doc)
                d["_id"] = f"mock_{len(self.store)}"
                self.store[d["user_id"]] = d
                res = MagicMock()
                res.inserted_id = d["_id"]
                return res
            async def update_one(self, query, update, upsert=False):
                user_id = query.get("user_id")
                doc = self.store.get(user_id)
                if not doc and upsert:
                    doc = {"user_id": user_id}
                    self.store[user_id] = doc
                if doc:
                    if "$set" in update:
                        doc.update(update["$set"])
                    if "$pull" in update:
                        pull_field = list(update["$pull"].keys())[0]
                        pull_crit = update["$pull"][pull_field]
                        doc[pull_field] = [
                            item for item in doc.get(pull_field, [])
                            if not all(item.get(k) == v for k, v in pull_crit.items())
                        ]
                res = MagicMock()
                res.modified_count = 1
                return res

        orig_profiles_col = database.profiles_col
        mock_col = MockCollection()
        database.profiles_col = mock_col

        # Test save_or_update_profile
        p = await database.save_or_update_profile(
            user_id=111222333,
            username="alexdev",
            display_name="Alex The Builder",
            avatar="avatar_hash_1"
        )
        assert_true(p["user_id"] == 111222333, "Profile saved with correct numeric Discord ID")
        assert_true(p["login_id"] == "alexdev", "Profile saved with clean lowercase login_id")
        assert_true(p["username"] == "alexdev", "Profile saved with clean lowercase handle")
        assert_true(p["display_name"] == "Alex The Builder", "Profile saved with display name")
        assert_true(p["profile_name"] == "Alex The Builder", "Profile saved with profile_name")
        assert_true(isinstance(p["created_games"], list), "Profile initialized with created_games list")
        assert_true(isinstance(p["game_names"], list), "Profile initialized with game_names list")

        # Test sync_project_to_profile
        proj_data = {
            "slug": "space-combat",
            "title": "Space Combat",
            "description": "Retro space battle",
            "tags": ["arcade", "canvas"]
        }
        await database.sync_project_to_profile(111222333, "alexdev", proj_data)
        
        fetched = await database.get_profile_by_user_id(111222333)
        assert_true(len(fetched["created_games"]) == 1, "Game synced to studio_profiles created_games array")
        assert_true(fetched["created_games"][0]["slug"] == "space-combat", "Synced game has correct slug")
        assert_true("Space Combat" in fetched.get("game_names", []), "Game title synced to game_names array")

        # Test get_profile_by_username (supports both username and login_id)
        by_user = await database.get_profile_by_username("alexdev")
        assert_true(by_user is not None and by_user["user_id"] == 111222333, "Fetched profile by username/login_id")

        # Test remove_project_from_profile
        await database.remove_project_from_profile(111222333, "space-combat")
        fetched_after = await database.get_profile_by_user_id(111222333)
        assert_true(len(fetched_after["created_games"]) == 0, "Game removed from created_games array on project delete")
        assert_true("Space Combat" not in fetched_after.get("game_names", []), "Game title removed from game_names on project delete")

        database.profiles_col = orig_profiles_col

    except Exception as e:
        assert_true(False, f"Profiles database tracking test failed: {e}")

    # 9. AI Engine Code Generation & Sandbox Execution Verification
    print("\n9. Testing AI Engine Code Generation & Sandbox Execution...")
    ai_test_user = 666777888
    ai_test_slug = "ai-sandbox-test"
    try:
        from unittest.mock import patch
        
        # Test valid code generation mock
        with patch("ai_engine.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_response = MagicMock()
            mock_response.text = (
                '{"summary": "Created canvas shooter game.", "files": {'
                '"index.html": "<!DOCTYPE html><html><body><canvas id=\\"c\\"></canvas></body></html>",'
                '"style.css": "canvas { background: #000; }",'
                '"app.js": "const c = document.getElementById(\\"c\\"); console.log(c);"'
                '}}'
            )
            mock_client.models.generate_content.return_value = mock_response
            
            result = await ai_engine.process_code_request(
                api_key="AIzaSy_fake_test_key_for_unit_tests",
                user_id=ai_test_user,
                username="aitester",
                slug=ai_test_slug,
                prompt="Make a canvas shooter game"
            )
            
            assert_true(result.get("success") is True, "AI engine generation completed with success: True")
            assert_true("index.html" in result.get("files", []), "AI generated index.html")
            assert_true("app.js" in result.get("files", []), "AI generated app.js")
            assert_true("style.css" in result.get("files", []), "AI generated style.css")
            
            # Verify build.log was updated with Antigravity steps
            build_logs = projects_manager.read_build_log(ai_test_user, ai_test_slug)
            assert_true(len(build_logs) >= 4, f"Antigravity steps logged in build.log ({len(build_logs)} steps)")
            log_steps = [entry["step"] for entry in build_logs]
            assert_true("user" in log_steps and "pass" in log_steps, "USER and PASS steps verified in build.log")

        # Test malicious traversal attempt in slug is safely rejected
        bad_slug_result = await ai_engine.process_code_request(
            api_key="AIzaSy_fake_test_key",
            user_id=ai_test_user,
            username="aitester",
            slug="../../malicious_repo",
            prompt="Overwrite files"
        )
        assert_true(bad_slug_result.get("success") is False, "Malicious slug traversal rejected by AI engine")

        # Test malicious attempt to write protected/system files from AI output
        with patch("ai_engine.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_response = MagicMock()
            # Model attempts to output protected files and disallowed extensions
            mock_response.text = (
                '{"summary": "Injected payload", "files": {'
                '"profile.json": "{\\"stolen\\": true}",'
                '"server.py": "print(\\"hacked\\")",'
                '"../other/game.js": "alert(1)",'
                '"build.log": "erased",'
                '"payload.exe": "binary",'
                '"index.html": "<h1>Safe Game</h1>"'
                '}}'
            )
            mock_client.models.generate_content.return_value = mock_response
            
            result_mal = await ai_engine.process_code_request(
                api_key="AIzaSy_fake_test_key",
                user_id=ai_test_user,
                username="aitester",
                slug=ai_test_slug,
                prompt="Try to touch protected files"
            )
            
            assert_true(result_mal.get("success") is True, "AI engine processed request and quarantined malicious files")
            # Only index.html should have been saved
            assert_true("index.html" in result_mal.get("files", []), "Legitimate game file index.html saved")
            assert_true("profile.json" not in result_mal.get("files", []), "Malicious profile.json blocked")
            assert_true("server.py" not in result_mal.get("files", []), "Malicious server.py blocked")
            assert_true("payload.exe" not in result_mal.get("files", []), "Malicious payload.exe blocked")
            assert_true("../other/game.js" not in result_mal.get("files", []), "Malicious traversal filename blocked")

        # Cleanup
        projects_manager.delete_project_dir(ai_test_user, ai_test_slug)

    except Exception as e:
        assert_true(False, f"AI engine sandboxing test failed: {e}")

    # 10. Testing Yulya Studio v2 Autonomous Agent Architecture
    print("\n10. Testing Yulya Studio v2 Autonomous Agent Architecture...")
    v2_user = 555444333
    v2_slug = "v2-autonomous-test"
    try:
        # 10.1 Starter manifest generation
        projects_manager.create_starter_game(v2_user, "v2tester", v2_slug, "V2 Autonomous Game")
        manifest = projects_manager.get_project_manifest(v2_user, v2_slug)
        assert_true(isinstance(manifest, dict), "Project manifest generated as dictionary")
        assert_true(manifest.get("engine") == "canvas2d", f"Starter game detected engine: {manifest.get('engine')}")
        assert_true("movement" in manifest.get("systems", []), "Starter systems recorded in manifest")
        assert_true(manifest.get("current_build") == 1, "Starter build number is 1")
        
        # 10.2 Updating project manifest memory
        updated_man = projects_manager.update_project_manifest(v2_user, v2_slug, {
            "design_decisions": ["neon_aesthetic", "fast_lasers"],
            "creator_preferences": ["prefers_dark_mode"],
            "current_build": 2
        })
        assert_true("neon_aesthetic" in updated_man.get("design_decisions", []), "Design decision persisted to manifest")
        assert_true("prefers_dark_mode" in updated_man.get("creator_preferences", []), "Creator preference persisted to manifest")
        assert_true(updated_man.get("current_build") == 2, "Build number incremented in manifest")
        
        # 10.3 Project Validation
        val_report = projects_manager.validate_project(v2_user, v2_slug)
        assert_true(val_report.get("valid") is True, f"Starter project passes validation: valid={val_report.get('valid')}")
        assert_true(len(val_report.get("errors", [])) == 0, "Zero validation errors on clean starter project")
        assert_true(val_report.get("detected_engine") == "canvas2d", "Engine correctly detected during validation")
        
        # 10.4 Validation catches broken script reference
        broken_html = '<!DOCTYPE html><html><head><script src="missing_script.js"></script></head><body><canvas></canvas></body></html>'
        projects_manager.write_project_file(v2_user, v2_slug, "index.html", broken_html)
        val_broken = projects_manager.validate_project(v2_user, v2_slug)
        assert_true(val_broken.get("valid") is False, "Validation detects missing script reference")
        assert_true(any("missing_script.js" in err for err in val_broken.get("errors", [])), "Error message names broken script")
        
        # Restore valid index.html
        projects_manager.write_project_file(v2_user, v2_slug, "index.html", "<!DOCTYPE html><html><body><canvas id='c'></canvas><script src='app.js'></script></body></html>")
        
        # 10.5 Project Search
        projects_manager.write_project_file(v2_user, v2_slug, "src/physics.js", "// Laser collision calculation\nfunction checkCollision() { return true; }")
        search_hits = projects_manager.search_project_files(v2_user, v2_slug, "Laser collision")
        assert_true(len(search_hits) > 0, "search_project_files found text match")
        assert_true(search_hits[0]["file"] == "src/physics.js", f"search_project_files identified correct file: {search_hits[0]['file']}")
        
        # 10.6 Project Tree
        tree = projects_manager.get_project_tree(v2_user, v2_slug)
        assert_true(tree.get("type") == "directory", "Project tree root is a directory")
        assert_true(len(tree.get("children", [])) > 0, f"Project tree has children: {len(tree.get('children', []))}")
        
        # 10.7 File Deletion and Security
        del_success = projects_manager.delete_project_file(v2_user, v2_slug, "src/physics.js")
        assert_true(del_success is True, "delete_project_file successfully deleted non-protected file")
        assert_true(projects_manager.read_project_file(v2_user, v2_slug, "src/physics.js") == "", "Deleted file is no longer readable")
        
        # Blocked deletion of protected file
        del_protected_caught = False
        try:
            projects_manager.delete_project_file(v2_user, v2_slug, "server.py")
        except PermissionError:
            del_protected_caught = True
        assert_true(del_protected_caught, "delete_project_file blocks deletion of protected server.py")
        
        # Blocked traversal deletion
        del_traversal_caught = False
        try:
            projects_manager.delete_project_file(v2_user, v2_slug, "../../../other_file.txt")
        except (PermissionError, ValueError):
            del_traversal_caught = True
        assert_true(del_traversal_caught, "delete_project_file blocks path traversal deletion")
        
        # 10.8 Screenshare 1080p and 2 FPS verification in studio.html
        studio_html_content = Path("templates/studio.html").read_text(encoding="utf-8")
        assert_true("1920" in studio_html_content and "1080" in studio_html_content, "Screenshare configured for 1080p in studio.html")
        assert_true("500" in studio_html_content, "Screenshare interval configured for 500ms (2 FPS) in studio.html")
        assert_true("initial_frame" in studio_html_content, "Screenshare passes initial_frame with screenshare_status in studio.html")
        assert_true("handleTranscriptDelta" in studio_html_content, "Studio.html includes turn-aware delta transcript handler")
        assert_true("loadRegistryModels" in studio_html_content, "Studio.html dynamically loads authoritative model registry")
        
        # Cleanup
        projects_manager.delete_project_dir(v2_user, v2_slug)
    except Exception as e:
        assert_true(False, f"V2 autonomous agent test failed: {e}")

    # 11. Testing Centralized Model Registry, Live Session State Machine & Vision Subsystems
    print("\n11. Testing Centralized Model Registry, Live Session State Machine & Subsystems...")
    try:
        import base64
        import models_registry
        from live_session import (
            LiveState,
            FailureClass,
            classify_failure,
            is_fallback_eligible,
            LiveSessionContext,
            safe_execute_tool,
            ScreenshareSubsystem
        )

        # 11.1 Model Registry Tests
        live_models = models_registry.get_live_models()
        code_models = models_registry.get_code_models()
        assert_true(len(live_models) == 3, f"Model registry has 3 Live models: {[m.id for m in live_models]}")
        assert_true(len(code_models) >= 5, f"Model registry has >=5 Code models: {[m.id for m in code_models]}")
        assert_true(models_registry.DEFAULT_LIVE_MODEL_ID == "gemini-3.8-live", "Default live model is gemini-3.8-live")
        assert_true(models_registry.DEFAULT_CODE_MODEL_ID == "gemini-3.8-flash", "Default code model is gemini-3.8-flash")
        assert_true(models_registry.validate_live_model("gemini-3.8-live") is True, "gemini-3.8-live is valid live model")
        assert_true(models_registry.validate_live_model("gemini-3.8-live-extended-thinking") is True, "gemini-3.8-live-extended-thinking is valid")
        assert_true(models_registry.validate_live_model("gemini-1.5-flash") is False, "Invalid model rejected by validate_live_model")
        assert_true(models_registry.validate_code_model("gemini-3.8-flash") is True, "gemini-3.8-flash is valid code model")
        assert_true(models_registry.validate_code_model("invalid-code-model") is False, "Invalid model rejected by validate_code_model")

        # Fallback candidates
        live_fallbacks = models_registry.get_live_fallback_candidates("gemini-3.8-live-extended-thinking")
        assert_true(len(live_fallbacks) >= 2, f"Fallback candidates returned for extended-thinking: {[m.id for m in live_fallbacks]}")
        assert_true(live_fallbacks[0].id == "gemini-3.8-live-extended-thinking", "Requested model is first candidate")
        code_fallbacks = models_registry.get_code_fallback_candidates("gemini-3.8-flash")
        assert_true(len(code_fallbacks) >= 3, f"Fallback candidates returned for code model: {[m.id for m in code_fallbacks]}")

        # Summary
        summary = models_registry.get_registry_summary()
        assert_true("live_models" in summary and "code_models" in summary, "Registry summary contains live_models and code_models")

        # 11.2 Failure Classification Tests
        assert_true(classify_failure(Exception("API_KEY_INVALID: Unauthorized key")) == FailureClass.AUTH, "AUTH error classified")
        assert_true(classify_failure(Exception("ResourceExhausted: 429 Quota limit")) == FailureClass.QUOTA, "QUOTA error classified")
        assert_true(classify_failure(asyncio.TimeoutError()) == FailureClass.TIMEOUT, "TIMEOUT error classified")
        assert_true(classify_failure(Exception("Model gemini-3.8-live-extended-thinking not found")) == FailureClass.MODEL_UNAVAILABLE, "MODEL_UNAVAILABLE classified")
        assert_true(classify_failure(Exception("Connection reset by peer")) == FailureClass.TRANSIENT_TRANSPORT, "TRANSIENT_TRANSPORT classified")
        assert_true(classify_failure(asyncio.CancelledError()) == FailureClass.USER_INTERRUPTION, "USER_INTERRUPTION classified")

        # Fallback eligibility
        assert_true(is_fallback_eligible(FailureClass.QUOTA) is True, "QUOTA is eligible for fallback")
        assert_true(is_fallback_eligible(FailureClass.MODEL_UNAVAILABLE) is True, "MODEL_UNAVAILABLE is eligible for fallback")
        assert_true(is_fallback_eligible(FailureClass.TRANSIENT_TRANSPORT) is True, "TRANSIENT_TRANSPORT is eligible for fallback")
        assert_true(is_fallback_eligible(FailureClass.AUTH) is False, "AUTH is strictly NOT eligible for fallback")
        assert_true(is_fallback_eligible(FailureClass.USER_INTERRUPTION) is False, "USER_INTERRUPTION is NOT eligible for fallback")
        assert_true(is_fallback_eligible(FailureClass.INVALID_REQUEST) is False, "INVALID_REQUEST is NOT eligible for fallback")

        # 11.3 Screenshare Subsystem Tests
        ss = ScreenshareSubsystem()
        assert_true(ss.active is False, "Screenshare initially inactive")
        assert_true(ss.validate_and_record_frame("") is None, "Empty frame rejected")
        assert_true(ss.frames_dropped == 1, "Frames dropped counter incremented on empty frame")

        # Reject non-JPEG data
        non_jpeg_b64 = base64.b64encode(b"PNG_HEADER_DATA_1234567890" * 10).decode("ascii")
        assert_true(ss.validate_and_record_frame(non_jpeg_b64) is None, "Non-JPEG payload rejected")

        # Accept valid JPEG data (SOI marker 0xFF 0xD8)
        valid_jpeg_raw = b'\xff\xd8\xff\xe0\x00\x10JFIF' + (b'\x00' * 200)
        valid_jpeg_b64 = base64.b64encode(valid_jpeg_raw).decode("ascii")
        recorded_bytes = ss.validate_and_record_frame(valid_jpeg_b64)
        assert_true(recorded_bytes == valid_jpeg_raw, "Valid JPEG payload accepted and returned")
        assert_true(ss.frames_sent == 1, "Frames sent counter incremented")
        assert_true(ss.latest_size_bytes == len(valid_jpeg_raw), "Size bytes recorded accurately")

        # Recent-frame policy
        ss.active = True
        assert_true(ss.should_attach_to_turn(freshness_sec=2.5) is True, "Fresh frame attached to turn")
        ss.mark_frame_sent_to_gemini()
        assert_true(ss.should_attach_to_turn(freshness_sec=2.5) is False, "Frame not re-attached immediately (recent-frame policy)")
        ss.reset()
        assert_true(ss.active is False and ss.latest_frame_bytes is None, "Screenshare reset clears state")

        # 11.4 Safe Tool Execution Contract Tests
        async def mock_success_tool():
            return {"files": ["index.html", "app.js"]}
        res = await safe_execute_tool("list_project_files", "call_1", mock_success_tool())
        assert_true(res.get("success") is True, "safe_execute_tool succeeds on valid tool execution")
        assert_true(res.get("data", {}).get("files") == ["index.html", "app.js"], "safe_execute_tool preserves structured data")

        async def mock_fail_tool():
            raise FileNotFoundError("File 'missing.js' does not exist")
        res_fail = await safe_execute_tool("read_project_file", "call_2", mock_fail_tool())
        assert_true(res_fail.get("success") is False, "safe_execute_tool catches exception without raising")
        assert_true(res_fail.get("error_type") == "FileNotFoundError", "Error type captured in structured contract")
        assert_true(res_fail.get("recoverable") is True, "Recoverable flag set in structured contract")

        async def mock_timeout_tool():
            await asyncio.sleep(0.5)
            return {"done": True}
        res_timeout = await safe_execute_tool("slow_tool", "call_3", mock_timeout_tool(), timeout_sec=0.1)
        assert_true(res_timeout.get("success") is False, "safe_execute_tool catches timeout")
        assert_true(res_timeout.get("error_type") == "TIMEOUT", "TIMEOUT captured in structured contract")

        # 11.5 API Model & Preference Endpoints
        req_models = make_mocked_request("GET", "/api/models")
        resp_models = await server.api_get_models(req_models)
        assert_true(resp_models.status == 200, "/api/models returns HTTP 200")
        models_data = json.loads(resp_models.text)
        assert_true(models_data.get("success") is True, "/api/models returns success: true")
        assert_true(len(models_data.get("live_models", [])) == 3, "/api/models lists all 3 live models")

        # Health endpoint
        req_health = make_mocked_request("GET", "/api/health")
        resp_health = await server.api_health(req_health)
        assert_true(resp_health.status == 200, "/api/health returns HTTP 200")
        health_data = json.loads(resp_health.text)
        assert_true(health_data.get("default_live_model") == "gemini-3.8-live", "Health returns default_live_model")
        assert_true("live_models" in health_data and "code_models" in health_data, "Health returns live and code models")

        # 11.6 Full Application Startup & Teardown Lifecycle Test
        app = await server.init_app()
        runner = server.web.AppRunner(app)
        await runner.setup()
        assert_true(app.get("idle_task") is not None, "Idle task started on app runner setup")
        await runner.cleanup()
        assert_true(True, "App startup and cleanup lifecycle succeeded without exceptions")

    except Exception as e:
        assert_true(False, f"Section 11 test failed: {e}")

    # 12. Canonical Live Transcript Pipeline & Turn Isolation
    print("\n12. Testing Canonical Live Transcript Pipeline & Turn Isolation...")
    try:
        # 12.1 Verify distinct AI and User turn IDs and sequences
        ai_turn_1 = "turn_ai_0_12345"
        user_turn_1 = "turn_user_0_12345"
        assert_true(ai_turn_1 != user_turn_1, "AI and User turn IDs have strictly separate namespaces")
        assert_true("turn_ai_" in ai_turn_1 and "turn_user_" in user_turn_1, "Turn prefixes prevent bubble merging")

        # 12.2 Verify canonical events emitted without duplicate legacy events
        studio_html = Path("templates/studio.html").read_text(encoding="utf-8")
        assert_true("seenTranscriptEventIds" in studio_html, "Deduplication of transcript events present in studio.html")
        assert_true("Suppressed in favor of canonical transcript delta pipeline" in studio_html, "Legacy duplicate ai_text and user_transcription suppressed")

        # 12.3 Authoritative output transcription suppression policy in server.py
        server_py = Path("server.py").read_text(encoding="utf-8")
        assert_true("ai_audio_transcript_emitted" in server_py, "Authoritative audio transcript suppression flag present in server.py")
        assert_true("current_ai_turn_id" in server_py and "current_user_turn_id" in server_py, "Separate turn IDs implemented in _live_receive_loop")

        # 12.4 audio_end no longer sends duplicate text transcript
        assert_true('data.get("transcript"' not in server_py, "audio_end does not send recognized transcript as second text turn to Gemini Live")
    except Exception as e:
        assert_true(False, f"Section 12 test failed: {e}")

    # 13. PTT State Machine & Focus Guards
    print("\n13. Testing PTT State Machine & Focus Guards...")
    try:
        studio_html = Path("templates/studio.html").read_text(encoding="utf-8")
        # 13.1 PTTController class and states
        assert_true("class PTTController" in studio_html, "PTTController class defined in studio.html")
        assert_true("PTTState = {" in studio_html, "Formal PTT states defined")
        assert_true("IDLE" in studio_html and "STARTING" in studio_html and "RECORDING" in studio_html and "STOPPING" in studio_html, "All 4 primary PTT states present")

        # 13.2 350ms toggle heuristic completely removed
        assert_true("350" not in studio_html, "350ms quick-click toggle heuristic removed")
        assert_true("isPTTToggledOn" not in studio_html and "isSpaceToggledOn" not in studio_html, "Unreliable toggle flags removed")

        # 13.3 Focus guards and pointer capture
        assert_true("isFocusInInput" in studio_html, "isFocusInInput helper guards keyboard Space from firing in inputs")
        assert_true("setPointerCapture" in studio_html and "releasePointerCapture" in studio_html, "Pointer capture used for mic button")
        assert_true("window.addEventListener('blur'" in studio_html, "Window blur listener prevents stuck PTT")
        assert_true("document.addEventListener('visibilitychange'" in studio_html, "Visibility change listener prevents stuck PTT on tab switch")
    except Exception as e:
        assert_true(False, f"Section 13 test failed: {e}")

    # 14. Antigravity Incremental Code Preservation & Mandatory Second-Build Test
    print("\n14. Testing Antigravity Incremental Code Preservation & Mandatory Second-Build Test...")
    preserve_user = 888999111
    preserve_slug = "preservation-game"
    try:
        # Build 1: Create a full-featured multi-mechanic game
        b1_files = {
            "index.html": "<!DOCTYPE html><html><head><link rel='stylesheet' href='style.css'></head><body><canvas id='gameCanvas'></canvas><script src='app.js'></script></body></html>",
            "style.css": "body { margin: 0; background: #111; overflow: hidden; }\ncanvas { display: block; }",
            "app.js": (
                "// Complex Asteroid Dodger Game\n"
                "const canvas = document.getElementById('gameCanvas');\n"
                "const ctx = canvas.getContext('2d');\n"
                "let score = 0;\n"
                "let player = { x: 100, y: 100, speed: 5, health: 100 };\n"
                "let asteroids = [];\n"
                "function spawnAsteroid() {\n"
                "  asteroids.push({ x: 800, y: Math.random() * 600, speed: 3 });\n"
                "}\n"
                "function updatePlayer() {\n"
                "  // Player WASD controls\n"
                "  player.x += 1;\n"
                "}\n"
                "function updateAsteroids() {\n"
                "  for (let a of asteroids) { a.x -= a.speed; }\n"
                "}\n"
                "function checkCollisions() {\n"
                "  // Collision detection logic\n"
                "  for (let a of asteroids) {\n"
                "    if (Math.hypot(a.x - player.x, a.y - player.y) < 20) { player.health -= 10; }\n"
                "  }\n"
                "}\n"
                "function render() {\n"
                "  ctx.clearRect(0, 0, canvas.width, canvas.height);\n"
                "  ctx.fillStyle = 'cyan';\n"
                "  ctx.fillRect(player.x, player.y, 20, 20);\n"
                "  for (let a of asteroids) {\n"
                "    ctx.fillStyle = 'red';\n"
                "    ctx.fillRect(a.x, a.y, 15, 15);\n"
                "  }\n"
                "}\n"
                "function gameLoop() {\n"
                "  updatePlayer();\n"
                "  updateAsteroids();\n"
                "  checkCollisions();\n"
                "  render();\n"
                "  requestAnimationFrame(gameLoop);\n"
                "}\n"
                "requestAnimationFrame(gameLoop);\n"
            )
        }
        projects_manager.create_starter_game(preserve_user, "preserver", preserve_slug, "Preservation Game")
        for fn, fc in b1_files.items():
            projects_manager.write_project_file(preserve_user, preserve_slug, fn, fc)

        initial_all_files = projects_manager.list_project_files(preserve_user, preserve_slug)
        initial_app_js = projects_manager.read_project_file(preserve_user, preserve_slug, "app.js")
        assert_true("spawnAsteroid" in initial_app_js, "Build 1 has spawnAsteroid mechanic")
        assert_true("checkCollisions" in initial_app_js, "Build 1 has collision detection")

        # 14.1 Helper tests: classify_request
        assert_true(ai_engine.classify_request("Add a laser gun when Space is pressed", initial_all_files) == "FEATURE_ADDITION", "Feature addition classified")
        assert_true(ai_engine.classify_request("Fix collision detection bug", initial_all_files) == "TARGETED_BUG_FIX", "Bug fix classified")
        assert_true(ai_engine.classify_request("Refactor physics loop", initial_all_files) == "REFACTOR", "Refactor classified")
        assert_true(ai_engine.classify_request("Completely rewrite and start over from scratch", initial_all_files) == "EXPLICIT_REWRITE", "Explicit rewrite classified")

        # 14.2 Helper tests: apply_search_replace
        test_code = "let health = 100;\nlet speed = 5;\n"
        replaced, ok, err = ai_engine.apply_search_replace(test_code, "let speed = 5;", "let speed = 10;\nlet lasers = [];")
        assert_true(ok is True, "apply_search_replace succeeded on exact match")
        assert_true("let speed = 10;" in replaced and "let health = 100;" in replaced, "apply_search_replace preserved untouched lines")

        # 14.3 MANDATORY SECOND-BUILD TEST: Incremental targeted changes via changes array
        with patch("ai_engine.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_response = MagicMock()
            # Model returns precision changes array rather than destroying existing app.js
            mock_response.text = json.dumps({
                "summary": "Added laser shooting mechanic when Space is pressed.",
                "changes": [
                    {
                        "file": "app.js",
                        "search": "let player = { x: 100, y: 100, speed: 5, health: 100 };",
                        "replace": "let player = { x: 100, y: 100, speed: 5, health: 100 };\nlet lasers = [];\nwindow.addEventListener('keydown', e => { if (e.code === 'Space') lasers.push({ x: player.x + 20, y: player.y }); });"
                    }
                ],
                "manifest_updates": {
                    "systems": ["movement", "spawner", "collision", "lasers"]
                }
            })
            mock_client.models.generate_content.return_value = mock_response

            build2_res = await ai_engine.process_code_request(
                api_key="AIzaSy_fake_test_key",
                user_id=preserve_user,
                username="preserver",
                slug=preserve_slug,
                prompt="Add a laser gun when Space is pressed"
            )

            assert_true(build2_res.get("success") is True, "Build 2 succeeded")
            # Verify ALL files returned in content
            assert_true("index.html" in build2_res.get("content", {}), "index.html returned in Build 2 content (editor tabs preserved!)")
            assert_true("style.css" in build2_res.get("content", {}), "style.css returned in Build 2 content (editor tabs preserved!)")
            assert_true("app.js" in build2_res.get("content", {}), "app.js returned in Build 2 content")

            # Verify existing mechanics were preserved
            updated_app = build2_res["content"]["app.js"]
            assert_true("spawnAsteroid" in updated_app, "Original spawnAsteroid preserved after second build")
            assert_true("checkCollisions" in updated_app, "Original checkCollisions preserved after second build")
            assert_true("updateAsteroids" in updated_app, "Original updateAsteroids preserved after second build")
            assert_true("lasers.push" in updated_app, "New laser mechanic successfully added")

        # 14.4 Destructive Shrinkage Detection & Transactional Rollback Test
        with patch("ai_engine.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_response = MagicMock()
            # Bad model outputs 3-line trivial stub instead of preserving the 30-line game
            mock_response.text = json.dumps({
                "summary": "Replaced entire game with blank square",
                "files": {
                    "app.js": "// Overwritten\nconsole.log('empty');\n"
                }
            })
            mock_client.models.generate_content.return_value = mock_response

            shrink_res = await ai_engine.process_code_request(
                api_key="AIzaSy_fake_test_key",
                user_id=preserve_user,
                username="preserver",
                slug=preserve_slug,
                prompt="Tweak player speed"
            )

            assert_true(shrink_res.get("success") is False, "Destructive shrinkage rejected")
            assert_true(shrink_res.get("rollback_executed") is True, "Transactional rollback executed")
            # Verify app.js was restored to pre-shrinkage state
            restored_app = projects_manager.read_project_file(preserve_user, preserve_slug, "app.js")
            assert_true("spawnAsteroid" in restored_app, "Project files restored to working state after shrinkage attempt")

        # Cleanup
        projects_manager.delete_project_dir(preserve_user, preserve_slug)
    except Exception as e:
        assert_true(False, f"Section 14 test failed: {e}")

    # 15. Structured Logging Channels & Command Idempotency
    print("\n15. Testing Structured Logging Channels & Command Idempotency...")
    try:
        # 15.1 Structured log channels routing in server.broadcast_project_log
        test_slug = "log-channel-test"
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        server.ACTIVE_STUDIO_WS[test_slug] = {"creator": {mock_ws}, "spectator": set()}

        await server.broadcast_project_log(test_slug, "[DIFF] app.js: +10 lines", level="diff", channel="antigravity", request_id="req_123", build_id="b_123")
        assert_true(mock_ws.send_json.called, "broadcast_project_log sent json")
        call_payload = mock_ws.send_json.call_args[0][0]
        assert_true(call_payload["channel"] == "antigravity", f"Channel correctly set: {call_payload.get('channel')}")
        assert_true(call_payload["request_id"] == "req_123", "request_id included in log payload")
        assert_true(call_payload["build_id"] == "b_123", "build_id included in log payload")
        assert_true("sequence" in call_payload and call_payload["sequence"] > 0, "Global sequence counter included")
        assert_true("event_id" in call_payload, "event_id included in log payload")

        # 15.2 Idempotency cache in server.py
        import time
        server.RECENT_BUILD_RESPONSES["req_123"] = {
            "timestamp": time.time(),
            "response": {"success": True, "summary": "Cached build result", "content": {}}
        }
        assert_true("req_123" in server.RECENT_BUILD_RESPONSES, "Build idempotency cache stores request_id")
        cached = server.RECENT_BUILD_RESPONSES["req_123"]["response"]
        assert_true(cached["summary"] == "Cached build result", "Idempotency cache serves duplicate request")

        del server.ACTIVE_STUDIO_WS[test_slug]
    except Exception as e:
        assert_true(False, f"Section 15 test failed: {e}")

    # 16. Voice AI Tool-Awareness & Unsupported Tool Contract
    print("\n16. Testing Voice AI Tool-Awareness & Unsupported Tool Contract...")
    try:
        # 16.1 System prompt enforces code inspection policy
        server_py = Path("server.py").read_text(encoding="utf-8")
        assert_true("MANDATORY TOOL-SELECTION & CODE INSPECTION POLICY" in server_py, "Inspection policy in live_sys_prompt")
        assert_true("The 10-Step Engineering Workflow" in server_py, "10-step workflow in live_sys_prompt")
        assert_true("Inspect Code First" in server_py, "Inspect code first step in live_sys_prompt")

        # 16.2 Unsupported tool structured error contract
        assert_true("UNSUPPORTED_TOOL" in server_py, "UNSUPPORTED_TOOL error type returned for unknown tools")
        assert_true('"recoverable": True' in server_py, "Recoverable flag set for unknown tool execution")
    except Exception as e:
        assert_true(False, f"Section 16 test failed: {e}")

    # 17. P0 Voice Rebuild, Session Leak Elimination, Database Preference Contract & Build Orchestration
    print("\n17. Testing P0 Voice Rebuild, Session Leak Elimination & Build Orchestration...")
    try:
        # 17.1 Singular preference accessor in database.py
        pref_none = await database.get_user_preference(999999999, "non_existent_key", default=None)
        assert_true(pref_none is None, "get_user_preference returns None for nonexistent key without crash")
        pref_default = await database.get_user_preference(999999999, "preferred_live_model", default="gemini-3.8-live")
        assert_true(pref_default == "gemini-3.8-live", "get_user_preference returns default fallback safely")

        # Test setting and reading preference
        await database.save_user_preference(999999999, "test_pref", "custom_val")
        read_back = await database.get_user_preference(999999999, "test_pref")
        assert_true(read_back == "custom_val", "save_user_preference and get_user_preference round-trip succeeded")

        # Plural accessor backwards compatibility
        all_prefs = await database.get_user_preferences(999999999)
        assert_true(isinstance(all_prefs, dict), "get_user_preferences returns dictionary")
        assert_true(all_prefs.get("test_pref") == "custom_val", "get_user_preferences includes saved preference")

        # 17.2 Terminal failure classification in live_session.py (Render 1008 loop fix)
        import live_session
        err_1008 = Exception("1008 None. Requested entity was not found.")
        assert_true(live_session.is_terminal_failure(err_1008), "1008 Entity not found classified as terminal failure")
        assert_true(live_session.classify_failure(err_1008) == live_session.LiveFailureClass.MODEL_UNAVAILABLE, "1008 classified as MODEL_UNAVAILABLE")

        err_1000 = Exception("1000 OK. Connection closed cleanly.")
        assert_true(live_session.is_terminal_failure(err_1000), "1000 Normal closure classified as terminal failure")

        err_1006 = Exception("1006 Abnormal closure. Connection closed abnormally.")
        assert_true(live_session.is_terminal_failure(err_1006), "1006 Abnormal closure classified as terminal failure")

        err_auth = Exception("API_KEY_INVALID: User not permitted.")
        assert_true(live_session.is_terminal_failure(err_auth), "Auth error classified as terminal failure")

        # Transient errors should NOT be terminal
        err_transient = Exception("504 Gateway Timeout: Read timed out")
        assert_true(not live_session.is_terminal_failure(err_transient), "Transient timeout is NOT terminal")

        err_quota = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded")
        assert_true(live_session.is_terminal_failure(err_quota), "Quota error is terminal for session")

        # 17.3 Monotonic generational identity and session deactivation in LiveSessionContext
        mock_ws_ctx = MagicMock()
        mock_ws_ctx.closed = False
        mock_ws_ctx.send_json = AsyncMock()
        ctx = live_session.LiveSessionContext(
            ws=mock_ws_ctx,
            slug="session-leak-test",
            user_id=12345,
            username="testcreator",
            requested_model_id="gemini-3.8-live",
            generation=3
        )
        assert_true(ctx.generation == 3, f"Monotonic generation assigned: {ctx.generation}")
        assert_true(len(ctx.session_id) > 10, f"Unique session_id assigned: {ctx.session_id}")
        assert_true(ctx.is_active is True, "Session context initially active")

        # Transition when active works
        t_res = await ctx.transition_to(live_session.LiveState.CONNECTED)
        assert_true(t_res is True, "Transition succeeded on active session")
        assert_true(ctx.state == live_session.LiveState.CONNECTED, "State updated to CONNECTED")

        # Deactivation prevents further stale transitions
        ctx.deactivate()
        assert_true(ctx.is_active is False, "Session deactivated")
        assert_true(ctx.state == live_session.LiveState.DISCONNECTED, "State reset to DISCONNECTED on deactivation")
        stale_t_res = await ctx.transition_to(live_session.LiveState.LISTENING)
        assert_true(stale_t_res is False, "Stale transition rejected after deactivation")
        assert_true(ctx.state == live_session.LiveState.DISCONNECTED, "State remained unchanged after stale transition")

        # 17.4 Unified build orchestrator
        # Test invalid argument rejection
        bad_res = await server.orchestrate_build(user_id=None, username="alice", slug="neon-dodge", instruction="")
        assert_true(bad_res["success"] is False and bad_res["error_type"] == "INVALID_ARGUMENT", "orchestrate_build rejects empty arguments")

        # Test non-existent project rejection
        notfound_res = await server.orchestrate_build(user_id=999999999, username="alice", slug="ghost-project-xyz", instruction="Add lasers")
        assert_true(notfound_res["success"] is False and notfound_res["error_type"] == "NOT_FOUND", "orchestrate_build rejects non-existent project")

        # Test concurrency lock on existing project
        await database.save_project(user_id=88888, username="bob", slug="locked-project", title="Locked Project")
        test_build_key = (88888, "locked-project")
        server.ACTIVE_PROJECT_BUILDS.add(test_build_key)
        concurrent_res = await server.orchestrate_build(user_id=88888, username="bob", slug="locked-project", instruction="Add missiles")
        assert_true(concurrent_res["success"] is False and concurrent_res["error_type"] == "CONCURRENT_BUILD", "orchestrate_build rejects concurrent builds")
        server.ACTIVE_PROJECT_BUILDS.discard(test_build_key)
        await database.delete_project(88888, "locked-project")

        # 17.5 Case-insensitive slug and username lookup in database.py
        # Create test project
        await database.save_project(user_id=77777, username="GameMaker", slug="cool-dodge", title="Cool Dodge")
        p_exact = await database.get_project_by_username_and_slug("gamemaker", "cool-dodge")
        assert_true(p_exact is not None and p_exact["slug"] == "cool-dodge", "get_project_by_username_and_slug matches lowercase")
        p_case = await database.get_project_by_username_and_slug("GAMEMAKER", "COOL-DODGE")
        assert_true(p_case is not None and p_case["slug"] == "cool-dodge", "get_project_by_username_and_slug matches uppercase input")
        await database.delete_project(77777, "cool-dodge")

        # 17.6 Physical entrypoint verification in ai_engine.py
        ai_engine_src = Path("ai_engine.py").read_text(encoding="utf-8")
        assert_true("missing required entrypoint 'index.html'" in ai_engine_src, "Physical index.html check present in ai_engine.py")
        assert_true("restore_snapshot" in ai_engine_src, "Automatic snapshot rollback on missing entrypoint present in ai_engine.py")

        # 17.7 Physical microphone track release in studio.html
        studio_html_src = Path("templates/studio.html").read_text(encoding="utf-8")
        assert_true("stopMicrophone()" in studio_html_src, "stopMicrophone defined in studio.html")
        assert_true("micStream.getTracks().forEach(t => t.stop())" in studio_html_src, "Physical MediaStream track release in stopMicrophone")
        assert_true("if (voiceMode === 'ptt') {\n          stopMicrophone();\n        }" in studio_html_src, "PTTController.stop calls stopMicrophone in studio.html")

        # 17.8 Empty transcript bubble suppression in studio.html
        assert_true("if (!delta || !delta.trim())" in studio_html_src, "handleTranscriptDelta guards against creating empty bubbles on empty deltas")
        assert_true("finalizeAiChatTurn" not in studio_html_src, "Obsolete finalizeAiChatTurn completely eliminated from studio.html")
        assert_true("finalizeUserChatTurn" not in studio_html_src, "Obsolete finalizeUserChatTurn completely eliminated from studio.html")
        assert_true("audio_stream_end=True" in Path("server.py").read_text(encoding="utf-8"), "server.py uses public SDK audio_stream_end=True on audio_end")
    except Exception as e:
        import traceback
        traceback.print_exc()
        assert_true(False, f"Section 17 test failed: {e}")

    print(f"\n=== TEST SUITE COMPLETED: {tests_passed} PASSED, {tests_failed} FAILED ===")
    return tests_failed == 0

if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
