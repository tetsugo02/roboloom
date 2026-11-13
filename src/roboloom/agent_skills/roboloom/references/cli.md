# CLI

Prefix with `uv run` and run from the project root. `roboloom <command> --help` lists the
arguments. `[robot]` is optional when `.roboloom/` holds one robot; a robot name or YAML
path also works. For commands with other positional words the first word is the robot only
when it names one (`roboloom commission follower` = `roboloom commission rakuda2 follower`).

Flags of commands that open devices:

| Flag | Meaning |
| --- | --- |
| `--with a,b` | enable options (plus what they `requires`; disables `conflicts`) |
| `--without a,b` | disable options (also `default: true` ones, and options requiring them) |
| `--mock` | mock devices instead of hardware (hardware is the default) |
| `--video-codec av1\|h264` | codec of `storage: video` images (omitted: the recorder YAML; see [configuration](configuration.md#video-codec)) |

`--hardware` was removed; passing it is an error.

## Commands

| Command | Purpose | Opens devices |
| --- | --- | --- |
| `roboloom [robot]` / `roboloom launch [robot]` | launcher: pick robot, operation, options, mock | on Launch |
| `roboloom init <robot> [--root DIR]` | create `.roboloom/<robot>/` from the template | no |
| `roboloom validate [robot]` | check configuration + dataflow; print options and dataset | no |
| `roboloom probe <port> [--device dynamixel\|pika\|pika_sense] [--ids 1,2] [--baudrate N]` | read-only bus inspection (a CAN name reads a PiPER) | reads |
| `roboloom commission [robot] <node>` | diff and write Dynamixel EEPROM after confirmation | writes |
| `roboloom calibrate-joints <calibration>` | save counts at the URDF zero pose | reads |
| `roboloom measure-travel <calibration> --out <path>` | save range moved by hand | reads |
| `roboloom identify-gravity <calibration> --out <path> --collect` | holding currents → gravity model | energizes |
| `roboloom tune-gravity [robot] leader <group> --with gravity` | interactive gain/hold tuning (TTY only) | energizes |
| `roboloom gravity-check [robot] leader <group> --with gravity` | pose change with/without compensation | energizes |
| `roboloom watchdog-test [robot] <node> <joint>` | bench test of the Bus Watchdog | energizes |
| `roboloom check-hold [robot] <follower> --tolerance <v> [--seconds 10]` | measure `unattended` for `unknown` models | energizes |
| `roboloom capture-pose [robot] [follower] <name> [--force]` | save current follower pose to `poses/` | reads |
| `roboloom run [robot] [--plain]` | operator screen, many episodes | yes |
| `roboloom record [robot] --task <text> --seconds <n> [--episodes 1] [--home] [--plain]` | fixed-length episodes | yes |
| `roboloom infer [robot] --seconds <n> [--episodes 1] [--policy mod:fn] [--policy-kwargs JSON] [--task <text>] [--home] [--plain]` | policy episodes (`--home`: the policy's `home:` pose first); enables option `policy`; saves only with `--task` | yes |
| `roboloom session [robot] <start\|stop\|save\|discard\|estop\|release\|home\|quit> [task]` | send one operation to a running `run` | no |
| `roboloom convert-handheld [robot] --action delta\|relative-chunk [--horizon 16] [--hands a,b] [--max-gap 3] [--output P] [--repo-id R]` | hand-held recording → training dataset (in development) | no |
| `roboloom skills install\|check\|path [--agent all\|agents\|claude] [--root .] [--force]` | install / check this agent skill | no |

`calibrate-joints`, `measure-travel`, `identify-gravity`, `commission`, `watchdog-test`,
`tune-gravity`, `gravity-check` are Dynamixel-only. `commission`, `watchdog-test`,
`check-hold`, `gravity-check` refuse mock configurations.

## Examples

```bash
uv run roboloom validate --with digit
uv run roboloom run --mock
uv run roboloom run --with gravity              # skips the launcher
uv run roboloom record --task "pick up the cup" --seconds 30 --episodes 3 --home
uv run roboloom infer --seconds 20 --policy my_lab.policies:load --task "pick up the cup"
uv run roboloom session start handover          # from another terminal
```

## Interactive vs. non-interactive

- In a terminal, `run`/`record`/`infer` open the launcher first unless `--with`,
  `--without` or `--plain` is given. The last choice is kept in
  `.roboloom/<robot>/logs/last_launch.yaml`.
- Before a hardware launch from a terminal the CLI compares Dynamixel EEPROM with the
  chosen options and writes differences after confirmation (e.g. `gravity` changes the
  leader's Operating Mode).
- `record --plain` / `infer --plain` and non-TTY runs need no key input – use these from
  an agent's shell (still hardware unless `--mock`). `run --plain` is line input.
  `tune-gravity` refuses non-TTY.

## Operator screen (Textual)

Operations: `start <task>`, `stop` (no torque change), `save`, `discard`, `home`,
`release` (support confirmation), `estop`, `quit` (Cancel / follower hold / choose options
again / supported release; Cancel selected first). Keys: Ctrl-L command input, Tab
completion, ↑↓ history, Ctrl-N/Ctrl-P panes, **Ctrl-G emergency stop**, Ctrl-C/Ctrl-Q exit
dialog. `FAULT`, `ESTOP`, `RELEASED` latch and never recover automatically.
