# Operator screen

| Detail | Description |
| --- | --- |
| — | Interactive `run`, `record`, `infer`, and `tune-gravity` use Textual. There is a launcher that chooses the operation and launch options before starting, and an operator screen that controls the running dataflow. The operator screen does not edit configuration or switch options. Options are never switched while the dataflow runs (they change control modes). |

## Launcher { #launcher }

| Detail | Description |
| --- | --- |
| — | `roboloom` (or `roboloom launch`) opens it. Naming the robot, as in `roboloom rakuda2`, skips the robot list. In an interactive terminal, `run`, `record`, and `infer` also open the launcher first unless `--with`, `--without`, or `--plain` is given; the command's arguments become its initial values. |

### Screens { #launcher-screens }

| Screen or field | Contents |
| --- | --- |
| Robot list | On the left the robots under `.roboloom/` with a `config.yaml` (with their dataset name and default options), on the right the highlighted robot's configuration (file, dataset name, and each option with its help, `requires`, conflicts, dataset name, and whether it is on by default). The cursor starts on the last robot |
| Operation | Choose `run`, `record`, or `infer`. For `record` and `infer`, enter task, seconds, and episodes, and whether to move home before every episode ("move home before every episode") |
| Options | The configuration's `options:` as cards with their `help` text (green when on, a yellow line and the reason when a conflict would turn one off). Ticking one also enables the options in its `requires` and unticks those in `conflicts`; unticking one also unticks the options that require it. The tooltip shows the reason for a conflict. Choosing `infer` turns on the option named `policy` when the configuration declares one |
| Devices | "mock devices (no hardware)" uses mock devices. "Video codec (storage: video)" chooses the video codec (`YAML / dataset`, `AV1`, `H.264`); `YAML / dataset` keeps the recorder YAML's choice (when appending, the saved videos' codec; H.264 when neither says; [Video codec](configuration/recorder.md#video-codec)) |
| Summary | The operation, `mock` or `HARDWARE` (`mock (mode: mock in config.yaml)` when the YAML declares mock without the checkbox), the enabled options, the dataset name, the video codec, and the node files that are replaced (removals as `(removed)`). For a combination that cannot start or missing input, it shows the reason and disables Launch |
| Sensors and policy observations | Separate checkboxes for the sensors to start and the policy's observations. The observation checkboxes follow the selected policy YAML when launch options change, including when switching to inference. Once observations are explicitly selected (including an empty selection), later mode or option changes preserve them ([sensor selection](cli.md#sensor-selection)) |
| Detail | Description |
| --- | --- |
| — | The second screen is split into the operation pane on the left (Operation, Devices), the options pane on the right, and the summary pane at the bottom. Below 90 columns the panes stack vertically. |

### Keys { #launcher-keys }

| Key or action | Effect |
| --- | --- |
| Enter (robot list) | Select and move on to the next screen |
| Esc (robot list) | Exit without starting anything |
| Launch (Ctrl-S) | Start |
| Cancel | Exit without starting anything |
| Back (Esc) | When it came from the robot list, return to the list; otherwise Esc is the same as Cancel |
| Drag a border, or focus it and use the arrow keys | Resize the panes (as on the operator screen) |
| Double-click a border, Ctrl-R | Reset the pane sizes |

### Saved choices { #launcher-files }

| File | Contents |
| --- | --- |
| `.roboloom/logs/last_robot` | The robot chosen; where the list's cursor starts next time |
| `.roboloom/<robot>/logs/last_launch.yaml` | The operation, options, devices, and sensor and observation choices; the next initial values. Observations keep whether they use the YAML defaults or an explicit override |

## Layout { #layout }

| Area | Contents |
| --- | --- |
| Header | The robot, mode (operation, mock or hardware, enabled options), recording progress, and warnings |
| Status tab | The node list and details, side by side at widths of 100 columns or more; below that, use Details to inspect the selected node |
| Details tab | The selected node's state, fields, units, and update age. Node selection changes the display; operations still target the whole dataflow |
| Logs tab | Hidden until its tab is selected. Scrolls independently; messages arriving while it is hidden are retained, and new entries preserve your position while reading older logs. Retains up to 10,000 lines; the full dora log stays in `logs/` beside the configuration |
| Operations | Stays visible below every tab and uses roughly half of the content area, with at least 10 rows by default at the supported 80×24 size (six at minimum). Unavailable operations remain in the menu with a reason. The operations menu has initial focus |
| Dividers | The vertical divider between the node list and details changes their widths; the horizontal divider above Operations changes the heights (also in Logs and at 80×24). Double-click a divider to reset that direction. Minimum sizes keep the panes and command input usable |
| Detail | Description |
| --- | --- |
| — | Resizing preserves the active tab, node selection, and command text. Width and height proportions last for the session and survive terminal resizing and tab changes. They are not saved to disk. |

### Colors { #colors }

| Item | Color |
| --- | --- |
| Node state (list and details) | Green when OK, yellow for warnings, red for errors |
| A node with no update for over 2 s | Red `STALE` |
| Home pose name (details) | Magenta |
| Task being recorded (details) | Cyan |
| Limits, rejections and errors (details) | Yellow or red |
| Header warning, `UNSAVED` | Yellow |
| Emergency stop | Red |
| Unavailable operations | Dimmed |
| Log lines | Keep the color of each report (recording, emergency stop and so on) |

## Keys { #keys }

| Key | Action |
| --- | --- |
| ↑ / ↓ | Select an item; browse history in the command input |
| Enter | Run the selected operation or submit a command |
| Tab / Shift-Tab | Cycle command-name completions in the input; change focus elsewhere |
| Ctrl-N / Ctrl-P | Move between panes; they also focus the dividers |
| Ctrl-L | Focus the command input |
| Esc | Cancel completion or a confirmation; release an active drag |
| Ctrl-G | Request emergency stop without confirmation (also in confirmations and while dragging) |
| Ctrl-C / Ctrl-Q | Open the common exit confirmation |
| Ctrl-O | Open Logs at the latest entry |
| Arrow keys (divider focused) | Resize along the divider's direction |
| Ctrl-R / Home (divider focused) | Reset that divider |
| Detail | Description |
| --- | --- |
| — | Outside input and confirmations, these character keys request operations. They are suppressed while typing and inside dialogs. |

| Key | Operation |
| --- | --- |
| `e` | estop |
| `q` | quit |
| `h` | home |
| `s` | save |
| `d` | discard |
| `t` | Teleop (hand over to the leader; only with `teleop:` in the policy) |
| `p` | Policy (hand back; only with `teleop:` in the policy) |
| Detail | Description |
| --- | --- |
| — | `t` and `p` work while recording and say why when unavailable ([teleoperation and interventions](../policy/intervention.md#teleop)). |

| Alias | Same as |
| --- | --- |
| F2 | Focus the command input |
| F6 / Shift-F6 | Pane movement |
| F12 | Emergency stop |
| Ctrl-End | Latest log entry |
| Detail | Description |
| --- | --- |
| — | The footer displays the primary Ctrl combinations. |

### Command input { #command-input }

| Detail | Description |
| --- | --- |
| — | Supports cursor movement, Delete, Backspace, and Japanese text. |
| — | History lasts only for this session. Confirmation answers are excluded from history. |
| — | Completion never executes an operation: Enter first accepts the visible candidate, and a second Enter submits it. |
| — | Multiline paste becomes one space-separated line and is not submitted automatically. |

## Operations { #operations }

| Detail | Description |
| --- | --- |
| — | Use these operations from either the menu or input. What each does is listed in [run operations](cli.md#run-operations). |

| Operation | On the screen |
| --- | --- |
| `start <task>` | Start in `run` opens the input for a task. A rejected start is a warning; status updates continue and you can retry once ready |
| `stop` | Stop following and recording |
| `save` | Typing `save success` or `save failure` in the input saves the episode with its evaluation verdict ([Episode records](../data/recording.md#episode-records)); anything else is refused and the episode stays stopped, not saved |
| `discard` | Discard the episode |
| `home` | Available only when a controller has a home pose; readiness is checked again after arrival |
| `release` | Names, from the devices' traits ([Behaviour without torque and when left alone](configuration/followers.md#torque-off-and-unattended)), what to support and what to empty, and asks you to confirm |
| `estop` | Emergency stop. Reports send failure, sent but unconfirmed, and fresh follower ESTOP confirmation separately; it cannot guarantee delivery through a disconnected bus or dataflow |
| `quit` | Open the exit confirmation |

### Exit confirmation { #exit-confirmation }

| Detail | Description |
| --- | --- |
| — | Cancel is initially selected. The confirmation names the devices that go (or may go) limp when the session ends and what to do about them. |

| Choice | Shown when | Effect |
| --- | --- | --- |
| Cancel | always | Return to the operator screen |
| Follower hold | some follower holds (otherwise "Quit without releasing") | Quit with the followers holding |
| Release and quit | some follower has torque | Confirm support, release, and quit |
| Quit and choose options again (followers hold) | an interactive terminal started from the CLI | Quit with the followers holding and return to the launcher to choose options again |
| Detail | Description |
| --- | --- |
| — | Actuated inputs release on exit even when followers hold. |
| — | UI failure keeps followers holding unless a release choice was already confirmed. |
| — | When the whole roboloom process stops (killed, its terminal closed), the dataflow discards the episode in progress, lets the followers hold and ends. |

## record and infer { #record-and-infer }

| Detail | Description |
| --- | --- |
| — | `record` and `infer` show readiness, episode count, remaining time, and save results. |

| Item | Behavior |
| --- | --- |
| Start | Select Start for each episode after readiness. `record --home` moves home before every episode |
| Saving | `record` saves; `infer` saves only with `--task`. Stop can finish a timed episode early and apply the same save policy |
| Count | After the requested episodes, the exit confirmation opens. The count is a goal, not a limit: close the confirmation and you can move the robot with Home or Teleop and run another episode with Start (shown as `episode 3 (2 planned)`). `--plain` ends after the count |
| Detail | Description |
| --- | --- |
| — | During an episode the top line shows its progress. |
| — | `episode 2/10  step 137/500  [█████░░░░░░░░░░░░░░░] 27%  at most 72.6 s left` |
| — | `step` is the number of actions the policy has executed; it appears when the length is given in steps (`infer --steps`, `steps` in an experiment file). Such an episode ends as soon as the policy has executed that many actions. With a length in seconds the bar shows the share of the time. |

## Gravity tuning { #gravity-tuning }

| Detail | Description |
| --- | --- |
| — | `tune-gravity` remains a separate command ([`roboloom tune-gravity`](cli.md#tune-gravity)). Stop the dataflow before opening the same bus. Its node list selects joints, and Details describes the selected joint and measured/model/sent current in mA. The menu and input share these commands: |
| — | `joint <name>`<br>`gain +`<br>`gain -`<br>`hold +`<br>`hold -`<br>`compare`<br>`resume`<br>`save`<br>`estop`<br>`quit` |

| Key | Action | Range |
| --- | --- | --- |
| `]` / `[` | Raise or lower the selected joint's gain | steps of 0.1 in [0, 3] |
| `=` / `-` | Raise or lower hold | steps of 5 mA in [0, 100] |
| `0` | Compare gravity | — |
| `r` | Resume a recoverable STOPPED state after support | — |
| Ctrl-G | Release torque at the next control step and latch ESTOP; resume cannot energize the device again until restart | — |
| Detail | Description |
| --- | --- |
| — | The character keys work outside input and dialogs. Opening, energizing, reading, changing values, and closing belong to one control thread at the configured period. File saving uses a detached snapshot on another thread. Changes made during saving stay unsaved. Exit offers Cancel, Save and quit, and Discard and quit; Cancel is initially selected. See [Gravity tuning](../explanation/gravity-compensation.md) for physical commissioning and interpretation. |

## Plain mode and Python API { #plain-mode }

| Invocation | Behavior |
| --- | --- |
| `run --plain` | Keeps line input |
| `record --plain`, `infer --plain` | Run the requested episodes without key input |
| Non-TTY | Selects these paths automatically |
| `tune-gravity` (non-TTY) | Rejected before opening any device |
| Detail | Description |
| --- | --- |
| — | `Session.launch(..., screen="auto")` continues to use a Rich status display at approximately 10 Hz. It reads no stdin, so `print()`, `input()`, and the existing operator exit prompts continue to work. `screen=False` disables that display; `operator=None` disables operator prompts. The CLI Textual backend launches with both settings and performs its own confirmations. See [Session](python-api/session.md). |

## Extending the display { #extending-the-display }

| Detail | Description |
| --- | --- |
| — | Follower, input, sensor, and controller registration and status publication remain the normal extension path. Publish the usual role, level, timestamp, and fields through `StatusReporter`; choose field names that include units. Joint counts, names, IDs, and units are not fixed in the common screen. Unknown roles and fields use generic key/value details. |
| — | A special display is optional. Register a presenter explicitly before starting the application. Device kind (the node YAML's `type`) takes precedence over a role presenter; existing `ui.render.RENDERERS` role renderers remain the next fallback, followed by generic values. The Presenter receives a `NodeSnapshot` and returns a `Presentation`, without widgets or device access: |
| — | `register_presenter(kind="my_stage")` / `register_presenter(role="my_role")`: `NodeSnapshot` → `Presentation(state, detail, fields)` |
| — | Use `role="my_role"` instead for a role presenter. A backend provides typed `Snapshot` / `Capabilities` / `Operation` values and receives operation requests through `ui.models.Backend`. Operations declare availability, reasons, and confirmation requirements for both menu and input. Backend and device implementations do not depend on Textual widgets. Extensions are explicit Python registrations; there is no external plugin discovery or new configuration format. |
| — | Thread notifications use [Textual messages](https://textual.textualize.io/guide/workers/). The tests use fake backends, MockBus, and [run_test / Pilot](https://textual.textualize.io/guide/testing/). Mock success does not establish hardware stop timing or collection quality. |

## Hook status { #hooks }

| Field | Unit | Meaning |
| --- | --- | --- |
| `hook_ms` <span class="status status--mock">Mock only</span> | ms | Total step-hook time in the latest period |
| `hook_max_ms` <span class="status status--mock">Mock only</span> | ms | Largest total this episode |
| `hook_errors` <span class="status status--mock">Mock only</span> | count | Step errors and barrier failures counted by on_error |
| `hook_over` <span class="status status--mock">Mock only</span> | count | Hook calls exceeding their measured budget |
| `filtered` <span class="status status--mock">Mock only</span> | periods | Periods changed by the chain this episode (policy and teleop) |
