# Configuration

## `config.yaml`

```yaml
repo_id: local/rakuda2
output: datasets/rakuda2        # relative to this file
dataset_fps: 15
# mode: hardware                # default; `mode: mock` also valid; --mock / mock= win
inputs:
  leader: nodes/leader.yaml
controllers:
  controller: nodes/controller.yaml
followers:
  follower: nodes/follower.yaml
sensors:
  camera: nodes/camera.yaml
# estimators: {}                # only for the paused bilateral feature
recorder: nodes/recorder.yaml
session: nodes/session.yaml
options: {}                     # see below
```

- Only these top-level keys are accepted: `repo_id`, `output`, `dataset_fps`, `mode`,
  `trackers`, `inputs`, `controllers`, `followers`, `sensors`, `estimators`, `recorder`, `session`,
  `options`. Anything else is refused at load.
- **Node names** (keys under the roles) are dora IDs and dataset feature names: letters,
  digits, `-`, `_`. Reserved: `recorder`, `session`, `action`, `tick`, names starting with
  `action_`, names ending in `_status`.
- Each node YAML has a `type`:
  - followers: `rakuda2_follower`, `piper_follower`, `pika_gripper_follower`
  - inputs: `rakuda_mini`, `pika_sense`
  - controllers: `joint`, `pose_ik`, `policy`
  - sensors: `realsense_rgb`, `digit`, `opencv_rgb`, `v4l2_rgb`, `pcm_mono`, `mel_mono`
- Several followers are allowed; **each follower is driven by exactly one controller**.
  `followers: {}` records inputs and sensors only (no `action`, no controllers; inputs need
  `poll_hz`, sensors `fps`).
- `validate` checks configuration and dataflow consistency without opening devices. It
  does not check EEPROM against hardware, image capture or stopping behaviour.

## Controllers and followers

| Controller | Drives | Notes |
| --- | --- | --- |
| `joint` | exactly one follower | maps leader joints (`joints` table: mapping, sign, offset); `alignment_tolerance`, `max_speed`, `command_deadline_ms`, `input_timeout_ms`, `follower_timeout_ms` (150), optional `couplings`, `home` |
| `pose_ik` | one arm + optional gripper | hand-held pose → IK (in development) |
| `policy` | every follower, in configuration order | `factory`, `kwargs`, `observe`, `rate_hz`, `action_horizon`, `max_speed` per follower, `command_deadline_ms` |

A multi-follower controller sends nothing until every follower reported state, and stops
commanding all of them when one latches `FAULT`/`ESTOP` or goes stale; it waits to
re-align before commanding again.

## Units

Every follower and input declares its joint unit (no default). Rakuda2:
`dynamixel_count`; PiPER and Pika Gripper: `rad`. A controller's `unit` must equal its
input's and follower's; a follower refuses commands in another unit.

`max_speed` is always in the follower's unit per second:

| Where | Limits |
| --- | --- |
| follower `limits[].max_speed` (per joint) | safety clamp, last line of defence – keep it above the controller's |
| `joint` controller `max_speed` | teleoperation target change per period |
| `policy` controller `max_speed: {follower: value}` | policy target change per period |
| controller `home.max_speed` | move to a saved pose (≤ controller `max_speed`); `home.tolerance` required |

## Launch options

```yaml
options:
  digit:
    help: record the left/right DIGIT tactile sensors
    set:
      sensors.digit_left: nodes/digit_left.yaml
      sensors.digit_right: nodes/digit_right.yaml
    dataset: digit
  gravity:
    help: gravity-compensated leader arms (after the measurement steps of README.md)
    set:
      inputs.leader: nodes/leader_gravity.yaml
  policy:
    help: a learned policy drives the follower (`roboloom infer` turns this on)
    conflicts: [gravity]
    set:
      inputs.leader: null          # null removes the node
      controllers.controller: null
      controllers.policy: nodes/policy.yaml
    dataset: eval
```

| Key | Meaning |
| --- | --- |
| `help` | shown in the launcher |
| `default` | `true` = on when nothing is chosen (default `false`) |
| `requires` / `conflicts` | enabled together / disabled together |
| `set` | `<role>.<node>` → node file, or `null` to remove |
| `dataset` | appended (`-name`, declaration order) to `repo_id` and `output` |

Rules: unknown names are errors; two options setting one node differently is an error
unless one requires the other (the dependent wins); disabling an option disables those
that require it; an option that changes recorded features **must** have a `dataset`.

Choosing options: CLI `--with a,b` / `--without a,b` (added to / removed from the
defaults); Python `options=[...]` is the **whole set** (not added to defaults), `None`
means defaults. `roboloom validate --with ...` prints the enabled options and dataset
name. Options never change while a dataflow runs.

