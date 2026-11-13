"""The launcher: choose the robot, then the operation, the launch options and
mock/hardware before the dataflow starts. Options are never switched while it runs (they change control modes);
the operator screen's quit dialog offers "choose options again", which comes back here.

The rules (requirements, conflicts, dataset names) are the configuration's own
(`roboloom.config`); this screen only presents them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import ClassVar, Literal

import yaml
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Input,
    Label,
    OptionList,
    RadioButton,
    RadioSet,
    Static,
)

from ..config import (
    CONFIG_FILE,
    INFER_OPTION,
    PROJECT_ROOT,
    Option,
    check_options,
    dataset_suffix,
    option_changes,
    parse_options,
    project_robots,
    read_config,
    toggle_option,
)
from ..errors import ConfigError
from ..recording.video import VIDEO_CODECS, normalize_video_codec
from .splitter import Splitter

MODES = ("run", "record", "infer")
# Video codec choices: `VIDEO_DEFAULT` leaves the choice to the recorder YAML (and, when
# appending, to the saved videos); the others are recording.video.VIDEO_CODECS names.
VIDEO_DEFAULT = "yaml"
VIDEO_CHOICES = {
    VIDEO_DEFAULT: "YAML / dataset",
    **{name: codec.label for name, codec in VIDEO_CODECS.items()},
}
BACK: Literal["back"] = "back"  # the options screen's Back: choose the robot again


@dataclass(frozen=True)
class LaunchPlan:
    """What the launcher (or the command line) decided to start."""

    mode: str = "run"
    options: tuple[str, ...] = ()
    mock: bool = False
    task: str = ""
    seconds: float = 0.0
    episodes: int = 1
    home: bool = False
    sensors: list[str] | None = None
    observe: list[str] | None = None
    video_codec: str | None = None  # None: the recorder YAML (recording.video)

    def problem(self) -> str:
        """Why it cannot start, or ''."""
        if self.mode not in MODES:
            return f"unknown operation {self.mode}"
        if self.mode in ("record", "infer"):
            if self.seconds <= 0 or self.episodes < 1:
                return "seconds > 0 and episodes >= 1 are required"
            if self.mode == "record" and not self.task.strip():
                return "record needs a task"
        return ""


def last_path(config: Path) -> Path:
    """The previous choices, next to the configuration (logs/ is ignored by git)."""
    return config.parent / "logs" / "last_launch.yaml"


def load_last(config: Path, options: dict[str, Option]) -> LaunchPlan | None:
    try:
        data = yaml.safe_load(last_path(config).read_text()) or {}
        plan = LaunchPlan(
            mode=str(data.get("mode", "run")),
            sensors=data.get("sensors"),
            observe=data.get("observe"),
            video_codec=_codec(data.get("video_codec")),
            options=tuple(n for n in data.get("options", []) if n in options),
            mock=bool(data.get("mock", False)),
            task=str(data.get("task", "")),
            seconds=float(data.get("seconds", 0.0)),
            episodes=int(data.get("episodes", 1)),
            home=bool(data.get("home", False)),
        )
        check_options(options, plan.options)
        return plan
    except (
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        yaml.YAMLError,
        ConfigError,
    ):
        return None


def _codec(value: object) -> str | None:
    """A saved codec, or None when it is no longer accepted."""
    try:
        return normalize_video_codec(value)
    except ConfigError:
        return None


def save_last(config: Path, plan: LaunchPlan) -> None:
    data = asdict(plan)
    data["options"] = list(plan.options)
    try:
        path = last_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    except OSError:
        pass  # a convenience only


def conflict_reason(options: dict[str, Option], chosen: set[str], name: str) -> str:
    clash = sorted(
        o
        for o in chosen
        if o != name and (o in options[name].conflicts or name in options[o].conflicts)
    )
    return f"cannot be used with {', '.join(clash)}" if clash else ""


def last_robot_path(root: Path) -> Path:
    return root / "logs" / "last_robot"


class OptionToggle(Checkbox):
    """A checkbox drawn as a small chip: empty when off, a green tick when on."""

    BUTTON_LEFT = " "
    BUTTON_INNER = "✓"
    BUTTON_RIGHT = " "
    DEFAULT_CSS = """
    OptionToggle {
        border: none;
        padding: 0;
        background: transparent;
        width: 1fr;
        & > .toggle--button { color: $panel; background: $panel; }
        &.-on > .toggle--button { color: $text; background: $success; text-style: bold; }
        & > .toggle--label { padding: 0 1; }
        &:focus { border: none; background-tint: transparent; }
        &:focus > .toggle--label {
            color: $text;
            background: transparent;
            text-style: bold underline;
        }
    }
    """


class Panes:
    """Resizable panes for the launcher screens, with the operator screen's Splitter:
    drag, or focus and use the arrow keys; double-click or Ctrl-R resets. `ratio` is
    the first column's share of the width; `bottom` the bottom pane's height (rows)."""

    NARROW = 90  # below this width the panes stack

    def __init__(self, ratio: float, bottom: int = 0) -> None:
        self.default_ratio, self.default_bottom = ratio, bottom
        self.ratio, self.bottom = ratio, bottom

    def columns(self, width: int, minimum: int = 24) -> int:
        """The first column's width in cells, leaving `minimum` for the other."""
        available = max(1, width - 1)
        return min(
            max(minimum, round(available * self.ratio)),
            max(minimum, available - minimum),
        )

    def reset(self, axis: str) -> None:
        if axis == "x":
            self.ratio = self.default_ratio
        else:
            self.bottom = self.default_bottom


