import os
import sys
import time
import threading
import asyncio
from pathlib import Path
from aiohttp import web
from playwright.sync_api import sync_playwright

import config
import database
import server
import projects_manager
from test_suite import MockCollection

def start_isolated_test_server(ready_event, stop_event):
    """Spins up an isolated in-memory test server on port 10001 without touching production MongoDB."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    mock_users = MockCollection()
    mock_profiles = MockCollection()
    mock_projects = MockCollection()
    mock_sessions = MockCollection()
    mock_signals = MockCollection()

    database.users_col = mock_users
    database.profiles_col = mock_profiles
    database.projects_col = mock_projects
    database.sessions_col = mock_sessions
    database.signals_col = mock_signals

    now = time.time()
    # Seed isolated test user with studio_api_key
    loop.run_until_complete(mock_users.insert_one({
        "user_id": 999999999,
        "username": "tester",
        "studio_api_key": "AIzaSy_fake_test_key_for_mock_e2e",
        "studio_terms_accepted": True,
        "created_at": now
    }))

    # Seed isolated test session
    loop.run_until_complete(mock_sessions.insert_one({
        "token": "test_e2e_token_12345",
        "user": {"id": 999999999, "username": "tester", "avatar": None},
        "created_at": now
    }))

    # Seed isolated test profile
    loop.run_until_complete(mock_profiles.insert_one({
        "user_id": 999999999,
        "login_id": "tester",
        "username": "tester",
        "display_name": "Tester",
        "profile_name": "Tester",
        "avatar": None,
        "created_games": [{
            "slug": "neon-dodge",
            "title": "Neon Dodge",
            "description": "Retro dodging game",
            "tags": ["arcade", "canvas"]
        }],
        "game_names": ["Neon Dodge"],
        "created_at": now,
        "updated_at": now
    }))

    # Seed isolated test project
    loop.run_until_complete(mock_projects.insert_one({
        "user_id": 999999999,
        "username": "tester",
        "slug": "neon-dodge",
        "title": "Neon Dodge",
        "description": "Retro dodging game",
        "tags": ["arcade", "canvas"],
        "is_public": True,
        "created_at": now,
        "updated_at": now
    }))

    projects_manager.create_starter_game(999999999, "tester", "neon-dodge", "Neon Dodge")

    app = loop.run_until_complete(server.init_app(init_database=False))
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "127.0.0.1", 10001)
    loop.run_until_complete(site.start())

    ready_event.set()

    while not stop_event.is_set():
        loop.run_until_complete(asyncio.sleep(0.2))

    loop.run_until_complete(runner.cleanup())
    projects_manager.delete_project_dir(999999999, "neon-dodge")

def run_browser_verification():
    print("[E2E BROWSER] Starting Playwright E2E browser verification...")
    server_ready = threading.Event()
    server_stop = threading.Event()
    server_thread = threading.Thread(target=start_isolated_test_server, args=(server_ready, server_stop), daemon=True)
    server_thread.start()

    if not server_ready.wait(timeout=10.0):
        raise RuntimeError("Failed to start isolated test server on port 10001")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_cookies([{
                "name": "yulya_studio_session",
                "value": "test_e2e_token_12345",
                "domain": "127.0.0.1",
                "path": "/"
            }])
            page = context.new_page()

            # 1. Verify Public Arcade
            print("[TEST 1] Visiting Public Arcade (http://127.0.0.1:10001/)...")
            page.goto("http://127.0.0.1:10001/", wait_until="networkidle")
            assert "Yulya" in page.title(), f"Unexpected title on arcade: {page.title()}"
            game_cards = page.locator(".game-card")
            print(f"  Found {game_cards.count()} game card(s)")
            assert game_cards.count() >= 1, "Expected at least 1 game card on arcade"
            assert "Neon Dodge" in page.content(), "Expected 'Neon Dodge' in arcade page"
            print("  [PASS] Public arcade rendered correctly.")

            # 2. Verify Studio Workspace (Authoritative Cookie Auth, NO query parameter workaround)
            print("[TEST 2] Visiting Studio Workspace (http://127.0.0.1:10001/studio?slug=neon-dodge)...")
            page.goto("http://127.0.0.1:10001/studio?slug=neon-dodge", wait_until="networkidle")
            page.wait_for_timeout(1500)

            title = page.title()
            print(f"  Workspace title: {title}")
            assert "Workspace" in title or "Studio" in title, f"Unexpected workspace title: {title}"

            # Check preview iframe and security sandbox attribute
            iframe = page.locator("#gamePreview, #previewFrame, iframe").first
            assert iframe.count() > 0, "Preview iframe missing in Studio"
            sandbox_attr = iframe.get_attribute("sandbox")
            print(f"  Iframe sandbox attribute: '{sandbox_attr}'")
            assert sandbox_attr is not None and "allow-scripts" in sandbox_attr, f"Invalid sandbox: {sandbox_attr}"
            assert "allow-same-origin" not in sandbox_attr, "Security failure: allow-same-origin must NOT be present!"
            print("  [PASS] Sandbox security check passed.")

            # Check file tabs and editor
            file_tabs = page.locator("#dynamicFileTabs button[data-file]")
            assert file_tabs.count() >= 3, "Expected at least 3 file tabs (index.html, style.css, app.js)"
            app_tab = page.locator("#dynamicFileTabs button[data-file='app.js']").first
            app_tab.click()
            page.wait_for_timeout(300)
            code_view = page.locator("#codeDisplay, #codeEditorView").first
            assert code_view.count() > 0 and len(code_view.inner_text()) > 0, "Code view content missing"
            print("  [PASS] File tab switching and code view verified.")

            # Check Microphone hardware is NOT active in PTT idle mode (P0 Microphone Contract)
            mic_is_null = page.evaluate("() => micStream === null")
            assert mic_is_null is True, "Microphone stream must be null in PTT idle mode (not actively recording)!"
            print("  [PASS] Microphone hardware is completely inactive in PTT idle mode.")

            # Check Live AI button initial state
            live_btn_label = page.locator("#liveBtnLabel").inner_text().strip()
            print(f"  Live button label: '{live_btn_label}'")
            assert "Connect" in live_btn_label, "Live button must be in 'Connect Live AI' state initially"

            # Check Typed Command Routing to Antigravity without polluting Voice Chat
            page.locator("#tabAntigravity").click()
            page.wait_for_timeout(300)
            cmd_input = page.locator("#commandInput")
            assert cmd_input.count() > 0, "Command input missing"
            cmd_input.fill("Add score tracking mechanic")
            send_btn = page.locator("#sendBtn")
            send_btn.click()
            page.wait_for_timeout(500)

            # Voice chat messages must NOT contain typed Antigravity command
            chat_has_command = page.evaluate("() => { const el = document.getElementById('chatFeed') || document.getElementById('chatMessages'); return el ? el.textContent.includes('Add score tracking mechanic') : false; }")
            assert chat_has_command is False, "Typed command must NOT pollute Voice Chat feed!"
            print("  [PASS] Typed Antigravity command cleanly routed without polluting Voice Chat.")

            # 3. Verify Direct Game URL and Canvas
            print("[TEST 3] Visiting Direct Game URL (http://127.0.0.1:10001/tester/neon-dodge/)...")
            page.goto("http://127.0.0.1:10001/tester/neon-dodge/", wait_until="networkidle")
            canvas = page.locator("#gameCanvas, canvas")
            assert canvas.count() > 0, "Game canvas missing in playable game view"
            print("  [PASS] Playable game loaded with valid canvas.")

            # 4. Verify User Profile Portfolio
            print("[TEST 4] Visiting User Profile Portfolio (http://127.0.0.1:10001/tester)...")
            page.goto("http://127.0.0.1:10001/tester", wait_until="networkidle")
            assert "tester" in page.content().lower(), "Username 'tester' not found on profile"
            print("  [PASS] User profile portfolio rendered correctly.")

            browser.close()
            print("\n[ALL BROWSER E2E TESTS PASSED SUCCESSFULLY!]")
    finally:
        server_stop.set()

if __name__ == "__main__":
    run_browser_verification()
