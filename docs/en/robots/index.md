# Robots

The robots (followers) roboloom drives. Each robot has an overview, a page of the controllers it can use and a page of its sensors.

<div class="grid cards" markdown>

-   **[Rakuda2](rakuda2/index.md)** <span class="status status--verified">Hardware-verified</span>

    ---

    17 joints: torso, head and two arms. Driven by the Rakuda-mini leader, a policy, or a policy with interventions.

-   **[PiPER](piper/index.md)** <span class="status status--dev">In development</span>

    ---

    AgileX's 6-joint arm. Driven by a Pika Sense through IK, or by a policy. Mock only so far.

-   **[Pika Gripper](pika/index.md)** <span class="status status--dev">In development</span>

    ---

    The gripper on the PiPER's flange, part of a set with wrist cameras and the Pika Sense.

-   **[Your own robot](../tutorials/own-robot.md)** <span class="status status--mock">Mock only</span>

    ---

    Add your own follower class and template without changing roboloom.

</div>

## Support matrix { #matrix }

| Robot | Controllers and inputs | Sensors |
| --- | --- | --- |
| [Rakuda2](rakuda2/index.md) | Leader <span class="status status--verified">Hardware-verified</span>, gravity-compensated leader <span class="status status--verified">Hardware-verified</span>, policy <span class="status status--verified">Hardware-verified</span>, policy with interventions <span class="status status--verified">Hardware-verified</span>, Pika Sense and IK <span class="status status--dev">In development</span> ([list](rakuda2/controllers.md)) | RealSense <span class="status status--verified">Hardware-verified</span>, DIGIT <span class="status status--verified">Hardware-verified</span>, audio <span class="status status--dev">In development</span> ([list](rakuda2/sensors.md)) |
| [PiPER](piper/index.md) + [Pika Gripper](pika/index.md) | Pika Sense and IK <span class="status status--dev">In development</span>, policy <span class="status status--dev">In development</span> ([list](piper/controllers.md)) | RealSense <span class="status status--dev">In development</span>, Pika wrist cameras <span class="status status--dev">In development</span> |

The table that also covers the kinds of policies is the [Support matrix](../get-started/support-matrix.md).

## Adding a robot { #adding }

- To add one without changing roboloom, see [Adding your own robot](../tutorials/own-robot.md); to add one to roboloom itself, see [Adding a new follower](../contribution/index.md#adding-a-follower).
- A robot page has an overview, joints and units, observation and action, launch options, and pages for its controllers and sensors. Keep what is implemented apart from what is verified on hardware, and give each a [status label](../reference/status-labels.md).
