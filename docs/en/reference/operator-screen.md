# Operator screen

Interactive `run`, `record`, `infer`, and `tune-gravity` use Textual. There is a launcher that chooses the operation and launch options before starting, and an operator screen that controls the running dataflow. The operator screen does not edit configuration or switch options.

## Launcher

`roboloom` (or `roboloom launch`) opens it. The first screen is the robot list: on the left the robots under `.roboloom/` with a `config.yaml`, on the right the highlighted robot's configuration (file, dataset name, and each option with its help, `requires`, conflicts, dataset name, and whether it is on by default). The cursor starts on the last robot; Enter moves on to the next screen and Esc exits. Naming the robot, as in `roboloom rakuda2`, skips the list. In an interactive terminal, `run`, `record`, and `infer` also open the launcher first unless `--with`, `--without`, or `--plain` is given.

- Operation: choose `run`, `record`, or `infer`. For `record` and `infer`, enter task, seconds, and episodes; for `record`, "move home before every episode" can also be chosen.
- Options: lists the configuration's `options:` with their `help` text. Ticking one also enables the options in its `requires` and unticks those in `conflicts`; unticking one also unticks the options that require it. The tooltip shows the reason for a conflict.
- Devices: "mock devices (no hardware)" uses mock devices.
- Summary: shows the operation, `mock` or `HARDWARE`, the enabled options, the dataset name, and the node files that are replaced (removals as `(removed)`). For a combination that cannot start or missing input, it shows the reason and disables Launch.

The next screen is split into the operation pane on the left (Operation, Devices), the options pane on the right (one card per option: green when on, a yellow line and the reason when a conflict would turn it off), and the summary pane at the bottom. On both screens the pane borders adjust like the operator screen's: drag them, or focus them and use the arrow keys; double-click or Ctrl-R resets. Below 90 columns the panes stack vertically.

Launch (Ctrl-S) starts; Cancel exits without starting anything. When it came from the robot list, Back (Esc) returns to the list; otherwise Esc is the same as Cancel. The choice is saved in `.roboloom/<robot>/logs/last_launch.yaml` and becomes the next initial value.

## Layout and focus

The header shows the robot, mode (operation, mock or hardware, enabled options), recording progress, and warnings. Select a node to inspect its state, fields, units, and update age. Node selection changes the display; operations still target the whole dataflow. Unavailable operations remain in the menu with a reason. The operations menu has initial focus.

Status, Details, and Logs tabs are always available. Status shows the node list and details side by side at widths of 100 columns or more; below that, use Details to inspect the selected node. Logs stays hidden until its tab is selected. Operations stays visible below every tab and uses roughly half of the content area, with at least 10 rows by default at the supported 80×24 size. Resizing preserves the active tab, node selection, and command text. Drag the vertical divider between the node list and details to change their widths. Drag the horizontal divider above Operations to change the heights of the upper pane and Operations, including in Logs and at 80×24. Double-click a divider to reset that direction. Minimum sizes keep the panes and command input usable; Operations can be reduced to six rows. Width and height proportions last for the session and survive terminal resizing and tab changes. They are not saved to disk.

Ctrl-N / Ctrl-P also focus the dividers. When a divider is focused, use the arrow keys along its direction to resize and Ctrl-R to reset it (Home is an alias). Esc releases an active drag. Emergency stop remains available during dragging.

Important items are shown in color. Node states in the list and the details are green when OK, yellow for warnings and red for errors; a node with no update for over 2 s turns into a red `STALE`. The details highlight the home pose name in magenta, the task being recorded in cyan, and limits, rejections and errors in yellow or red. The header warning and `UNSAVED` are yellow, Emergency stop is red, and unavailable operations are dimmed. Log lines keep the color of each report (recording, emergency stop and so on).

The log scrolls independently; messages arriving while it is hidden are retained, and new entries preserve your position while reading older logs. Ctrl-O opens Logs at the latest entry. The log retains up to 10,000 lines; the full dora log stays in `logs/` beside the configuration.

| Key | Action |
| --- | --- |
| ↑ / ↓ | Select an item; browse history in the command input |
| Enter | Run the selected operation or submit a command |
| Tab / Shift-Tab | Cycle command-name completions in the input; change focus elsewhere |
| Ctrl-N / Ctrl-P | Move between panes |
| Ctrl-L | Focus the command input |
| Esc | Cancel completion or a confirmation |
| Ctrl-G | Request emergency stop without confirmation |
| Ctrl-C / Ctrl-Q | Open the common exit confirmation |
| Ctrl-O | Open Logs at the latest entry |

The input supports cursor movement, Delete, Backspace, and Japanese text. History lasts only for this session. Completion never executes an operation: Enter first accepts the visible candidate, and a second Enter submits it. Multiline paste becomes one space-separated line and is not submitted automatically. Confirmation answers are excluded from history.

