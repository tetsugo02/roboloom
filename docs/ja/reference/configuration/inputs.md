# 入力（inputs，trackers）

`inputs:` は操作者の入力機器（leader arm，手に持つ機器）です．入力はfollowerへ直接は指令せず，controllerが入力をfollowerの指令に変えます（[controller](controllers.md)）．`trackers:` は，手に持つ機器の姿勢を測る追跡systemです．

## 共通のkey { #common }

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `type` | 文字列 | 必須 | — | 機種（`rakuda_mini`，`pika_sense`）か `module:Class` |
| `poll_hz` | 数値 | 動かすfollowerのうち最も速い `control_hz` | Hz | 入力を読む周期（[制御周期](followers.md#control-rate)）．followerのない構成では必須 |

関節の入力は，関節の位置を入力の単位で `observation.<入力名>` に記録します．姿勢の入力は `x`，`y`，`z`，`qx`，`qy`，`qz`，`qw`，`gripper`，`tracking`，`engaged` を記録します（[datasetの列](../dataset-features.md#observation)）．

## rakuda_mini { #rakuda-mini }

Rakuda2のleader arm（Rakuda-mini）です．関節名と単位（`dynamixel_count`）はRakuda2 followerと同じなので，`joint` controllerは同じ名前の関節どうしを対応させます．`control` を書くと，関節groupごとに制御則で動きます（重力補償，triggerのばねなど）．torqueが切れると落ち（`falls`），sessionの終了時に脱力します（`torque_off`）．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `port` | 文字列 | 必須 | — | U2D2のport（`/dev/serial/by-id/...`） |
| `motor_ids` | 整数のリスト | 必須 | — | 関節の順のmotor ID．[Rakuda2 follower](followers.md#rakuda2-follower) と同じ決まった並び |
| `registers` | mapping | 必須 | — | 起動時に照合するEEPROMの値．項目は [Rakuda2 follower](followers.md#rakuda2-follower) と同じ |
| `control` | リスト | — | — | 関節groupごとの制御則（[control](control.md)）．書かなければ読むだけ |
| `bus_watchdog_ms` | 整数か `null` | — | ms | DynamixelのBus Watchdog．電流制御の制御則には実機で必須 |

## pika_sense <span class="status status--dev">開発中</span> { #pika-sense }

手に持つPika Senseです．姿勢はVive trackerを `trackers:` の追跡systemが読み，顎の開きとclutch（`engaged`）はSenseのserialから読みます．`pose_ik` controllerが腕の関節に変えます（[Pika SenseとIK](../../controllers/pose-ik.md)）．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `port` | 文字列 | 必須 | — | Senseのserial port（`/dev/serial/by-path/...`） |
| `tracker` | `{system, serial}` | 必須 | — | `system`：`trackers:` のnode名．`serial`：trackerのserial番号（`LHR-...`） |
| `stale_ms` | 数値 | `100` | ms | これより古い姿勢やserialの値は，見失ったとみなす |

## 追跡system（trackers） <span class="status status--dev">開発中</span> { #trackers }

追跡systemは1つのnodeで，見えている全ての追跡対象の姿勢をserial番号つきで流します．同じsystemを複数の入力が使えます（USBの受信機と，較正した世界座標は1つ）．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `type` | 文字列 | 必須 | — | `libsurvive` か `module:Class` |
| `poll_hz` | 数値 | 読む入力のうち最も速い周期 | Hz | 姿勢を流す周期 |

### libsurvive { #libsurvive }

Lighthouse（Vive）の追跡をlibsurviveで行います．追跡対象はserial番号（`LHR-...`）で区別します．

| key | 型 | 既定値 | 単位 | 説明 |
| --- | --- | --- | --- | --- |
| `args` | 文字列のリスト | `[]` | — | libsurviveに渡す追加の引数（例：`[--lighthouse-gen, "2"]`） |

## 例 { #example }

```yaml
# nodes/right_sense.yaml
type: pika_sense
port: SET_RIGHT_SENSE_PORT
tracker: {system: lighthouse, serial: SET_RIGHT_TRACKER_SERIAL}
stale_ms: 100
```

```yaml
# nodes/lighthouse.yaml（config.yaml の trackers.lighthouse）
type: libsurvive
args: []
```
