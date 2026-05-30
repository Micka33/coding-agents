from __future__ import annotations

import base64
import io
import json
import runpy
import sys
import threading
import unittest
import warnings
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

from src.webapp import server as server_module
from src.webapp.application.conversation_web_app_launcher import ConversationWebAppLauncher
from src.webapp.server import ConversationRequestHandler


class FakeConversation:
    def __init__(self) -> None:
        self.messages = []
        self.stopped = []
        self.runtime_calls = []
        self.runtime = SimpleNamespace(
            set_mention_hook_enabled=lambda enabled: self.runtime_calls.append(("hook", enabled)),
            set_max_cascade_turns=lambda value: self.runtime_calls.append(("cascade", value)),
            stop_agent=lambda agent_id: self.stopped.append(agent_id),
        )

    def state(self):
        return {
            "team_id": "team",
            "conversation_id": "thread",
            "runtime": {"mention_hook_enabled": True, "max_cascade_turns": None},
            "events": [],
            "agent_states": [{"agent_id": "agent", "running": True, "queued": False}],
            "deliveries": [],
            "activities": [{"agent_id": "agent", "running": True, "queued": False}],
            "activity": {"agent_id": "agent"},
            "participants": ["agent"],
        }

    def activity(self, agent_id=None):
        state = self.state()
        state["private_thread_id"] = f"thread:mention:{agent_id}"
        state["private_messages"] = [{"type": "human", "content": "hello"}]
        return state

    def create_public_file_ref(self, *, filename, content, added_by, media_type=None):
        return SimpleNamespace(
            id="file-1",
            filename=filename,
            uri="conversation://files/file-1",
            media_type=media_type,
            size_bytes=len(content),
            added_by=added_by,
            to_dict=lambda: {"id": "file-1", "filename": filename},
        )

    def append_human_message(self, content, *, author_id, files, wait):
        self.messages.append((content, author_id, files, wait))
        return SimpleNamespace(
            event=SimpleNamespace(to_dict=lambda: {"seq": 1, "content": content}),
            deliveries=(),
            failures=(),
        )


class ConversationWebAppTests(unittest.TestCase):
    def test_state_activity_and_message_apis(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), ConversationRequestHandler)
        server.conversation = FakeConversation()  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"
            state = self._get_json(f"{base_url}/api/state")
            activity = self._get_json(f"{base_url}/api/activity?agent_id=agent")
            result = self._post_json(
                f"{base_url}/api/messages",
                {
                    "content": "@agent hello",
                    "author_id": "mickael",
                    "attachments": [
                        {
                            "filename": "notes.txt",
                            "content_base64": base64.b64encode(b"hello").decode("ascii"),
                        }
                    ],
                },
            )
            passthrough = self._post_json(
                f"{base_url}/api/messages",
                {
                    "content": "@agent passthrough",
                    "attachments": [{"id": "raw-file", "filename": "raw.txt", "uri": "conversation://files/raw-file"}],
                },
            )
            runtime = self._post_json(
                f"{base_url}/api/runtime",
                {"mention_hook_enabled": False, "max_cascade_turns": ""},
            )
            self._post_raw(f"{base_url}/api/runtime", b"{not-json")
            self._post_json(f"{base_url}/api/stop", {"agent_id": "agent"})
            static_html = urllib.request.urlopen(f"{base_url}/", timeout=2).read().decode("utf-8")

            self.assertEqual(state["team_id"], "team")
            self.assertEqual(activity["agent_states"][0]["agent_id"], "agent")
            self.assertEqual(activity["private_messages"][0]["content"], "hello")
            self.assertEqual(result["event"]["content"], "@agent hello")
            self.assertEqual(passthrough["event"]["content"], "@agent passthrough")
            self.assertEqual(runtime["team_id"], "team")
            self.assertIn("<", static_html)
            self.assertEqual(server.conversation.messages[0][2][0].filename, "notes.txt")  # type: ignore[attr-defined]
            self.assertEqual(server.conversation.messages[1][2][0]["id"], "raw-file")  # type: ignore[attr-defined]
            self.assertEqual(server.conversation.runtime_calls, [("hook", False), ("cascade", None)])  # type: ignore[attr-defined]
            self.assertEqual(server.conversation.stopped, ["agent"])  # type: ignore[attr-defined]
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_error_and_static_edges(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), ConversationRequestHandler)
        server.conversation = FakeConversation()  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            base_url = f"http://127.0.0.1:{server.server_address[1]}"

            self.assertEqual(self._http_error(f"{base_url}/api/stop", method="POST", body={}), 400)
            self.assertEqual(self._http_error(f"{base_url}/api/unknown", method="POST", body={}), 404)
            self.assertEqual(self._http_error(f"{base_url}/missing.css"), 404)
            self.assertEqual(self._http_error(f"{base_url}/../pyproject.toml"), 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_launcher_closes_team_on_missing_conversation_and_shutdown(self) -> None:
        missing_team = SimpleNamespace(closed=False, conversation_for=lambda _conversation_id: None)
        missing_team.close = lambda: setattr(missing_team, "closed", True)

        class FakeInstanciator:
            def __init__(self, config_variables=None) -> None:
                self.config_variables = config_variables

            def instantiate(self, team_file, variables):
                return missing_team

        with patch("src.webapp.application.conversation_web_app_launcher.TeamInstanciator", FakeInstanciator):
            with self.assertRaisesRegex(ValueError, "conversation"):
                ConversationWebAppLauncher().launch(team_file="team.yaml")

        self.assertTrue(missing_team.closed)

        served_team = SimpleNamespace(closed=False, conversation_for=lambda _conversation_id: FakeConversation())
        served_team.close = lambda: setattr(served_team, "closed", True)

        class ServedInstanciator(FakeInstanciator):
            def instantiate(self, team_file, variables):
                return served_team

        class FakeServer:
            def __init__(self, address, handler):
                self.address = address
                self.handler = handler
                self.closed = False

            def serve_forever(self):
                raise KeyboardInterrupt

            def server_close(self):
                self.closed = True

        with (
            patch("src.webapp.application.conversation_web_app_launcher.TeamInstanciator", ServedInstanciator),
            patch("src.webapp.application.conversation_web_app_launcher.ThreadingHTTPServer", FakeServer),
        ):
            ConversationWebAppLauncher().launch(team_file="team.yaml", variables={"topic": "ai"}, port=9999)

        self.assertTrue(served_team.closed)

    def test_server_main_parse_args_and_main_guard(self) -> None:
        with patch("src.webapp.server.ConversationWebAppLauncher") as launcher:
            exit_code = server_module.main(
                [
                    "team.yaml",
                    "--thread-id",
                    "thread",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "9999",
                    "--var",
                    "topic=ai",
                    "--no-env-file",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(launcher.return_value.launch.call_args.kwargs["conversation_id"], "thread")

        output = io.StringIO()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with patch.object(sys, "argv", ["server.py", "--help"]), patch("src.webapp.server.ConversationWebAppLauncher"), self.assertRaises(SystemExit) as raised:
                with patch("sys.stdout", output):
                    runpy.run_module("src.webapp.server", run_name="__main__")

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Serve the mention-router", output.getvalue())

    def _get_json(self, url: str):
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, url: str, body: dict):
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_raw(self, url: str, body: bytes):
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.read()

    def _http_error(self, url: str, *, method: str = "GET", body: dict | None = None) -> int:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=2)
        return raised.exception.code


if __name__ == "__main__":
    unittest.main()
