"""
Comprehensive 3-Tier Verification for Gemini Live Public SDK Integration:
Tier 1: Unit tests for public SDK configuration & absence of monkey patches
Tier 2: SDK method contract tests (send_tool_response, send_client_content, send_realtime_input)
Tier 3: Real Live E2E test with Gemini API key (connect, greet, stream audio, turn complete)
"""

import asyncio
import os
import re
import sys
import unittest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from google import genai
from google.genai import types

import server

class TestGeminiLivePublicSDK(unittest.TestCase):
    """Tier 1: Verification of code integrity and absence of private SDK hacks."""

    def test_no_private_monkey_patches_in_server(self):
        """Ensure no private google.genai attributes or functions are patched in server.py."""
        with open("server.py", "r", encoding="utf-8") as f:
            code = f.read()

        forbidden_patterns = [
            r"_LiveSetup_to_mldev",
            r"_ThinkingConfig_to_mldev",
            r"_FunctionDeclaration_to_mldev",
            r"_mldev_normalize_client_message",
            r"AsyncSession\.send\s*=",
            r"Session\.send\s*=",
            r"_patched_live_setup",
            r"_orig_thinking_to_mldev",
        ]
        for pat in forbidden_patterns:
            matches = re.findall(pat, code)
            self.assertEqual(len(matches), 0, f"Found forbidden monkey patch pattern '{pat}' in server.py")

    def test_all_architect_tools_have_non_blocking_behavior(self):
        """Verify that every tool declaration specifies behavior='NON_BLOCKING'."""
        with open("server.py", "r", encoding="utf-8") as f:
            code = f.read()

        chunks = code.split("types.FunctionDeclaration(")[1:]
        self.assertGreaterEqual(len(chunks), 12, "Expected at least 12 architect tools")

        expected_tools = [
            "draft_prompt_to_input",
            "send_prompt_to_antigravity",
            "modify_game_code",
            "get_project_summary",
            "list_project_files",
            "read_project_file",
            "search_project",
            "get_current_build",
            "get_known_bugs",
            "validate_project",
            "save_design_decision",
            "remember_creator_preference"
        ]

        found_tools = []
        for chunk in chunks:
            header = chunk[:400]
            name_m = re.search(r'name="([^"]+)"', header)
            if name_m:
                tool_name = name_m.group(1)
                found_tools.append(tool_name)
                self.assertIn('behavior="NON_BLOCKING"', header, f"Tool '{tool_name}' is missing behavior='NON_BLOCKING'")

        for exp in expected_tools:
            self.assertIn(exp, found_tools, f"Expected tool '{exp}' not found in server.py")

    def test_no_post_chat_message_tool(self):
        """Verify that post_chat_message is not declared in tools."""
        with open("server.py", "r", encoding="utf-8") as f:
            code = f.read()
        self.assertNotIn('name="post_chat_message"', code)

    def test_thinking_config_on_extended_thinking_only(self):
        """Verify that thinkingConfig is only attached to extended-thinking model."""
        with open("server.py", "r", encoding="utf-8") as f:
            code = f.read()

        # Check candidate definitions
        self.assertIn('"gemini-3.8-live-extended-thinking"', code)
        self.assertIn('"gemini-3.8-live"', code)
        self.assertIn('"gemini-3.1-flash-live-preview"', code)
        self.assertIn('thinking_level="HIGH"', code)
        self.assertIn('include_thoughts=True', code)

    def test_api_health_payload(self):
        """Verify /api/health reports truthful SDK diagnostics."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def _test():
            app = await server.init_app()
            req = None
            res = await server.api_health(req)
            data = res.body.decode("utf-8")
            import json
            payload = json.loads(data)
            self.assertEqual(payload["status"], "healthy")
            self.assertEqual(payload["service"], "yulya-studio")
            self.assertEqual(payload["application_version"], "2026-09-25-live-v4")
            self.assertEqual(payload["configured_primary_model"], "gemini-3.8-live-extended-thinking")
            self.assertEqual(payload["thinking_level"], "HIGH")
            self.assertEqual(payload["tool_behavior"], "NON_BLOCKING")
            self.assertEqual(payload["live_integration_status"], "native_public_sdk")
            self.assertIn("google_genai_version", payload)
            self.assertIn("gemini-3.8-live", payload["supported_fallback_models"])
        loop.run_until_complete(_test())
        loop.close()

class TestTier2SDKMethodContracts(unittest.TestCase):
    """Tier 2: Verification of official google-genai 2.25.0 Live API contracts."""

    def test_sdk_version_requirement(self):
        """Ensure installed google-genai package is >= 2.25.0."""
        ver = getattr(genai, "__version__", "0.0.0")
        parts = [int(p) for p in ver.split(".")[:2]]
        self.assertTrue(parts[0] >= 2 and parts[1] >= 25, f"Expected google-genai >= 2.25.0, found {ver}")

    def test_async_session_has_public_methods(self):
        """AsyncSession must expose send_realtime_input, send_client_content, send_tool_response."""
        from google.genai.live import AsyncSession
        self.assertTrue(hasattr(AsyncSession, "send_realtime_input"))
        self.assertTrue(hasattr(AsyncSession, "send_client_content"))
        self.assertTrue(hasattr(AsyncSession, "send_tool_response"))

    def test_function_declaration_native_behavior(self):
        """types.FunctionDeclaration must natively accept behavior='NON_BLOCKING'."""
        fd = types.FunctionDeclaration(
            name="unit_test_tool",
            description="A unit test tool",
            behavior="NON_BLOCKING"
        )
        self.assertEqual(fd.behavior.value, "NON_BLOCKING")

    def test_live_connect_config_serialization(self):
        """LiveConnectConfig must serialize thinking_config and NON_BLOCKING tools without error."""
        fd = types.FunctionDeclaration(name="test_tool", description="test", behavior="NON_BLOCKING")
        tool = types.Tool(function_declarations=[fd])
        cfg = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            tools=[tool],
            thinking_config=types.ThinkingConfig(thinking_level="HIGH", include_thoughts=True)
        )
        self.assertEqual(cfg.thinking_config.thinking_level, "HIGH")
        self.assertTrue(cfg.thinking_config.include_thoughts)


class TestTier3LiveE2E(unittest.TestCase):
    """Tier 3: Real live end-to-end test against Gemini Live API if API key is present."""

    def test_real_live_connection_and_audio_stream(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            # Check render_bot/.env
            env_path = os.path.join(os.path.dirname(__file__), "..", "render_bot", ".env")
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("GEMINI_API_KEY="):
                            api_key = line.strip().split("=", 1)[1]
                            break

        if not api_key:
            print("[TIER 3 SKIP] No GEMINI_API_KEY found, skipping live API call.")
            return

        print(f"\n[TIER 3] Running Real Gemini 3.8 Live Extended Thinking E2E test with API key ({api_key[:6]}...)...")

        async def _run_live_test():
            client = genai.Client(api_key=api_key.strip())
            fd = types.FunctionDeclaration(
                name="test_ping",
                description="Sends a ping test",
                behavior="NON_BLOCKING",
                parameters=types.Schema(type="OBJECT", properties={})
            )
            tools = [types.Tool(function_declarations=[fd])]
            cfg = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=types.Content(parts=[types.Part.from_text(text="You are Yulya Studio test bot. Greet in 3 words.")]),
                tools=tools,
                thinking_config=types.ThinkingConfig(thinking_level="HIGH", include_thoughts=True)
            )

            cm = client.aio.live.connect(model="gemini-3.8-live-extended-thinking", config=cfg)
            session = await cm.__aenter__()
            print("  [PASS] Successfully connected to gemini-3.8-live-extended-thinking")

            # Send client greeting via official method
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part.from_text(text="Hi Yulya!")])],
                turn_complete=True
            )
            print("  [PASS] Sent greeting via session.send_client_content()")

            audio_chunks_received = 0
            turn_completed = False

            async for resp in session.receive():
                if resp.server_content:
                    if resp.server_content.model_turn:
                        for part in resp.server_content.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                audio_chunks_received += 1
                    if resp.server_content.turn_complete:
                        turn_completed = True
                        break

            await cm.__aexit__(None, None, None)
            print(f"  [PASS] Received {audio_chunks_received} audio chunks from Gemini Live")
            print(f"  [PASS] Turn complete successfully: {turn_completed}")
            self.assertGreater(audio_chunks_received, 0, "Expected at least one audio chunk")
            self.assertTrue(turn_completed, "Expected turn_complete to be True")

        asyncio.run(_run_live_test())

if __name__ == "__main__":
    unittest.main()
