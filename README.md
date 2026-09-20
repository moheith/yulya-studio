# Yulya Studio 🎮⚡

AI-powered voice-to-game development studio. Speak games into existence using Gemini 3.8 Live Extended Thinking directly in Discord Voice Channels.

## Features
- **Voice-Driven Creation**: Speak directly in Discord Voice or via Web Push-to-Talk (PTT).
- **1080p Screenshare**: Gemini 3.8 Live inspects game screens in real time.
- **BYOK (Bring Your Own Key)**: Free Google AI Studio Gemini API key support with duplicate protection and live verification.
- **Instant Hot-Reload**: Dual-pane workspace with live code streaming and synchronized game preview.
- **Spectator HUD**: Friends in Discord VC can play the live game and watch the code changes in real time.

## Local Setup
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env with your MONGO_URI and DISCORD credentials

# 3. Start server
python server.py
```

## Render Deployment
- **Runtime**: Python 3
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `python server.py`
- **Port**: Set `PORT` environment variable to `10000` (default on Render)
