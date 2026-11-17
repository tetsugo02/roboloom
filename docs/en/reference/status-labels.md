# Status labels

| Detail | Description |
| --- | --- |
| — | These four labels show how far a feature, robot or configuration key has been checked. They appear at the top of a page, next to headings and in table rows. An item without a label has the same status as the feature its page describes. |

## Labels { #labels }

| Label | Meaning |
| --- | --- |
| <span class="status status--verified">Hardware-verified</span> | Run and checked on real hardware |
| <span class="status status--mock">Mock only</span> | Implemented and checked by tests and the mock (`--mock`) dataflow, not on hardware |
| <span class="status status--dev">In development</span> | Partly implemented, or never run on hardware |
| <span class="status status--design">Design only</span> | At the design stage; not to be used as a feature |

## Current status { #current }

| Item | Status |
| --- | --- |
| Local hooks, policy teleop hooks, lifecycle events and `action.filtered` | <span class="status status--mock">Mock only</span> |
| Rakuda2 teleoperated collection | <span class="status status--verified">Hardware-verified</span> |
| Gravity compensation | <span class="status status--verified">Hardware-verified</span> |
| Collection with DIGIT | <span class="status status--verified">Hardware-verified</span> |
| Policy inference and intervention on Rakuda2 with your own policy (`policy`, `policy_teleop`) | <span class="status status--verified">Hardware-verified</span> |
| LeRobot checkpoints (`roboloom.policy.lerobot:load`), `lerobot-train` | <span class="status status--mock">Mock only</span> (PiPER + Pika) |
| RealSense | <span class="status status--verified">Hardware-verified</span> |
| Asynchronous inference, replaying a recording, a policy in another process (`serve-policy`) | <span class="status status--mock">Mock only</span> |
| PiPER, Pika (Gripper, Sense, wrist cameras), web camera, audio | <span class="status status--dev">In development</span> |
| Force feedback (`feedback`), estimators (`estimators`) | <span class="status status--mock">Mock only</span> (paused) |
| Bilateral control design, stage 6 onward | <span class="status status--design">Design only</span> (paused) |
| Detail | Description |
| --- | --- |
| — | Implemented features not listed above count as <span class="status status--mock">Mock only</span>. |

## Writing a label { #usage }

| Detail | Description |
| --- | --- |
| — | `<span class="status status--verified">Hardware-verified</span>`<br>`<span class="status status--mock">Mock only</span>`<br>`<span class="status status--dev">In development</span>`<br>`<span class="status status--design">Design only</span>` |
