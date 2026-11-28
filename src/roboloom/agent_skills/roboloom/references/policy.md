# Policies

A `type: policy` controller drives **every follower** with a learned policy, inside the
dataflow (policy node). Own policies and LeRobot checkpoints load the same way.

> Status: own policies have been used with the Rakuda2 configuration and mock devices.
> LeRobot policies were checked only with the mock PiPER + Pika configuration (a briefly
> trained ACT), not on hardware or with a well-trained policy. Tell the user.

## Configuration (`nodes/policy.yaml`, Rakuda2 template)

```yaml
type: policy
followers: [follower]               # every follower, in configuration order
factory: roboloom.policy:hold       # "module:callable" returning the policy (template default: hold still)
kwargs: {}
observe: [camera]                  # explicit inputs/sensors; [] for joint state only
rate_hz: 15                         # set to the training dataset's dataset_fps
interpolation_multiplier: auto      # commands at rate_hz * N; left out/auto: from control_hz
action_horizon: 8                   # chunk steps executed before asking again (1 for mode: step)
max_speed: {follower: 1024}         # per follower, follower unit/s
command_deadline_ms: 300
```

- The `factory` module is looked up in installed packages first, then in
  `.roboloom/<robot>/` (so `.roboloom/rakuda2/my_policy.py` → `factory: my_policy:load`,
  no `PYTHONPATH`). An installed module of the same name wins.
- In the Rakuda2 template the option `policy` removes the leader and joint controller,
  adds `controllers.policy`, makes DIGIT optional, conflicts with `gravity`, and records to
  `-eval`. `roboloom infer` enables it; `--policy` / `--policy-kwargs` override the YAML.
- Start real-hardware inference with the default `roboloom.policy:hold` to check the path.
- `interpolation_multiplier: N` (left out/`auto`: the largest N with `rate_hz * N` whole Hz and
  <= the slowest follower's `control_hz`, e.g. 8 for 15 Hz at 120 Hz; `1`: no interpolation)
  commands at `rate_hz * N`: one action every N
  ticks, the straight line from the previous action in between (LeRobot's
  `ActionInterpolator`; roboloom also ramps the first action from the held target).
  Keep `rate_hz` at the training fps; never raise it to command faster. `rate_hz * N`
  must be whole Hz and <= every follower's `control_hz`. Followers lag one action period;
  the recorded `action` is the interpolated target.
- `interpolation: pchip` (default `linear`): a monotone cubic through the same actions
  (each reached at its own time, no overshoot between two actions; uses the next queued
  action, falls back to the line's slope at a chunk's last action). Speed is continuous
  at an action only while that lookahead holds: it can jump at a chunk boundary,
  with `action_horizon: 1`, and when `inference: async` replaces the queue.
- `inference: async` (default `sync`): `infer` runs on a worker thread while queued
  actions keep going; the next inference starts when `replan_at` actions are left (`auto`:
  half of `action_horizon`); the new chunk replaces the queue minus the d actions executed
  since its observation (`dropped`). Queue empty first: followers hold (`late_inference`).
  No blending of chunks; LeRobot RTC: not supported. A chunk must start at its
  observation's time: `roboloom.policy.replay:load` refuses async (`spec.inference`).
- `home: {pose, max_speed, tolerance[, timeout_s]}` (several followers: `{follower: {...}}`)
  moves the followers to a `capture-pose` pose with `home` / `Session.home()` /
  `infer --home`. Arrival is measured: every joint within `tolerance` within 2 s after the
  move (`reached`), else `short` – home fails and start is refused. Same for teleop homes.
- `teleop: [controller.yaml]` (Rakuda2 option `policy_teleop`, dataset `-eval-teleop`):
  session commands `teleop` (outside an episode: drive with the leader, unrecorded;
  during one: an intervention), `policy` (hand back during an episode), `stop_teleop`
  (end teleop outside an episode); `Session.teleop()/policy()/stop_teleop()`, keys `t`/`p`.
  `Session.stop_teleop()` returns once every follower holds.
  Joints are taken over one by one: each holds until the leader is within the teleop
  controller's `alignment_tolerance` or crosses it (a gripper stays closed until the
  trigger reaches it). Rows a person drove: `action.intervention` = 1. Only `type: joint`
  teleop controllers (pose_ik refused). Handing back calls `policy.reset()`.

