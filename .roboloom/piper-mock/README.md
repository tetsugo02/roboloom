# PiPER + Pika Gripper mock

Mock devices only: two PiPER arms (`left`, `right`) with a Pika Gripper each
(`left_gripper`, `right_gripper`) and a camera, so the operator screen can be checked
without hardware. Pika Sense teleoperation is not implemented yet; the demo policy
`demo_policy.py` swings joint1 and joint4 of each arm and opens and closes the grippers.

```bash
uv run roboloom run piper-mock      # Launch (Ctrl+S), then "Start episode"
```

| file | what |
| --- | --- |
| `config.yaml` | the followers, the camera and the policy controller |
| `nodes/left.yaml`, `nodes/right.yaml` | PiPER followers (`can_left`, `can_right` on hardware) |
| `nodes/*_gripper.yaml` | Pika Gripper followers (a `/dev/serial/by-path/...` port on hardware) |
| `nodes/policy.yaml`, `demo_policy.py` | the demo policy, imported from this directory |

Neither the PiPER nor the Pika Gripper driver has run on hardware; see the docs pages
"PiPER follower" and "Pika Gripper follower" under Contribution before using either.
