"""A policy that runs in another process, e.g. another Python environment or a GPU machine.

The policy node loads `roboloom.policy.remote:connect`, which forwards `bind`, `reset`
and `infer` to a server that holds the real policy:

    # where the model lives (its own environment; only numpy and roboloom are needed)
    export ROBOLOOM_POLICY_AUTHKEY=...            # any shared secret
    python -m roboloom.policy.remote my_lab.policies:load --kwargs '{"checkpoint": "..."}'

    # nodes/policy.yaml
    factory: roboloom.policy.remote:connect
    kwargs: {address: "127.0.0.1:18765"}

This is for models whose dependencies do not fit the environment roboloom runs in (a
different torch) or that should run on another machine. The server loads the model once
and serves one policy node at a time, across episodes and sessions; a second node that
connects meanwhile is told so instead of being left waiting.

Every call carries a number the answer repeats. An answer that arrives after its call
timed out is dropped, so it is never taken for the answer to the next call.

Wire format: `multiprocessing.connection` (the key authenticates both ends with HMAC;
nothing is encrypted, so keep it on the loopback interface or a trusted network). A
message is a JSON header followed by the raw bytes of its arrays: no pickle, so a peer
cannot run code here and numpy versions may differ.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import threading
import time
import traceback
from dataclasses import asdict
from multiprocessing.connection import Client, Connection, Listener
from typing import Any

import numpy as np

from ..core.checks import positive, unknown_keys
from ..errors import ConfigError
from . import Policy, PolicySpec, load_policy

ADDRESS = "127.0.0.1:18765"
AUTHKEY_ENV = "ROBOLOOM_POLICY_AUTHKEY"
OPTIONS = ("observation_history", "hold", "action_horizon")
BACKENDS = ("process", "server")  # a policy controller's `backend:`
SERVER_KEYS = ("address", "authkey_env", "timeout_s", "connect_timeout_s")


def server_settings(raw: object, where: str = "server") -> dict[str, Any]:
    """A policy controller's `server:` mapping as the arguments of `connect`."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: expected a mapping with {', '.join(SERVER_KEYS)}")
    unknown_keys(raw, SERVER_KEYS, where)
    out = dict(raw)
    for key in ("address", "authkey_env"):
        if key in out and not isinstance(out[key], str):
            raise ConfigError(f"{where}.{key}: expected text")
    if "address" in out:
        _address(out["address"])
    for key in ("timeout_s", "connect_timeout_s"):
        if key in out:
            out[key] = positive(out[key], f"{where}.{key}")
    return out


def served(path: str) -> tuple[str, dict, dict[str, Any]]:
    """What the policy server of the policy node file `path` loads and where it
    listens: its `factory`, `kwargs` and `server:` (`serve-policy --from`)."""
    from pathlib import Path

    import yaml

    try:
        cfg = yaml.safe_load(Path(path).read_text())
    except OSError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    if not isinstance(cfg, dict) or not isinstance(cfg.get("factory"), str):
        raise ConfigError(f"{path}: not a policy node file (no factory)")
    if cfg["factory"] == "roboloom.policy.remote:connect":
        raise ConfigError(
            f"{path}: its factory connects to a server; write the policy's own "
            "factory and kwargs there, with backend: server"
        )
    kwargs = cfg.get("kwargs") or {}
    if not isinstance(kwargs, dict):
        raise ConfigError(f"{path}: kwargs must be a mapping")
    return cfg["factory"], kwargs, server_settings(cfg.get("server"), f"{path}: server")


def served_by_experiment(path: str) -> tuple[str, dict, dict[str, Any]]:
    """What the policy server of the experiment file `path` loads and where it
    listens: `factory`, `kwargs` and `server:` of the policy its `nodes` give
    (`serve-policy --experiment`). Only this file is read: the server may run in an
    environment and a directory without the robot's configuration."""
    from pathlib import Path

    import yaml

    try:
        raw = yaml.safe_load(Path(path).expanduser().read_text())
    except OSError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    nodes = raw.get("nodes") if isinstance(raw, dict) else None
    policies = [
        node
        for key, node in (nodes or {}).items()
        if str(key).startswith("controllers.")
        and isinstance(node, dict)
        and isinstance(node.get("factory"), str)
    ]
    if len(policies) != 1:
        raise ConfigError(
            f"{path}: expected one policy under nodes (controllers.<name> with a "
            f"factory), found {len(policies)}"
        )
    kwargs = policies[0].get("kwargs") or {}
    if not isinstance(kwargs, dict):
        raise ConfigError(f"{path}: kwargs must be a mapping")
    server = server_settings(policies[0].get("server"), f"{path}: server")
    return policies[0]["factory"], kwargs, server


