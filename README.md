# Yulya Studio

Yulya Studio is an open, browser-native web game development engine and community arcade. It enables creators to design, iterate, and publish playable HTML5 Canvas games using conversational voice, multimodal vision, and real-time code synthesis directly inside their web browser.

The platform requires no local installation, compiler toolchains, or paid API subscriptions. Creators bring their own free Google AI Studio API key, and Yulya Studio orchestrates two cooperating tiers of AI models to translate spoken instructions into verified, sandboxed web applications.

---

## Architectural Overview

Yulya Studio splits artificial intelligence operations into two distinct, decoupled execution tiers:

```
+-------------------------------------------------------------------------+
|                              CREATOR BROWSER                            |
|  [Microphone 16kHz PCM]   [Screenshare 720p 1FPS]   [Web Audio 24kHz]   |
+-------------------+--------------------+--------------------+-----------+
                    |                    |                    ^
                    | Binary WebSocket   | Base64 Frames      | Audio Stream
                    v                    v                    |
+-------------------------------------------------------------------------+
|                        YULYA STUDIO BACKEND SERVER                      |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  |             TIER 1: GEMINI 3.8 LIVE MULTIMODAL ARCHITECT           |  |
|  |  - Bidirectional duplex streaming via google-genai live connect   |  |
|  |  - Immediate context: index.html, style.css, app.js repository    |  |
|  |  - Visual frame inspection of canvas gameplay and UI layout      |  |
|  |  - Conversational voice generation (24kHz PCM returned to user)   |  |
|  |  - Tool call dispatch: modify_game_code(instruction)              |  |
|  +-----------------------------------+-------------------------------+  |
|                                      |                                  |
|                                      v Tool Trigger                     |
|  +-------------------------------------------------------------------+  |
|  |             TIER 2: ANTIGRAVITY WATERFALL CODING ENGINE            |  |
|  |  - Google Search Grounding for modern HTML5 Canvas & Web APIs     |  |
|  |  - Multi-model fallback cascade (absorbs free-tier 20 RPD caps):  |  |
|  |      1. gemini-3.8-flash      (Primary 20 RPD)                    |  |
|  |      2. gemini-3.7-flash      (Fallback 1 20 RPD)                 |  |
|  |      3. gemini-3.6-flash      (Fallback 2 20 RPD)                 |  |
|  |      4. gemini-3.5-flash      (Fallback 3 20 RPD)                 |  |
|  |      5. gemini-3.5-flash-lite (Fallback 4 500 RPD)                |  |
|  |      6. gemini-3.1-flash-lite (Fallback 5 500 RPD)                |  |
|  |  - Formatted terminal steps: [THINKING], [SEARCH], [READ_FILE],   |  |
|  |    [REPLACE_CONTENT], [PASS], [FAIL]                              |  |
|  |  - Atomic write to data/projects/{user_id}/{slug}/ + build.log    |  |
|  +-----------------------------------+-------------------------------+  |
+--------------------------------------|----------------------------------+
                                       | Hot-Reload Update
                                       v
+-------------------------------------------------------------------------+
|                           BROWSER GAME PREVIEW                          |
|  <iframe sandbox="allow-scripts" src="/{username}/{slug}/"></iframe>    |
+-------------------------------------------------------------------------+
```

### Tier 1: Multimodal Live Architect
- **Model**: `Gemini 3.8 Live Extended Thinking (High)` (powered by Google GenAI Live WebSocket API).
- **Audio Capture**: In-browser Web Audio API captures microphone input, resamples to single-channel 16 kHz signed 16-bit PCM, and streams chunks over the studio WebSocket.
- **Audio Playback**: The client runs a custom gapless PCM audio player at 24 kHz, playing Gemini Live voice responses directly through browser speakers without external voice chat dependencies.
- **Vision Feed**: An optional 1 frame-per-second 720p screenshare feed streams JPEG snapshots of the canvas directly to the live session, allowing the model to spot visual alignment errors, collision bugs, and animation glitches.
- **Orchestration**: When a modification is requested, Gemini Live formulates an explicit engineering specification and calls the backend tool `modify_game_code`.

