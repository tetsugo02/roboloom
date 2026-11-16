# Policy server <span class="status status--mock">Mock only</span>

How to run the policy in a process and environment of its own, apart from roboloom. The keys are listed in [Policy configuration](../reference/configuration/policy.md#backend) and the command in the [CLI](../reference/cli.md#serve-policy).

## Running the policy in another process { #running-the-policy-in-another-process }

A policy is loaded in one of two places, chosen with `backend` in the policy's YAML. The policy itself (`bind`, `reset`, `infer`, `options`) is written the same for both.

| `backend` | Process that loads the policy | When |
| --- | --- | --- |
| `process` (default) | The policy node itself | The policy's dependencies fit roboloom's environment; no server to start |
| `server` | A policy server started separately | A model whose dependencies do not fit (another torch version, for example), or that runs on another machine |

```yaml
# nodes/policy.yaml
factory: my_lab.policies:load        # the policy itself, with either backend
kwargs: {checkpoint: "..."}
backend: server                      # left out: process
server: {address: "127.0.0.1:18765"} # read only with backend: server
```

With `backend: server` the policy node does not load `factory`; it connects to `server.address`. The server starts from the same YAML: it reads `factory`, `kwargs` and `server.address`.

## Starting the server { #starting-the-server }

```bash
# where the model lives: its own environment, with roboloom installed without extras
export ROBOLOOM_POLICY_AUTHKEY=some-shared-secret
uv run roboloom serve-policy --experiment configs/roboloom/drawer.yaml   # the experiment's policy
# from a policy YAML: roboloom serve-policy --from .roboloom/rakuda2/nodes/policy.yaml
# without roboloom's command line: python -m roboloom.policy.remote --from <the same file>
# without the YAML: roboloom serve-policy my_lab.policies:load --kwargs '{"checkpoint": "..."}'
```

| Key of `server` | Meaning |
| --- | --- |
| `address` | `host:port` (default `127.0.0.1:18765`) |
| `timeout_s` | Bound of one `infer` (default 30 s) |
| `connect_timeout_s` | Bound of the wait for the server to come up (default 30 s) |
| `authkey_env` | Environment variable holding the shared secret (default `ROBOLOOM_POLICY_AUTHKEY`); the environment roboloom runs in needs the same value |

- The module of `factory` and relative paths in `kwargs` are resolved in the directory and environment the server was started in.
- With `backend: server`, `roboloom infer --policy` and `--policy-kwargs` are refused (the server loads the policy).
- The earlier form, `factory: roboloom.policy.remote:connect` with `kwargs: {address: ...}`, still works.

## How the server behaves { #behavior }

- The server loads the model once and serves one policy node at a time, across episodes and sessions. Start it before `roboloom infer`; the node waits up to `connect_timeout_s` (30 s) for it. A second node that connects while one is served is told so (`the policy server is serving another policy node`) instead of waiting.
- A call that gets no answer within `timeout_s` fails that episode (`TimeoutError`). Its answer, when it comes later, is dropped: every call carries a number and only the answer with that number is taken.
- The server side needs only numpy and roboloom without extras (no LeRobot, no torch from roboloom).
- An exception raised by the policy is shown on the controller's line, as for a policy in the same process ([When the policy fails](custom.md#failures)).
- The shared secret authenticates both ends; the data is not encrypted. Keep the address on the loopback interface or a trusted network. Messages carry a JSON header and raw array bytes (no pickle).
- Over a network, every `infer` sends the observation (about 0.9 MB per 480×640 image, times `observation_history`).
