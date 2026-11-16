# PiPER + Pika path

!!! warning "Status: in development"
    <span class="status status--dev">In development</span> The PiPER, Pika Gripper and Pika Sense drivers and `roboloom setup` are checked only by tests with mock devices and fake hardware. They have not run on hardware.

Two PiPER arms, each with a Pika Gripper, teleoperated with two Pika Senses. The pages follow [Stages of bringing up a robot](../../explanation/robot-setup-flow.md).

| Order | Page | Stages | Content |
| --- | --- | --- | --- |
| 0 | [On mock devices](mock.md) | — | Go through recording, training and inference without hardware |
| 1 | [Robot setup](setup.md) | 1–3 | `roboloom init piper-pika`, identify the devices with `roboloom setup`, and check by reading |
| 2 | [First teleoperation](first-teleop.md) | 4–5 | Check holding, move home, and teleoperate with a loose configuration |
| 3 | [Tightening the configuration](tighten.md) | 6 | Add `tool_offset` and `workspace`, and raise the speed |

Details of the configuration are in [PiPER](../../robots/piper/index.md), [Pika Gripper](../../robots/pika/index.md) and [Pika Sense and IK](../../controllers/pose-ik.md).

## Differences from the official software

As in AgileX's official teleoperation (`pika_remote_piper` in PikaAnyArm, ROS Noetic), the mapping is relative to the hand and tool poses at the moment teleoperation starts (`T_a0 · inv(T_s0) · T_s`), and there is no calibration between the tracker and robot frames. Trackers are read with libsurvive (not SteamVR). `workspace`, which the official software lacks, is an optional safety limit added by roboloom.
