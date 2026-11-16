# Controllers

A controller turns the values of an input (a leader, a hand-held device, a policy) into follower targets. The settings come in three parts.

| Setting | Role | Examples |
| --- | --- | --- |
| `inputs` | reads the device the operator moves | Rakuda-mini (`rakuda_mini`), Pika Sense (`pika_sense`) |
| `controllers` | turns the input into follower targets; holds the start condition (alignment), speed limits and the input deadline | `joint`, `pose_ik`, `policy`, `parts` |
| `control` | the control law applied to a device's motors (the leader's spring, gravity compensation, …), run by the follower or leader node itself | `spring`, `gravity_comp`, `position` |

```mermaid
flowchart LR
  I["input<br/>inputs"] --> C["controller<br/>controllers"]
  P["policy"] --> C
  C -- "targets" --> F["follower<br/>followers"]
  F -- "state" --> C
  L["control law<br/>control"] -.-> I
  L -.-> F
```

## Types { #types }

| Controller | `type` | Input | Status |
| --- | --- | --- | --- |
| [Leader](leader.md) | `joint` | a leader with the same joints | <span class="status status--verified">Hardware-verified</span> |
| [Policy](policy.md) | `policy` | a learned policy (and a `joint` leader for interventions) | <span class="status status--verified">Hardware-verified</span> |
| [Pika Sense and IK](pose-ik.md) | `pose_ik` (`parts` to split it per arm) | the pose of a hand-held device | <span class="status status--dev">In development</span> |

## By robot { #by-robot }

| Robot | Leader | Policy | Policy with interventions | Pika Sense and IK |
| --- | --- | --- | --- | --- |
| [Rakuda2](../robots/rakuda2/controllers.md) | <span class="status status--verified">Hardware-verified</span> | <span class="status status--verified">Hardware-verified</span> | <span class="status status--verified">Hardware-verified</span> | <span class="status status--dev">In development</span> |
| [PiPER + Pika Gripper](../robots/piper/controllers.md) | — | <span class="status status--dev">In development</span> | — | <span class="status status--dev">In development</span> |

The table that also covers sensors and kinds of policies is the [Support matrix](../get-started/support-matrix.md). The controller keys are listed in [Controllers configuration](../reference/configuration/controllers.md).
