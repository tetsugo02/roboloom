# PiPER, Pika Gripper, Pika Sense + `pose_ik`

> **Status: in development, mock only, not verified on hardware.** The PiPER follower,
> Pika Gripper follower, Pika Sense input and `pose_ik` controller have run only with
> mock devices and tests against fake SDKs/serial ports. **Tell the user this** whenever
> you configure or use them, and do not present them as supported hardware.

## Parts and extras

| Node `type` | Role | Unit | Needs |
| --- | --- | --- | --- |
| `piper_follower` | AgileX PiPER arm, joint position (MOVE J) over CAN | rad (joint1…joint6); effort N·m | extra `piper` (piper_sdk 0.6 and Pinocchio) |
| `pika_gripper_follower` | Pika Gripper, one joint `gripper` = motor angle, 0 = closed | rad; effort mA | nothing extra (pyserial) |
| `pika_sense` (input) | hand-held pose (Vive tracker via libsurvive) + jaw angle + engage button | m, quaternion xyzw, rad | extra `pika` (pysurvive wheel from the libsurvive fork, Linux x86_64); admin-provided udev rules |
| `pose_ik` (controller) | Sense pose → arm joints by IK, jaw → gripper angle | follower units | Pinocchio, included in `piper` or standalone `ik`; also for mock and `validate` |

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --extra record --extra piper --extra pika
```

After registering the Git source: `uv add 'roboloom[piper,pika]'`. `pysurvive` is needed
only for real Sense tracker poses: PiPER joint commands, Pika serial/cameras and mocks
do not use it. The full `pika` extra installs it together with OpenCV for wrist cameras.
PyPI has no Python 3.12 distribution, so the extra installs a wheel built by the
libsurvive fork tetsugo02/libsurvive (Linux x86_64, libusb bundled, no build at install
time; [../installation.md](../installation.md)). For mocks, use `ik` without `pika`.

The unit is fixed in code (`rad`); do not add `unit:` or `control:` (both followers refuse
`control:`). Do not convert to degrees or mm.

## Getting a configuration

There is **no template**: `roboloom init` only knows `rakuda2` (`TEMPLATES` in
`roboloom/project.py`). The working mock configuration `.roboloom/piper-mock/` lives in
the roboloom repository, not in the installed package. To use it in a downstream project,
copy that directory from <https://github.com/tetsugo02/roboloom> into the user's
`.roboloom/`. It has `mode: mock` and mock ports/limits: **never reuse its `can`, `port`,
`tracker`, `limits`, `tool_offset` or `workspace` values for hardware.** For hardware, write
the YAML by hand with `SET_` placeholders and let the user fill them from measurements
(`roboloom validate` lists the remaining `SET_` values; `can`/`port`/`tracker.serial` left as
`SET_` are refused).

## Node keys (verified against code)

`piper_follower`: `can` (interface name), `control_hz`, `speed_percent` (**required**, int
1–100), `stale_ms` (default 50), `health` (**required**; `every_ticks` default 10,
`max_temperature_c`), `limits` (6 entries `name,min,max,max_speed,max_jump`, refused
outside the PiPER range), `torque` (default true), `record_effort` (default false),
optional `unattended` (only from `check-hold`).

`pika_gripper_follower`: `port` (use `/dev/serial/by-path/...`), `control_hz`,
`current_limit_A` (**required**, 0 < x ≤ 2), `stale_ms` (default 100), `health`
(**required**), `limits` (1 entry `gripper`, inside 0–1.67 rad), `torque`, `record_effort`.

`pika_sense`: `port`, `tracker: {system: <node under trackers:>, serial: LHR-...}` (the
tracker's serial number; names like `WM0` swap between runs and are refused, as are the old
keys `tracker.name`/`tracker.args`), `stale_ms` (default 100), `poll_hz` (optional;
required when there are no followers).

`trackers:` role, `type: libsurvive`: `args` (optional list of libsurvive arguments),
`poll_hz` (optional). One node opens libsurvive once for every Sense (a second context in
another process finds no tracker) and publishes poses by serial; not recorded. An all-zero
rotation marks that tracker lost (`tracking` 0, disengage) until the next good pose.
Calibration (`--force-calibrate` from Python) prints each tracker's serial via
`pysurvive.simple_serial_number(obj.ptr)`.

`pose_ik`:

```yaml
type: pose_ik
input: left_sense
followers: [left, left_gripper]
arm: left                     # follower with a kinematic model (PiPER)
gripper: left_gripper         # optional, a one-joint follower
tool_offset: {xyz: SET_TOOL_XYZ, rpy: SET_TOOL_RPY}  # flange (link6) -> tool; measure
workspace: {min: SET_MIN_XYZ, max: SET_MAX_XYZ}       # m, arm base_link
max_input_jump: {position_m: ..., rotation_rad: ...}  # required
ik: {iterations: 30, damping: 0.001, position_tolerance_m: 0.005, rotation_tolerance_rad: 0.05}  # defaults
gripper_map: {scale: 1.0, offset: 0.0}                # defaults; clipped to gripper limits
max_speed: {left: ..., left_gripper: ...}             # one per follower, unit/s
home: {left: {pose: ../poses/left/ready.yaml, max_speed: ..., tolerance: ...}}
command_deadline_ms: ...      # required
input_timeout_ms: ...         # required
```

`arm` + `gripper` must name exactly `followers`. Unknown `ik` keys are refused.

## Dual-arm layout

One Sense drives one arm + one gripper: two arms = two Senses, two `pose_ik` controllers.
In `.roboloom/piper-mock/`: inputs `left_sense`, `right_sense`; controllers `left_ik`,
`right_ik`; followers `left`, `right`, `left_gripper`, `right_gripper` (this order defines
`action`); sensors `camera`, `left_wrist`, `right_wrist` (`v4l2_rgb`, see
[../sensors.md](../sensors.md)); option `policy` replaces Senses and IK by a `policy`
controller.

## Behaviour

- Mapping is relative: on the Sense's rising `engaged`, target = `T_a0 · inv(T_s0) · T_s`
  (no tracker-to-base calibration).
- Stops (operator must disengage and engage again): pose lost/stale, jump >
  `max_input_jump`, input gap > `input_timeout_ms`, follower `FAULT`/`ESTOP`, move home.
- Holds without stopping: target outside `workspace` or IK not reached. Controller states
  shown on screen: `waiting_input`, `ready`, `following`, `out_of_workspace`, `unreachable`, `tracking_lost`,
  `input_jump`, `input_stale`, `homing`, `follower_fault`.
- PiPER's power-on pose (all zeros) is singular: **Move home first** (`home`, `record
  --home`, `Session.home()`). Safety traits: PiPER `falls`/`unknown`, gripper
  `lets_go`/`unknown` (see [../safety.md](../safety.md)).
- PiPER and gripper `record_effort` cannot both be on (N·m and mA in one vector is refused).

## Observation / action (`piper-mock`)

| Feature | Size | Unit |
| --- | --- | --- |
| `observation.state`, `action` | 14: `left.joint1..6`, `right.joint1..6`, `left_gripper.gripper`, `right_gripper.gripper` | rad |
| `observation.effort` | 12 (arms only) | N·m |
| `observation.left_sense`, `observation.right_sense` | 10: `x y z qx qy qz qw gripper tracking engaged` (teleoperation only) | m, quat, rad, 0/1 |
| `observation.images.camera`, `.left_wrist`, `.right_wrist` | 48×64×3 in mock | RGB |

A policy returns `[14]` or `[H, 14]` in rad; the policy configuration has no Senses. See
[../policy.md](../policy.md).

## Mock usage

```bash
uv run roboloom validate piper-mock            # needs the ik extra
uv run roboloom run piper-mock                 # Launch, then Move home; mock Senses engage at 2 s, 10 s on / 2 s off
uv run roboloom record piper-mock --task "pick" --seconds 10 --home --plain
uv run roboloom run piper-mock --with policy   # demo_policy.py instead of the Senses
```

```python
from roboloom import Session

with Session.launch("piper-mock", mock=True) as s:
    s.home(timeout=30)
    s.wait_ready(30)
    print(s.status()["left_ik"]["fields"]["state"])
    s.record("follow", 5.0)
```

## Hardware steps (only when the user asks; tell them it is unverified)

CAN interfaces (1 Mbps, one per arm) and libsurvive udev rules need an administrator.
`pysurvive` comes with the `pika` extra; it has no `survive-cli`, so calibration opens
`pysurvive.SimpleContext` with `--force-calibrate` (unverified on hardware). Read
only: `roboloom probe <can>`, `roboloom probe <port> --device pika`, `roboloom probe <port>
--device pika_sense`. `roboloom check-hold <follower> --tolerance <x>` energizes the arm.

## Limitations

No template or Quick start; joint signs/zeros, `tool_offset`, gripper zero, feedback rates,
both Senses on one `libsurvive` tracker node, recovery after a USB unplug (the fork
carries upstream PRs #383/#378, tested against a fake libusb only) and `unattended` are
unchecked. URDF matches PiPER
firmware S-V1.6-3 and later. Closing the dataflow does not disable PiPER or gripper motors.
