# The policy controller (policy)

Keys of a `type: policy` controller (`nodes/policy.yaml` in the template). How to run a policy, and why it works as it does, is on the pages of [Running a policy](../../policy/index.md).

A `policy` controller drives every follower in configuration order (`followers:` lists them all). Besides the [keys of every controller](controllers.md#common) (`type`, `followers`, `command_deadline_ms`, `follower_timeout_ms`) it reads the following.

## Loading the policy { #loading }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `factory` | text | required | — | `module:callable` returning the policy; also looked up in the robot's directory ([Your own policy](../../policy/custom.md), [LeRobot policies](../../policy/lerobot.md)) |
| `kwargs` | mapping | `{}` | — | Arguments for `factory` (a checkpoint, ...) |

When the policy has `options()`, the `observation_history`, `hold` and `action_horizon` it returns win over the YAML. `--policy` and `--policy-kwargs` replace `factory` and `kwargs` (not with `backend: server`).

## Where it runs (backend) { #backend }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `backend` | text | `process` | — | `process`: this node loads the policy. `server`: it connects to a policy server <span class="status status--mock">Mock only</span> |
| `server` | mapping | `{}` | — | Where the server of `backend: server` listens (table below) |

Start the server of `backend: server` with `roboloom serve-policy --from <this file>` (or `--experiment`); the server reads `factory` and `kwargs`. See [Running the policy in another process](../../policy/remote.md#running-the-policy-in-another-process).

| `server` key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `address` | text | `127.0.0.1:18765` | — | The server's `host:port` |
| `authkey_env` | text | `ROBOLOOM_POLICY_AUTHKEY` | — | Name of the environment variable holding the shared secret |
| `timeout_s` | number | `30` | s | Limit of one call (`infer`, ...) |
| `connect_timeout_s` | number | `30` | s | How long to wait for the server to come up |

## Observation and action { #observation-and-action }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `observe` | list of text | `[]` | — | Inputs and sensors given to the policy; follower states are always given ([Choosing observations](../../policy/custom.md#observations)) |
| `rate_hz` | number | required | Hz | The policy's action rate (the rate it was trained at) |
| `action_horizon` | integer | `1` | actions | Actions of a chunk that are used; when they run out the policy infers again |
| `max_speed` | `{follower: value}` | required | follower unit/s | How far a policy target may move per period, one value per follower ([Units](index.md#units)) |
| `observation_history` | integer | `1` | frames | 2 or more gives the last N frames of observations and executed actions as `observation["history"]` |
| `hold` | list of text | `[]` | — | `<follower>.<joint>` entries the policy does not drive; they keep their held target ([hold](../../policy/custom.md#hold)) |
| `home` | mapping | — | — | Saved pose moved to before starting ([home](control.md#home), [how to use it](../../policy/run.md#home)) |

When the latest sample of an observed input or sensor gets older than the recorder's `max_age_ms.<node>`, the policy stops (`stale_observation`; the followers hold). Once it is fresh again the policy restarts after `reset()`.

## Inference (inference) { #inference }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `inference` | text | `sync` | — | `sync`: no command while inferring. `async`: inference runs on a worker thread while the queued actions keep being sent <span class="status status--mock">Mock only</span> |
| `replan_at` | `auto` or integer | `auto` | actions | With `async`, the next inference starts when this many actions are left. `auto` is half of `action_horizon`; values are capped at `action_horizon − 1` |

See [Asynchronous inference](../../policy/async.md#asynchronous-inference).

## Interpolation { #interpolation }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `interpolation_multiplier` | `auto` or integer | `auto` | — | Commands go out at `rate_hz × N`, N steps between consecutive actions. `auto` is the largest N with `rate_hz × N` whole Hz and at most the slowest follower's `control_hz`; 1 does not interpolate |
| `interpolation` | text | `linear` | — | `linear` (straight line) or `pchip` (a monotone cubic through the actions) |

An integer N must keep `rate_hz × N` whole Hz and at most `control_hz`. See [Interpolation](../../policy/async.md#interpolation).

## teleop { #teleop }

| Key | Type | Default | Unit | Description |
| --- | --- | --- | --- | --- |
| `teleop` | list of paths | — | — | Files of the controllers the leader drives through, relative to this file's directory; the operator can drive before and during an episode (an intervention) |

- Only `type: joint` controllers can be listed (`parts` and `pose_ik` cannot take over from a policy), and they cannot have `feedback`.
- Together the `teleop` controllers drive every follower of the policy exactly once.
- Each joint holds until the leader comes within `alignment_tolerance` of the target it holds, or crosses it, and then follows.
- Commands of the `teleop` controllers are recorded with `action.intervention` 1.

See [Teleop and intervention](../../policy/intervention.md#teleop).

## Example { #example }

```yaml
# nodes/policy.yaml
type: policy
followers: [follower]
factory: roboloom.policy:hold
kwargs: {}
observe: [camera]
rate_hz: 15
action_horizon: 8
max_speed: {follower: 1024}
command_deadline_ms: 300
```

```yaml
# nodes/policy_teleop.yaml (option policy_teleop)
extends: policy.yaml
teleop: [controller.yaml]
```
