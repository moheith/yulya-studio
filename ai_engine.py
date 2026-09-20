import os
import json
import asyncio
from google import genai
from google.genai import types
from google.genai.errors import APIError
import projects_manager
import database

# Per-project lock dictionary: (user_id, slug) -> asyncio.Lock() (Section 83)
PROJECT_LOCKS = {}

def get_project_lock(user_id: int, slug: str) -> asyncio.Lock:
    key = (int(user_id), slug.lower())
    if key not in PROJECT_LOCKS:
        PROJECT_LOCKS[key] = asyncio.Lock()
    return PROJECT_LOCKS[key]

SYSTEM_PROMPT = """You are Yulya Studio Code Engine.
You generate and modify HTML5 Canvas web games.

Rules:
1. Output valid JSON.
2. Return:
{
    "summary": "Brief 1-sentence summary of the update",
    "files": {
        "index.html": "<complete html file>",
        "style.css": "<complete css file>",
        "app.js": "<complete javascript file>"
    }
}
3. Return complete files. Never return partial diffs or placeholders.
4. Games must be responsive and centered in the window.
5. Games must be playable with keyboard and mouse/touch.
6. Prefer HTML5 Canvas and vanilla JavaScript.
7. Avoid unnecessary external libraries; everything should run self-contained.
8. Include clean error handling, scoring, restart mechanism, and clear game loop.
9. If a request is unclear, make an engaging and polished creative interpretation.
10. When modifying or fixing an issue, inspect the existing code carefully and preserve working mechanics while applying the requested changes.
11. Do NOT wrap output in markdown codeblocks. Output strictly valid parseable JSON.
"""

def truncate_context(content: str, max_chars: int = 20000) -> str:
    """Limits code context sent to Gemini to avoid runaway token explosion (Section 84)."""
    if len(content) <= max_chars:
        return content
    # Keep beginning and end of file if overly large
    half = max_chars // 2
    return content[:half] + "\n/* ... [context truncated for length] ... */\n" + content[-half:]

async def process_code_request(api_key: str, user_id: int, username: str, slug: str, prompt: str) -> dict:
    """
    Executes an AI code creation or modification request using the user's personal Gemini API key.
    Uses per-project locks and robust error handling.
    """
    lock = get_project_lock(user_id, slug)
    if lock.locked():
        # Someone is already generating for this project
        pass

    async with lock:
        cleaned_key = api_key.strip()
        
        # Read existing files (truncated to 20 KB to prevent token explosion)
        current_html = truncate_context(projects_manager.read_project_file(user_id, slug, "index.html"))
        current_css = truncate_context(projects_manager.read_project_file(user_id, slug, "style.css"))
        current_js = truncate_context(projects_manager.read_project_file(user_id, slug, "app.js"))
        
        context_payload = {
            "user_request": prompt,
            "project_name": slug,
            "creator": username,
            "existing_code": {
                "index.html": current_html,
                "style.css": current_css,
                "app.js": current_js
            }
        }
        
        def _call_gemini():
            client = genai.Client(api_key=cleaned_key)
            last_err = None
            # Multi-model waterfall to absorb free-tier 20 RPD caps:
            # 1. gemini-3.6-flash (20 RPD) -> primary
            # 2. gemini-3.8-flash (20 RPD) -> fallback 1
            # 3. gemini-3.1-flash-lite (500 RPD) -> high-capacity fallback 2
            for model_name in ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.1-flash-lite"]:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=json.dumps(context_payload),
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            temperature=0.4
                        )
                    )
                    if response and response.text:
                        return response.text
                except APIError as ae:
                    last_err = ae
                    err_str = str(ae)
                    # If 429 quota exhausted or 404 on this model, fall down to the next model in the waterfall
                    if "RESOURCE_EXHAUSTED" in err_str or ae.code in (429, 404):
                        continue
                    # If invalid API key (400, 403), stop immediately
                    if "API_KEY_INVALID" in err_str or ae.code in (400, 403):
                        raise ae
                except Exception as e:
                    last_err = e
                    continue
            if last_err:
                raise last_err
            raise RuntimeError("All models in the generation waterfall failed.")
            
        try:
            # 50 second timeout on AI code generation (Section 85)
            raw_response = await asyncio.wait_for(asyncio.to_thread(_call_gemini), timeout=50.0)
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": "Yulya couldn't finish the request. The Google AI Studio request timed out. Please try again."
            }
        except APIError as ae:
            err_msg = str(ae)
            if "RESOURCE_EXHAUSTED" in err_msg or ae.code == 429:
                return {
                    "success": False,
                    "error": "Google AI Studio quota reached. Your API key has reached its current usage limit. Check your Google AI Studio quota or try again later."
                }
            elif "API_KEY_INVALID" in err_msg or ae.code in [400, 403]:
                return {
                    "success": False,
                    "error": "Your Google AI Studio API key could not be verified by Google AI. Please update your key in setup."
                }
            return {
                "success": False,
                "error": f"Google AI Studio returned an error: {err_msg[:120]}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to connect to Google AI Studio: {str(e)[:120]}"
            }
            
        try:
            # Clean markdown code blocks if the model wrapped output anyway
            clean_text = raw_response.strip()
            if clean_text.startswith("```"):
                lines = clean_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                clean_text = "\n".join(lines).strip()
                
            data = json.loads(clean_text)
            summary = data.get("summary", "Updated project files.")
            files = data.get("files", {})
            
            if not isinstance(files, dict) or not files:
                return {
                    "success": False,
                    "error": "AI response did not contain updated files."
                }
                
            saved_files = []
            for fname in ["index.html", "style.css", "app.js"]:
                content = files.get(fname)
                if content and isinstance(content, str):
                    projects_manager.write_project_file(user_id, slug, fname, content)
                    saved_files.append(fname)
                    
            if not saved_files:
                return {
                    "success": False,
                    "error": "No valid game files (HTML, CSS, JS) were generated."
                }
                
            # Preserve existing project title and tags if present
            existing_proj = await database.get_project(user_id, slug)
            existing_title = existing_proj.get("title") if existing_proj else None
            project_title = existing_title or slug.replace("-", " ").title()
            existing_tags = existing_proj.get("tags") if existing_proj else None

            # Update database record
            await database.save_project(
                user_id=user_id,
                username=username,
                slug=slug,
                title=project_title,
                description=summary,
                files=saved_files,
                tags=existing_tags
            )
            
            # Read back saved files
            updated_content = {f: projects_manager.read_project_file(user_id, slug, f) for f in saved_files}
            
            return {
                "success": True,
                "summary": summary,
                "files": saved_files,
                "content": updated_content
            }
        except json.JSONDecodeError as jde:
            print(f"[AI_ENGINE] JSON decode error: {jde}\nOutput snippet: {raw_response[:300]}")
            return {
                "success": False,
                "error": "Yulya generated invalid formatted code. Please try rephrasing your request."
            }
        except ValueError as ve:
            return {
                "success": False,
                "error": f"File validation error: {str(ve)}"
            }
        except Exception as e:
            print(f"[AI_ENGINE] Unexpected error: {e}")
            return {
                "success": False,
                "error": f"Unexpected error processing update: {str(e)}"
            }
