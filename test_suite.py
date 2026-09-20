"""
Comprehensive Verification Test Suite for Yulya Studio
"""
import os
import sys
import asyncio
import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

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
            "active_project": {"slug": "neon-dodge", "title": "Neon Dodge"},
            "spectator_token": "test-token"
        }),
        ("spectator.html", {
            "author": "carol",
            "slug": "neon-dodge",
            "title": "Neon Dodge",
            "spectator_token": "test-token"
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
            if tmpl in ["studio.html", "spectator.html", "profile.html"]:
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
            elif tmpl == "spectator.html":
                assert_true('id="codeEditorWrap"' in resp.text, "Code viewer wrapper exists in spectator.html")
                assert_true('tabApp' in resp.text and 'tabIndex' in resp.text, "File tabs exist in spectator.html")
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

        # Test WebSocket rejection for unauthorized spectator with invalid slug/token
        req_bad_ws = make_mocked_request(
            "GET",
            "/ws/studio?slug=nonexistent-game-xyz-999&token=bogus_token&role=spectator",
            headers={"Upgrade": "websocket", "Connection": "Upgrade"},
            app=app
        )
        ws_res = await server.handle_ws_studio(req_bad_ws)
        assert_true(isinstance(ws_res, server.web.Response) and ws_res.status == 401, "Rejected invalid spectator WebSocket connection with 401")

        # Test user slug studio redirect
        req_studio = make_mocked_request("GET", "/moheith/neon-dodge/studio", match_info={"username": "moheith", "slug": "neon-dodge"}, app=app)
        try:
            res_studio = await server.handle_user_slug_studio(req_studio)
            # When not logged in, redirects to login
            assert_true(res_studio.status in [302, 303, 401] or isinstance(res_studio, server.web.HTTPFound), "Studio direct route redirects unauthenticated user safely")
        except server.web.HTTPFound:
            assert_true(True, "Studio direct route redirects unauthenticated user safely")

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
            "sub/file.js"
        ]
        for bad_fn in bad_filenames:
            caught = False
            try:
                projects_manager.write_project_file(isolation_user_id, game_a, bad_fn, "evil")
            except (PermissionError, ValueError):
                caught = True
            assert_true(caught, f"Filename traversal blocked: {bad_fn}")

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

    print(f"\n=== TEST SUITE COMPLETED: {tests_passed} PASSED, {tests_failed} FAILED ===")
    return tests_failed == 0

if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
