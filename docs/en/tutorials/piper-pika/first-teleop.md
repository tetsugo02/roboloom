# PiPER + Pika: first teleoperation

!!! warning "Status: in development"
    <span class="status status--dev">In development</span> These steps have never been run on hardware. Do them with two people, one supporting the arms and one ready to stop (at the operator screen), and without anything in the grippers.

- **Goal**: enable the arms and check that they hold, move them to the start pose, and teleoperate from the Senses with a loose configuration (no `workspace` or `tool_offset`, low speed).
- **Prerequisites**: [Robot setup](setup.md) is done and `roboloom validate piper-pika` passes. The space around the arms (within their reach) is clear.
- **Time**: 30 minutes.
- **Result**: both arms follow the Senses' motion, and the Grippers follow the jaws opening and closing.

## Decide how to stop first

- `Stop` on the operator screen (or `hold` when quitting with `q`) makes the arms hold in place.
- `release` disables the motors. **A PiPER drops when disabled.** Tell the person supporting the arm before choosing it.
- Closing the connection (or the process ending) does not disable the PiPER and Gripper motors.

## 1. Check holding

For each arm, measure whether it holds when commands stop. Run it ready to support the arm, with the space around it clear.

```bash
uv run roboloom check-hold piper-pika left --tolerance 0.02
uv run roboloom check-hold piper-pika right --tolerance 0.02
```

Typing `record` writes `unattended:` to the follower YAML. At the end, choose `release` (torque off; the arm drops) or leave it as it is. For details, see [PiPER](../../robots/piper/index.md).

## 2. Check the start pose

`poses/left/ready.yaml` and `poses/right/ready.yaml` hold the template's values (joint2 = 1.2, joint3 = −0.9 and so on, not measured on this robot). Check against how the arms are placed that, on the way from the rest pose to this pose, an arm does not hit the table or the other arm. If it might, change the values.

## 3. Start and move home

```bash
uv run roboloom run piper-pika
```

1. Start with Launch (Ctrl-S). The motors are enabled and the arms hold in place.
2. Move to the start pose with "Move home" (`max_speed` 0.3 rad/s). The rest pose (all joints about 0) is a singular pose, where the IK cannot follow the hand.
3. When the controller row shows `ready`, teleoperation can start.

## 4. Teleoperate

1. Hold the Sense in the same orientation as the Gripper (jaws forward).
2. **Open and close the Sense twice quickly to start.** The Sense pose and the arm's tool pose at that moment become the reference, and from then on the hand's motion becomes the tool's motion (no calibration between the tracker and the robot is needed).
3. Move slowly at first, a few centimetres at a time. The arm speed is limited by `max_speed` (arms 0.5 rad/s) and `speed_percent` 20.
4. Open and close twice again to stop. The arms hold in place.

Controller states on the screen:

| State | Meaning | What to do |
| --- | --- | --- |
| `following` | Following | — |
| `unreachable` | The IK cannot reach the target (outside the joint ranges, for example) | Bring the hand back; following continues once it is back |
| `input_jump` / `tracking_lost` | The tracker jumped or was lost | Start again where the base stations can see it |
| `homing` | Moving home | Wait until it finishes |

The first time there is no `workspace`, so the screen shows `workspace: none`. Only the joint ranges and the IK stop the target. The arm will try to go below the table too, so move especially slowly near the table.

## Next

[Tightening the configuration](tighten.md): add `tool_offset` and `workspace`, and raise the speed.
