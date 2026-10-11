import time
from playwright.sync_api import sync_playwright

def run_browser_verification():
    print("[E2E BROWSER] Starting Playwright E2E browser verification...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context.add_cookies([{
            "name": "yulya_studio_session",
            "value": "test_e2e_token_12345",
            "domain": "localhost",
            "path": "/"
        }])
        page = context.new_page()

        # 1. Verify Public Arcade
        print("[TEST 1] Visiting Public Arcade (http://localhost:10001/)...")
        page.goto("http://localhost:10001/", wait_until="networkidle")
        assert "Yulya" in page.title(), f"Unexpected title on arcade: {page.title()}"
        game_cards = page.locator(".game-card")
        print(f"  Found {game_cards.count()} game card(s)")
        assert game_cards.count() >= 1, "Expected at least 1 game card on arcade"
        assert "Neon Dodge" in page.content(), "Expected 'Neon Dodge' in arcade page"
        print("  [PASS] Public arcade rendered correctly.")

        # 2. Verify Studio Workspace
        print("[TEST 2] Visiting Studio Workspace (http://localhost:10001/studio?slug=neon-dodge&token=test_e2e_token_12345)...")
        page.goto("http://localhost:10001/studio?slug=neon-dodge&token=test_e2e_token_12345", wait_until="networkidle")
        page.wait_for_timeout(2000)

        title = page.title()
        print(f"  Workspace title: {title}")
        assert "Workspace" in title or "Studio" in title, f"Unexpected workspace title: {title}"

        # Check project title
        project_title = page.locator("#currentProjectTitle, .project-name, #projectTitle").first
        if project_title.count() > 0:
            print(f"  Project title text: {project_title.inner_text()}")

        # Check preview iframe and security sandbox attribute
        iframe = page.locator("#gamePreview, #previewFrame, iframe").first
        assert iframe.count() > 0, "Preview iframe missing in Studio"
        sandbox_attr = iframe.get_attribute("sandbox")
        print(f"  Iframe sandbox attribute: '{sandbox_attr}'")
        assert sandbox_attr is not None and "allow-scripts" in sandbox_attr, f"Invalid sandbox: {sandbox_attr}"
        assert "allow-same-origin" not in sandbox_attr, "Security failure: allow-same-origin must NOT be present!"
        print("  [PASS] Sandbox security check passed.")

        # Check file tabs
        file_tabs = page.locator("#dynamicFileTabs button[data-file]")
        print(f"  File tabs found: {file_tabs.count()}")
        assert file_tabs.count() >= 3, "Expected at least 3 file tabs (index.html, style.css, app.js)"
        
        # Click on app.js tab and verify editor displays code
        app_tab = page.locator("#dynamicFileTabs button[data-file='app.js']").first
        app_tab.click()
        page.wait_for_timeout(500)
        code_view = page.locator("#codeDisplay, #codeEditorView").first
        assert code_view.count() > 0, "Code view element missing"
        print(f"  Code view content length: {len(code_view.inner_text())}")
        print("  [PASS] File tab switching and code view verified.")

        # Check Terminal Activity Feed
        terminal = page.locator("#terminalFeed, #terminal, .terminal-logs").first
        assert terminal.count() > 0, "Terminal feed missing"
        print("  [PASS] Terminal feed present.")

        # Check PTT Button and Command input
        ptt_btn = page.locator("#pttBtn, .btn-ptt, button:has-text('Space')").first
        assert ptt_btn.count() > 0, "PTT button missing in Studio"
        print(f"  PTT button label: {ptt_btn.inner_text().strip()}")

        cmd_input = page.locator("#commandInput, #promptInput, input[type='text'], textarea").first
        assert cmd_input.count() > 0, "Command input missing"
        print("  [PASS] Command input and PTT button present.")

        # 3. Verify Direct Game URL and Canvas
        print("[TEST 3] Visiting Direct Game URL (http://localhost:10001/tester/neon-dodge/)...")
        page.goto("http://localhost:10001/tester/neon-dodge/", wait_until="networkidle")
        canvas = page.locator("#gameCanvas, canvas")
        assert canvas.count() > 0, "Game canvas missing in playable game view"
        start_btn = page.locator("#startBtn")
        assert start_btn.count() > 0, "Start game button missing in Neon Dodge"
        print("  [PASS] Playable game loaded with valid canvas and start button.")

        # 4. Verify User Profile Portfolio
        print("[TEST 4] Visiting User Profile Portfolio (http://localhost:10001/tester)...")
        page.goto("http://localhost:10001/tester", wait_until="networkidle")
        assert "tester" in page.content().lower(), "Username 'tester' not found on profile"
        print("  [PASS] User profile portfolio rendered correctly.")

        browser.close()
        print("\n[ALL BROWSER E2E TESTS PASSED SUCCESSFULLY!]")

if __name__ == "__main__":
    run_browser_verification()
