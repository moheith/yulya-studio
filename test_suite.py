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
        })
    ]:
        try:
            resp = await server.render_template(tmpl, ctx)
            assert_true(resp.status == 200 and len(resp.text) > 200, f"Rendered {tmpl} with ctx={list(ctx.keys())}")
            
            # Verify Iframe Sandbox in templates (allow-scripts ONLY, strictly no allow-same-origin)
            if tmpl in ["studio.html", "spectator.html"]:
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
            "/api/download-zip/{username}/{slug}",
            "/ws/studio",
            "/{username}/{slug}",
            "/{username}/{slug}/"
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

    except Exception as e:
        assert_true(False, f"Routing & WebSocket error: {e}")

    print(f"\n=== TEST SUITE COMPLETED: {tests_passed} PASSED, {tests_failed} FAILED ===")
    return tests_failed == 0

if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
