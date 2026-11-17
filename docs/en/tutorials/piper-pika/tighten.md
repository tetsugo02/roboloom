# PiPER + Pika: tightening the configuration

!!! warning "Status: in development"
    <span class="status status--dev">In development</span> The values are to be measured on your robot. The numbers here are examples and have not been checked on hardware.

- **Goal**: once teleoperation works with a loose configuration, add the tool dimensions (`tool_offset`), the workspace (`workspace`) and the joint ranges (`limits`) fitted to the hardware, and raise the speed.
- **Prerequisites**: [First teleoperation](first-teleop.md) is done.
- **Result**: hand rotations pivot about the fingertips, and the arm stops at targets heading toward the table or the other arm.

## 1. Tool dimensions (`tool_offset`)

`tool_offset` is the position and orientation of the fingertip centre seen from the flange (link6). Without it, the flange is the tool. Then, twisting the wrist makes the arm rotate about the flange, and the fingertips swing widely.

1. With the Pika Gripper mounted, measure the distance from the flange face to the fingertip centre.
2. link6's z axis is perpendicular to the flange face and points outward. If the fingertips are on that axis, `xyz` is `[0, 0, distance]`.
3. To keep the tool frame's orientation the same as the flange's, `rpy` is `[0, 0, 0]`.

```yaml
# nodes/left_ik.yaml (example: fingertips 0.17 m from the flange)
tool_offset: {xyz: [0.0, 0.0, 0.17], rpy: [0.0, 0.0, 0.0]}
```

For reference: AgileX's official teleoperation uses 0.19 m (`gripper_xyzrpy`) for its own gripper. The official software has no value for the Pika Gripper either, so measure it.

## 2. Workspace (`workspace`)

`workspace` is a box (m) seen from the arm's base (base_link: the centre of the base, x forward, z up). When the target tool position leaves the box, the arm holds instead of being commanded (`out_of_workspace`).

- Set the `min` z slightly above the table surface (so the arm does not hit the table).
- Set the y toward the space between the arms (the negative direction for the left arm) so the arm cannot reach the other arm.
- Make it a little wider than the range actually used in teleoperation.

```yaml
# nodes/left_ik.yaml (example)
workspace: {min: [0.10, -0.15, 0.03], max: [0.55, 0.40, 0.50]}
```

## 3. Joint ranges and speed

- The `limits` in `nodes/left.yaml` and the others only stay inside the PiPER manufacturer's ranges; they are not ranges that avoid collisions. Narrow the joints that would hit the table or cables.
- While checking the motion, raise `speed_percent` (from 20), `max_speed` (from 0.5 rad/s for the arms) and the Gripper's `current_limit_A` (from 0.5 A, up to 2 A).
- To fit the start pose to your task, make the pose by teleoperation, quit with `hold`, and then save it.

```bash
uv run roboloom capture-pose piper-pika left ready --force
```

## 4. Check

```bash
uv run roboloom validate piper-pika   # the workspace note disappears
uv run roboloom run piper-pika
```

Lower the hand toward the table, and check slowly that the arm stops at the bottom face of the box (`out_of_workspace`).

## Next

- Recording and training work as in [On mock devices](mock.md) (with the configuration name changed to `piper-pika`).
- To add wrist cameras, see [Pika wrist cameras](../../sensors/pika-cameras.md).