### Tier 2: Antigravity Waterfall Coding Engine
- **Search Grounding**: Queries Google Search Grounding to reference modern HTML5 Canvas APIs, game math, easing functions, and browser event patterns.
- **Resilient Waterfall**: Free-tier Gemini keys provide 20 requests per day on primary flash models. If a rate limit (HTTP 429) or quota threshold is encountered, the engine automatically cascades through six tiers down to high-capacity lite models (500 RPD) without terminating the user session.
- **Antigravity CLI Activity**: Every build action is formatted and logged sequentially (`[USER]`, `[ARCHITECT]`, `[THINKING]`, `[SEARCH]`, `[READ_FILE]`, `[REPLACE_CONTENT]`, `[PASS]`, `[FAIL]`), streaming live to the in-browser terminal and persisting to `data/projects/{user_id}/{slug}/build.log`.

---

## Repository & URL Routing Model

Yulya Studio organizes projects similarly to GitHub repositories. Game assets remain physically stored as plain files on the server disk, isolated from database records and other users.

| Route Pattern | Access Level | Description |
| :--- | :--- | :--- |
| `project.yulya.me/` | Public | Main landing hub displaying community-created games and active creators. |
| `project.yulya.me/{username}` | Public | User portfolio showing profile metadata and all games published by that creator. |
| `project.yulya.me/{username}/{slug}` | Public | Direct game player hosting the sandboxed HTML5 Canvas application. |
| `project.yulya.me/{username}/{slug}/studio` | Authenticated Owner | Dual-pane development workspace (Code/Terminal on left, Live Sandbox on right). |
| `project.yulya.me/studio?slug={slug}` | Authenticated Owner | Direct query routing to the active creator IDE for that project slug. |
| `project.yulya.me/spectate/{token}` | Public Spectator | Read-only spectator stream displaying real-time code changes and screenshares. |

### Disk Isolation
Each repository is stored under:
```
data/projects/{user_id}/{slug}/
├── index.html        # HTML5 entrypoint
├── style.css         # Styling and canvas viewport rules
├── app.js            # Game loop, state machines, input listeners
└── build.log         # Antigravity CLI activity history
```
No database entries contain code; MongoDB exclusively stores public profile metadata (`user_id`, `login_id`, `profile_name`, `display_name`, `avatar`, and `created_games` arrays).

---

## Free Access & Bring-Your-Own-Key (BYOK) Guide

Yulya Studio does not charge subscriptions or token markups. All generative tasks run through the user's personal Google AI Studio API key.