class RobotApp(App[str | None]):
    """The first launcher screen: which robot under the project root to operate. The
    list and the selected robot's details are resizable panes."""

    TITLE = "roboloom"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #title { height: 1; padding: 0 1; background: $boost; text-style: bold; }
    #panes { height: 1fr; layout: grid; grid-size: 3 1; grid-columns: 1fr 1 1fr; }
    #panes.narrow { grid-size: 1 3; grid-columns: 1fr; grid-rows: 1fr 1 1fr; }
    #robots, #robot-detail { border: round $primary; height: 1fr; }
    #robot-detail { padding: 0 1; }
    #detail { height: auto; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, root: Path, robots: list[str], initial: str | None = None):
        super().__init__()
        self.root, self.robots = root, robots
        self.initial = initial if initial in robots else robots[0]
        self.panes = Panes(0.4)

    def compose(self) -> ComposeResult:
        yield Static(
            f"roboloom — choose the robot  ({self.root})", id="title", markup=False
        )
        with Container(id="panes"):
            yield OptionList(*self.robots, id="robots")
            yield Splitter("x", id="col-splitter")
            yield Splitter("y", id="row-splitter")
            with VerticalScroll(id="robot-detail"):
                yield Static("", id="detail", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#robots").border_title = "Robots · Enter: select"
        self.query_one("#robot-detail").border_title = "Configuration"
        robots = self.query_one("#robots", OptionList)
        robots.highlighted = self.robots.index(self.initial)
        robots.focus()
        self._show(self.initial)
        self._layout()

    def _show(self, robot: str) -> None:
        self.query_one("#detail", Static).update(robot_detail(self.root, robot))

    def _layout(self) -> None:
        panes = self.query_one("#panes")
        width, height = self.size.width, max(1, self.size.height - 2)
        narrow = width < Panes.NARROW
        panes.set_class(narrow, "narrow")
        self.query_one("#col-splitter").display = not narrow
        self.query_one("#row-splitter").display = narrow
        if narrow:
            top = min(max(3, round(height * self.panes.ratio)), max(3, height - 4))
            panes.styles.grid_rows = f"{top} 1 1fr"
            panes.styles.grid_columns = "1fr"
        else:
            panes.styles.grid_rows = "1fr"
            panes.styles.grid_columns = f"{self.panes.columns(width)} 1 1fr"

    def on_resize(self, _: events.Resize) -> None:
        self._layout()

    def on_splitter_moved(self, event: Splitter.Moved) -> None:
        size = max(
            1, self.size.width if event.splitter.axis == "x" else self.size.height - 2
        )
        self.panes.ratio = min(0.85, max(0.15, self.panes.ratio + event.delta / size))
        self._layout()

    def on_splitter_reset(self, _: Splitter.Reset) -> None:
        self.panes.reset("x")
        self._layout()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        self._show(self.robots[event.option_index])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.exit(self.robots[event.option_index])

    def action_cancel(self) -> None:
        self.exit(None)


def robot_detail(root: Path, robot: str) -> RenderableType:
    """The robot list's right pane: dataset, devices and every option with its rules."""
    path = root / robot / CONFIG_FILE
    try:
        raw = yaml.safe_load(path.read_text()) or {}
        options = parse_options(raw.get("options"))
    except (OSError, yaml.YAMLError, ConfigError, AttributeError) as exc:
        return Text(f"{path}\n\ncannot read: {exc}", style="red")
    repo_id = str(raw.get("repo_id", "?"))
    head = Table.grid(padding=(0, 2))
    head.add_column(style="dim")
    head.add_column()
    head.add_row("file", str(path))
    head.add_row("dataset", repo_id)
    head.add_row("devices", f"{raw.get('mode', 'hardware')} by default")
    table = Table.grid(padding=(0, 1))
    table.add_column(width=1)
    table.add_column(ratio=1)
    for name, option in options.items():
        cell = Text(name, style="bold")
        if option.help:
            cell.append(f"\n{option.help}", style="dim")
        rules = [f"requires {', '.join(option.requires)}"] if option.requires else []
        rules += [f"not with {', '.join(option.conflicts)}"] if option.conflicts else []
        if option.dataset:
            rules.append(f"dataset {repo_id}-{option.dataset}")
        if rules:
            cell.append("\n" + " · ".join(rules), style="italic")
        table.add_row(
            Text("✓", style="bold green") if option.default else Text("·"), cell
        )
        table.add_row("", "")
    title = Text("\noptions" if options else "\noptions: none", style="bold")
    legend = Text("✓ on by default", style="dim") if options else Text("")
    return Group(head, title, table, legend)


def choose_robot(root: str | Path = PROJECT_ROOT) -> str | None:
    """Show the robot list; the chosen robot (remembered for next time), or None."""
    root = Path(root)
    robots = project_robots(root)
    if not robots:
        raise ConfigError(
            f"no {root}/<robot>/{CONFIG_FILE} here (create one with `roboloom init <robot>`)"
        )
    try:
        last = last_robot_path(root).read_text().strip()
    except OSError:
        last = None
    robot = RobotApp(root, robots, last).run()
    if robot is not None:
        try:
            last_robot_path(root).parent.mkdir(parents=True, exist_ok=True)
            last_robot_path(root).write_text(robot + "\n")
        except OSError:
            pass  # a convenience only
    return robot


class LauncherApp(App[LaunchPlan | Literal["back"] | None]):
    """The options screen: operation (and recording) and devices, the options, and the
    summary, in resizable panes."""

    TITLE = "roboloom"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    Screen { layout: vertical; }
    #title { height: 1; padding: 0 1; background: $boost; text-style: bold; }
    #panes {
        height: 1fr; layout: grid; grid-size: 3 3;
        grid-columns: 1fr 1 1fr; grid-rows: 1fr 1 8;
    }
    #panes.narrow { grid-size: 1 4; grid-columns: 1fr; grid-rows: 1fr 1fr 1 8; }
    #left, #options, #summary-pane { border: round $primary; height: 1fr; padding: 0 1; }
    #row-splitter, #summary-pane { column-span: 3; }
    #panes.narrow #row-splitter, #panes.narrow #summary-pane { column-span: 1; }
    .section { margin-top: 1; color: $text-muted; text-style: bold; }
    .section.first { margin-top: 0; }
    RadioSet#mode, RadioSet#video-codec {
        layout: horizontal; border: none; padding: 0; background: transparent;
    }
    RadioSet#mode > RadioButton, RadioSet#video-codec > RadioButton {
        width: auto; margin-right: 2;
    }
    #recording { height: auto; }
    .field-label { margin-top: 1; color: $text-muted; }
    #task { width: 1fr; }
    #numbers { height: auto; }
    #numbers > Vertical { width: 1fr; height: auto; }
    #numbers > Vertical:first-of-type { margin-right: 2; }
    #numbers Input { width: 1fr; }
    #home, #mock { margin-top: 1; }
    .option {
        height: auto; margin-bottom: 1; padding: 0 1;
        border: none; border-left: outer $panel-lighten-2; background: $boost;
    }
    .option:focus-within { border-left: outer $accent; }
    .option.on { border-left: outer $success; background: $success 12%; }
    .option.blocked { border-left: outer $warning; }
    .option OptionToggle > .toggle--label { text-style: bold; }
    .option.blocked OptionToggle > .toggle--label { color: $text-muted; }
    .option .help { color: $text-muted; padding-left: 4; }
    .option .reason { color: $warning; padding-left: 4; }
    #summary { height: auto; }
    #buttons { height: 3; padding: 0 1; }
    #buttons Button { margin-right: 2; min-width: 12; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "launch", "Launch"),
        Binding("escape", "escape", "Back / Cancel"),
    ]

    def __init__(self, config: Path, initial: LaunchPlan, *, back: bool = False):
        """`back`: offer Back (and Esc) to return to the robot list."""
        super().__init__()
        self.config, self.back = config, back
        raw = yaml.safe_load(config.read_text()) or {}
        self.options = parse_options(raw.get("options"))
        self.sensor_names = list(raw.get("sensors") or {})
        for option in self.options.values():
            for key, value in option.set.items():
                if (
                    key.startswith("sensors.")
                    and value is not None
                    and key[8:] not in self.sensor_names
                ):
                    self.sensor_names.append(key[8:])
        self.observation_names = list(
            dict.fromkeys([*self.sensor_names, *(raw.get("inputs") or {})])
        )
        self.repo_id = str(raw.get("repo_id", ""))
        self.yaml_mock = raw.get("mode") == "mock"  # runs mock even when not ticked
        self.plan = initial
        self.chosen = set(initial.options)

        observation_defaults: list[str]
        try:
            tree = read_config(config, initial.options)
            sensor_defaults = list(tree["sensors"])
            observation_defaults = next(
                (
                    c.get("observe", [])
                    for c in tree["controllers"].values()
                    if c.get("type") == "policy"
                ),
                [],
            )
        except (ValueError, TypeError, OSError):
            sensor_defaults, observation_defaults = [], []
        self.sensor_selection = (
            sensor_defaults if initial.sensors is None else initial.sensors
        )
        self.observation_selection = (
            observation_defaults if initial.observe is None else initial.observe
        )
        self._observe_explicit = initial.observe is not None
        self._observation_options = frozenset(self.chosen)
        self._syncing = False
        self.panes = Panes(0.45, bottom=8)

    def compose(self) -> ComposeResult:
        robot = (
            self.config.parent.name
            if self.config.name == CONFIG_FILE
            else self.config.stem
        )
        yield Static(f"roboloom — {robot}  ({self.config})", id="title", markup=False)
        with Container(id="panes"):
            with VerticalScroll(id="left"):
                with RadioSet(id="mode"):
                    for mode in MODES:
                        yield RadioButton(
                            mode, value=mode == self.plan.mode, id=f"mode-{mode}"
                        )
                with Vertical(id="recording"):
                    yield Label("Task (stored with every frame)", classes="field-label")
                    yield Input(
                        self.plan.task, placeholder="e.g. pick up the cup", id="task"
                    )
                    with Horizontal(id="numbers"):
                        with Vertical():
                            yield Label("Seconds per episode", classes="field-label")
                            yield Input(
                                str(self.plan.seconds or ""),
                                placeholder="30",
                                type="number",
                                id="seconds",
                            )
                        with Vertical():
                            yield Label("Episodes", classes="field-label")
                            yield Input(
                                str(self.plan.episodes),
                                placeholder="1",
                                type="integer",
                                id="episodes",
                            )
                    yield OptionToggle(
                        "Move home before every episode", self.plan.home, id="home"
                    )
                yield Static("Devices", classes="section")
                yield OptionToggle(
                    "Mock devices (no hardware)", self.plan.mock, id="mock"
                )
                yield Static("Video codec (storage: video)", classes="section")
                with RadioSet(id="video-codec"):
                    for codec, label in VIDEO_CHOICES.items():
                        yield RadioButton(
                            label,
                            value=codec == (self.plan.video_codec or VIDEO_DEFAULT),
                            id=f"video-{codec}",
                        )
            yield Splitter("x", id="col-splitter")
            with VerticalScroll(id="options"):
                if not self.options:
                    yield Static("(this configuration declares no options)")
                yield Static("Start / record sensors", classes="section")
                for index, name in enumerate(self.sensor_names):
                    yield OptionToggle(
                        name, name in self.sensor_selection, id=f"sensor-{index}"
                    )
                yield Static("Policy observation inputs", classes="section")
                for index, name in enumerate(self.observation_names):
                    yield OptionToggle(
                        name, name in self.observation_selection, id=f"observe-{index}"
                    )
                for name, option in self.options.items():
                    with Vertical(classes="option", id=f"card-{name}"):
                        yield OptionToggle(name, name in self.chosen, id=f"opt-{name}")
                        if option.help:
                            yield Static(option.help, classes="help", markup=False)
                        yield Static(
                            "", classes="reason", id=f"why-{name}", markup=False
                        )
            yield Splitter("y", id="row-splitter")
            with VerticalScroll(id="summary-pane"):
                yield Static("", id="summary", markup=False)
        with Horizontal(id="buttons"):
            yield Button("Launch", variant="primary", id="launch")
            if self.back:
                yield Button("Back", id="back")
            yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#left").border_title = "Operation"
        self.query_one("#options").border_title = "Options"
        self.query_one("#summary-pane").border_title = "Summary"
        self._sync()
        self._layout()

    # -- layout ------------------------------------------------------------------

    def _layout(self) -> None:
        panes = self.query_one("#panes")
        width, height = self.size.width, max(1, self.size.height - 5)
        narrow = width < Panes.NARROW
        panes.set_class(narrow, "narrow")
        self.query_one("#col-splitter").display = not narrow
        bottom = min(max(3, self.panes.bottom), max(3, height - 6))
        if narrow:
            panes.styles.grid_columns = "1fr"
            panes.styles.grid_rows = f"1fr 1fr 1 {bottom}"
        else:
            panes.styles.grid_columns = f"{self.panes.columns(width, 30)} 1 1fr"
            panes.styles.grid_rows = f"1fr 1 {bottom}"

    def on_resize(self, _: events.Resize) -> None:
        self._layout()

    def on_splitter_moved(self, event: Splitter.Moved) -> None:
        if event.splitter.axis == "x":
            size = max(1, self.size.width - 1)
            self.panes.ratio = min(
                0.85, max(0.15, self.panes.ratio + event.delta / size)
            )
        else:
            limit = max(3, self.size.height - 11)
            self.panes.bottom = min(max(3, self.panes.bottom - event.delta), limit)
        self._layout()

    def on_splitter_reset(self, event: Splitter.Reset) -> None:
        self.panes.reset(event.splitter.axis)
        self._layout()

    # -- state -------------------------------------------------------------------

    def _read(self) -> LaunchPlan:
        mode = next(
            (m for m in MODES if self.query_one(f"#mode-{m}", RadioButton).value),
            self.plan.mode,
        )

        def number(widget: str, kind: type, default: float) -> float:
            try:
                return kind(self.query_one(f"#{widget}", Input).value.strip())
            except ValueError:
                return default

        return replace(
            self.plan,
            mode=mode,
            options=tuple(n for n in self.options if n in self.chosen),
            sensors=[
                n
                for i, n in enumerate(self.sensor_names)
                if self.query_one(f"#sensor-{i}", Checkbox).value
            ]
            if self.sensor_names
            else None,
            observe=[
                n
                for i, n in enumerate(self.observation_names)
                if self.query_one(f"#observe-{i}", Checkbox).value
            ]
            if self._observe_explicit
            else None,
            video_codec=next(
                (
                    codec
                    for codec in VIDEO_CHOICES
                    if codec != VIDEO_DEFAULT
                    and self.query_one(f"#video-{codec}", RadioButton).value
                ),
                None,
            ),
            mock=self.query_one("#mock", Checkbox).value,
            task=self.query_one("#task", Input).value,
            seconds=float(number("seconds", float, 0.0)),
            episodes=int(number("episodes", int, 0)),
            home=self.query_one("#home", Checkbox).value,
        )

    def _refresh_observation_defaults(self) -> None:
        """Follow newly selected policy YAML until the user overrides observations."""
        selected = frozenset(self.chosen)
        if selected == self._observation_options:
            return
        self._observation_options = selected
        if self._observe_explicit:
            return
        try:
            # Only controller defaults are needed; inactive sensor files stay unread.
            tree = read_config(self.config, self.chosen, sensors=[])
        except (ValueError, TypeError, OSError):
            return  # incomplete configurations remain editable in the launcher
        self.observation_selection = list(
            dict.fromkeys(
                source
                for controller in tree["controllers"].values()
                if controller.get("type") == "policy"
                for source in controller.get("observe", [])
            )
        )
        for index, name in enumerate(self.observation_names):
            self.query_one(f"#observe-{index}", Checkbox).value = (
                name in self.observation_selection
            )

    def _sync(self) -> None:
        """Reflect `chosen` on the checkboxes and refresh the summary."""
        self._syncing = True
        try:
            self._refresh_observation_defaults()
            for name in self.options:
                on = name in self.chosen
                self.query_one(f"#opt-{name}", Checkbox).value = on
                reason = conflict_reason(self.options, self.chosen, name)
                card = self.query_one(f"#card-{name}")
                card.set_class(on, "on")
                card.set_class(bool(reason), "blocked")
                why = self.query_one(f"#why-{name}", Static)
                why.update(
                    f"turning it on turns off: {reason.removeprefix('cannot be used with ')}"
                    if reason
                    else ""
                )
                why.display = bool(reason)
            plan = self._read()
            self.query_one("#recording").display = plan.mode in ("record", "infer")
            self.query_one("#home").display = plan.mode == "record"
            self.query_one("#summary", Static).update(self._summary(plan))
            self.query_one("#launch", Button).disabled = bool(self._problem(plan))
        finally:
            self._syncing = False

    def _problem(self, plan: LaunchPlan) -> str:
        try:
            check_options(self.options, plan.options)
        except ConfigError as exc:
            return str(exc)
        observed = self.observation_selection if plan.observe is None else plan.observe
        missing = set(observed) & (set(self.sensor_names) - set(plan.sensors or []))
        if missing:
            return f"policy observes inactive sensors: {sorted(missing)}"
        return plan.problem()

    def _devices(self, plan: LaunchPlan) -> str:
        if plan.mock:
            return "mock"
        return (
            f"mock (mode: mock in {self.config.name})" if self.yaml_mock else "HARDWARE"
        )

    def _summary(self, plan: LaunchPlan) -> str:
        lines = [
            f"{plan.mode} · {self._devices(plan)} · options: "
            + (", ".join(plan.options) or "none")
        ]
        problem = self._problem(plan)
        if problem:
            return "\n".join([*lines, f"cannot launch: {problem}"])
        lines.append(
            f"dataset: {self.repo_id}{dataset_suffix(self.options, plan.options)}"
        )
        lines.append(
            "video codec: "
            + (
                plan.video_codec
                or "from the YAML (appending: the saved videos'; default h264)"
            )
        )
        for key, value in option_changes(self.options, plan.options).items():
            lines.append(f"  {key}: {value if value is not None else '(removed)'}")
        return "\n".join(lines)

    # -- events ------------------------------------------------------------------

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if self._syncing:
            return
        widget_id = event.checkbox.id or ""
        if widget_id.startswith("observe-"):
            source = self.observation_names[int(widget_id.removeprefix("observe-"))]
            # Programmatic refresh events arrive after _sync returns, too.
            if event.value != (source in self.observation_selection):
                self._observe_explicit = True
                self.observation_selection = [
                    name
                    for index, name in enumerate(self.observation_names)
                    if self.query_one(f"#observe-{index}", Checkbox).value
                ]
        name = widget_id.removeprefix("opt-")
        if event.checkbox.id and event.checkbox.id.startswith("opt-"):
            before = option_changes(self.options, self.chosen)
            self.chosen = toggle_option(self.options, self.chosen, name, event.value)
            after = option_changes(self.options, self.chosen)
            for index, sensor in enumerate(self.sensor_names):
                key = f"sensors.{sensor}"
                if before.get(key) != after.get(key):
                    self.query_one(f"#sensor-{index}", Checkbox).value = (
                        after.get(key) is not None
                    )
        self._sync()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if self._syncing:
            return
        if (
            event.radio_set.id == "mode"
            and self._read().mode == "infer"
            and INFER_OPTION in self.options
        ):
            self.chosen = toggle_option(self.options, self.chosen, INFER_OPTION, True)
        self._sync()

    def on_input_changed(self, _: Input.Changed) -> None:
        if not self._syncing:
            self._sync()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "launch":
            self.action_launch()
        elif event.button.id == "back":
            self.exit(BACK)
        else:
            self.action_cancel()

    def action_launch(self) -> None:
        plan = self._read()
        if not self._problem(plan):
            self.exit(plan)

    def action_cancel(self) -> None:
        self.exit(None)

    def action_escape(self) -> None:
        self.exit(BACK if self.back else None)


def choose(
    config: Path, initial: LaunchPlan, *, back: bool = False
) -> LaunchPlan | Literal["back"] | None:
    """Show the launcher; the chosen plan (saved as the next initial one), BACK (only
    with `back`) or None (cancelled)."""
    plan = LauncherApp(config, initial, back=back).run()
    if isinstance(plan, LaunchPlan):
        save_last(config, plan)
    return plan