- `observation_history: N` (default 1): the observation is sampled once per action and
  `infer` also gets `observation["history"]`: every array stacked `[N, ...]`, oldest first,
  current frame last (the first frame fills it), plus `"action"` `[N, n]`, the command
  sent before each frame (after `max_speed`, as recorded in `action`). `hold: [<follower>.<joint>, ...]`: action entries the policy
  does not drive; whatever it returns there (NaN too) becomes the held target, other
  entries must be finite. A policy may return both (and `action_horizon`) from an optional
  `options()`; it wins over the YAML. `bind(spec)` sees `spec.history`, `spec.hold`,
  `spec.units`. Normalization, resizing and decoding deltas stay in the policy.
- An observed input or sensor older than `recorder.max_age_ms.<node>` stops the policy
  (`stale_observation`, followers hold, also mid-interpolation); when fresh again it restarts with `reset()`.

- A model that cannot share roboloom's environment (other torch) or runs elsewhere:
  keep the policy's own `factory`/`kwargs` in the YAML and add `backend: server`
  (default `backend: process`: the policy node loads it) with
  `server: {address: "127.0.0.1:18765"}` (also `timeout_s`, `connect_timeout_s`,
  `authkey_env`). Start the server in the model's environment and directory with
  `roboloom serve-policy --from <that YAML>` (or, when an experiment file gives the
  policy, `--experiment <file>`; also `python -m roboloom.policy.remote --from
  ...`; needs only numpy + roboloom without extras). `--policy`/`--policy-kwargs` are
  refused with `backend: server`. The older `factory: roboloom.policy.remote:connect`
  with `kwargs: {address: ...}` still works.
  Both sides need the same `ROBOLOOM_POLICY_AUTHKEY`. `bind`/`reset`/`infer`/`options` are
  forwarded; policy errors show on the controller line. Not encrypted: loopback or a
  trusted network only.

- roboloom fixes no model form: joint selection (`hold`), normalization, image
  preprocessing and decoding the model's action form (deltas) into absolute targets are
  the policy's; history, interpolation, speed limit and safety are roboloom's. A lower
  action rate: train on every k-th row, `rate_hz = dataset_fps / k`. A worked example
  (train script + policy with `options()`) is `examples/policies/chunk_mlp.py` in the
  roboloom repository. For training, table columns are in `LeRobotDataset(...).hf_dataset`.
- `roboloom.policy.replay:load` (`kwargs: {path, episode: 0, horizon: 8, stride: 1}`)
  replays one recorded episode's `action` (or a `.npy` `[T, n]`) open loop through the
  policy path: checks the path without a model. Names and rate are checked at load;
  `home` to the first pose first, low `max_speed`.

- With `teleop:` and `home:`, `home` moves the teleop leader to the pose as well; leader
  joints in a `law: position` group stay there afterwards (e.g. torso and head, to keep
  the camera angle while Teleop moves the arms). Order: `home`, Teleop if needed, `start`.

## Writing a policy

Rakuda2 defaults to joint state + RealSense without DIGIT. Set `observe: []` for joint
state only, or `observe: [camera, digit_left, digit_right]` and enable `digit` for tactile
inputs. Enabling `digit` alone only adds recorded sensors; it does not change policy
inputs. All observed sensors must exist in `sensors`. To avoid opening unused sensors,
also remove their nodes from `config.yaml`. A checkpoint requiring DIGIT cannot run
unchanged without it; LeRobot checks this at load, custom policies can use `bind`.

Existing project files are not overwritten on update. Migrate older Rakuda2 configs
with `roboloom init rakuda2 --update` (adds `nodes/policy.yaml`, lists the options
`config.yaml` lacks), then by removing `options.policy.requires: [digit]` and setting `observe: [camera]` in
`nodes/policy.yaml`. Evaluation datasets are `rakuda2-eval` without DIGIT and
`rakuda2-digit-eval` with the `digit` option.

