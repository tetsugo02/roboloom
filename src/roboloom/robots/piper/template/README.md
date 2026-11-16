# PiPER x2 + Pika Gripper x2 + Pika Sense x2

**In development: not verified on hardware.**

The full walk-through is in the docs: Tutorials > PiPER + Pika.

1. Ask an administrator for what needs root once: the Vive udev rules (81-vive.rules),
   membership of the dialout group, and bringing the CAN interfaces up at 1 Mbps.
2. `uv run roboloom setup piper-pika`: identifies each arm (turn its joint1 by hand),
   each Sense (open and close it), each tracker (move its Sense) and each gripper
   (unplug its USB), and writes them into nodes/*.yaml. Read-only on the devices.
3. `uv run roboloom check-hold piper-pika left --tolerance 0.02` (and `right`), with
   someone supporting the arm.
4. `uv run roboloom run piper-pika`: Move home (check poses/*/ready.yaml clears the
   table first), then double-click a Sense to engage and move it slowly.
5. Then measure tool_offset and set workspace in nodes/*_ik.yaml, and raise the speeds.
