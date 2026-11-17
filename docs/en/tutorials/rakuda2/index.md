# Rakuda2 path

<span class="status status--verified">Hardware-verified</span>

The order from bringing up Rakuda2 through collection, training and inference. Stages 1–4 of [Stages of bringing up a robot](../../explanation/robot-setup-flow.md) correspond to "Configuration and read check", and stage 5 to "Teleoperated collection".

| Order | Page | Content |
| --- | --- | --- |
| 1 | [Configuration and read check](setup.md) | Create the configuration, read the ports, and go once through the path with the torque off |
| 2 | [Gravity compensation](gravity.md) | Measure the zero points, the range of motion and the gravity model, and tune the leader's compensation |
| 3 | [Teleoperated collection](collect.md) | Drive with the leader and record together with the RealSense and DIGIT |
| 4 | [From collection to inference](train-infer.md) | Go through checking, training with LeRobot, inference and recording success |
| 5 | [Evaluating with interventions](intervention.md) | Take over from the policy with the leader partway, and record the intervened rows separately |

To try it first without devices, start from [First run without devices](../first-run-mock.md).
