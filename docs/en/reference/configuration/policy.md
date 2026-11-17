# The policy controller (policy)

| Scope | Description |
| --- | --- |
| `type: policy` | Drives every follower in configuration order; [common controller keys](controllers.md#common), [running policies](../../policy/index.md) |

## Loading the policy { #loading }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `factory` | text | `required` | — | module:callable returning a policy; installed packages, then robot directory |
| `kwargs` | mapping | `{}` | — | Factory arguments |

## Where it runs (backend) { #backend }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `backend` | text | `process` | — | process: load in the node; server: remote inference (mock only) |
| `server` | mapping | `{}` | — | Server connection settings below; [remote guide](../../policy/remote.md) |
| `server.address` | text | `127.0.0.1:18765` | — | Server host:port |
| `server.authkey_env` | text | `ROBOLOOM_POLICY_AUTHKEY` | — | Shared secret environment variable name |
| `server.timeout_s` | number | `30` | s | Call timeout |
| `server.connect_timeout_s` | number | `30` | s | Connection wait |

## Observation and action { #observation-and-action }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `observe` | list[text] | `[]` | — | Input/sensor sources; follower state is always included |
| `rate_hz` | number | `required` | Hz | Policy action rate; use training rate |
| `action_horizon` | integer | `1` | actions | Use this many actions from each chunk |
| `max_speed` | mapping | `required` | follower unit/s | One positive speed per follower |
| `observation_history` | integer | `1` | frames | N frames in infer observation[history], plus preceding sent actions |
| `hold` | list[text] | `[]` | — | Replace these follower.joint targets before hooks; claimed hooks may change them |
| `home` | mapping | `—` | — | Saved pose; [home](control.md#home) |

## Inference (inference) { #inference }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `inference` | text | `sync` | — | sync or async (mock only); [guide](../../policy/async.md#asynchronous-inference) |
| `replan_at` | auto or integer | `auto` | actions | Async replan queue threshold; auto: half horizon, capped at horizon - 1 |

## Interpolation { #interpolation }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `interpolation_multiplier` | auto or integer | `auto` | — | Commands at rate_hz × N, whole Hz and at most slowest follower control_hz; auto: largest valid N |
| `interpolation` | text | `linear` | — | linear or pchip; [guide](../../policy/async.md#interpolation) |

## teleop { #teleop }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `teleop` | list[path] | `—` | — | Joint-controller YAMLs relative to this file; cover all followers exactly once; no feedback; [intervention](../../policy/intervention.md#teleop) |

## Hooks { #hooks }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `hooks` | list[mapping] | `[]` | — | Mock only. Policy controllers only; YAML order. [How-to](../../policy/hooks.md), [execution](../../explanation/hooks.md) |
| `hooks[].factory` | text | `—` | — | module:callable; exactly one of factory or from |
| `hooks[].from` | text | `—` | — | policy only, at most once; required for policy-contributed writes |
| `hooks[].kwargs` | mapping | `{}` | — | Factory arguments; cannot be used with from |
| `hooks[].writes` | list[text] | `[]` | — | Unique valid follower.joint names; limit containing all declared writes; nonempty enables action.filtered |
| `hooks[].sources` | list[text] | `requirements.sources` | — | Subset of declared policy/teleop; may only narrow; teleop requires teleop: |
| `hooks[].on_error` | text | `requirements or fail/pass` | — | fail: fail episode; hold: writable entries use held; pass: unchanged. Writing defaults fail, observe-only defaults pass |
| `hooks[].budget_ms` | number | `requirements or 0.5 / rate_hz` | ms | Positive finite; measured only, overruns warn/count; teleop uses input period |
| `hooks[].name` | text | `Class:index` | — | Nonempty log/stats name |

## Load rules { #load-rules }

| Rule | Behavior |
| --- | --- |
| `options()` | Policy observation_history, hold and action_horizon override YAML |
| `--policy / --policy-kwargs` | Override factory/kwargs only with process backend |
| `stale observation` | No pop or step; hold followers until fresh, then reset and PolicyRestarted(stale_recovered) |
| `from: policy` | Writing hooks require the slot and writes limit; absent observe-only contributions go first |
| `backend: server` | from: policy + nonempty writes is refused; step hooks stay local |
| `overlap` | Allowed, logged at load; later hook wins |
| `API` | HOOKS_API = 1; newer requirements refused |

## Example { #example }

| Example | Link |
| --- | --- |
| Policy factory and local release gate | [Hooks](../../policy/hooks.md#configure) |
