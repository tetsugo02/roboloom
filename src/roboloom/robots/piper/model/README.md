# PiPER kinematic model

`piper_no_gripper_description.urdf` is copied unchanged from
[agilexrobotics/piper_ros](https://github.com/agilexrobotics/piper_ros) at commit
`ac41fcbcdda598f01b51cf6175ed9a24d0dacadc`
(`src/piper_description/urdf/piper_no_gripper_description.urdf`), MIT License
(`LICENSE.piper_ros`).

- It matches the DH parameters piper_sdk uses for firmware S-V1.6-3 and later
  (`piper_description_old.urdf` is for earlier firmware); the chain ends at `link6`,
  the flange, without the stock gripper.
- roboloom uses only the joint frames (`controllers.pose_ik`). Joint limits come from the
  follower's `limits`, not from this file (its `joint1` upper limit reads 2.168, where the
  SDK and the other joints suggest 2.618).