### 1. Obtaining a Free Google AI Studio API Key
1. Visit [aistudio.google.com](https://aistudio.google.com/) and sign in with any standard Google account.
2. Click **Get API Key** in the left navigation menu.
3. Click **Create API Key** and select **Create key in new project**.
4. Copy the generated API key (format: `AIzaSy...`).

### 2. Rate Limits & Free Quotas
Google AI Studio provides generous free-tier allowances:
- **Primary Flash Models**: 20 requests per day (RPD), 15 requests per minute (RPM).
- **Flash-Lite Models**: 500 requests per day (RPD), 30 requests per minute (RPM).
- **Multimodal Live**: Real-time bidirectional streaming session support.

Because Yulya Studio implements a 6-stage waterfall fallback, if a creator reaches their 20 RPD cap on `gemini-3.8-flash`, the engine automatically steps down to `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`, and finally to high-volume `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite` (500 RPD). This ensures uninterrupted prototyping.

### 3. Key Storage & Privacy
- Keys are saved via an authenticated POST request to `/api/save-key`.
- The key is validated against Google AI Studio with a test ping.
- Keys are stored securely in MongoDB associated with the creator's Discord user ID.
- Keys are never rendered in client HTML, never written to git, and never shared with spectators or other users.

---

## Security & Sandboxing Specification

### File System Sandboxing
The backend enforces path validation on all file reads and writes:
- **Path Traversal Defense**: All slugs and filenames are stripped of `..`, `/`, `\`, null bytes, and control characters. Slugs are constrained to `^[a-zA-Z0-9_-]+$`.
- **Protected File Shield**: AI generation and API endpoints are blocked from touching internal files (`profile.json`, `user.json`, `server.py`, `config.py`, `database.py`, `ai_engine.py`, `build.log`, `.env`).
- **File Extension Lockdown**: Only standard web assets (`.html`, `.css`, `.js`, `.json`, `.svg`, `.txt`, `.csv`) may be created. Executable extensions (`.py`, `.sh`, `.bat`, `.exe`, `.cmd`) are rejected with 403 Forbidden.
- **Cross-Repository Isolation**: User directory boundaries (`data/projects/{user_id}/`) are resolved to canonical absolute paths. Symlinks and parent directory traversals are rejected.

### Client-Side Iframe Isolation
The live game preview iframe is strictly sandboxed:
```html
<iframe id="gameIframe" class="preview-iframe" sandbox="allow-scripts" src="/{username}/{slug}/"></iframe>
```
- `allow-scripts` is granted so the HTML5 Canvas game loop can execute.
- `allow-same-origin` is strictly omitted. The game running in the iframe cannot access the parent window's DOM, local storage, session cookies, or WebSocket connection.

### WebSocket Session Lifecycle
- **Authentication**: WebSocket links on `/ws/studio?slug={slug}` require authentication. Only the verified project owner may transmit creator commands and audio chunks; all other connections are relegated to spectator status.
- **Auto-Disconnect on Unload**: When a creator closes the studio browser tab or navigates away, `beforeunload` and `pagehide` listeners immediately transmit a `disconnect_live` payload and close the socket. The server cancels background live tasks and cleanly shuts down the Gemini Live session.

---

## Workspace Controls & Shortcuts

| Control | Action | Details |
| :--- | :--- | :--- |
| `Spacebar` (Hold) | Push-to-Talk (PTT) | Captures 16kHz PCM audio from microphone; streams live to Gemini Live. |
| `Voice Mode` Dropdown | Switch Voice Mode | Toggle between Push-to-Talk and Continuous Voice ("Always On"). |
| `Connect Live AI` Button | Live Session Toggle | Manually initiate or cleanly terminate Gemini 3.8 Live duplex session. |
| `Screenshare` Button | Multimodal Vision | Streams 720p 1 FPS video frames to Gemini Live for canvas inspection. |
| `Ctrl + K` or `Cmd + K` | Command Palette | Quick switcher for project switching, ZIP exports, and terminal views. |
| `Up / Down Arrows` | Input History | Navigate through previously sent text modification prompts. |
| `Terminal` / File Tabs | Code Viewer | Inspect live `index.html`, `style.css`, and `app.js` with syntax formatting. |
| `Restart` Button | Preview Reload | Hot-reloads the sandboxed game iframe without refreshing the IDE. |

---

## Local Development & Deployment

### Prerequisites
- Python 3.10+
- MongoDB 6.0+ (local instance or MongoDB Atlas cluster)
- Discord Developer Application credentials (for OAuth authentication)

### 1. Installation
```bash
git clone https://github.com/moheith/yulya-studio.git
cd yulya-studio

# Create and activate virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration
Create a `.env` file in the root directory:
```ini
# Server
PORT=8000
BASE_URL=http://localhost:8000
COOKIE_SECURE=false

# Database
MONGO_URI=mongodb://localhost:27017/yulya_studio

# Discord OAuth
DISCORD_CLIENT_ID=your_discord_client_id
DISCORD_CLIENT_SECRET=your_discord_client_secret
DISCORD_OAUTH_URL=https://discord.com/api/oauth2/authorize?client_id=YOUR_ID&redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fauth%2Fcallback&response_type=code&scope=identify
```

### 3. Run Server
```bash
python server.py
```
Visit `http://localhost:8000` to open the studio.

### 4. Running the Test Suite
The repository includes a standalone test suite covering template security, path isolation, rate limiting, and AI engine sandboxing:
```bash
python test_suite.py
```

### 5. Production Deployment (Render)
- **Environment**: Python 3
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python server.py`
- **Environment Variables**:
  - `PORT`: `10000`
  - `BASE_URL`: `https://project.yulya.me`
  - `COOKIE_SECURE`: `true`
  - `MONGO_URI`: `mongodb+srv://...`
  - `DISCORD_CLIENT_ID`: `...`
  - `DISCORD_CLIENT_SECRET`: `...`
  - `DISCORD_OAUTH_URL`: `https://discord.com/api/oauth2/authorize?...`

---

## License

All Rights Reserved. Copyright (c) 2026 Mohieth and the Yulya Development Team.
