from __future__ import annotations

import io
import json
import runpy
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib import request

from src.webapp_studio.application.studio_development_launcher import StudioDevelopmentLauncher
from src.webapp_studio.server import main, parse_args

ROOT = Path(__file__).resolve().parents[2]
ROOT_ENV = ROOT / ".env"
PHILOSOPHERS_TEAM = ROOT / "teams" / "conversing_philosophers" / "team.yaml"


class LocalLauncherTests(unittest.TestCase):
    def test_parse_and_main_preserve_current_cli_shape(self) -> None:
        args = parse_args(
            [
                "team.yaml",
                "--thread-id",
                "thread",
                "--host",
                "0.0.0.0",
                "--port",
                "9999",
                "--frontend-port",
                "3000",
                "--var",
                "topic=ai",
                "--config",
                "model=gpt",
                "--openai-api-key",
                "openai",
                "--tavily-api-key",
                "tavily",
                "--env-file",
                ".env.local",
                "--no-env-file",
            ]
        )

        self.assertEqual(args.team_file, "team.yaml")
        self.assertEqual(args.thread_id, "thread")
        self.assertEqual(args.port, 9999)
        self.assertEqual(args.frontend_port, 3000)

        with patch("src.webapp_studio.server.StudioDevelopmentLauncher") as launcher:
            self.assertEqual(main(["team.yaml", "--thread-id", "thread", "--no-env-file"]), 0)
        self.assertEqual(launcher.return_value.launch_from_args.call_args.args[0].thread_id, "thread")

        output = io.StringIO()
        with patch.object(sys, "argv", ["server.py", "--help"]), self.assertRaises(SystemExit) as raised:
            with patch("sys.stdout", output):
                runpy.run_module("src.webapp_studio.server", run_name="__main__")
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Serve Webapp Studio", output.getvalue())

    def test_launch_starts_backend_then_frontend_and_stops_on_interrupt(self) -> None:
        records = []

        def process_factory(command, cwd=None, env=None):
            record = {"command": command, "cwd": cwd, "env": env, "terminated": False, "killed": False}
            records.append(record)
            process = SimpleNamespace(returncode=None)
            process.poll = lambda: process.returncode
            process.terminate = lambda: record.update({"terminated": True})
            process.kill = lambda: record.update({"killed": True})
            process.wait = lambda timeout=None: 0
            return process

        def socket_factory(_address, timeout=None):
            raise OSError("available")

        def sleep(_seconds):
            raise KeyboardInterrupt()

        launcher = StudioDevelopmentLauncher(
            root_dir=Path("/repo"),
            workspace_dir=Path("/workspace"),
            process_factory=process_factory,
            socket_factory=socket_factory,
            urlopen=lambda _url, timeout=None: SimpleNamespace(status=200),
            sleep=sleep,
        )

        with patch("sys.executable", "/python"):
            with patch("sys.stdout", io.StringIO()):
                launcher.launch(
                    team_file="team.yaml",
                    variables={"topic": "ai"},
                    config_variables={"model": "gpt"},
                    conversation_id="thread",
                    host="0.0.0.0",
                    backend_port=9999,
                    frontend_port=3000,
                )

        backend_command = records[0]["command"]
        frontend_command = records[1]["command"]

        self.assertEqual(backend_command[:4], ["/python", "-m", "src.webapp_studio.backend.server", "team.yaml"])
        self.assertIn("--thread-id", backend_command)
        self.assertIn("topic=ai", backend_command)
        self.assertIn("model=gpt", backend_command)
        self.assertEqual(records[0]["cwd"], Path("/workspace"))
        self.assertEqual(frontend_command, ["pnpm", "--dir", "/repo/src/webapp_studio/frontend", "dev", "--hostname", "0.0.0.0", "--port", "3000"])
        self.assertEqual(records[1]["cwd"], Path("/repo"))
        self.assertEqual(records[1]["env"]["STUDIO_API_BASE_URL"], "http://127.0.0.1:9999")
        self.assertTrue(records[0]["terminated"])
        self.assertTrue(records[1]["terminated"])

    def test_launch_accepts_required_philosophers_team_file(self) -> None:
        records = []

        def process_factory(command, cwd=None, env=None):
            record = {"command": command, "cwd": cwd, "env": env, "terminated": False}
            records.append(record)
            process = SimpleNamespace(returncode=None)
            process.poll = lambda: process.returncode
            process.terminate = lambda: record.update({"terminated": True})
            process.kill = lambda: None
            process.wait = lambda timeout=None: 0
            return process

        launcher = StudioDevelopmentLauncher(
            root_dir=ROOT,
            workspace_dir=ROOT,
            process_factory=process_factory,
            socket_factory=lambda _address, timeout=None: (_ for _ in ()).throw(OSError("available")),
            urlopen=lambda _url, timeout=None: SimpleNamespace(status=200),
            sleep=lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

        self.assertTrue(PHILOSOPHERS_TEAM.exists())
        with patch("sys.executable", "/python"):
            with patch("sys.stdout", io.StringIO()):
                launcher.launch(
                    team_file=PHILOSOPHERS_TEAM,
                    conversation_id="philosophers-smoke",
                    backend_port=9876,
                    frontend_port=3876,
                )

        self.assertEqual(records[0]["cwd"], ROOT)
        self.assertEqual(records[0]["command"][:4], ["/python", "-m", "src.webapp_studio.backend.server", str(PHILOSOPHERS_TEAM)])
        self.assertIn("philosophers-smoke", records[0]["command"])
        self.assertEqual(records[1]["env"]["STUDIO_API_BASE_URL"], "http://127.0.0.1:9876")
        self.assertTrue(records[0]["terminated"])
        self.assertTrue(records[1]["terminated"])

    @unittest.skipUnless(ROOT_ENV.exists(), "root .env is required for the real-team Studio smoke test")
    def test_required_philosophers_backend_starts_with_root_env_without_dispatch(self) -> None:
        port = self._free_port()
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "src.webapp_studio.backend.server",
                str(PHILOSOPHERS_TEAM),
                "--thread-id",
                "philosophers-smoke",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--env-file",
                str(ROOT_ENV),
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            self._wait_for_health(process, port)
            health = self._json_get(port, "/api/studio/v1/health")
            state = self._json_get(port, "/api/studio/v1/state")

            self.assertEqual(health["schema_version"], "studio.v1")
            self.assertEqual(health["data"]["status"], "ok")
            self.assertEqual(state["schema_version"], "studio.v1")
            self.assertEqual(state["data"]["team_id"], "philosophers")
            self.assertIn("Francis-Bacon", state["data"]["participants"])
            self.assertEqual(state["data"]["conversation"]["events"], [])
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

    def test_launch_from_args_keeps_env_and_no_env_file_flags_in_backend_command(self) -> None:
        records = []

        def process_factory(command, cwd=None, env=None):
            record = {"command": command, "terminated": False}
            records.append(record)
            process = SimpleNamespace(returncode=None)
            process.poll = lambda: process.returncode
            process.terminate = lambda: record.update({"terminated": True})
            process.kill = lambda: None
            process.wait = lambda timeout=None: 0
            return process

        launcher = StudioDevelopmentLauncher(
            root_dir=Path("/repo"),
            process_factory=process_factory,
            socket_factory=lambda _address, timeout=None: (_ for _ in ()).throw(OSError("available")),
            urlopen=lambda _url, timeout=None: SimpleNamespace(status=200),
            sleep=lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
        )

        with patch("sys.executable", "/python"):
            with patch("sys.stdout", io.StringIO()):
                launcher.launch_from_args(
                    parse_args(["team.yaml", "--env-file", ".env.test", "--no-env-file", "--config", "model=gpt"])
                )

        command = records[0]["command"]
        self.assertIn("--env-file", command)
        self.assertIn(".env.test", command)

    def _free_port(self) -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _wait_for_health(self, process: subprocess.Popen[str], port: int) -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.fail("Webapp Studio backend exited before real-team /health became available.")
            try:
                with request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.25)
        self.fail("Webapp Studio backend did not become healthy for the real-team smoke test.")

    def _json_get(self, port: int, path: str) -> dict[str, object]:
        with request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
        self.assertIn("--no-env-file", command)
        self.assertIn("model=gpt", command)

    def test_port_conflicts_fail_before_processes_start(self) -> None:
        connection = SimpleNamespace(closed=False)
        connection.close = lambda: setattr(connection, "closed", True)
        launcher = StudioDevelopmentLauncher(
            process_factory=lambda *args, **kwargs: self.fail("process should not start"),
            socket_factory=lambda _address, timeout=None: connection,
        )

        with self.assertRaisesRegex(RuntimeError, "backend port 8765"):
            launcher.launch(team_file="team.yaml")

        self.assertTrue(connection.closed)

    def test_backend_health_timeout_terminates_backend(self) -> None:
        record = {"terminated": False}
        process = SimpleNamespace(returncode=None)
        process.poll = lambda: process.returncode
        process.terminate = lambda: record.update({"terminated": True})
        process.kill = lambda: None
        process.wait = lambda timeout=None: 0
        monotonic_values = iter([0.0, 0.0, 31.0])

        launcher = StudioDevelopmentLauncher(
            process_factory=lambda *args, **kwargs: process,
            socket_factory=lambda _address, timeout=None: (_ for _ in ()).throw(OSError("available")),
            urlopen=lambda _url, timeout=None: (_ for _ in ()).throw(OSError("not ready")),
            monotonic=lambda: next(monotonic_values),
            sleep=lambda _seconds: None,
        )

        with self.assertRaisesRegex(RuntimeError, "did not become healthy"):
            launcher.launch(team_file="team.yaml")

        self.assertTrue(record["terminated"])

    def test_backend_exit_and_frontend_exit_are_clear_failures(self) -> None:
        exited_backend = SimpleNamespace(returncode=7)
        exited_backend.poll = lambda: exited_backend.returncode
        exited_backend.terminate = lambda: None
        exited_backend.kill = lambda: None
        exited_backend.wait = lambda timeout=None: 0

        launcher = StudioDevelopmentLauncher(
            process_factory=lambda *args, **kwargs: exited_backend,
            socket_factory=lambda _address, timeout=None: (_ for _ in ()).throw(OSError("available")),
            urlopen=lambda _url, timeout=None: (_ for _ in ()).throw(OSError("not ready")),
        )

        with self.assertRaisesRegex(RuntimeError, "backend exited before"):
            launcher.launch(team_file="team.yaml")

        backend_processes = []

        def backend_exit_process_factory(command, cwd=None, env=None):
            process = SimpleNamespace(returncode=None)
            process.poll = lambda: process.returncode
            process.terminate = lambda: setattr(process, "returncode", -15)
            process.kill = lambda: None
            process.wait = lambda timeout=None: 0
            backend_processes.append(process)
            return process

        def backend_exit_sleep(_seconds):
            backend_processes[0].returncode = 8

        backend_exit_launcher = StudioDevelopmentLauncher(
            process_factory=backend_exit_process_factory,
            socket_factory=lambda _address, timeout=None: (_ for _ in ()).throw(OSError("available")),
            urlopen=lambda _url, timeout=None: SimpleNamespace(status=200),
            sleep=backend_exit_sleep,
        )

        with self.assertRaisesRegex(RuntimeError, "backend exited with code 8"):
            with patch("sys.stdout", io.StringIO()):
                backend_exit_launcher.launch(team_file="team.yaml")

        processes = []

        def process_factory(command, cwd=None, env=None):
            process = SimpleNamespace(returncode=None)
            process.poll = lambda: process.returncode
            process.terminate = lambda: setattr(process, "returncode", -15)
            process.kill = lambda: None
            process.wait = lambda timeout=None: 0
            processes.append(process)
            return process

        def sleep(_seconds):
            processes[1].returncode = 9

        frontend_exit_launcher = StudioDevelopmentLauncher(
            process_factory=process_factory,
            socket_factory=lambda _address, timeout=None: (_ for _ in ()).throw(OSError("available")),
            urlopen=lambda _url, timeout=None: SimpleNamespace(status=200),
            sleep=sleep,
        )

        with self.assertRaisesRegex(RuntimeError, "frontend exited with code 9"):
            with patch("sys.stdout", io.StringIO()):
                frontend_exit_launcher.launch(team_file="team.yaml")

    def test_termination_kills_process_after_timeout(self) -> None:
        record = {"terminated": False, "killed": False, "waits": 0}
        process = SimpleNamespace(returncode=None)
        process.poll = lambda: process.returncode
        process.terminate = lambda: record.update({"terminated": True})
        process.kill = lambda: record.update({"killed": True, "returncode": -9}) or setattr(process, "returncode", -9)

        def wait(timeout=None):
            record["waits"] += 1
            if record["waits"] == 1:
                raise subprocess.TimeoutExpired("cmd", timeout)
            return 0

        process.wait = wait

        StudioDevelopmentLauncher()._terminate_process(process)

        self.assertTrue(record["terminated"])
        self.assertTrue(record["killed"])


if __name__ == "__main__":
    unittest.main()
