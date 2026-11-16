# Rakuda2: gravity compensation

<span class="status status--verified">Hardware-verified</span>

- **Goal**: measure the zero points, directions and travel of the leader arms, identify the gravity model, and tune the gravity-compensated leader (option `gravity`).
- **Prerequisites**: [Rakuda2: configuration and read check](rakuda2-setup.md) is done. Someone can support the arms.
- **Time**: 1–2 hours.
- **Result**: `calibration/` holds `gravity_<side>.yaml`, `travel_<side>.yaml` and `gravity_tuning_<side>.yaml`, and `--with gravity` starts.

## 1. Set zero points, directions, and travel for gravity compensation

Do everything on this page with the dataflow stopped and no other tool holding the leader bus open. Support the arms and confirm torque is off. Check the mapping between motor IDs and URDF joints in the left and right calibration YAMLs, place the arm in the URDF zero pose, and measure.

```bash
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_right.yaml
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_left.yaml
```

Check the saved `zero` and each joint's `direction` (`1` or `-1`), and once the mapping, zero points, and directions are verified, set `confirmed: true` in each file. Do not approve template zero points or signs without checking them.

Slowly move the torque-off leader by hand to measure the left and right travel.

```bash
uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/travel_right.yaml
uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_left.yaml --out .roboloom/rakuda2/calibration/travel_left.yaml
```

This operation only reads positions from the bus, but saves the result to YAML. This range is used to detect leader runaway; do not use it as a substitute for the follower's safety limits.

## 2. Identify the gravity model

`identify-gravity --collect` **powers the motors** to measure holding current. Check the surroundings and how the arm is supported, and follow the on-screen instructions for pose placement and releasing your hands.

```bash
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/gravity_right.yaml --collect
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_left.yaml --out .roboloom/rakuda2/calibration/gravity_left.yaml --collect
```

It asks whether to continue before energizing the motors.

Check the output fit and warnings. Saving is refused if joint directions or measurement quality are inadequate. Fix the cause and measure again; do not proceed with a model that was not generated. Errors remain depending on the configuration and measured poses, so tune gain and hold next.

## 3. Configure and tune gravity compensation mode

Gravity compensation is the option `gravity`. Enabling it replaces the leader `nodes/leader.yaml` with `nodes/leader_gravity.yaml`. `nodes/leader_gravity.yaml` references the left and right `gravity_<side>.yaml`, `travel_<side>.yaml`, and `gravity_tuning_<side>.yaml`. After checking the current limits, watchdog, and travel, validate the configuration and check the EEPROM changes.

```bash
uv run roboloom validate --with gravity
uv run roboloom commission leader --with gravity
uv run roboloom tune-gravity leader right_arm --with gravity
uv run roboloom tune-gravity leader left_arm --with gravity
```

The leader's Operating Mode depends on whether `gravity` is enabled. If you later launch without `gravity`, the CLI shows the EEPROM differences before launching and writes them back after you confirm.

Support both arms when tuning starts. The side not being tuned has torque off.

| Key | Action |
| --- | --- |
| `↑` / `↓` | Select a joint |
| `[` / `]` | Decrease / increase the gain that cancels weight |
| `-` / `=` | Decrease / increase the holding force at motion onset, `hold_mA` |
| `0` | Toggle gravity compensation for the selected joint to compare |
| `s` | Save the tuned values |
| `q` | Quit |

If the arm drops, increase gain; if it rises, decrease it. If starting to move feels heavy, decrease hold. If the current stays pinned at the limit, stop tuning and review the configuration. Details and constraints are in [Gravity tuning](../explanation/gravity-compensation.md). Current Limit and the watchdog are separate protections; do not assume that the XC330 watchdog triggering alone brings the current to zero.

## Next

- Collect with the gravity-compensated leader: [Rakuda2: teleoperated collection](rakuda2-collect.md)
- What the equations and tuning values mean: [Gravity compensation](../explanation/gravity-compensation.md)
