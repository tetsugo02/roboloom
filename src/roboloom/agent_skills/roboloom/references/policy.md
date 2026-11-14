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
  (each reached at its own time, no overshoot between two actions, continuous speed;
  uses the next queued action, falls back to the line's slope at a chunk's last action).
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
  serve it with `roboloom serve-policy <module:callable> --kwargs '{...}'` (or
  `python -m roboloom.policy.remote ...`; needs only numpy + roboloom without extras) and
  set `factory: roboloom.policy.remote:connect`, `kwargs: {address: "127.0.0.1:18765"}`.
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

## Writing a policy

Rakuda2 defaults to joint state + RealSense without DIGIT. Set `observe: []` for joint
state only, or `observe: [camera, digit_left, digit_right]` and enable `digit` for tactile
inputs. Enabling `digit` alone only adds recorded sensors; it does not change policy
inputs. All observed sensors must exist in `sensors`. To avoid opening unused sensors,
also remove their nodes from `config.yaml`. A checkpoint requiring DIGIT cannot run
unchanged without it; LeRobot checks this at load, custom policies can use `bind`.

Existing project files are not overwritten on update. Migrate older Rakuda2 configs by
removing `options.policy.requires: [digit]` and setting `observe: [camera]` in
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

## Running

```bash
uv run roboloom infer --seconds 30 --policy my_lab.policies:load \
  --policy-kwargs '{"checkpoint": "outputs/act/last"}' --task "pick up the cup"
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
        s.record(f"pick up the cup (eval {k})", seconds=30)
```

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
  --wandb.enable=false --output_dir=outputs/train/act
```

- Checkpoint: `<output_dir>/checkpoints/last/pretrained_model` → `path`; no `rename`
  needed for the same configuration.
- Path check on CPU in minutes: `--policy.device=cpu --steps=200 --batch_size=8`; offline:
  `--policy.pretrained_backbone_weights=null`.
- Check that a GPU is free (`labstatus` on the lab machines) before GPU work.
