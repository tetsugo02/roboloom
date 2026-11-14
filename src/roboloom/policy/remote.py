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
and serves one policy node at a time, across episodes and sessions.

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
import time
import traceback
from dataclasses import asdict
from multiprocessing.connection import Client, Connection, Listener
from typing import Any

import numpy as np

from ..errors import ConfigError
from . import Policy, PolicySpec, load_policy

ADDRESS = "127.0.0.1:18765"
AUTHKEY_ENV = "ROBOLOOM_POLICY_AUTHKEY"
OPTIONS = ("observation_history", "hold", "action_horizon")


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
        self.connection.send_bytes(encode([method, *arguments]))
        if not self.connection.poll(self.timeout_s):
            raise TimeoutError(
                f"remote policy {self.address}: no answer to {method} within "
                f"{self.timeout_s:g} s"
            )
        status, *result = decode(self.connection.recv_bytes())
        if status == "error":
            kind, text, trace = result
            raise RemotePolicyError(f"{kind}: {text}\n(on the policy server)\n{trace}")
        return result[0]

    def options(self) -> dict:
        return self._call("options")

    def bind(self, spec: PolicySpec) -> None:
        self._call("bind", asdict(spec))

    def reset(self) -> None:
        self._call("reset")

    def infer(self, observation: dict[str, Any]) -> np.ndarray:
        return np.asarray(self._call("infer", observation), dtype=np.float64)

    def close(self) -> None:
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


def _serve_client(policy: Policy, connection: Connection) -> None:
    while True:
        try:
            method, *arguments = decode(connection.recv_bytes())
        except (EOFError, ConnectionError):
            return
        try:
            reply: list = ["ok", _answer(policy, method, arguments)]
        except Exception as exc:  # noqa: BLE001 - reported to the policy node
            reply = ["error", type(exc).__name__, str(exc), traceback.format_exc()]
        try:
            connection.send_bytes(encode(reply))
        except (EOFError, ConnectionError):
            return


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
            with connection:
                _serve_client(served, connection)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m roboloom.policy.remote",
        description="Serve a policy to a roboloom policy node "
        "(factory: roboloom.policy.remote:connect).",
    )
    parser.add_argument("policy", help="module:callable returning the policy")
    parser.add_argument(
        "--kwargs", type=json.loads, default={}, help="JSON arguments of the callable"
    )
    parser.add_argument("--address", default=ADDRESS, help="host:port to listen on")
    parser.add_argument(
        "--authkey-env",
        default=AUTHKEY_ENV,
        help="environment variable holding the shared secret",
    )
    args = parser.parse_args(argv)
    print(f"policy server: loading {args.policy}")
    serve(
        args.policy,
        args.address,
        kwargs=args.kwargs,
        authkey_env=args.authkey_env,
        ready=lambda: print(f"policy server: listening on {args.address}"),
    )


if __name__ == "__main__":
    main()
