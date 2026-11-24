# PiPER＋Pika：機体設定

!!! warning "状態：開発中"
    <span class="status status--dev">開発中</span> `roboloom setup` は偽の機器を使った試験でだけ確かめています．実機で動かしたことはありません．うまくいかない段階があれば，その段階の表示を添えて報告してください．

- **目的**：`.roboloom/piper-pika/` を作り，どのCAN interface・serial port・trackerがどの機器かを `roboloom setup` で特定して書き込み，読み取りで確かめる．
- **前提**：[Installation](../../get-started/installation.md) が済んでいる．PiPER 2台，Pika Gripper 2台，Pika Sense 2台，基地局（Lighthouse）を配線し，電源を入れている．腕は折りたたんだ休止の姿勢で，motorは無効（電源を入れた直後の状態）．
- **所要**：30分（管理者の作業を除く）．
- **結果**：`roboloom validate piper-pika` が通る．機器を何も有効にせず，動かさない．

## 0. 管理者に頼むこと

rootが要る作業です．roboloomはsudoを呼びません．

- serial portを開く権限（`dialout` group）．
- Vive trackerのudev rules（libsurviveの `81-vive.rules`）．
- CAN interfaceを1 Mbpsで有効にする．名前は決めなくてかまいません（`can0`，`can1` のままでよい）．roboloomはUSB-CAN adapterのserial番号で腕を見分けます．

## 1. 設定を作る

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.2.1 --extra piper --extra pika --extra record
uv run roboloom init piper-pika
uv run roboloom validate piper-pika --mock   # 装置なしで設定が読めることを確かめる
```

`.roboloom/piper-pika/` に，腕・Gripper・Senseごとのnodeのfileができます．機器の識別子（CAN adapterのserial，serial port，trackerのserial）は `SET_` のままです．

## 2. 機器を特定する

```bash
uv run roboloom setup piper-pika
```

画面の指示に従って，1台ずつ手で動かします．変化したものがちょうど1つのときに，それをその機器として書きます．0個や2個以上のときは，もう一度聞きます．

| 段階 | 調べること | 頼まれる操作 |
| --- | --- | --- |
| `check` | extras，serial portの権限，Viveのudev rules | なし |
| `can` | CAN interfaceの状態，bitrate，adapterのserial | 有効でなければ，表示されたcommandを管理者に実行してもらい，Enter |
| `arms` | どのCANがどの腕か | 指定された腕のjoint1（根元）を手で20°ほど回して戻し，Enter |
| `senses` | どのportがどのSenseか | 指定されたSenseを何度か開閉し，Enter |
| `trackers` | どのtracker（`LHR-…`）がどのSenseに入っているか | 指定されたSenseを30 cmほど動かし（他は静かに），Enter |
| `grippers` | どのportがどのGripperか | 指定されたGripperのUSBを抜いてEnter，同じ差し口に挿し直してEnter |
| `validate` | 実機用に設定が読めるか | なし |

- **motorが有効な腕は断ります．** PiPERは無効にすると落ちるので，setupは無効にしません．支えてから `check-hold` の最後に release するか，休止の姿勢で電源を入れ直してから，もう一度実行します．
- **trackerが見えないとき**は，基地局の校正（libsurviveの `--force-calibrate`）を提案します．両方のSenseを，両方の基地局から見える場所に静かに置いてから `yes` と答えます．校正の結果はlibsurviveの設定（`~/.config/libsurvive/`）に残るので，一度だけで済みます．
- **Gripperは手で回せないので**，USBの抜き差しで特定します（LeRobotの `lerobot-find-port` と同じ方式）．portの名前はUSBの差し口で決まるので，挿し直すときは同じ差し口に挿します．
- 最後の1台は，候補が1つだけなら聞かずに決めます．

書き込んだ行には `# roboloom setup <日付>` が付きます．fileのほかの行とcommentは変えません．

```yaml
# nodes/left.yaml（抜粋）
can: {serial: "0029002F5746570A20383839"}  # roboloom setup 2026-11-17
# nodes/left_sense.yaml（抜粋）
port: /dev/serial/by-path/pci-0000:00:14.0-usb-0:3.4:1.0-port0  # roboloom setup 2026-11-17
tracker: {system: lighthouse, serial: "LHR-F7BA2042"}  # roboloom setup 2026-11-17
```

### 一部だけやり直す

```bash
uv run roboloom setup piper-pika --step grippers        # Gripperだけ
uv run roboloom setup piper-pika --step can,arms        # CANと腕
```

設定済みの値は先に表示されます．Enterでそのまま使い，`r` で特定し直します．cableや機器を替えたあとの確認に使います．

## 3. 読み取りで確かめる

```bash
uv run roboloom validate piper-pika
uv run roboloom probe can0          # 腕（CANの名前は setup の can の段階に表示される）
uv run roboloom probe /dev/serial/by-path/<Gripperのport> --device pika
uv run roboloom probe /dev/serial/by-path/<Senseのport> --device pika_sense
```

- `validate` は，`workspace` を書いていないIKのnodeに `note:` を出します．初回はそれでかまいません（[設定を絞る](tighten.md) で足します）．
- 休止の姿勢では，joint2が少し負，joint3が少し正になり，`limits`（joint2 ≥ 0，joint3 ≤ 0）の外に出ることがあります．home へ動かすときに範囲の内側へ戻るので，そのままでかまいません．
- Gripperを閉じた状態の角度が0より小さい（例：−0.015 rad）ときは，setupが `note:` で知らせます．零点の書き込み（pika_sdkの `set_zero`）はroboloomではまだ行いません．小さいずれなら，そのまま次へ進めます．

## 次へ

[初めての遠隔操作](first-teleop.md)：保持を確かめ，home へ動かし，ゆるい設定で遠隔操作します．
