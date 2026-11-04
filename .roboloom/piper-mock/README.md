# PiPER + Pika mock

Mock devices only: two PiPER arms (`left`, `right`) with a Pika Gripper each
(`left_gripper`, `right_gripper`), teleoperated by two mock Pika Senses through IK
(`pose_ik`), a camera, and the grippers' fisheye wrist cameras (`left_wrist`,
`right_wrist`). The operator screen can be checked without hardware.

```bash
uv run roboloom run piper-mock                     # Launch (Ctrl+S), Move home, then Start episode
uv run roboloom run piper-mock --with policy       # demo_policy.py moves them instead
uv run roboloom infer piper-mock --seconds 20 \
  --policy roboloom.policy.lerobot:load --policy-kwargs '{"path": "<checkpoint>"}'  # a LeRobot policy
```

The arms start folded (all joints 0), where the IK can hardly follow a hand: "Move home"
brings them to `poses/<arm>/ready.yaml` first. A mock Sense engages 2 s after opening and
then repeats 10 s engaged, 2 s disengaged.

| file | what |
| --- | --- |
| `config.yaml` | inputs, controllers, followers, camera; option `policy` |
| `nodes/left.yaml`, `nodes/right.yaml` | PiPER followers (`can_left`, `can_right` on hardware) |
| `nodes/*_gripper.yaml` | Pika Gripper followers (a `/dev/serial/by-path/...` port on hardware) |
| `nodes/*_sense.yaml` | Pika Sense inputs (serial port and libsurvive tracker on hardware) |
| `nodes/*_ik.yaml` | `pose_ik` controllers: tool offset, workspace, IK and speed limits, home |
| `nodes/*_wrist.yaml` | the grippers' fisheye cameras (`v4l2_rgb`; a `/dev/v4l/by-path/...` path on hardware) |
| `poses/<arm>/ready.yaml` | the pose "Move home" goes to |
| `nodes/policy.yaml`, `demo_policy.py` | the demo policy (`--with policy`), imported from this directory |

None of the PiPER, Pika Gripper and Pika Sense drivers has run on hardware; see the docs
pages under Contribution before using them. `tool_offset` is AgileX's value for its own
gripper, not a measurement of the Pika Gripper.
