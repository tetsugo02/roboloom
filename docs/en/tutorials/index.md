# Tutorials

Step-by-step guides, by goal. Most give the goal, prerequisites, time, result and what to do next. The labels are defined in [Status labels](../reference/status-labels.md).

```mermaid
flowchart LR
  A["collect<br/>teleop"] --> B["check<br/>check-dataset"]
  B --> C["train<br/>lerobot-train"]
  C --> D["run<br/>roboloom infer"]
  D --> E["evaluate<br/>label"]
  E --> F["collect with interventions<br/>policy_teleop"]
  F --> B
```

## First steps { #first-steps }

<div class="grid cards gallery" markdown>

-   [![First run without devices](../assets/gallery/first-run-mock.svg)](first-run-mock.md)

    **[First run without devices](first-run-mock.md)**

    Start, record and check a dataset with examples/mock.

    <span class="gallery-tags">mock Rakuda · 15 min · <span class="status status--mock">Mock only</span></span>

-   [![Adding your own robot](../assets/gallery/own-robot.svg)](own-robot.md)

    **[Adding your own robot](own-robot.md)**

    Run a mock arm from your own follower class and template.

    <span class="gallery-tags">your robot · 20 min · <span class="status status--mock">Mock only</span></span>

</div>

## Rakuda2 { #rakuda2 }

<div class="grid cards gallery" markdown>

-   [![Rakuda2: configuration and read check](../assets/gallery/rakuda2-setup.svg)](rakuda2-setup.md)

    **[Rakuda2: configuration and read check](rakuda2-setup.md)**

    Create the configuration, read the buses, and go once through with the torque off.

    <span class="gallery-tags">Rakuda2 · 1–2 h · <span class="status status--verified">Hardware-verified</span></span>

-   [![Rakuda2: gravity compensation](../assets/gallery/rakuda2-gravity.svg)](rakuda2-gravity.md)

    **[Rakuda2: gravity compensation](rakuda2-gravity.md)**

    Measure zero points, travel and the gravity model, and tune the leader.

    <span class="gallery-tags">Rakuda2 · 1–2 h · <span class="status status--verified">Hardware-verified</span></span>

-   [![Rakuda2: teleoperated collection](../assets/gallery/rakuda2-collect.svg)](rakuda2-collect.md)

    **[Rakuda2: teleoperated collection](rakuda2-collect.md)**

    Drive with the leader and record with the RealSense and DIGIT.

    <span class="gallery-tags">Rakuda2 · 30 min+ · <span class="status status--verified">Hardware-verified</span></span>

</div>

## Policies { #policy }

<div class="grid cards gallery" markdown>

-   [![Rakuda2: from collection to inference](../assets/gallery/rakuda2-train-infer.svg)](rakuda2-train-infer.md)

    **[Rakuda2: from collection to inference](rakuda2-train-infer.md)**

    Check, train with LeRobot, run the policy and record the verdicts.

    <span class="gallery-tags">Rakuda2 · training + 1 h · <span class="status status--verified">Hardware-verified</span></span>

-   [![Rakuda2: evaluating with interventions](../assets/gallery/rakuda2-intervention.svg)](rakuda2-intervention.md)

    **[Rakuda2: evaluating with interventions](rakuda2-intervention.md)**

    Take over from the policy with the leader; intervened rows are marked.

    <span class="gallery-tags">Rakuda2 · 1 h · <span class="status status--verified">Hardware-verified</span></span>

-   [![Running your own policy](../assets/gallery/custom-policy.svg)](custom-policy.md)

    **[Running your own policy](custom-policy.md)**

    Train the sample chunk_mlp.py on a mock recording and run it with infer.

    <span class="gallery-tags">mock Rakuda2 · 30 min · <span class="status status--mock">Mock only</span></span>

</div>

## Robots in development { #in-development }

<div class="grid cards gallery" markdown>

-   [![PiPER + Pika on mock devices](../assets/gallery/piper-pika-mock.svg)](piper-pika-mock.md)

    **[PiPER + Pika on mock devices](piper-pika-mock.md)**

    Record with mock Pika Senses through IK and run a LeRobot policy.

    <span class="gallery-tags">PiPER + Pika · 30 min · <span class="status status--dev">In development</span></span>

-   [![Hand-held collection with Pika Sense](../assets/gallery/pika-handheld.svg)](pika-handheld.md)

    **[Hand-held collection with Pika Sense](pika-handheld.md)**

    Collect with Senses in the hand, no robot, and convert for training.

    <span class="gallery-tags">Pika Sense · 30 min · <span class="status status--dev">In development</span></span>

</div>
