"""The Rerun server lifecycle, over loopback and with browser launches stubbed."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from contextlib import suppress
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import pytest
import yaml
from conftest import mock_project

from roboloom.config import RobotConfig, load_config
from roboloom.runtime import viewer


@pytest.fixture
def free_ports():
    # Reserve both at once to avoid selecting the same ephemeral port twice.
    with socket.socket() as grpc, socket.socket() as web:
        grpc.bind(("127.0.0.1", 0))
        web.bind(("127.0.0.1", 0))
        ports = grpc.getsockname()[1], web.getsockname()[1]
    return ports


def _config(tmp_path: Path, **settings) -> RobotConfig:
    project = mock_project(tmp_path / ".roboloom")
    (project / "nodes" / "viewer.yaml").write_text(yaml.safe_dump(settings))
    return load_config(project / "config.yaml", options=["viewer"], mock=True)


@pytest.mark.skipif(viewer._rerun_cli() is None, reason="rerun CLI is unavailable")
@pytest.mark.parametrize("public_host", ["robot.example", "2001:db8::9"])
def test_start_serves_web_and_reuses_the_detached_server(
    tmp_path, free_ports, monkeypatch, capsys, public_host
):
    import rerun as rr
    from rerun.experimental import RrdReader

    grpc_port, web_port = free_ports
    recording = tmp_path / "view.rrd"
    cfg = _config(
        tmp_path,
        bind="127.0.0.1",
        port=grpc_port,
        web_port=web_port,
        server_memory_limit="64MiB",
        public_host=public_host,
        cors_allow_origins=["https://*.viewer.example"],
        save=str(recording),
    )
    monkeypatch.setenv("ROBOLOOM_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("RERUN_TELEMETRY_ENDPOINT", "http://127.0.0.1:1")
    processes = []
    popen = subprocess.Popen

    def track_process(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(viewer.subprocess, "Popen", track_process)
    opened = []
    monkeypatch.setattr(
        viewer.webbrowser, "open", lambda url: opened.append(url) or True
    )
    try:
        url, local_url, warning = viewer.start(cfg)
        assert warning is None and opened == []
        parsed = urlsplit(url)
        assert parsed.hostname == public_host and parsed.port == web_port
        authority = f"[{public_host}]" if ":" in public_host else public_host
        assert parse_qs(parsed.query) == {
            "url": [f"rerun+http://{authority}:{grpc_port}/proxy"],
        }
        parsed_local = urlsplit(local_url)
        assert parsed_local.hostname == "localhost" and parsed_local.port == web_port
        assert parse_qs(parsed_local.query) == {
            "url": [f"rerun+http://localhost:{grpc_port}/proxy"],
        }
        (process,) = processes
        assert os.getsid(process.pid) == process.pid
        assert (tmp_path / "rerun-server.log").is_file()
        lines = capsys.readouterr().err.splitlines()
        assert any(f"PID {process.pid}" in line and url in line for line in lines)
        assert sum(local_url in line for line in lines) == 1

        http = HTTPConnection("127.0.0.1", web_port, timeout=2)
        try:
            http.request("GET", "/")
            response = http.getresponse()
            assert response.status == 200
            assert "text/html" in response.getheader("Content-Type", "")
            response.read()
        finally:
            http.close()
        opener = build_opener(ProxyHandler({}))
        for origin in (
            f"{parsed.scheme}://{parsed.netloc}",
            f"http://localhost:{web_port}",
            "https://relay.viewer.example",
        ):
            preflight = Request(
                f"http://127.0.0.1:{grpc_port}/",
                method="OPTIONS",
                headers={
                    "Origin": origin,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type,x-grpc-web",
                },
            )
            with opener.open(preflight, timeout=2) as response:
                assert response.headers["Access-Control-Allow-Origin"] == origin

        rr.log("test", rr.Scalars(1.0))
        rr.rerun_shutdown()
        assert any(
            chunk.entity_path == "/test"
            for chunk in RrdReader(recording).store().stream()
        )
        assert process.poll() is None  # SDK shutdown leaves the server up

        cfg.viewer["open_browser"] = True
        cfg.viewer["save"] = None
        assert viewer.start(cfg) == (url, local_url, None)
        assert processes == [process] and process.poll() is None
        assert opened == [local_url]
    finally:
        try:
            rr.rerun_shutdown()
        finally:
            for process in processes:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
    assert not viewer._listening(grpc_port)
    assert not viewer._listening(web_port)


@pytest.mark.parametrize("save", [None, "view.rrd"])
def test_an_explicit_server_takes_priority_over_local_serving(
    tmp_path, monkeypatch, save
):
    import rerun as rr

    cfg = _config(
        tmp_path,
        ip="127.0.0.1",
        port=9876,
        public_host="robot.example",
        save=save,
        open_browser=True,
    )
    sinks = []
    monkeypatch.setattr(rr, "set_sinks", lambda *args: sinks.extend(args))

    def unexpected(*args):
        pytest.fail("external mode tried to launch a server or browser")

    monkeypatch.setattr(viewer, "_ensure_server", unexpected)
    monkeypatch.setattr(viewer.webbrowser, "open", unexpected)
    try:
        assert viewer.start(cfg) == (None, None, None)
    finally:
        rr.rerun_shutdown()
    assert sinks[0] == rr.GrpcSink("rerun+http://127.0.0.1:9876/proxy")
    if save is None:
        assert len(sinks) == 1
    else:
        assert sinks[1:] == [
            rr.FileSink(tmp_path / ".roboloom" / "rakuda2" / "nodes" / save)
        ]


def test_native_mode_passes_the_window_memory_limit(tmp_path, monkeypatch):
    import rerun as rr

    cfg = _config(tmp_path, serve=False, memory_limit="128MiB")
    windows = []
    monkeypatch.setattr(rr, "spawn", lambda **kwargs: windows.append(kwargs))
    try:
        assert viewer.start(cfg) == (None, None, None)
    finally:
        rr.rerun_shutdown()
    assert windows == [{"memory_limit": "128MiB"}]


def test_an_occupied_web_port_is_reported(tmp_path):
    import rerun as rr

    with socket.socket() as grpc, socket.socket() as web:
        grpc.bind(("127.0.0.1", 0))
        web.bind(("127.0.0.1", 0))
        web.listen()
        grpc_port, web_port = grpc.getsockname()[1], web.getsockname()[1]
        cfg = _config(tmp_path, bind="127.0.0.1", port=grpc_port, web_port=web_port)
        try:
            with pytest.raises(
                RuntimeError, match=f"web port {web_port}.*gRPC port {grpc_port}"
            ):
                viewer.start(cfg)
        finally:
            rr.rerun_shutdown()


@pytest.mark.parametrize("raises", [False, True])
def test_browser_failure_does_not_fail_start(tmp_path, monkeypatch, raises):
    import rerun as rr

    cfg = _config(tmp_path, open_browser=True)
    monkeypatch.setattr(viewer, "_ensure_server", lambda *args: None)
    monkeypatch.setattr(rr, "set_sinks", lambda *args: None)

    def open_browser(url):
        if raises:
            raise OSError("no display")
        return False

    monkeypatch.setattr(viewer.webbrowser, "open", open_browser)
    try:
        url, local_url, warning = viewer.start(cfg)
    finally:
        rr.rerun_shutdown()
    assert url and local_url and "Could not open the Rerun web viewer" in warning
    assert ("no display" in warning) == raises


@pytest.mark.parametrize(
    ("host", "authority", "web_port", "origin"),
    [
        ("robot.example", "robot.example", 23457, "http://robot.example:23457"),
        (None, "Robot-Host", 23457, "http://robot-host:23457"),
        ("2001:db8::9", "[2001:db8::9]", 23457, "http://[2001:db8::9]:23457"),
        ("robot.example", "robot.example", 80, "http://robot.example"),
    ],
)
def test_shareable_url_and_server_cors_flags(
    tmp_path, monkeypatch, host, authority, web_port, origin
):
    import rerun as rr

    extras = ["https://*.example.org", "http://viewer.example:9000"]
    cfg = _config(
        tmp_path,
        public_host=host,
        port=23456,
        web_port=web_port,
        open_browser=True,
        cors_allow_origins=extras,
    )
    command = []
    sinks = []
    opened = []

    def popen(args, **kwargs):
        command.extend(args)
        return SimpleNamespace(pid=123, poll=lambda: None, wait=lambda: None)

    monkeypatch.setenv("ROBOLOOM_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(viewer, "_rerun_cli", lambda: "/virtual/bin/rerun")
    monkeypatch.setattr(viewer, "_listening", lambda port: bool(command))
    monkeypatch.setattr(viewer.subprocess, "Popen", popen)
    monkeypatch.setattr(viewer.socket, "gethostname", lambda: "Robot-Host")
    monkeypatch.setattr(rr, "set_sinks", lambda *args: sinks.extend(args))
    monkeypatch.setattr(
        viewer.webbrowser, "open", lambda url: opened.append(url) or True
    )
    try:
        url, local_url, warning = viewer.start(cfg)
    finally:
        rr.rerun_shutdown()
    assert command == [
        "/virtual/bin/rerun",
        "--serve-web",
        "--port",
        "23456",
        "--web-viewer-port",
        str(web_port),
        "--bind",
        "0.0.0.0",
        "--server-memory-limit",
        "25%",
        "--cors-allow-origin",
        origin,
        "--cors-allow-origin",
        extras[0],
        "--cors-allow-origin",
        extras[1],
    ]
    assert sinks == [rr.GrpcSink("rerun+http://127.0.0.1:23456/proxy")]
    assert urlsplit(url).netloc == f"{authority}:{web_port}"
    assert parse_qs(urlsplit(url).query) == {
        "url": [f"rerun+http://{authority}:23456/proxy"]
    }
    assert urlsplit(local_url).netloc == f"localhost:{web_port}"
    assert parse_qs(urlsplit(local_url).query) == {
        "url": ["rerun+http://localhost:23456/proxy"]
    }
    assert opened == [url] and warning is None
