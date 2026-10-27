# Bilateral control design (FACTR 2)

!!! warning "Unimplemented design proposal"
    This page is a design proposal that lays out the implementation steps. roboloom does not implement force feedback yet. The configuration keys, commands and node names here are proposals and do not work in the current roboloom. Nothing here has been verified on hardware.

Written 2026-10-27. Sources studied (code was read, not run):

| Source | Version |
| --- | --- |
| [philiphan0109/factr2_next](https://github.com/philiphan0109/factr2_next) | `0df02c5` (2026-09-04) |
| [FACTR teleop](https://github.com/RaindragonD/factr_teleop) (first version, for comparison) | `7a07ab3` |
| FACTR: Liu et al., *Force-Attending Curriculum Training for Contact-Rich Policy Learning*, RSS 2025, [arXiv:2502.17432](https://arxiv.org/abs/2502.17432) | |
| FACTR 2: Oh, Liu, Tao, Han et al., [arXiv:2606.12406](https://arxiv.org/abs/2606.12406) v2 | |

## 1. Chosen approach

There are two main kinds of bilateral control.

| Approach | Follower | Sent back to the leader | Needs |
| --- | --- | --- | --- |
| Force reflection (FACTR / FACTR 2) | Stays position-controlled; current-based position also works | An estimate of the joint torque the follower receives **from outside** | An external torque estimate (torque sensors, or estimation from current) |
| Symmetric (position–position, robopy's `bilateral_joint`) | Current-controlled; the same PD coupling on both sides | Coupling torque from the position difference | Gravity models of both arms, torque constants, current control on the follower |

roboloom adopts FACTR 2's force reflection, because:

- The follower stays position-controlled. The existing `FollowerSafety` (range, speed, deadline and jump checks, and HOLD) keeps working as the safety mechanism.
- Only external force is sent back. The operator does not feel the follower's friction or inertia.
- FACTR 2's NEXT estimates external torque from motor current on arms without torque sensors. It applies to Dynamixel robots such as Rakuda2.
- It does not prevent adding the symmetric approach later (§8).

## 2. FACTR principles

### Leader control law

The leader motors run in current (torque) control and output this sum (paper Eq. 5):

```text
τ = τ_feedback + τ_null + τ_grav + τ_friction + τ_limit
```

| Term | Equation (paper) | Purpose |
| --- | --- | --- |
| Force feedback | `τ_feedback = μ_f K_fp τ_ext − K_fd q̇` (Eq. 1) | Return the follower's external torque to the leader. `K_fp` is the ratio of leader to follower maximum torque, `μ_f` a scaling-down factor, `K_fd` damping against oscillation in contact |
| Gripper | `τ_h,t = α(−k_h I_g,t) + (1−α) τ_h,t−1`, α = 0.1 (Eq. 2) | Return the follower gripper current as force on the finger, with an exponential moving average |
| Null space | `τ_null = (I − J⁺J)(−K_np (q − q_rest) − K_nd q̇)` (Eq. 3) | Pull the redundant DOF (7-axis arm) toward a rest posture without an end-effector force |
| Gravity | `g(q)` by RNEA (Eq. 4) | Keep the arm from falling |
| Friction | Static: a dither that flips sign at low speed. Kinetic: `μ_c sgn(q̇) + μ_v q̇` (appendix Eq. 7–8) | Break stiction so the arm moves easily by hand |
| Joint limits | A potential that repels near the ends (appendix Eq. 9–10) | Push back at the ends of travel |

Hardware: the leader uses XC330-T288-T and XM430-W210-T (about USD 1,230), the follower is a Franka Panda. The loop runs at 500 Hz. The Franka's own external torque estimate `τ_ext` is used as is.

The paper has no stability or passivity analysis. The only stabilizers are the damping `K_fd`, the factor `μ_f` and the gripper smoothing.

### Policy learning

The external torque `τ_ext` enters the ACT policy as one token. Early in training the images are blurred, and the blur decreases over time (Force-Attending Curriculum), so that the policy does not ignore force. Average success on unseen objects: images only 21.3%, images + force (no curriculum) 61.2%, FACTR 87.5%.

Teleoperation with force feedback raised task completion by 64.7% and cut completion time by 37.4% compared with no feedback. The paper does not compare policies trained on data collected with and without feedback.

## 3. FACTR 2 and NEXT principles

FACTR 2 extends FACTR to arms without torque sensors. Its core is NEXT (Neural External Torque estimation).

```text
τ̂_ext = τ_m − τ̂_free(x_{t−H+1..t}),  x_t = [q, q̇, q_cmd − q]
```

- `τ_m` is the torque from motor current (`K·I`).
- `τ̂_free` predicts the torque the motors output **without contact**. An LSTM (2 layers × 128) predicts it from the last H = 50 steps of joint position, velocity and tracking error. It learns gravity, friction, inertia and the position controller's response together.
- Training data is about 10 minutes of contact-free motion. Training takes about 1 minute; inference runs at 100 Hz.
- Accuracy: L1 error against the Franka torque sensor in contact is 0.547 Nm, against 1.471 Nm for a disturbance observer.
- Limits: the model must be retrained for each robot. The absolute torque scale depends on the accuracy of `K`.

Feedback to the leader (Eq. 8) is `τ_feedback = K_fp τ̂_ext`. The gravity, friction and null-space terms stay as in FACTR. Policy learning replaced FACTR's curriculum with FIRST, which resamples training data to favour the phases around contact. As policy input, `τ̂_ext` did better than raw current (0.567 vs 0.431 on NIST insertion).

## 4. The factr2_next implementation

factr2_next is the official implementation of NEXT. It also contains a teleoperation demo in which a Gello-style leader drives an AgileX Piper. All communication uses ROS 2 `JointState`.

| Part | Content |
| --- | --- |
| Leader | 7 × XC330-T288-T, 4 Mbps, current control (Operating Mode 0). Control at 500 Hz; commands to the follower sent at 100 Hz |
| Follower | Piper (CAN). MIT mode (joint PD); each received command is written at once. No interpolation or speed limit |
| External torque | Piper `effort` − LSTM prediction. Velocity is a 200 Hz finite difference. The estimate is smoothed by an exponential moving average (α = 0.2) |
| Contact | Hysteresis on the L1 norm of the estimate (contact at 2.0, released at 1.0) |
| Feedback | `gate · gains · τ_ext − damping · q̇`, clipped to `±max_torque` |
| Gate | 1 while in contact and the estimate is fresh (within 0.2 s), otherwise 0. It follows with `ramp_alpha` = 0.35 per 500 Hz tick, never stepping |

From `factr2_feedback.py:162-176`:

```python
target_gate = 1.0 if self.contact and self._fresh() else 0.0
self.gate = (1.0 - self.ramp_alpha) * self.gate + self.ramp_alpha * target_gate
tau = self.gate * self.gains * self.tau_ext
tau -= self.damping * leader_joint_vel
tau = np.clip(tau, -self.max_torque, self.max_torque)
```

The default gains are negative (`[-0.06, -0.08, -0.08, -0.03, -0.03, -0.02]`). The estimate is the extra torque the motors output, which opposes the external force. The negative gains appear to return a force in the direction of the external force to the leader (our reading).

Points to note:

- In the shipped configuration, force feedback, gravity compensation and dither are all disabled. Only the null-space term and gripper feedback are enabled.
- According to the README, the gate, ramp and smoothing were not used in the paper's experiments.
- The Piper has 6 axes and is not redundant, so the null-space term is a weak posture spring with a fixed diagonal matrix.
- The follower has no command deadline. If the leader stops, it keeps holding the last target.

## 5. What roboloom already has

| Needed | roboloom today |
| --- | --- |
| Leader current control and combined laws | `JointDevice` and control laws (`free`, `position`, `spring`, `gravity_comp`, `impedance`), replaceable per group |
| Gravity compensation | `gravity_comp`, with `g(q)` (mA) identified from measured holding currents. No torque constant needed |
| Joint limits | The range barrier of `gravity_comp` (`barrier_mA_per_count`) and the runaway check (`max_velocity`, out of range) |
| Stiction | Breakaway hold (`hold_mA`). The opposite of FACTR's dither: it keeps the arm where it is left |
| Damping | `kd` (mA per count/s) |
| Follower state | The robot node's `state` has `positions`, `velocities`, `currents_mA` and the target actually written, `target` (= `q_cmd`) |
| Recording | `record_effort: true` records `observation.effort` (current) |
| Follower control laws | `control` in `robot.yaml` applies control laws on the follower too (e.g. current-based position). Not verified on hardware |
| Safety | `FollowerSafety`, command deadlines, Bus Watchdog detection, leader goes limp on estop, release and quit |

Missing:

1. External torque estimation (model residual, NEXT).
2. A return path from the follower to the leader. The leader node currently receives only `session`.
3. The feedback term on the leader (gate, ramp, deadline, limit).
4. Gripper force feedback.
5. Recording of external torque, and of training data for the estimator.

Rakuda2's arms have 6 axes plus a gripper per side and are not redundant, so the null-space term is out of scope for now. Dither has the opposite aim of the breakaway hold; it will be considered as a separate control law if needed.

## 6. Design

### Units and signs

roboloom handles joint values in raw motor units (counts, mA). The gravity model is also identified in mA, absorbing the torque constant. Feedback follows the same approach.

- The estimator outputs a `residual` per follower joint, in the follower's current unit (mA for Dynamixel).
- The definition is `residual = measured current − predicted current in free motion`. It is the extra the motor outputs against the external force.
- The external force acts in the direction of `−residual`.
- The leader current is computed as follows. `sign` is the sign in the controller's `joints` map.

```text
i_feedback[leader j] = − k_j · sign_j · residual[follower j]
```

- A starting point for `k_j` (leader mA / follower mA) is, like FACTR's `K_fp`, the ratio of leader to follower maximum torque times a scaling-down factor. For Rakuda2 this includes the ratio of the XC330 and XM430/XM540 torque constants.
- On robots with `torque_constant_Nm_per_A` set per joint, values are also shown in N·m. For a robot that reports external force in N·m, such as a Franka, the estimator declares unit `Nm` and `k_j` is in mA/Nm.
- Signs are checked on hardware one joint at a time (§7 stage 5).

### Dataflow

```text
leader ──sample──► controller ──command──► robot ──state──► estimator
  ▲                    │  ▲                                  │
  └──── feedback ──────┘  └────────────── estimate ──────────┘
```

| Node | Added inputs and outputs | Role |
| --- | --- | --- |
| estimator (new role `estimators`) | Input `<robot>/state` (latest only); outputs `estimate`, `status` | Compute `residual` and contact from the follower state. A separate process, so that heavy inference never disturbs the robot node's period |
| controller | Input `<estimator>/estimate` (latest only); output `feedback` | Map follower residuals to leader joints through `joints`, apply `gain`, send with a deadline. Send zero while the follower is not `ACTIVE` or before alignment (any state other than `following`) |
| leader | Input `<controller>/feedback` (latest only) | Add the feedback term to the control law. The deadline, gate, ramp and limits are applied on the leader every tick |

- Joint correspondence and signs are written only in the controller's `joints`. No separate map for feedback.
- Feedback messages carry an absolute deadline, like robot commands (the same shape as `make_command`).
- The path is a cycle (leader → controller → robot → estimator → controller → leader). Stage 1 checks in mock that dora-rs dataflows accept cyclic edges.

### Writing an experiment

Users never write edges. As in roboloom today, the experiment YAML only lists nodes by role. `runtime/flow.py` derives the edges from each node's references.

```yaml
# experiment_bilateral.yaml
inputs:
  leader: nodes/leader_bilateral.yaml        # type: rakuda_mini
controllers:
  controller: nodes/controller_bilateral.yaml
robots:
  robot: nodes/robot.yaml                     # type: rakuda2_follower
estimators:
  effort: nodes/effort.yaml                   # robot: robot
```

The pairing follows from references alone.

| Reference | Written in | Derived edges |
| --- | --- | --- |
| `input: leader`, `robot: robot` | controller | `leader/sample` → controller, controller `command` → robot (as today) |
| `robot: robot` | estimator | `robot/state` → estimator |
| `feedback.estimator: effort` | controller | `effort/estimate` → controller, controller `feedback` → `leader` (the controller's `input`) |

The rule is closed per pair. Treating the two arms as separate robots, or putting pairs of other robots in the same experiment, only means listing one set of nodes per pair (the current "one robot per experiment" limit is a separate issue). For example, another follower with another leader would be written as below. The device names are examples and do not exist in roboloom today.

```yaml
inputs:
  leader: nodes/leader.yaml                   # type: gello_dynamixel (example)
controllers:
  controller: nodes/controller.yaml           # type: joint, feedback.estimator: effort
robots:
  robot: nodes/robot.yaml                     # type: piper_follower (example)
estimators:
  effort: nodes/effort.yaml                   # type: next, robot: robot
```

### Capabilities devices declare

Whether a combination works is checked when the configuration is read. Nothing branches on the device type; each class declares values that are compared.

| Declared by | Value | Checked |
| --- | --- | --- |
| Follower (`Robot`) | `effort_signal`: the force quantity in `state` (one of `currents_mA`, `torques_Nm`, `external_torques_Nm`) and its unit | It matches the estimator's input. `sensor` works only with robots that provide `external_torques_Nm` |
| Leader (`JointInput`) | Joints that accept feedback (groups of a current-mode law with `feedback`) and their unit (`mA`, `Nm`) | Every joint in `feedback.gain` accepts feedback |
| Controller | The unit of `feedback.gain` (leader unit / follower unit) | The unit matches both sides' declarations; every feedback joint maps one-to-one in `joints` |
| Estimator | `robot`, `joint_names`, `unit`, the `state` fields it needs | The robot exists and provides those fields |

The feedback term is a part shared by every current-mode law (subclasses of `CurrentLaw`), not only `gravity_comp`. Another leader using another law accepts feedback with the same configuration.

### Messages

Messages carry joint names and units, so that differences between devices never get mixed up silently.

| kind | payload |
| --- | --- |
| `effort_estimate` | `joints` (follower), `residual`, `unit`, `contact`, `valid`, `robot_t_ns` (time of the source state) |
| `feedback` | `joints` (leader), `effort`, `unit`, `deadline_ns`, `gate` (the controller's requested gate) |

The leader drops messages whose joint names or unit do not match its own and shows why in status.

### Proposed configuration

`nodes/controller_bilateral.yaml` (added to the existing `joints` and so on):

```yaml
feedback:
  estimator: effort               # a name under estimators in experiment.yaml
  deadline_ms: 100
  unit: mA/mA                     # leader unit / follower unit
  gain:                           # only joints listed here feed back (follower joint names)
    r_arm_sh_pitch1: 0.1
    r_arm_el_yaw: 0.1
```

An arm group in `nodes/leader_bilateral.yaml`:

```yaml
- group: right_arm
  law: gravity_comp               # any current-mode law
  # ... existing gravity_model, tuning, range, etc.
  feedback:
    max_mA: 40                    # limit on the feedback part; the total stays limited by max_current_mA
    ramp_s: 0.3                   # time to open or close the gate
    contact_on: 30                # L1 norm of |residual|, with hysteresis
    contact_off: 15
    kd: 0.0                       # extra damping in contact
```

`nodes/effort.yaml`:

```yaml
type: model_residual              # none | sensor | model_residual | next
robot: robot
joints: [r_arm_sh_pitch1, r_arm_sh_roll, r_arm_sh_pitch2, r_arm_el_yaw, r_arm_wr_roll, r_arm_wr_yaw]
model: ../calibration/effort_gravity_right.yaml
smoothing_alpha: 0.2
```

### Estimator contract

Like robots, inputs and sensors, estimators live in a registry `ESTIMATORS` (`roboloom/estimators/`) that selects the class by `type`. Robot-independent estimators are implemented in `roboloom/estimators/`; those for one robot only live in `roboloom/robots/<model>/` and register in the same registry.

```python
class EffortEstimator(Protocol):
    robot: str                        # the robot node it reads
    joint_names: tuple[str, ...]      # follower joints
    unit: str                         # e.g. "mA" or "Nm"
    needs: tuple[str, ...]            # state fields used, e.g. ("positions", "velocities", "currents_mA", "target")
    def reset(self) -> None: ...
    def update(self, state: dict, t_ns: int) -> Estimate: ...   # robot_state payload

@dataclass
class Estimate:
    residual: list[float]             # measured − predicted in free motion
    contact: bool
    valid: bool                       # False with too little history, a stale state, etc.
```

| `type` | Content | Use |
| --- | --- | --- |
| `none` | Always `valid=False` | Path tests, no feedback |
| `sensor` | The robot's own external torque estimate (e.g. Franka `tau_ext`) | Robots with torque sensors |
| `model_residual` | `currents_mA − g_f(q)`, with `g_f` identified on the follower by the existing regressor gravity model | First baseline. Works without learning; friction and inertia remain in the residual |
| `next` | `currents_mA − LSTM(q, q̇, target − q)` | The FACTR 2 method |

Robot-specific parts stay inside the estimator implementation and its configuration. The controller and leader see only `Estimate`.

### Where models are stored

Measured values and trained weights are kept with the configuration of each physical unit in `.roboloom/<robot>/` (the directory `roboloom init <robot>` creates), never in the package. As with today's gravity models, YAML is tracked in Git and large raw data and weights are excluded.

| Location | Content | Git |
| --- | --- | --- |
| `calibration/effort_gravity_<side>.yaml` | The follower gravity model for `model_residual` (the existing regressor format) | Tracked |
| `models/<estimator name>/<run_id>/model.yaml` | The NEXT manifest (table below) | Tracked |
| `models/<estimator name>/<run_id>/weights.safetensors` | Trained weights | Excluded (`*.safetensors`) |
| `logs/<run>/robot_trace.npz` | Free-motion training data (the stage-2 trace) | Excluded (existing `*.npz`, `logs/`) |

- `run_id` is the training date and time (e.g. `20261101-153000`). The node YAML names the version explicitly; "latest" is never chosen automatically, so that which model ran stays reproducible.
- Weights are stored as safetensors. Without pickle, loading never executes code. `torch` becomes an optional extra (`next`).
- Datasets record the estimator's `type` and `run_id` used while recording.

What the manifest (`model.yaml`) records:

| Item | Example |
| --- | --- |
| Format | `format: 1`, `type: next` |
| Robot | Robot `type`, node name, `port` (by-id, identifies the unit), joint names, motor IDs |
| Inputs | Features and order (`positions`, `velocities`, `target - positions`), units, **`rate_hz`**, history length, normalization mean and variance |
| Model | Architecture (e.g. LSTM 2×128), training settings |
| Data | `logs/` paths used and the sha256 of each file |
| Evaluation | Error on validation data, checks with known weights |
| Provenance | sha256 of the weights, creation time, roboloom commit |

On loading, these are checked and startup is refused on any mismatch:

- The robot `type`, joint names and motor IDs match.
- `rate_hz` equals the robot's `control_hz`. NEXT's history length depends on the rate, so a changed rate needs retraining.
- The sha256 of the weights matches.
- `port` is the same unit. Using it on another unit requires an explicit setting that allows it.

The `roboloom init` template gains a description of `models/` and `*.safetensors` in `.gitignore`.

### Safety

- Feedback is disabled by default. Only joints listed in `feedback.gain` feed back.
- On an expired deadline, `valid=False`, follower `HOLD`, `FAULT` or `ESTOP`, or before controller alignment, the gate closes to zero over `ramp_s`, never at once.
- `estop`, `release` and `quit` make the leader limp as before.
- Feedback current is first limited by `feedback.max_mA`. The total with gravity, hold and barrier is then limited by the existing `max_current_mA`.
- The EEPROM Current Limit is the only limit that remains when the host stops. On XC330 a fired Bus Watchdog does not stop the current. Raising the Current Limit for feedback is written with `commission`, knowingly.
- The existing runaway check (`max_velocity`, out of range) stays active during feedback.
- The follower stays protected by `FollowerSafety`. With the follower in current-based position control (Operating Mode 5), contact force is also capped.

## 7. Implementation steps

Each stage is committed and passes mock tests before moving to hardware. Hardware checks are done by the user.

| Stage | Content | Done when |
| --- | --- | --- |
| 1. Path | Add the `estimators` role, the `ESTIMATORS` registry and the `none` estimator. Add capability declarations and their check when the configuration is read. Derive edges from references in `flow.py`; add the controller `feedback` output and the leader `feedback` input. Feedback values are always zero | Tests in a mock dataflow cover the cyclic edges, the feedback deadline, latest-only delivery, and refusal of configurations whose units or joints do not match. Existing tests pass |
| 2. Follower recording | Add a per-tick trace to the robot node (`positions`, `velocities`, `currents_mA`, `target`, `mode`) in the same form as the leader's `leader_trace.npz`. Allow recording estimator output as `observation.effort_ext` and `observation.contact` | The npz and dataset features are checked in mock |
| 3. Follower mode | Add a configuration example that runs the arms in current-based position (`current_position`, Mode 5) through `control` in `robot.yaml`. Write the mode and Current Limit with `commission` | Hardware: tracking and holding match today's; current stops at the limit in contact |
| 4. `model_residual` | Build a tool that measures holding currents on the follower and identifies `g_f(q)` with the existing regressor (`identify-gravity` for the follower). Implement the `model_residual` estimator | Hardware: record residual size at rest and in free motion; check the residual under a known weight |
| 5. Leader feedback term | Add `feedback` as a part shared by current-mode laws: gate, ramp, deadline, contact hysteresis, `max_mA`, `kd`. Show `feedback_mA` and the gate in status and the trace | Mock: tests ramp to zero on deadline expiry, HOLD and estop. Hardware: enable one joint with a small gain; check the sign and that it does not oscillate |
| 6. Gripper | Move the trigger to a new current-mode law (spring + damping + contact term, like factr2_next's `compute_gripper_feedback_torque`), driven by follower gripper current (Mode 5, Current Limit 54 mA) | Hardware: the trigger gets heavier when gripping an object and returns when released |
| 7. NEXT | Recording procedure for free motion (the stage-2 trace), training (`torch` as an optional extra) and an inference node (running at the robot's rate), under the same contract as `model_residual`. Write weights and manifest as in "Where models are stored" and check them on loading | Hardware: compare with `model_residual` under known weights and pushes. Document the training and inference commands |
| 8. Delay | Report feedback delay (from the follower state's time until the leader writes current) in status. For the rate, see §9 | Hardware: record the delay distribution; document it with the gain limits |
| 9. Docs | For each implemented stage, update Controllers, Robots, Reference and Quick start, and remove the corresponding part of this page | The strict docs build passes |

## 8. Supporting new robots and leaders

A robot added as a follower needs:

- `state` with `positions`, `velocities`, `currents_mA` (or external force) and `target`. For robots without `velocities`, the estimator takes differences.
- One way to provide external force: `sensor` if it has sensors, otherwise `model_residual` or `next`.
- To run under position control. A torque-controlled robot also works if it accepts position targets within `FollowerSafety`'s range.

A device added as a leader needs:

- Current (torque) control on the joints that receive force. Inputs that only produce positions (e.g. VR) are used without feedback.
- Gravity compensation (`gravity_comp`, or that device's gravity model).
- A one-to-one leader–follower joint correspondence in the controller's `joints`.

A leader and follower with different kinematics (different number or order of joints) cannot be mapped joint by joint. They need an estimate of the end-effector force `F`, turned into `Jᵀ F` on the leader. That is out of scope here; the same contract (an estimator that outputs end-effector force instead of `residual`) allows adding it later.

The symmetric approach (robopy's `bilateral_joint`) can also be added later as a control law shared by leader and follower. It needs follower current control, gravity models of both arms and torque constants.

## 9. Open issues

- Delay: Rakuda2's bus runs at 1 Mbps and reads the state in 4 ms (Fast Sync Read). With it and the skipped wait before writes, the leader and follower went from 60 Hz to 120 Hz, checked on the hardware ([Configuration](../reference/configuration.md), Control rate). The feedback path goes through one follower period, estimation, the controller and one leader period, so the delay is expected to be a few periods (about 20–30 ms at 120 Hz). That is still slower than FACTR's 500 Hz, so start with the gate, ramp, damping and weak gains. Raising the bus to 4 Mbps would allow higher rates, but it means rewriting the EEPROM of every motor and is not done here.
- Estimation accuracy: friction and inertia remain in `model_residual`. Fast motion produces residual without contact. The contact threshold suppresses it, but replacing it with NEXT is the plan.
- Current limit: the leader's Current Limit must be raised by the feedback amount. More force remains when the host stops.
- Use in policies: roboloom's scope ends at recording external force. FACTR's curriculum and FIRST belong to training.
- Scope of this study: FACTR 2's user-study numbers appear only in figures and were not verified. factr2_next's README and code disagree in places (e.g. the README lists gravity compensation as a feature, but it is disabled in the shipped configuration).