```python
# my_lab/policies.py  (or .roboloom/<robot>/my_policy.py)
import numpy as np


class MyPolicy:
    def __init__(self, checkpoint: str):
        self.checkpoint = checkpoint

    def bind(self, spec):  # optional, once after loading; raise if the config differs
        if "observation.images.camera" not in spec.observation:
            raise ValueError("add camera to observe")

    def reset(self):  # each episode start
        pass

    def infer(self, observation) -> np.ndarray:
        state = observation["observation.state"]  # float32 [n]
        image = observation["observation.images.camera"]  # uint8 [h, w, 3] RGB
        task = observation["task"]
        return np.asarray(state)  # [n] one step, or [H, n] a chunk


def load(checkpoint: str) -> MyPolicy:
    return MyPolicy(checkpoint)
```

- Protocol: `roboloom.Policy` (`reset()`, `infer(observation)`); optional `bind(spec)`
  with `roboloom.policy.PolicySpec(observation, action, rate_hz, dataset_fps)`:
  `observation` maps feature name → `{"dtype", "shape", "names"}`, `action` is the tuple
  of `<follower>.<joint>` names.
- Observation keys are the dataset feature names; output is joint targets in the order and
  **units** of the recorded `action` (Rakuda2: 17 counts; PiPER+Pika mock: 14 rad).
- A failing `bind` marks the controller `failed`; `infer` and `Session.wait_ready` stop
  with the reason.
- `infer` or `reset` raising during an episode: the controller turns `failed`, the
  followers hold, the episode is discarded (`EpisodeFailed`). After `stop`/`discard`
  the policy is `ready` again; the error stays on its row until the next `start`.

## Running

```bash
uv run roboloom infer --seconds 30 --policy my_lab.policies:load \
  --policy-kwargs '{"checkpoint": "outputs/act/last"}' --task "pick up the cup"
# or everything in the project's configs/roboloom/cup.yaml (configuration.md):
uv run roboloom infer --experiment cup
```

```python
from roboloom import Session

with Session.launch(
    "rakuda2",
    options=["policy"],
    policy="my_lab.policies:load",
    policy_kwargs={"checkpoint": "outputs/act/last"},
) as s:
    s.wait_ready()
    for k in range(10):
        # judge(ep: EpisodeResult) -> "success" | "failure" | None: your own check
        s.record(f"pick up the cup (eval {k})", seconds=30, label=judge)
```

`label`: `"success"` / `"failure"`, or a function of the stopped `EpisodeResult`
returning one (None: no verdict). The verdict, the policy's status (`infer_max_ms`,
`dropped`, `error`) and the metrics go to the evaluation dataset's
`meta/roboloom_episodes.jsonl`; `roboloom label [robot] --with policy <episode>
success|failure` sets it afterwards and `roboloom check-dataset --with policy` counts
them. From the operator screen: type `save success` / `save failure`.

By default inference is synchronous: no command is sent during `infer`; if it exceeds
`command_deadline_ms` the followers HOLD and wait (`inference: async` avoids the pause). Targets are clipped to `max_speed` and
checked by `FollowerSafety` as in teleoperation. LeRobot RTC is not supported. `InProcessSession.step(policy=fn)` is the in-process alternative
(see [in-process.md](in-process.md)).

## LeRobot checkpoints

Needs `uv add 'roboloom[policy]'` (+ `lerobot[diffusion]`, `lerobot[smolvla]`,
`lerobot[pi]` for those policies).

```yaml
factory: roboloom.policy.lerobot:load
kwargs:
  path: outputs/train/act/checkpoints/last/pretrained_model   # or a Hub ID
  device: auto      # cuda if available
  mode: step        # step (select_action; use action_horizon: 1) or chunk (ACT-like only)
  rename: {}        # {checkpoint feature: this config's feature}
  # revision: main  # Hub revision
action_horizon: 1
```

Loading checks the checkpoint's `observation.state`, `observation.images.*`,
`observation.environment_state` and action size against this configuration and refuses
mismatches by name. ACT temporal ensembling works only with `mode: step`.

## Training with LeRobot

```bash
uv add 'roboloom[policy,train]'
uv run lerobot-train --dataset.repo_id=<repo_id> --dataset.root=<output from project root> \
  --policy.type=act --policy.device=cuda --policy.push_to_hub=false \
  --trackio.enable=false --output_dir=outputs/train/act
```