## Safety traits (behaviour without torque / when left alone)

Each follower and actuated input model declares:

| Trait | Values |
| --- | --- |
| `torque_off` | `falls` (support it), `lets_go` (gripper drops objects), `stays` |
| `unattended` | `holds` (keeps last target), `torque_off` (goes limp), `unknown` (treated as limp) |

Rakuda2 follower: `falls`; `holds`, except `torque_off` when a group runs a current-mode
law. Rakuda-mini leader: `falls` / `torque_off`. PiPER: `falls` / `unknown`. Pika Gripper:
`lets_go` / `unknown`. Only an `unknown` `unattended` may be overridden in follower YAML,
with a measured value from `roboloom check-hold`.

## Control laws (`control:` in Dynamixel node YAML)

Groups of joints, each with one law; every joint exactly once.

| Law | Mode | Use |
| --- | --- | --- |
| `free` | torque off | joints moved by hand |
| `position` | position | follower default; on a leader, locks the pose at torque-on |
| `current_position` | current-limited position | grippers |
| `spring` | current | leader trigger spring |
| `gravity_comp` | current | leader gravity compensation |
| `impedance` | current | not verified on hardware; refused without `allow_unvalidated: true` |

Current-mode laws on hardware need `bus_watchdog_ms` and an EEPROM Current Limit
(`registers.current_limit`) ≤ `max_current_mA`. Dynamixel nodes declare expected EEPROM in
`registers`; startup refuses a mismatch (fix with `roboloom commission`).

## Control rate

`control_hz` (follower) and `poll_hz` (leader) are bus rates; templates use 120 Hz
(needs FTDI latency 1 ms and Fast Sync Read). Use `roboloom probe <port>` for a rough
limit; on the `run` screen keep max `work` ≤ ~70 % of the period; otherwise lower to 60.

## Logs

`logs/<dataset>-<time>/` next to `config.yaml`: `dora.log`, `<leader>_trace.npz`,
`<follower>_trace.npz`. `Session.log_dir` gives the path.

### Image storage

Set `storage: video | image` in each image sensor's node YAML (RealSense, DIGIT, V4L2 including Pika wrist cameras). The default is `video`: the existing lossy MP4 encoding. `image` embeds lossless PNG frames in Parquet; use it for DIGIT/background pixel differences. Formats can be mixed in one dataset. Invalid values are refused at configuration load, including `validate`.

PNG generally needs more disk space and PNG compression/write work; actual size and throughput depend on image content and hardware. As an uncompressed RGB reference, 320×240×3 at 30 dataset fps is 6.9 MB/s per sensor (640×480: 27.6 MB/s); these are not measured PNG rates. LeRobot 0.6.1 uses PNG compression level 6 for `image`. Changing storage changes the feature dtype: choose a separate dataset `output`; resume into the previous schema is refused.

Live observations remain HWC uint8 RGB, and LeRobot dataset reads return CHW float32 in [0, 1] for either format by default. Checkpoint inputs remain `VISUAL`. Storage was tested with mock/synthetic frames only, without hardware.

### Video codec

`video_codec` in `nodes/recorder.yaml` chooses the MP4 codec of `storage: video` images for every robot: `h264` (the default; plays almost everywhere) or `av1` (alias `libsvtav1`, LeRobot's own default, smaller files). Not set: H.264 for a new dataset; when appending, the codec and settings of the saved videos. Per launch: `load_config(..., video_codec=...)`, `Session.launch(..., video_codec=...)` (a loaded `RobotConfig` plus `video_codec` is an error, as with `sensors`/`observe`), `--video-codec av1` on the CLI, or the launcher's "Video codec" choice (saved with the last launch). None keeps the YAML's choice. The dora nodes reload the same choice.

roboloom passes LeRobot's `RGBEncoderConfig(vcodec=...)` to `LeRobotDataset.create/resume`; CRF, GOP and preset stay at LeRobot's defaults and are not settings. An encoder missing from the local FFmpeg/PyAV is refused at launch and `validate` (no silent fallback). An explicit codec that differs from the saved videos is refused before writing with `video_codec: 'av1' (saved videos) -> 'h264' (requested)`: set another `repo_id` and `output`; nothing is converted or moved. `storage: image`, audio and joints are unaffected.

AV1 generally gives smaller files at the same quality; H.264 plays in almost every player and browser (AV1 may not, e.g. in some editor/browser video previews). With LeRobot's defaults both encoded a synthetic 640×480 × 90-frame episode in about 0.9 s. Whether H.264 fixes black videos in the VS Code LeRobot Viewer is unverified; the codec choice is tested with synthetic frames and the mock dataflow only.
