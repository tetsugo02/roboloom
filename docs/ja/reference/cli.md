# CLI

`roboloom` commandの一覧です．uv環境では先頭に `uv run` を付けます．`roboloom --version`（`-V`）で版を表示し，各commandの引数は `roboloom <command> --help` で確認できます．CLIは [Python API](python-api/index.md) の関数を呼んで結果を表示するだけの薄い層です．

## 設定とdeviceの選び方 { #choosing-the-configuration }

設定は機体ごとに1つ（`.roboloom/<robot>/config.yaml`）です．書式の `[robot]` は省略でき，`.roboloom/` の下に機体が1台だけならそれを使います．機体名（`rakuda2`）やYAML fileのpathも指定できます．ほかの位置引数を取るcommandでは，先頭の語が設定を指すときだけ設定として扱います（`roboloom commission follower` と `roboloom commission rakuda2 follower`，`roboloom session home` と `roboloom session rakuda2 home` はどちらも有効です）．

### 共通のoption { #common-options }

既定は実機です．設定を読むcommandの多くは，次の指定を受け付けます（各commandの表に「共通のoption」とあるもの）．

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `--with A,B` | 名前のリスト | — | 起動optionを有効にする（`requires` も有効になり，`conflicts` は無効になる） |
| `--without A,B` | 名前のリスト | — | 起動optionを無効にする（`default: true` のものも．これを必要とするoptionも無効になる） |
| `--mock` | flag | 切 | 実機の代わりにmock deviceを使う |
| `--video-codec CODEC` | `av1`，`libsvtav1`，`h264` | recorder の YAML | `storage: video` の画像の codec（省略時は recorder の YAML，追記では保存済みの動画の codec，どちらもなければ H.264．[Video codec](configuration/recorder.md#video-codec)） |
| `--experiment NAME` | 名前かpath | — | 実験file（projectの `configs/roboloom/<NAME>.yaml` か，fileのpath）．robot，option，nodeへの上書き（方策など），保存先を与え，`record`・`infer` では task，長さ，回数，home も与える．command lineに書いた値が優先（[実験file](configuration/index.md#experiments)） |
| `--sensors A,B` | 名前のリスト | 設定の既定 | 起動・記録するsensor（`""` で選択なし．[sensor選択](#sensor-selection)） |
| `--observe A,B` | 名前のリスト | 方策の YAML の `observe` | 方策が観測するsensor（`""` で選択なし） |

`--hardware` は廃止しました．指定すると `--mock` を使うよう促すerrorになります．起動optionの定義と規則は [起動option](configuration/index.md#launch-options) を参照してください．

## launcher { #launcher }

端末で `roboloom`（または `roboloom launch`）を実行すると，まずrobotの一覧が開きます．`.roboloom/<robot>/config.yaml` を持つrobotを，dataset名と既定で有効なoptionつきで並べます．`run`・`record`・`infer` も，端末では `--with`・`--without`・`--plain` のどれも指定しなければ先にlauncherを開き，commandの引数を初期値にします．画面とkeyは [操作画面のlauncher](operator-screen.md#launcher) を参照してください．

端末から実機で起動する前に，CLIは各Dynamixel nodeのEEPROM（Operating Mode，Current Limit）を選んだoptionと比べます．違いがあれば差分を表示し，操作者の確認後に書き込みます（[`roboloom commission`](#commission) と同じ手順です）．たとえば `gravity` を有効・無効にするとleaderのOperating Modeが変わります．

## runの操作 { #run-operations }

起動した `run` は，操作画面か [`roboloom session`](#session) で次の操作を受けます．

| 入力 | 動作 |
| --- | --- |
| `start <task>` | 準備状態を確認し追従・記録を始める |
| `stop` | 追従・記録を止める（保存は別操作） |
| `save` | episodeを保存する |
| `discard` | episodeを破棄する |
| `release` | 支持確認後に追従を止め，通電している入力機器とfollowerを脱力する |
| `home` | leaderとfollowerを，controllerで選んだ初期姿勢へゆっくり動かす．到着後，leaderは通常の制御に戻る |
| `estop` | 非常停止する |
| `quit` | 終了確認を開く．Cancel・follower保持・optionを選び直す・支持確認後の脱力から選ぶ |

Textualの操作menuは使えない操作も理由付きで表示し，初期姿勢がない `home` も含めます．Ctrl-Lで編集可能なcommand欄，Ctrl-Gで非常停止へ進みます．Ctrl-CとCtrl-Qは同じ終了確認を開き，初期選択はCancelです．key・pane・確認・時間指定mode・拡張契約は [操作画面](operator-screen.md) を参照してください．

`run --plain` は行入力を維持し，`record --plain`・`infer --plain` はkey入力なしで収集します．非TTYも同じ経路です（launcherは開きません）．`tune-gravity` はdeviceを開く前にTTYを要求します．Python APIのRich表示と確認は従来どおりです．
`stop` は脱力操作ではありません．`FAULT` / `ESTOP` / `RELEASED` は自動復帰しません．実機の開始・終了手順は [Rakuda2：teleopで収集](../tutorials/rakuda2-collect.md) にあります．

## sensor選択 { #sensor-selection }

`--sensors camera,audio --observe camera` で，起動・記録するsensorと方策が観測するsensorを独立に選びます．空の選択は `--sensors "" --observe ""` です．launcherにはsensor起動と方策の観測の独立したチェック欄があり，前回の選択を保存します．規則は [sensor選択](configuration/sensors.md#sensor-selection) に，Python から選ぶ例は [Session](python-api/session.md#sensor-selection) にあります．

## commandの一覧 { #commands }

| command | 用途 |
| --- | --- |
| [`launch`](#launch) | launcherを開く（`roboloom [robot]` と同じ） |
| [`init`](#init) | 機体設定を生成する |
| [`skills`](#skills) | coding agent向けのskillを入れる・確かめる |
| [`validate`](#validate) | deviceを開かず設定とdataflowを検証する |
| [`run`](#run) | 操作画面で収集する |
| [`record`](#record) | 一定の長さのepisodeを収集する |
| [`infer`](#infer) | 方策でepisodeを走らせる |
| [`session`](#session) | 起動済みの `run` へ操作を送る |
| [`serve-policy`](#serve-policy) | 方策を別のprocessから提供する |
| [`check-dataset`](#check-dataset) | 記録したdatasetを検査する |
| [`label`](#label) | 保存済みのepisodeに評価の成否を付ける |
| [`convert-handheld`](#convert-handheld) | 手に持って記録したdatasetを学習用に変換する |
| [`probe`](#probe) | busや機器を読むだけで調べる |
| [`calibrate-joints`](#calibrate-joints) | URDF零姿勢の実測countを保存する |
| [`measure-travel`](#measure-travel) | 手で動かした可動域を保存する |
| [`identify-gravity`](#identify-gravity) | 重力modelを同定する |
| [`capture-pose`](#capture-pose) | followerの今の姿勢を保存する |
| [`commission`](#commission) | EEPROMを設定に合わせる |
| [`watchdog-test`](#watchdog-test) | 卓上試験：Bus Watchdog |
| [`check-hold`](#check-hold) | 卓上試験：指令が止まったfollowerが姿勢を保つか |
| [`tune-gravity`](#tune-gravity) | 重力補償を対話調整する |
| [`gravity-check`](#gravity-check) | 補償の有無による姿勢の変化を測る |

`calibrate-joints`，`measure-travel`，`identify-gravity`，`commission`，`watchdog-test`，`tune-gravity`，`gravity-check` はDynamixelの機体専用です（`probe` はDynamixel，PiPER，Pika Gripper，Pika Senseを読めます）．Dynamixelでないnodeを指定すると，理由を示して拒否します．`commission`，`watchdog-test`，`check-hold`，`gravity-check` はmockの設定を拒否します．

同じbusは，同時に1つのprocessしか開けません．dataflowが使っているbusを `probe` や `tune-gravity` で開くと（逆も同じ），あとから開いた方が `... is in use by another process` で止まります．

## roboloom launch { #launch }

launcherを開き，操作（`run`・`record`・`infer`）とoptionを選んでから起動します（[launcher](#launcher)）．

```text
roboloom [robot] [COMMON_OPTIONS]
roboloom launch [robot] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 指定するとrobotの一覧を出さずに次の画面を開く |
| 共通のoption | — | — | [共通のoption](#common-options)．launcherの初期値になる |

```bash
uv run roboloom                                   # launcher
```

## roboloom init { #init }

機体設定（`.roboloom/<robot>/`）を，templateから生成します（同梱のtemplateは `rakuda2`）．

```text
roboloom init <robot> [--root DIR] [--template PACKAGE_OR_DIR] [--update]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | str | 必須 | 機体名．projectの名前にもなる |
| `--root DIR` | path | `.roboloom` | 生成先の親directory |
| `--template PACKAGE_OR_DIR` | packageかpath | 同梱のtemplate | roboloomに入っていないtemplateから作る：`template/` を持つpackage（`my_lab.robots.arm`）かdirectory（[自分のpackageから足す](../contribution/index.md#own-types)） |
| `--update` | flag | 切 | 既存のprojectを今の版のtemplateに追いつかせる：ないfileを足し，コピーしたままのfileを置き換え，編集済み・測定済みのfileは変えずに，templateだけにあるkeyとoptionを一覧にする |

```bash
uv run roboloom init rakuda2
```

## roboloom skills { #skills }

coding agent向けのskill（Agent Skill）を自分のprojectの `.agents/skills/` と `.claude/skills/` にコピーする（`install`）・コピーが今の版と合っているか確かめる（`check`．合わなければ終了code 1）・同梱の場所を表示する（`path`）．deviceは開きません（[Installation](../get-started/installation.md) の「coding agentで使う」）．

```text
roboloom skills install|check|path [--agent all|agents|claude] [--root DIR] [--force]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `action` | `install`，`check`，`path` | 必須 | 行う操作 |
| `--agent` | `all`，`agents`，`claude` | `all` | どのagentのskillのdirectoryか（`agents`：`.agents/skills`，`claude`：`.claude/skills`） |
| `--root DIR` | path | `.` | projectの根 |
| `--force` | flag | 切 | 内容の違うコピーを置き換える |

```bash
uv run roboloom skills install
```

## roboloom validate { #validate }

deviceを開かず，設定とdataflowを検証します．有効なoption，dataset名，動画の codec を表示します．

```text
roboloom validate [robot] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 検証する設定 |
| 共通のoption | — | — | [共通のoption](#common-options)（`--experiment` も受ける） |

```bash
uv run roboloom validate --with digit
```

## roboloom run { #run }

dataflowを起動し，操作画面で続けて収集します（[runの操作](#run-operations)）．

```text
roboloom run [robot] [--plain] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 起動する設定 |
| `--plain` | flag | 切 | 固定の画面の代わりに行入力を使う（launcherも開かない） |
| 共通のoption | — | — | [共通のoption](#common-options) |

```bash
uv run roboloom run --with gravity                # launcherを開かずに起動
uv run roboloom run --mock                        # mock device
```

## roboloom record { #record }

一定時間のepisodeを収集して終わります．準備ができたら毎回Startを選びます（[操作画面](operator-screen.md#operations)）．

```text
roboloom record [robot] --task TEXT --seconds N [--episodes N] [--home] [--plain] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 起動する設定 |
| `--task TEXT` | str | 必須（実験fileの `task:` でも可） | 各frameに保存する task |
| `--seconds N` | float | 必須（実験fileの `seconds:` でも可） | 1 episodeの長さ（秒） |
| `--episodes N` | int | 1 | episodeの数 |
| `--home` | flag | 切 | 毎回，controllerの初期姿勢へ動かしてから開始する |
| `--plain` | flag | 切 | key入力なしで収集する |
| 共通のoption | — | — | [共通のoption](#common-options) |

実験fileが `steps:` を与えるときは，`--seconds` を指定します（`steps` は方策の手数なので `record` では使えません）．

```bash
uv run roboloom record --task "pick up the cup" --seconds 30 --home
```

## roboloom infer { #infer }

方策でepisodeを走らせます．option `policy` を自動で有効にします．`--task` がある場合だけ保存します（[方策で動かす](../policy/run.md)）．

```text
roboloom infer [robot] (--seconds N | --steps N) [--episodes N] [--home] [--policy MODULE:CALLABLE] [--policy-kwargs JSON] [--task TEXT] [--plain] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 起動する設定 |
| `--seconds N` | float | `--steps` かどちらか必須（実験fileでも可） | 1 episodeの長さ（秒） |
| `--steps N` | int | — | 方策が実行した行動の手数で，episodeを終える（1以上．`--seconds` とは同時に使えない） |
| `--episodes N` | int | 1 | episodeの数 |
| `--home` | flag | 切 | 毎回，方策の初期姿勢へ動かしてから開始する（[方策の home](../policy/run.md#home)） |
| `--policy MODULE:CALLABLE` | str | YAML の `factory` | 方策を返す関数 |
| `--policy-kwargs JSON` | JSON | YAML の `kwargs` | その関数の引数 |
| `--task TEXT` | str | — | 方策に渡す task．指定すると実行を保存する |
| `--plain` | flag | 切 | key入力なしで実行する |
| 共通のoption | — | — | [共通のoption](#common-options) |

```bash
uv run roboloom infer --seconds 20 --policy my_lab.policies:load
uv run roboloom infer --experiment drawer         # configs/roboloom/drawer.yaml
```

## roboloom session { #session }

起動済みの `run` へ操作を1つ送ります．

```text
roboloom session [robot] <operation> [task]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 操作を送る `run` の設定（optionは問わない） |
| `operation` | 下記のどれか | 必須 | `start`，`stop`，`save`，`discard`，`home`，`estop`，`release`，`quit`．方策に `teleop:` があれば `teleop`・`policy`・`stop_teleop` も（[teleopと介入](../policy/intervention.md#teleop)） |
| `task` | str | — | `start` では task，`save` では成否（`success` か `failure`） |

```bash
uv run roboloom session home
uv run roboloom session save success               # 別端末から，成否を付けて保存
```

## roboloom serve-policy { #serve-policy }

<span class="status status--mock">模擬のみ</span>

この環境の方策を，`backend: server` の方策nodeへ提供します（[別のprocess](../policy/remote.md#running-the-policy-in-another-process)）．robotの設定は読みません．

```text
roboloom serve-policy (<module:callable> | --from POLICY_YAML | --experiment EXPERIMENT_YAML) [--kwargs JSON] [--address HOST:PORT] [--authkey-env NAME]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `policy` | `module:callable` | — | 方策を返す関数（`--from`・`--experiment` とどれか1つ） |
| `--from POLICY_YAML` | path | — | この方策nodeのfile（例：`.roboloom/<robot>/nodes/policy.yaml`）の `factory`，`kwargs`，`server.address` を使う |
| `--experiment EXPERIMENT_YAML` | path | — | この実験file（例：`configs/roboloom/<name>.yaml`）が方策に与える `factory`，`kwargs`，`server.address` を使う |
| `--kwargs JSON` | JSON | fileの `kwargs` | 関数の引数（fileのものを置き換える） |
| `--address HOST:PORT` | str | fileの `server.address`，なければ `127.0.0.1:18765` | 待ち受けるaddress |
| `--authkey-env NAME` | str | fileの `server.authkey_env`，なければ `ROBOLOOM_POLICY_AUTHKEY` | 秘密の文字列を読む環境変数 |

```bash
uv run roboloom serve-policy --from .roboloom/rakuda2/nodes/policy.yaml
```

## roboloom check-dataset { #check-dataset }

記録したdatasetを読むだけで検査します：episode数とfileの整合，動画の長さと行数，`valid` が0の行の割合，成否の数．問題があれば終了code 1です（[dataの検査](../data/check-and-train.md)）．

```text
roboloom check-dataset [robot | DATASET_DIR] [--recover] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath，またはdatasetのdirectory | 唯一の機体のdataset | 検査するdataset．optionで名前が変わるdatasetは `--with` で選ぶ |
| `--recover` | flag | 切 | 先に，保存の途中で止まったepisodeを取り除く（[保存したepisode](../data/recording.md#saved-episodes)） |
| 共通のoption | — | — | [共通のoption](#common-options)（dataset名を決める `--with`・`--without`・`--experiment`） |

```bash
uv run roboloom check-dataset --with digit
```

## roboloom label { #label }

保存済みのepisodeに，評価の成否を付ける・付け直します．datasetの `meta/roboloom_episodes.jsonl` に追記し，成否の数を表示します（[episodeごとの記録](../data/recording.md#episode-records)）．

```text
roboloom label [robot | DATASET_DIR] <episode> success|failure [--note TEXT] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath，またはdatasetのdirectory | 唯一の機体のdataset | 対象のdataset．optionで名前が変わるdatasetは `--with` で選ぶ |
| `episode` | int | 必須 | datasetでのepisode番号 |
| `verdict` | `success`，`failure` | 必須 | 成否 |
| `--note TEXT` | str | — | 成否と一緒に残すメモ |
| 共通のoption | — | — | [共通のoption](#common-options)（dataset名を決める `--with`・`--without`・`--experiment`） |

```bash
uv run roboloom label --with policy 3 failure     # 評価のdatasetのepisode 3
```

## roboloom convert-handheld { #convert-handheld }

<span class="status status--dev">開発中</span>

followerのない構成で手に持って記録したdatasetを，相対の姿勢の行動を持つ学習用のdatasetに変換します（[手に持って収集する](../tutorials/pika-handheld.md)）．

```text
roboloom convert-handheld [robot] [--action delta|relative-chunk] [--horizon N] [--hands A,B] [--max-gap N] [--output DIR] [--repo-id ID]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 記録した設定（そのdatasetを読む） |
| `--action` | `delta`，`relative-chunk` | `delta` | `delta`：1手 `inv(P[t]) P[t+1]`．`relative-chunk`：`inv(P[t]) P[t+k]`（k=1..horizon）を1行に並べる（chunk_size 1 で学習する） |
| `--horizon N` | int | 16 | `relative-chunk` の手数 |
| `--hands A,B` | 名前のリスト | すべての姿勢 | 変換する姿勢の入力 |
| `--max-gap N` | int | 3 | 追跡が切れた行を，1つの切れ目につき何行まで埋めるか |
| `--output DIR` | path | 記録の `<output>-<action>` | 変換先 |
| `--repo-id ID` | str | `<repo_id>-<action>` | 変換先の repo id |

```bash
uv run roboloom convert-handheld --action relative-chunk --horizon 16
```

## roboloom probe { #probe }

Dynamixelのbusを読むだけで調べます：ID・model・registerと読み出し時間（目安の周期上限）．`can_left` のようなCAN interfaceを渡すと，PiPER（[開発中](../robots/piper/index.md)）のfirmware・関節角・状態・有効化・温度・異常を読みます（有効化も移動もしない）．`--device pika` では，serial portのPika Gripper（[開発中](../robots/pika/index.md)）の版・角度・状態のbit・温度・feedbackの周期を，`--device pika_sense` では，Pika Sense（[開発中](../controllers/pose-ik.md)）のserialの版・挟みの角度・`Command`・feedbackの周期を読みます．

```text
roboloom probe <port> [--device dynamixel|pika|pika_sense] [--ids 1,2,3] [--baudrate N]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `port` | str | 必須 | serial port（Dynamixel，Pika）かCAN interface（PiPER） |
| `--device` | `dynamixel`，`pika`，`pika_sense` | `dynamixel` | serial portの先の機器（CAN interfaceならPiPER） |
| `--ids 1,2,3` | 整数のリスト | broadcastで見つけたID | 読むDynamixelのID |
| `--baudrate N` | int | 1000000 | baud rate |

```bash
uv run roboloom probe /dev/ttyUSB0
```

## roboloom calibrate-joints { #calibrate-joints }

URDF零姿勢の実測countをcalibrationに保存します．busには書き込みませんが，local YAMLを保存します．腕のtorqueが切れていることが必要です．

```text
roboloom calibrate-joints <calibration> [--joints A,B]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `calibration` | path | 必須 | calibrationのYAML |
| `--joints A,B` | 名前のリスト | すべての関節 | 記録する関節 |

```bash
uv run roboloom calibrate-joints .roboloom/rakuda2/calibration/leader_right.yaml
```

## roboloom measure-travel { #measure-travel }

手で動かした可動域を保存します．busには書き込みませんが，local YAMLを保存します．腕のtorqueが切れていることが必要です．

```text
roboloom measure-travel <calibration> --out PATH
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `calibration` | path | 必須 | calibrationのYAML |
| `--out PATH` | path | 必須 | 可動域を保存するfile |

```bash
uv run roboloom measure-travel .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/travel_right.yaml
```

## roboloom identify-gravity { #identify-gravity }

保持電流を測定して重力modelを同定します（leaderの重力補償，followerの `model_residual` 推定器）．`--collect` はmotorに通電するので，通電前に操作者へ確認します．

```text
roboloom identify-gravity <calibration> --out PATH [--collect] [--data NPZ] [--delta N] [--max-rms-mA X]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `calibration` | path | 必須 | calibrationのYAML |
| `--out PATH` | path | 必須 | 重力modelを保存するfile |
| `--collect` | flag | 切 | 先に新しい姿勢を集める（腕に通電する） |
| `--data NPZ` | path | `--out` の隣 | 保持電流のnpz |
| `--delta N` | int | 30 | 近づくときのずらし（count） |
| `--max-rms-mA X` | float | 15.0 | 当てはめの残差のRMSの上限（mA）．超えるとmodelを保存しない |

```bash
uv run roboloom identify-gravity .roboloom/rakuda2/calibration/leader_right.yaml --out .roboloom/rakuda2/calibration/gravity_right.yaml --collect
```

## roboloom capture-pose { #capture-pose }

followerの今の姿勢を `poses/<follower>/<name>.yaml` に保存します（動かしません）．home に使います．

```text
roboloom capture-pose [robot] [follower] <name> [--force] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 設定 |
| `follower` | str | 唯一のfollower | 姿勢を読むfollower（followerが1台なら省略可） |
| `name` | str | 必須 | 姿勢の名前 |
| `--force` | flag | 切 | 同じ名前の姿勢を上書きする |
| 共通のoption | — | — | [共通のoption](#common-options) |

```bash
uv run roboloom capture-pose ready
```

## roboloom commission { #commission }

nodeのEEPROM（Operating Mode，Current Limit）を読んで設定と比べ，差分と操作者の確認を経て書き込み，読み戻します．

```text
roboloom commission [robot] <node> [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 設定 |
| `node` | str | 必須 | Dynamixelのnode |
| 共通のoption | — | — | [共通のoption](#common-options)（optionで期待する値が変わる） |

```bash
uv run roboloom commission leader --with gravity
```

## roboloom watchdog-test { #watchdog-test }

卓上試験：Bus Watchdogが電流modeのmotorを止めるかを確かめます（通電する）．nodeに `bus_watchdog_ms` が必要です．

```text
roboloom watchdog-test [robot] <node> <joint> [--current-mA X] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 設定 |
| `node` | str | 必須 | Dynamixelのnode |
| `joint` | str | 必須 | 押す関節 |
| `--current-mA X` | float | 30.0 | 押す電流（mA） |
| 共通のoption | — | — | [共通のoption](#common-options) |

```bash
uv run roboloom watchdog-test leader r_arm_sh_pitch1 --with gravity
```

## roboloom check-hold { #check-hold }

卓上試験：指令が来なくなったfollowerが姿勢を保つかを測り，確認後にYAMLへ `unattended:` を書きます（通電する）．`unattended` を `unknown` と宣言する機種だけが対象です（[脱力したときと放置したときの性質](configuration/followers.md#torque-off-and-unattended)）．

```text
roboloom check-hold [robot] <follower> --tolerance X [--seconds N] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 設定 |
| `follower` | str | 必須 | 試すfollower |
| `--tolerance X` | float | 必須 | 保持とみなす最大の変化（followerの単位） |
| `--seconds N` | float | 10.0 | 指令を止めて見ている時間（秒） |
| 共通のoption | — | — | [共通のoption](#common-options) |

```bash
uv run roboloom check-hold left --tolerance 0.02                 # PiPER の left
```

## roboloom tune-gravity { #tune-gravity }

leaderの重力補償のgainとholdを，関節ごとに対話調整します（腕に通電する）．deviceを開く前にTTYを要求します．同じbusを開くdataflowは先に止めます．keyは [重力調整](operator-screen.md#gravity-tuning) を参照してください．

```text
roboloom tune-gravity [robot] <node> <group> [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 設定 |
| `node` | str | 必須 | Dynamixelのleader node |
| `group` | str | 必須 | `gravity_comp` のgroup（例：`right_arm`） |
| 共通のoption | — | — | [共通のoption](#common-options)（`--with gravity` で重力補償の設定を選ぶ） |

```bash
uv run roboloom tune-gravity leader right_arm --with gravity
```

## roboloom gravity-check { #gravity-check }

同じ姿勢で，設定のgainの倍率ごとに腕を放し，補償の有無による姿勢の変化を測ります（腕に通電する）．

```text
roboloom gravity-check [robot] <node> <group> [--poses N] [--scales 1,0] [COMMON_OPTIONS]
```

| option | 型 | 既定値 | 説明 |
| --- | --- | --- | --- |
| `robot` | 機体名かpath | 唯一の機体 | 設定 |
| `node` | str | 必須 | Dynamixelのleader node |
| `group` | str | 必須 | 制御のgroup（例：`right_arm`） |
| `--poses N` | int | 3 | 試す姿勢の数 |
| `--scales 1,0` | 数のリスト | `1,0` | 各姿勢で試す，設定のgainの倍率（例：`1,0,2,-2`） |
| 共通のoption | — | — | [共通のoption](#common-options)（`--with gravity`） |

```bash
uv run roboloom gravity-check leader right_arm --with gravity
```