class RemotePolicyError(RuntimeError):
    """The policy on the server raised; the message carries its type and text."""


# -- messages ---------------------------------------------------------------------


def encode(message: object) -> bytes:
    """`message` (None, bool, numbers, strings, lists, dicts with string keys, numpy
    arrays) as a JSON header plus the arrays' bytes."""
    buffers: list[bytes] = []

    def pack(value: object) -> object:
        if isinstance(value, np.ndarray):
            data = np.ascontiguousarray(value)
            if data.dtype.hasobject:
                raise TypeError("arrays of Python objects cannot be sent")
            buffers.append(data.tobytes())
            return {
                "__array__": len(buffers) - 1,
                "dtype": data.dtype.str,
                "shape": list(data.shape),
            }
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, dict):
            if not all(isinstance(k, str) for k in value):
                raise TypeError("only string keys can be sent")
            return {k: pack(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [pack(v) for v in value]
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        raise TypeError(f"cannot send a {type(value).__name__}")

    header = json.dumps(
        {"body": pack(message), "sizes": [len(b) for b in buffers]}
    ).encode()
    return b"".join([struct.pack("<I", len(header)), header, *buffers])


def decode(data: bytes) -> Any:
    (size,) = struct.unpack_from("<I", data)
    header = json.loads(data[4 : 4 + size].decode())
    offsets, at = [], 4 + size
    for length in header["sizes"]:
        offsets.append((at, length))
        at += length
    if at != len(data):
        raise ValueError("truncated message")

    def unpack(value: object) -> object:
        if isinstance(value, dict):
            if "__array__" in value:
                start, length = offsets[value["__array__"]]
                dtype = np.dtype(value["dtype"])
                flat = np.frombuffer(
                    data, dtype=dtype, count=length // dtype.itemsize, offset=start
                )
                return flat.reshape(value["shape"]).copy()
            return {k: unpack(v) for k, v in value.items()}
        if isinstance(value, list):
            return [unpack(v) for v in value]
        return value

    return unpack(header["body"])


def _address(address: str) -> tuple[str, int]:
    host, _, port = address.rpartition(":")
    if not host or not port.isdigit():
        raise ConfigError(f"policy address {address!r}: expected host:port")
    return host, int(port)


def _authkey(authkey: bytes | str | None, authkey_env: str) -> bytes:
    key = authkey if authkey is not None else os.environ.get(authkey_env)
    if not key:
        raise ConfigError(
            f"remote policy: set the shared secret in {authkey_env} on both sides "
            "(any string; it authenticates the connection)"
        )
    return key.encode() if isinstance(key, str) else key


def _spec(fields: dict) -> PolicySpec:
    return PolicySpec(
        observation=fields["observation"],
        action=tuple(fields["action"]),
        rate_hz=fields["rate_hz"],
        dataset_fps=fields["dataset_fps"],
        history=fields.get("history", 1),
        hold=tuple(fields.get("hold", ())),
        units=tuple(fields.get("units", ())),
        inference=fields.get("inference", "sync"),
    )


# -- client -----------------------------------------------------------------------


class RemotePolicy:
    """The Policy the node loads; every call is answered by the server's policy."""

    def __init__(
        self,
        address: str = ADDRESS,
        authkey_env: str = AUTHKEY_ENV,
        timeout_s: float = 30.0,
        connect_timeout_s: float = 30.0,
    ):
        self.address, self.timeout_s = address, float(timeout_s)
        self.calls = 0  # the number of the last call; its answer repeats it
        target, key = _address(address), _authkey(None, authkey_env)
        deadline = time.monotonic() + connect_timeout_s
        while True:  # the server may still be loading its model
            try:
                self.connection: Connection = Client(target, authkey=key)
                break
            except ConnectionRefusedError as exc:
                if time.monotonic() >= deadline:
                    raise ConfigError(
                        f"remote policy: no server at {address} (start it with "
                        "`python -m roboloom.policy.remote <module:callable>`)"
                    ) from exc
                time.sleep(0.2)

    def _call(self, method: str, *arguments: object) -> Any:
        self.calls += 1
        self.connection.send_bytes(encode([self.calls, method, *arguments]))
        deadline = time.monotonic() + self.timeout_s
        while True:
            if not self.connection.poll(max(0.0, deadline - time.monotonic())):
                raise TimeoutError(
                    f"remote policy {self.address}: no answer to {method} within "
                    f"{self.timeout_s:g} s"
                )
            reply = decode(self.connection.recv_bytes())
            if isinstance(reply[0], str):  # a server from before calls had numbers
                status, *result = reply
                break
            if reply[0] == self.calls:
                status, *result = reply[1:]
                break
            # the answer to a call that timed out earlier: not this one's
        if status == "error":
            kind, text, trace = result
            raise RemotePolicyError(f"{kind}: {text}\n(on the policy server)\n{trace}")
        return result[0]

    def options(self) -> dict:
        """The served policy's `options()` (empty when it has none)."""
        return self._call("options")

    def bind(self, spec: PolicySpec) -> None:
        """Forward `bind` to the served policy."""
        self._call("bind", asdict(spec))

    def reset(self) -> None:
        """Forward `reset` to the served policy."""
        self._call("reset")

    def infer(self, observation: dict[str, Any]) -> np.ndarray:
        """The served policy's answer to `observation`."""
        return np.asarray(self._call("infer", observation), dtype=np.float64)

    def close(self) -> None:
        """Close the connection to the server."""
        self.connection.close()


def connect(
    address: str = ADDRESS,
    authkey_env: str = AUTHKEY_ENV,
    timeout_s: float = 30.0,
    connect_timeout_s: float = 30.0,
) -> RemotePolicy:
    """`roboloom.policy.remote:connect`: the policy served at `address` (host:port).
    `timeout_s` bounds one call (an `infer`), `connect_timeout_s` the wait for the
    server to come up; the secret is read from the environment variable `authkey_env`."""
    return RemotePolicy(address, authkey_env, timeout_s, connect_timeout_s)


# -- server -----------------------------------------------------------------------


def _answer(policy: Policy, method: str, arguments: list) -> object:
    if method == "options":
        options = getattr(policy, "options", None)
        return dict(options()) if callable(options) else {}
    if method == "bind":
        bind = getattr(policy, "bind", None)
        if callable(bind):
            bind(_spec(arguments[0]))
        return None
    if method == "reset":
        policy.reset()
        return None
    if method == "infer":
        return np.asarray(policy.infer(arguments[0]))
    raise ValueError(f"unknown call {method!r}")


BUSY = (
    "the policy server is serving another policy node (one at a time); end that "
    "dataflow, or start a second server on another --address"
)


def _serve_client(policy: Policy | None, connection: Connection) -> None:
    """Answer one client's calls until it disconnects; without a policy (the server is
    busy with another client) every call is answered with that."""
    while True:
        try:
            call = decode(connection.recv_bytes())
        except (EOFError, ConnectionError):
            return
        # the call's number comes first; a client from before calls had numbers sends none
        numbered = not isinstance(call[0], str)
        method, *arguments = call[1:] if numbered else call
        try:
            if policy is None:
                raise RuntimeError(BUSY)
            reply: list = ["ok", _answer(policy, method, arguments)]
        except Exception as exc:  # noqa: BLE001 - reported to the policy node
            reply = ["error", type(exc).__name__, str(exc), traceback.format_exc()]
        try:
            connection.send_bytes(encode([call[0], *reply] if numbered else reply))
        except (EOFError, ConnectionError):
            return


def _serve_connection(
    policy: Policy, connection: Connection, busy: threading.Lock
) -> None:
    with connection:
        if not busy.acquire(blocking=False):
            _serve_client(None, connection)  # tells it why, instead of a silent wait
            return
        try:
            _serve_client(policy, connection)
        finally:
            busy.release()


def serve(
    policy: Policy | str,
    address: str = ADDRESS,
    authkey: bytes | str | None = None,
    kwargs: dict | None = None,
    authkey_env: str = AUTHKEY_ENV,
    clients: int | None = None,
    ready: Any = None,
) -> None:
    """Answer policy nodes at `address` with `policy` (an object with `reset` and
    `infer`, or a "module:callable" factory called with `kwargs`), one at a time, until
    interrupted (or after `clients` connections). `ready`, if given, is called once the
    server listens."""
    key = _authkey(authkey, authkey_env)
    served = load_policy(policy, kwargs) if isinstance(policy, str) else policy
    busy = threading.Lock()  # held by the one client the policy answers
    threads: list[threading.Thread] = []
    with Listener(_address(address), authkey=key) as listener:
        if ready is not None:
            ready()
        count = 0
        while clients is None or count < clients:
            try:
                connection = listener.accept()
            except Exception as exc:  # noqa: BLE001 - a wrong key: wait for the next
                print(f"policy server: refused a connection ({exc})")
                continue
            count += 1
            # on a thread, so the next connection is accepted (and told the server is
            # busy) while this one is served
            thread = threading.Thread(
                target=_serve_connection,
                args=(served, connection, busy),
                name="policy-client",
                daemon=True,
            )
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m roboloom.policy.remote",
        description="Serve a policy to a roboloom policy node "
        "(factory: roboloom.policy.remote:connect).",
    )
    add_arguments(parser)
    try:
        run(parser.parse_args(argv))
    except ConfigError as exc:
        raise SystemExit(f"error: {exc}") from None


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """The words of `roboloom serve-policy` and `python -m roboloom.policy.remote`."""
    parser.add_argument(
        "policy", nargs="?", help="module:callable returning the policy"
    )
    parser.add_argument(
        "--from",
        dest="from_",
        metavar="POLICY_YAML",
        help="serve the policy of this policy node file (its factory, kwargs and "
        "server.address), e.g. .roboloom/<robot>/nodes/policy.yaml",
    )
    parser.add_argument(
        "--experiment",
        metavar="EXPERIMENT_YAML",
        help="serve the policy of this experiment file (the factory, kwargs and "
        "server.address its nodes give the policy), e.g. "
        "configs/roboloom/<name>.yaml",
    )
    parser.add_argument(
        "--kwargs", type=json.loads, default=None, help="JSON arguments of the callable"
    )
    parser.add_argument("--address", default=None, help=f"host:port ({ADDRESS})")
    parser.add_argument(
        "--authkey-env",
        default=None,
        help=f"environment variable holding the shared secret ({AUTHKEY_ENV})",
    )


def run(args: argparse.Namespace) -> None:
    """Serve what the words say: a node file's policy (`--from`) or `policy`; the
    other words replace the file's."""
    factory: str | None = args.policy
    kwargs: dict = {}
    server: dict[str, Any] = {}
    given = [x for x in (args.policy, args.from_, args.experiment) if x]
    if len(given) > 1:
        raise ConfigError(
            "give one of: the policy, --from <policy YAML>, --experiment <file>"
        )
    if args.from_:
        factory, kwargs, server = served(args.from_)
    elif args.experiment:
        factory, kwargs, server = served_by_experiment(args.experiment)
    if not factory:
        raise ConfigError(
            "give module:callable, --from <policy YAML> or --experiment <file>"
        )
    address = args.address or server.get("address", ADDRESS)
    print(f"policy server: loading {factory}", flush=True)
    serve(
        factory,
        address,
        kwargs=kwargs if args.kwargs is None else args.kwargs,
        authkey_env=args.authkey_env or server.get("authkey_env", AUTHKEY_ENV),
        ready=lambda: print(f"policy server: listening on {address}", flush=True),
    )


if __name__ == "__main__":
    main()
