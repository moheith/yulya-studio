import os
import json
import asyncio
from google import genai
from google.genai import types
import projects_manager
import database

SYSTEM_PROMPT = """You are Yulya Studio AI — an elite web and game developer.
You build and modify HTML5 Canvas, Web Audio API, WebGL, Phaser, Three.js, and modern CSS games for users.

When asked to create or modify a project:
1. Ensure the code is production-ready, beautiful, responsive, and completely functional.
2. Include engaging gameplay, smooth controls, visual effects, and retro/modern synth styling.
3. Return your output strictly as a valid JSON object containing the updated files:
{
  "summary": "Brief 1-sentence description of the changes made",
  "files": {
    "index.html": "<full html content>",
    "style.css": "<full css content>",
    "app.js": "<full javascript content>"
  }
}
Do NOT include markdown backticks around the JSON. Only output valid parseable JSON.
"""

async def process_code_request(api_key: str, user_id: int, username: str, slug: str, prompt: str) -> dict:
    """
    Executes an AI code creation or modification request using the user's personal Gemini API key.
    """
    cleaned_key = api_key.strip()
    
    # Read existing files if any
    current_html = projects_manager.read_project_file(user_id, slug, "index.html")
    current_css = projects_manager.read_project_file(user_id, slug, "style.css")
    current_js = projects_manager.read_project_file(user_id, slug, "app.js")
    
    context_payload = {
        "user_request": prompt,
        "existing_code": {
            "index.html": current_html,
            "style.css": current_css,
            "app.js": current_js
        }
    }
    
    def _call_gemini():
        client = genai.Client(api_key=cleaned_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=json.dumps(context_payload),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.4
            )
        )
        return response.text
        
    raw_response = await asyncio.to_thread(_call_gemini)
    
    try:
        data = json.loads(raw_response)
        summary = data.get("summary", "Updated project files.")
        files = data.get("files", {})
        
        saved_files = []
        for fname, content in files.items():
            if fname in ["index.html", "style.css", "app.js"] and content:
                projects_manager.write_project_file(user_id, slug, fname, content)
                saved_files.append(fname)
                
        # Update database record
        await database.save_project(
            user_id=user_id,
            username=username,
            slug=slug,
            title=slug.replace("-", " ").title(),
            description=summary,
            files=saved_files
        )
        
        return {
            "success": True,
            "summary": summary,
            "files": saved_files,
            "content": {f: projects_manager.read_project_file(user_id, slug, f) for f in saved_files}
        }
    except Exception as e:
        print(f"[AI_ENGINE] Error parsing AI response: {e}\nRaw output: {raw_response[:300]}")
        return {
            "success": False,
            "error": f"Failed to parse generated code: {str(e)}"
        }
