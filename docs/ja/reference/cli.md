# CLI

以下では `roboloom` と略記します．uv環境では先頭に `uv run` を付けます．各コマンドの引数は `roboloom <command> --help` でも確認できます．

## 設定とデバイスの選び方

設定は機体ごとに1つ（`.roboloom/<robot>/config.yaml`）です．表の `[robot]` は省略でき，`.roboloom/` の下に機体が1台だけならそれを使います．機体名（`rakuda2`）やYAMLファイルのパスも指定できます．ほかの位置引数を取るコマンドでは，先頭の語が設定を指すときだけ設定として扱います（`roboloom commission follower` と `roboloom commission rakuda2 follower`，`roboloom session home` と `roboloom session rakuda2 home` はどちらも有効です）．

既定は実機です．デバイスを開くコマンドは次の指定を受け付けます．

| 指定 | 意味 |
| --- | --- |
| `--with a,b` | 起動オプションを有効にする（`requires` も有効になり，`conflicts` は無効になる） |
| `--without a,b` | 起動オプションを無効にする（`default: true` のものも．これを必要とするオプションも無効になる） |
| `--mock` | 実機の代わりにmockデバイスを使う |
| `--video-codec av1\|h264` | `storage: video` の画像の codec（省略時は recorder の YAML．[Video codec](configuration.md#video-codec)） |

`--hardware` は廃止しました．指定すると `--mock` を使うよう促すエラーになります．起動オプションの定義と規則は [設定](configuration.md) の「起動オプション」を参照してください．

## コマンド

| コマンド | 用途 |
| --- | --- |
| `roboloom [robot]` | ランチャーを開く（`roboloom launch [robot]` と同じ） |
| `init rakuda2` | 機体設定を生成する |
| `probe <port>` | DynamixelのID・モデル・レジスタと読み出し時間（目安の周期上限）を読み取る．`can_left` のようなCANインターフェースを渡すと，PiPER（[開発中](../contribution/piper.md)）のファームウェア・関節角・状態・有効化・温度・異常を読む（有効化も移動もしない）．`--device pika` を付けると，シリアルポートのPika Gripper（[開発中](../contribution/pika-gripper.md)）の版・角度・状態のビット・温度・フィードバックの周期を読む．`--device pika_sense` では，Pika Sense（[開発中](../contribution/pika-sense.md)）のシリアルの版・挟みの角度・`Command`・フィードバックの周期を読む |
| `validate [robot]` | デバイスを開かず設定とdataflowを検証する（有効なオプションとデータセット名を表示） |
| `calibrate-joints <calibration>` | URDF零姿勢の実測カウントをcalibrationに保存する |
| `measure-travel <calibration> --out <path>` | 手で動かした可動域を保存する |
| `identify-gravity <calibration> --out <path> --collect` | 保持電流を測定して重力モデルを同定する（leaderの重力補償，followerの `model_residual` 推定器）．通電前に操作者へ確認する |
| `capture-pose [robot] [follower] <name>` | フォロワの今の姿勢を `poses/<follower>/<name>.yaml` に保存する（動かさない．`--force` で上書き．フォロワが1台なら `follower` は省略可） |
| `commission [robot] <node>` | 差分と操作者の確認を経てEEPROMを書き，読み戻す |
| `watchdog-test [robot] <node> <joint>` | 卓上試験：Bus Watchdogが電流モードのモーターを止めるかを確かめる（通電する） |
| `check-hold [robot] <follower> --tolerance <値>` | 卓上試験：指令が来なくなったフォロワが姿勢を保つかを測り，確認後にYAMLへ `unattended:` を書く（通電する．`--seconds` 既定10．`unattended` を `unknown` と宣言する機種だけ） |
| `tune-gravity [robot] leader <group> --with gravity` | gainとholdを対話調整する |
| `gravity-check [robot] leader <group> --with gravity` | 補償の有無による姿勢の変化を測る |
| `run [robot]` | 操作画面で収集する |
| `record [robot] --task <text> --seconds <n>` | 一定時間のエピソードを収集する（`--episodes` で回数指定，`--home` で毎回初期姿勢へ動かしてから開始） |
| `infer [robot] --seconds <n>` | 時間指定の方策実行．オプション `policy` を自動で有効にする．`--task` がある場合だけ保存 |
| `session [robot] <operation> [task]` | 起動済みの `run` へ操作を送る |
| `convert-handheld [robot] --action delta\|relative-chunk` | フォロワのない構成で手に持って記録したデータセットを，相対の姿勢の行動を持つ学習用のデータセットに変換する（[開発中](../contribution/pika-handheld.md)．`--horizon`，`--hands`，`--max-gap`，`--output`，`--repo-id`） |
| `skills install\|check\|path` | コーディングエージェント向けのスキル（Agent Skill）を自分のプロジェクトの `.agents/skills/` と `.claude/skills/` にコピーする・コピーが今の版と合っているか確かめる（合わなければ終了コード1）・同梱の場所を表示する（`--agent all\|agents\|claude`，`--root`，`--force`．[Installation](../quick-start/installation.md) の「コーディングエージェントで使う」）．デバイスは開かない |

`calibrate-joints`，`measure-travel`，`identify-gravity`，`commission`，`watchdog-test`，`tune-gravity`，`gravity-check` はDynamixelの機体専用です（`probe` はDynamixel，PiPER，Pika Gripper，Pika Senseを読めます）．Dynamixelでないノードを指定すると，理由を示して拒否します．

例：

```bash
uv run roboloom                                   # ランチャー
uv run roboloom run --with gravity                # ランチャーを開かずに起動
uv run roboloom run --mock                        # mockデバイス
uv run roboloom record --task "pick up the cup" --seconds 30 --home
uv run roboloom infer --seconds 20 --policy my_lab.policies:load
uv run roboloom validate --with digit
uv run roboloom session home
```

`calibrate-joints` / `measure-travel` はバスには書き込みませんが，ローカルYAMLを保存します．腕のトルクが切れていることが必要です．`identify-gravity --collect`，`tune-gravity`，`gravity-check` はモーターに通電します．dataflowと同時に同じバスを開かないでください．`commission`，`watchdog-test`，`check-hold`，`gravity-check` はmockの設定を拒否します．

## ランチャー

端末で `roboloom`（または `roboloom launch`）を実行すると，まずロボットの一覧が開きます．`.roboloom/<robot>/config.yaml` を持つロボットを，データセット名と既定で有効なオプションつきで並べます．前回選んだロボットにカーソルがあり，Enterで選び，Escで何も起動せずに終わります．選んだロボットは `.roboloom/logs/last_robot` に残ります．`roboloom rakuda2` のようにロボットを指定すると，一覧を出さずに次の画面を開きます．`run`・`record`・`infer` も，端末では `--with`・`--without`・`--plain` のどれも指定しなければ先にランチャーを開き，コマンドの引数を初期値にします．

- 操作（`run` / `record` / `infer`）を選びます．`record` と `infer` ではtask・秒数・回数を，`record` では毎回初期姿勢へ動かすかも入力します．
- オプションにチェックを入れます．必要なオプションは一緒に有効になり，競合するオプションは無効になります．`infer` を選ぶと，`policy` という名前のオプションがあれば自動で有効になります．
- mockデバイスを使うかと，`storage: video` の画像の codec（`YAML / dataset`・`AV1`・`H.264`）を選びます．
- 要約に，操作・mockか実機か・有効なオプション・データセット名・動画の codec・置き換わるノードファイルが表示されます．

Launch（Ctrl-S）で起動し，Cancelで何も起動せずに終わります．ロボットの一覧から開いた場合はBack（Esc）で一覧へ戻り，それ以外ではEscはCancelと同じです．前回の選択は `.roboloom/<robot>/logs/last_launch.yaml` に残り，次回の初期値になります．

オプションはdataflowの実行中には切り替えません（制御モードが変わるためです）．切り替えるときは，操作画面の終了確認で「Quit and choose options again (followers hold)」を選びます．followerを保持したまま終了し，ランチャーへ戻ります．

端末から実機で起動する前に，CLIは各DynamixelノードのEEPROM（Operating Mode，Current Limit）を選んだオプションと比べます．違いがあれば差分を表示し，操作者の確認後に書き込みます（`roboloom commission` と同じ手順です）．たとえば `gravity` を有効・無効にするとleaderのOperating Modeが変わります．

## runの操作

| 入力 | 動作 |
| --- | --- |
| `start <task>` | 準備状態を確認し追従・記録を始める |
| `stop` | 追従・記録を止める（保存は別操作） |
| `save` | エピソードを保存する |
| `discard` | エピソードを破棄する |
| `release` | 支持確認後に追従を止め，通電している入力機器とfollowerを脱力する |
| `home` | leaderとfollowerを，controllerで選んだ初期姿勢へゆっくり動かす．到着後，leaderは通常の制御に戻る |
| `estop` | 非常停止する |
| `quit` | 終了確認を開く．Cancel・follower保持・オプションを選び直す・支持確認後の脱力から選ぶ |

Textualの操作メニューは使えない操作も理由付きで表示し，初期姿勢がない `home` も含めます．Ctrl-Lで編集可能なコマンド欄，Ctrl-Gで非常停止へ進みます．Ctrl-CとCtrl-Qは同じ終了確認を開き，初期選択はCancelです．キー・ペイン・確認・時間指定モード・拡張契約は [操作画面](operator-screen.md) を参照してください．

`run --plain` は行入力を維持し，`record --plain`・`infer --plain` はキー入力なしで収集します．非TTYも同じ経路です（ランチャーは開きません）．`tune-gravity` はデバイスを開く前にTTYを要求します．Python APIのRich表示と確認は従来どおりです．
`stop` は脱力操作ではありません．`FAULT` / `ESTOP` / `RELEASED` は自動復帰しません．実機の開始・終了手順は [Quick start](../quick-start/rakuda2.md) にあります．既存の方策APIなど，leader以外の詳細は [Python API](python-api.md) を参照してください．

## センサー選択

`load_config(..., sensors=[...], observe=[...])` と
`Session.launch(..., sensors=[...], observe=[...])` で起動・記録と policy 観測を
独立に指定します。None は設定の既定、[] は選択なしです。フォロワ状態は常に渡します。
RobotConfig を渡す場合は load_config で選択を確定してください。

```python
with Session.launch(
    "rakuda2",
    options=["policy"],
    sensors=["camera", "audio"],
    observe=["camera"],
    policy="my_lab.policies:load",
) as session:
    session.wait_ready()
    session.record("pick", seconds=20)
```

CLI は `--sensors camera,audio --observe camera`、
空の選択は `--sensors "" --observe ""` です。ランチャーにはセンサー起動と
policy 観測の独立したチェック欄があり、前回の選択を保存します。
未選択センサーの YAML は読み込みません。未起動センサーの観測指定はエラーです。
左右の DIGIT を含め、オプションで追加されるセンサーも個別選択できます。
任意センサーは `{file: nodes/audio.yaml, default: false}` と宣言し、
従来の文字列パスは既定で有効です。オプション適用後に選択を解決します。
observe に含めないセンサーも、起動すれば記録対象になります。
[音声](../sensors/audio.md)も参照してください。