Outside input and confirmations, `e`, `q`, `h`, `s`, and `d` request estop, quit, home, save, and discard. These character shortcuts are suppressed while typing and inside dialogs. Ctrl-G remains available in confirmations.

F2, F6 / Shift-F6, F12, and Ctrl-End remain aliases for command input, pane movement, emergency stop, and latest log. The footer displays the primary Ctrl combinations.

## Operations

Use `start <task>`, `stop`, `save`, `discard`, `home`, `release`, `estop`, and `quit` from either the menu or input. Start in `run` opens the input for a task. A rejected start is a warning; status updates continue and you can retry once ready. Home is available only when a controller has a home pose, and readiness is checked again after arrival.

Release names, from the devices' traits ("Behaviour without torque and when left alone" in [Configuration](configuration.md)), what to support and what to empty, and asks you to confirm. Exit offers Cancel, follower hold (when some follower holds), release and quit (when available), and choosing options again (Quit and choose options again). Cancel is initially selected. The confirmation names the devices that go (or may go) limp when the session ends and what to do about them. Options are never switched while the dataflow runs (they change control modes); choosing them again quits with the followers holding and returns to the launcher. This choice appears only in an interactive terminal started from the CLI. Actuated inputs release on exit even when followers hold. UI failure keeps followers holding unless a release choice was already confirmed. An emergency request reports send failure, sent but unconfirmed, and fresh follower ESTOP confirmation separately; it cannot guarantee delivery through a disconnected bus or dataflow.

`record` and `infer` show readiness, episode count, remaining time, and save results. Select Start for each episode after readiness. `record --home` moves home before every episode. `record` saves; `infer` saves only with `--task`. Stop can finish a timed episode early and apply the same save policy. After the requested episodes, the exit confirmation opens.

## Gravity tuning

`tune-gravity` remains a separate command. Stop the dataflow before opening the same bus. Its node list selects joints, and Details describes the selected joint and measured/model/sent current in mA. The menu and input share these commands:

```text
joint <name>
gain +
gain -
hold +
hold -
compare
resume
save
estop
quit
```

Gain changes by 0.1 in [0, 3]; hold changes by 5 mA in [0, 100]. Outside input and dialogs, `]` / `[` change gain, `=` / `-` change hold, `0` compares gravity, and `r` resumes a recoverable STOPPED state after support. Ctrl-G releases torque at the next control step and latches ESTOP; resume cannot energize the device again until restart.

Opening, energizing, reading, changing values, and closing belong to one control thread at the configured period. File saving uses a detached snapshot on another thread. Changes made during saving stay unsaved. Exit offers Cancel, Save and quit, and Discard and quit; Cancel is initially selected. See [Gravity tuning](gravity-tuning.md) for physical commissioning and interpretation.

## Plain mode and Python API

`run --plain` keeps line input. `record --plain` and `infer --plain` run the requested episodes without key input. Non-TTY invocation selects these paths automatically. `tune-gravity` rejects non-TTY invocation before opening any device.

`Session.launch(..., screen="auto")` continues to use a Rich status display at approximately 10 Hz. It reads no stdin, so `print()`, `input()`, and the existing operator exit prompts continue to work. `screen=False` disables that display; `operator=None` disables operator prompts. The CLI Textual backend launches with both settings and performs its own confirmations. See [Python API](python-api.md).

## Extending the display

Follower, input, sensor, and controller registration and status publication remain the normal extension path. Publish the usual role, level, timestamp, and fields through `StatusReporter`; choose field names that include units. Joint counts, names, IDs, and units are not fixed in the common screen. Unknown roles and fields use generic key/value details.

A special display is optional. Register a presenter explicitly before starting the application. Device kind (the node YAML's `type`) takes precedence over a role presenter; existing `ui.render.RENDERERS` role renderers remain the next fallback, followed by generic values. The Presenter receives a `NodeSnapshot` and returns a `Presentation`, without widgets or device access:

```python
from roboloom.ui.models import NodeSnapshot
from roboloom.ui.presenters import Presentation, register_presenter


@register_presenter(kind="my_stage")
def stage(node: NodeSnapshot) -> Presentation:
    return Presentation(
        str(node.fields.get("state", "")),
        "Position in millimetres",
        tuple((key, str(value)) for key, value in node.fields.items()),
    )
```

Use `role="my_role"` instead for a role presenter. A backend provides typed `Snapshot` / `Capabilities` / `Operation` values and receives operation requests through `ui.models.Backend`. Operations declare availability, reasons, and confirmation requirements for both menu and input. Backend and device implementations do not depend on Textual widgets. Extensions are explicit Python registrations; there is no external plugin discovery or new configuration format.

Thread notifications use [Textual messages](https://textual.textualize.io/guide/workers/). The tests use fake backends, MockBus, and [run_test / Pilot](https://textual.textualize.io/guide/testing/). Mock success does not establish hardware stop timing or collection quality.
