from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib import request

from src.team_instanciator.interfaces.cli_support import build_config_variables, parse_key_value_pairs
from src.type_defs import JsonObject
from src.webapp_studio.application.studio_server_args import StudioServerArgs


class StudioDevelopmentLauncher:
    def __init__(
        self,
        *,
        root_dir: Path | None = None,
        workspace_dir: Path | None = None,
        process_factory: Callable[..., Any] = subprocess.Popen,
        socket_factory: Callable[..., Any] = socket.create_connection,
        urlopen: Callable[..., Any] = request.urlopen,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        health_timeout_seconds: float = 30.0,
    ) -> None:
        self._root_dir = root_dir or Path(__file__).resolve().parents[3]
        self._workspace_dir = workspace_dir or Path.cwd()
        self._process_factory = process_factory
        self._socket_factory = socket_factory
        self._urlopen = urlopen
        self._monotonic = monotonic
        self._sleep = sleep
        self._health_timeout_seconds = health_timeout_seconds

    def launch_from_args(self, args: StudioServerArgs) -> None:
        self.launch(
            team_file=args.team_file,
            variables=parse_key_value_pairs(args.var),
            config_variables=build_config_variables(args),
            conversation_id=args.thread_id,
            host=args.host,
            backend_port=args.port,
            frontend_port=args.frontend_port,
            raw_args=args,
        )

    def launch(
        self,
        *,
        team_file: str | Path | None = None,
        variables: JsonObject | None = None,
        config_variables: JsonObject | None = None,
        conversation_id: str | None = None,
        host: str = "127.0.0.1",
        backend_port: int = 8765,
        frontend_port: int = 3765,
        raw_args: StudioServerArgs | None = None,
    ) -> None:
        backend_url = f"http://{self._browser_host(host)}:{backend_port}"
        frontend_url = f"http://{self._browser_host(host)}:{frontend_port}"
        self._ensure_port_available(host, backend_port, "backend")
        self._ensure_port_available(host, frontend_port, "frontend")

        backend = self._start_backend(team_file, variables, config_variables, conversation_id, host, backend_port, raw_args)
        frontend = None
        try:
            self._wait_for_backend_health(backend, f"{backend_url}/health")
            frontend = self._start_frontend(host, frontend_port, backend_url)
            print(f"Webapp Studio backend: {backend_url}")
            print(f"Webapp Studio frontend: {frontend_url}")
            if team_file is not None:
                print(f"Webapp Studio team: {team_file}")
            else:
                print("Webapp Studio teams: discovered from workspace and repository")
            self._wait_until_interrupted(backend, frontend)
        except KeyboardInterrupt:
            pass
        finally:
            self._terminate_process(frontend)
            self._terminate_process(backend)

    def _start_backend(
        self,
        team_file: str | Path | None,
        variables: JsonObject | None,
        config_variables: JsonObject | None,
        conversation_id: str | None,
        host: str,
        port: int,
        raw_args: StudioServerArgs | None,
    ) -> Any:
        command = self._backend_command(team_file, variables, config_variables, conversation_id, host, port, raw_args)
        return self._process_factory(command, cwd=self._workspace_dir)

    def _start_frontend(self, host: str, port: int, backend_url: str) -> Any:
        return self._process_factory(
            ["pnpm", "--dir", str(self._frontend_dir()), "dev", "--hostname", host, "--port", str(port)],
            cwd=self._root_dir,
            env={**os.environ, "STUDIO_API_BASE_URL": backend_url},
        )

    def _backend_command(
        self,
        team_file: str | Path | None,
        variables: JsonObject | None,
        config_variables: JsonObject | None,
        conversation_id: str | None,
        host: str,
        port: int,
        raw_args: StudioServerArgs | None,
    ) -> list[str]:
        command = [
            sys.executable,
            "-m",
            "src.webapp_studio.backend.server",
            "--host",
            host,
            "--port",
            str(port),
        ]
        if team_file is not None:
            command.insert(3, str(team_file))
        self._append_optional(command, "--thread-id", conversation_id)
        self._append_mapping(command, "--var", variables)
        self._append_mapping(command, "--config", config_variables)
        if raw_args is not None:
            self._append_optional(command, "--env-file", raw_args.env_file)
            if raw_args.no_env_file:
                command.append("--no-env-file")
        return command

    def _wait_for_backend_health(self, backend: Any, health_url: str) -> None:
        deadline = self._monotonic() + self._health_timeout_seconds
        while self._monotonic() < deadline:
            if backend.poll() is not None:
                raise RuntimeError("Webapp Studio backend exited before /health became available.")
            if self._is_healthy(health_url):
                return
            self._sleep(0.2)
        raise RuntimeError(f"Webapp Studio backend did not become healthy at {health_url}.")

    def _wait_until_interrupted(self, backend: Any, frontend: Any) -> None:
        while True:
            backend_code = backend.poll()
            frontend_code = frontend.poll()
            if backend_code is not None:
                raise RuntimeError(f"Webapp Studio backend exited with code {backend_code}.")
            if frontend_code is not None:
                raise RuntimeError(f"Webapp Studio frontend exited with code {frontend_code}.")
            self._sleep(0.25)

    def _is_healthy(self, health_url: str) -> bool:
        try:
            response = self._urlopen(health_url, timeout=1)
        except OSError:
            return False
        return getattr(response, "status", 200) == 200

    def _ensure_port_available(self, host: str, port: int, label: str) -> None:
        connection = None
        try:
            connection = self._socket_factory((self._browser_host(host), port), timeout=0.2)
        except OSError:
            return
        finally:
            if connection is not None:
                connection.close()
        raise RuntimeError(f"Webapp Studio {label} port {port} is already in use.")

    def _terminate_process(self, process: Any | None) -> None:
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def _frontend_dir(self) -> Path:
        return self._root_dir / "src" / "webapp_studio" / "frontend"

    def _browser_host(self, host: str) -> str:
        if host == "0.0.0.0":
            return "127.0.0.1"
        return host

    def _append_optional(self, command: list[str], flag: str, value: str | None) -> None:
        if value:
            command.extend([flag, value])

    def _append_mapping(self, command: list[str], flag: str, values: JsonObject | None) -> None:
        for key, value in (values or {}).items():
            command.extend([flag, f"{key}={value}"])