- Checkpoint: `<output_dir>/checkpoints/last/pretrained_model` → `path`; no `rename`
  needed for the same configuration.
- Path check on CPU in minutes: `--policy.device=cpu --steps=200 --batch_size=8`; offline:
  `--policy.pretrained_backbone_weights=null`.
- Check that a GPU is free (`labstatus` on the lab machines) before GPU work.

## Local hooks (mock only)

Use `roboloom.hooks` for per-action-period extensions. A policy may optionally return
`Sequence[Hook]` from `hooks()`, called after `bind`. A standalone hook factory works
with LeRobot/replay too. Writing policy contributions require this explicit claim:

```yaml
hooks:
  - from: policy
    writes: [follower.r_arm_grip, follower.l_arm_grip]
```

```python
from roboloom.hooks import Hook, HookSpec, Requirements, StepContext, EpisodeEnded


class SessionHook(Hook):
    def requirements(self) -> Requirements:
        return Requirements(
            observe=(
                "observation.state",
                "observation.images.digit_left",
                "observation.images.digit_right",
            ),
            writes=("follower.r_arm_grip", "follower.l_arm_grip"),
            on_error="hold",
        )

    def step(self, action, ctx: StepContext):
        # Read declared keys through ctx.observation; return an array or None.
        # ctx.chunk has id/position/length on policy steps and is None on teleop.
        return action

    def on_episode_ended(self, event: EpisodeEnded):
        # Finish video/log output here, on this hook's ordered event worker.
        pass
```

- `Requirements.sources` defaults to `(policy,)`; include teleop to support takeover.
  YAML `sources` may only narrow it; teleop requires the policy's `teleop:` controllers.
- Factory entry keys: `factory`, `kwargs`, `writes`, `sources`, `on_error`, `budget_ms`,
  `name`. Exactly one of `factory` and `from`; at most one `from: policy` slot.
  All declared writes must fit inside the YAML limit; overlapping claims run in order.
- Hold substitution precedes hooks. Claimed held joints may be written; remove old
  gripper-not-in-hold guards and NaN embedding from adapters. Keep shape/finite and
  outside-writes entries unchanged. Interpolation, max_speed and FollowerSafety follow.
- Steps run locally and synchronously during episodes, once per queued action (policy)
  or after pickup/alignment (policy teleop), never on the pchip lookahead. Plain joint
  controllers have no enabled hooks. `ctx.names` is the follower slice during teleop.
- Observations are lazy, declared keys only, read-only arrays. Undeclared keys raise
  KeyError mentioning observe. No full image frame is built just because a hook exists.
- Error policies: fail (writing default), hold (only written entries), pass (observe-only
  default). Budget defaults to `0.5 / rate_hz` ms, using the input period for teleop;
  overruns count/warn only. V1 has no fallback or on_overrun. API = 1; newer refused.
- Each hook has one ordered event worker; its methods never overlap. Start barrier
  waits 60 s, ControlChanged/PolicyRestarted barriers budget_ms * 10, for step hooks
  only. EpisodeEnded is async, after orphaned inference waits (10 s cap). Next start
  queues behind it; a 60 s timeout refuses start. Event errors are logged, not fatal.
  Shutdown drains 60 s then workers close when finished. Protect state shared with async
  infer using the policy's own lock (the hook lock does not serialize infer).
- Events: EpisodeStarted, EpisodeEnded (stopped/discarded/failed/estop/released/
  interrupted/shutdown), ControlChanged (takeover/handback), PolicyRestarted
  (handback/stale_recovered), ObservationStale. Base on_event routes to on_<kind>.
- Remote capabilities protocol 2 forwards lifecycle events only through RemoteEvents
  under the inference call lock. Server step_hooks refuse connect: local factory or
  backend: process. Older servers have no events. from: policy + writes + server is
  refused at config load.
- Record `action.filtered` only for YAML writing claims; see [recording](recording.md).
  Report hooks as mock only, never hardware-verified. Effort feedback paths remain
  available for future extensions; do not resume paused bilateral work.
