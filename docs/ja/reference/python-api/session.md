# Session

`roboloom` packageの直下にある，収集と推論のための API です．使い方の例のあとに，docstring から生成した説明（英語）を載せます．

## 構成 { #architecture }

調べたrobot学習の系（franka_ros2，DROID，deoxys，diffusion_policy，OpenPI など）は，どれも次の 3 つを分けていました．

- motorを動かす速いloop
- 遠隔操作と記録
- 方策

roboloom も同じ構成をとります．

- **dora の dataflow**：次のものが，それぞれ別のprocessで動きます．
  - followerのnodeと leader node（制御のloop）
  - sensor
  - recorder
  - 方策node
- **`Session`**：dataflow を起動し，出来事を送ります．出来事とは，開始，停止，保存，task 名などです．制御のloopは回しません．
  - そのため，利用者のscriptが重い処理をしたり，止まったりしても，制御の周期は乱れません．

実験ごとの設定（方策，option，保存先）は，`Session.launch(experiment=...)` で渡せます．名前（`configs/roboloom/<名前>.yaml`），fileのpath，同じkeyのmappingのどれかです（[実験file](../configuration/index.md#experiments)）．

## 設定を読む { #loading-a-configuration }

設定は，fileのpathでも，`.roboloom/` の下の機体名（`rakuda2` は `.roboloom/rakuda2/config.yaml`）でも指定できます．

起動optionは `options=` で選びます．指定したoptionと，それが必要とするoptionが有効になります．`None`（既定）なら `default: true` のoptionが有効です．CLIの `--with`／`--without` と違い，`options=` は有効にするものの全体を表します（既定のoptionに足すのではありません）．`mock=True` はmock device，`mock=False` は実機で動かします．`None` ならYAMLの `mode`（既定 `hardware`）に従います．

```python
from roboloom import load_config

cfg = load_config("rakuda2", options=["gravity", "digit"])
print(cfg.options, cfg.repo_id)  # ('digit', 'gravity') local/rakuda2-digit
```

`load_config(..., video_codec="av1")` と `Session.launch(..., video_codec="av1")` で，`storage: video` の画像を AV1 で記録します（`"h264"` は H.264，`None` は recorder の YAML の指定．どちらもなければ H.264）．構成済みの `RobotConfig` を渡すときは `load_config` で選びます．既存のdatasetと codec が違うときの扱いは [Video codec](../configuration/recorder.md#video-codec) を参照してください．

## episodeを録る { #recording-episodes }

```python
from roboloom import Session

with Session.launch("rakuda2", options=["gravity"]) as s:
    s.wait_ready()
    result = s.record("pick up the cup", seconds=30)
    if result.pending:
        (result,) = s.wait_saves()
    print(result.index, result.frames, result.warnings)
```

- `launch` は，すべてのnodeが状態を報告し始めるまで待ちます．
- 毎回の `start` の前に，followerがleaderから `alignment_tolerance` 以内にあるかを確かめます（最初の位置合わせだけではありません）．`record` はepisodeごとに，揃うまで待ちます（`ready_timeout`，既定 60 秒）．`start` は，ずれていると `SessionError` を出します．
- 既定は実機です．mock deviceで動かすときは `mock=True` を渡します．
- `launch` の `options`・`mock` は，設定をpathか機体名で渡したときだけ使われます．読み込み済みの `RobotConfig` を渡す場合は，`load_config(..., options=..., mock=...)` で選んでおきます．
- 各nodeのprocessには，有効なoptionが `ROBOLOOM_OPTIONS`，modeが `ROBOLOOM_MODE` で渡ります．
- `with` を抜けると，次のことをします．
  - 途中のepisodeがあれば破棄する．
  - `operator` が設定されていれば，腕を支えるように求める．Enter で follower も脱力し，`hold` と入力すると follower は保持を続ける．
  - 保存待ちの処理を待ってからdataflowを止める．
  - leader は脱力する．follower は，脱力を選んだときだけtorqueを切り，それ以外はtorqueと最後の目標を保持する．ただし，放置したときに保持しない（`unattended` が `holds` でない）follower は保持しない．性質は [脱力したときと放置したときの性質](../configuration/followers.md#torque-off-and-unattended) にある．
  - scriptから決めるときは `s.close(release=True)`（脱力）または `s.close(release=False)`（保持）を呼ぶ．
- logは，設定fileの隣の `logs/<dataset name>-<time>/` に残ります（例：`logs/rakuda2-digit-20261102-101500/`）．
  - `dora.log`
  - leader のtrace
  - 場所は `s.log_dir` で分かります．

## 状態画面と終了時の確認 { #status-screen }

- `Session.launch(..., screen="auto")` が既定です．標準出力が端末なら，Richのnode状態表とmessage欄を別threadで10 Hzで更新します．対話CLIは別の [Textual操作画面](../operator-screen.md) を使います．
  - `screen=False` で表示を切れます．pipeなど標準出力が端末でない場合，既定では表示しません．
  - scriptの `print()` は画面の上に出ます．画面はkeyを読まないので，`input()` や API 呼び出しで操作できます．CLI の `record` のようなkey操作は追加しません．
  - 保存結果と品質の警告もmessage欄に出ます．
- `operator="auto"` が既定です．標準入力が端末なら，終了前に leader と follower の腕を支える確認を出します．
  - 腕を支えてから Enter を押すと，follower のtorqueも切って終了します．
  - `hold` と入力すると，follower は保持を続けたまま終了します．
  - follower が `torque: false` のときは，leader の確認だけを出します．
  - 確認文は機器の性質から作ります．支える機器（`falls`）と物を外す機器（`lets_go`）を名前で示し，保持できる follower がなければ，`hold` は脱力せずに終了することを示します（その follower は保持しないかもしれません）．`s.release_note()` で，`release` の前にすることを文字列で得られます．`release(confirm=False)` は，これを添えた `HardwareError` を出します．
  - `operator=None`，または標準入力が端末でない場合は，この確認を出さず，follower は保持を続けます．`screen=False` だけでは確認は無効になりません．
  - 保持を続けた follower は，電源を切る前に腕を支えるか安全な姿勢に下ろしてください．

## task名の自動命名 { #task-names }

`task` には，文字列のほか，`EpisodeInfo` を受け取って文字列を返す関数を渡せます．

| `EpisodeInfo` の項目 | 中身 |
| --- | --- |
| `index` | 保存待ちがすべて成功した場合の次のdataset内の番号（`next_info()` は保存済みと保存待ちの数を足す） |
| `number` | このSessionで保存した数と，受け付け済みで結果を待つ保存の数の合計 |
| `dataset` | datasetの名前（`repo_id` の `/` より後ろ．有効なoptionの名前が付く．例：`rakuda2-digit`） |
| `previous` | この Session で保存した task の一覧 |

```python
import itertools

objects = itertools.cycle(["cup", "bottle", "sponge"])

with Session.launch("rakuda2") as s:
    s.wait_ready()
    for _ in range(9):
        s.record(lambda info: f"pick up the {next(objects)}", seconds=20)
```

```python
# 番号つき，操作者に毎回たずねる，など
s.record(lambda info: f"trial {info.index:03d}", seconds=20)
s.record(lambda info: input(f"task for episode {info.index}: "), seconds=20)
```

- 決まった task の文字列は，LeRobotDataset の各frameの `task` に保存されます．
- 学習のときは，そのまま言語指示として使えます．

## 細かく操作する { #step-by-step }

- `start(task)`，`stop()`，`save()`，`discard()`，`estop()`，`release(confirm=True)` を，1 つずつ呼べます．
- <span class="status status--mock">模擬のみ</span> [background保存](../../data/recording.md#background-saving) の結果と操作を以下に示します．

| 呼び出し・項目 | 動作 |
| --- | --- |
| `save(timeout=300, *, label=None, note=None, wait=None)` | `wait=None` は `background_save` に従う．`wait=True` はこのepisodeの確定した保存結果を待つ．`background_save: false` では常に書き込み完了を待つ． |
| `EpisodeResult.pending` | background保存では既定の `save()` と，保持するepisodeに対する `record()` が `pending=True`，`saved=False`，`index=None` の結果を返す．保存済みepisodeの番号は確定した結果から取得する． |
| `wait_saves(timeout=None) -> list[EpisodeResult]` | このSessionで保存待ちに入れたepisodeの結果を，未回収の完了分も含めて受け付け順に集める．対象の保存がすべて終わってから，失敗があれば `SessionError` を上げる．`report["results"]` に成功分，`report["failures"]` に失敗分が入る．timeoutは `SessionError` になり，結果は後から取得できる． |
| `pending_saves` | 保存中と保存待ちを合わせたrecorderの最新報告値． |

- 状態を見る：
  - `status()`：各nodeの最新の状態．
  - `reports()`：未読の報告．robot のmodeの変化など．
- commandが拒否されたとき（leader が揃っていないなど）は，`SessionError` になります．
  - `start` は，記録中，`save`・`discard` を待つ停止中，同期保存中，またはbackground保存が上限に達したときに拒否されます．recorderが受けられなかった `start` がfollowerと方策に届いた場合は，それらも止めます．
- `record` は，episodeの途中でcontrollerが失敗したとき（方策の例外など）と，followerがFAULT・ESTOPになったとき，そのepisodeを破棄して `EpisodeFailed`（`SessionError` の一種）を上げます．方策は次のepisodeでそのまま使えます．
- `estop()` は，nodeが落ちたあとでも送れます（ほかのcommandは，nodeの障害を見つけると `SessionError` になります）．
- `Session.launch` を呼んだprocessが終わると，どう終わった場合でも（強制終了，例外，端末を閉じた），dataflowは記録中のepisodeを破棄し，followerを保持させて終わります．`close()` を呼ばずに放置しても，robotが方策で動き続けることはありません．`multiprocessing` などで作った子processが残っている間は，終わったと見なされません．
- `home(timeout=None, *, pose=None)` は各設定の既定姿勢へ動かします．`pose` に名前を渡すとその姿勢を選びます．`timeout`（秒）または設定の timeout まで到着を待ち，拒否時や未到着時は `SessionError` になります． <span class="status status--mock">模擬のみ</span>
- `begin_home(pose=None) -> tuple[int, float]` は移動を指示し，monotonic clock の送信時刻（ns）と設定中の最大 timeout（s）を返します．`home_waiting(sent_ns)` で到着待ちの node を確認できます．
- `record(..., home: bool | str = False)` は `False` なら移動を省き，`True` なら既定姿勢，姿勢名ならその姿勢へ episode の前に動きます．
- `teleop()`，`policy()`，`stop_teleop()`：方策に `teleop:` があるとき，leaderに切り替え（episodeの前，または途中の介入），方策に戻し，episodeの外のteleopを終えます．詳しくは [teleopと介入](../../policy/intervention.md#teleop) を参照してください．
- すべてのcontrollerが操作者の入力に従う構成では，`teleop()` は `start` と同じように準備状態と姿勢合わせを確認し，記録せずにfollowerを入力に従わせます．`stop_teleop()` はすべてのfollowerが保持状態になるまで待ちます．teleop中は `home()` の前に呼び出します．詳しくは [episodeの外でのteleop](../../controllers/index.md#teleop) を参照してください．<span class="status status--mock">Mock only</span>

```python
s.start("wipe the table")
while not task_done():
    print(s.status()["follower"]["fields"]["mode"])
    time.sleep(0.5)
stopped = s.stop()
s.save(wait=True) if stopped.ok else s.discard()
```

## 方策・評価・episodeの選別 { #guides }

- 方策で動かす：[方策で動かす](../../policy/run.md)
- 評価の成否を残す：[評価の成否](../../policy/evaluation.md#labels)
- 残すepisodeを選ぶ（`keep`）：[残すepisodeを選ぶ](../../data/recording.md#choosing-episodes)

## sensor選択 { #sensor-selection }

`load_config(..., sensors=[...], observe=[...])` と `Session.launch(..., sensors=[...], observe=[...])` で，起動・記録するsensorと方策の観測を独立に指定します．`None` は設定の既定，`[]` は選択なしです．followerの状態は常に渡します．`RobotConfig` を渡す場合は `load_config` で選択を確定してください（`Session.launch` は追加の選択の引数を拒否します）．

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

- 未選択のsensorの YAML は読み込みません．起動していないsensorの観測を指定するとerrorです．
- 左右の DIGIT を含め，optionで追加されるsensorも個別に選べます．選択はoptionを適用したあとで解決します．
- 任意のsensorは `{file: nodes/audio.yaml, default: false}` と宣言します．従来の文字列のpathは既定で有効です．
- `observe` に含めないsensorも，起動すれば記録します．

CLIでの指定は [CLI のsensor選択](../cli.md#sensor-selection) に，規則は [sensor選択](../configuration/sensors.md#sensor-selection) にあります．[音声](../../sensors/audio.md) も参照してください．

## 1つのprocessで動かす：InProcessSession { #inprocesssession }

- `InProcessSession` は，robotのbus，sensor，controller の呼び出しを，すべて呼び出し側のthreadで行います．
- 使いどころ：
  - 試験
  - 模擬
  - sensorの少ない簡単な機体
- 動かせるfollowerは1台です．followerが複数ある設定は `Session` で動かします．
- `save_episode()` は常に同期保存します．dataflow用のrecorder YAMLでbackground保存が有効な場合も同じです．
- 方策を `step(policy=...)` に直接渡せます．
  - ただし，方策やsensorが遅いと，制御の周期も遅れます．
- 実機の Rakuda-2 は，`Session` で動かします．
  - motorを制御する leader（triggerのばね，重力補償）を使う設定では，`from_yaml` を拒否します．
  - 方策の controller を使う設定でも，`from_yaml` を拒否します．
- `InProcessSession.from_yaml(path, *, options=None, mock=None, sensors=None, dataset=None)` の `options`・`mock` は `load_config` と同じ意味です．

deviceやrepository内のsample fileを使わない模擬例です．`record` extraが必要です．この例の関節範囲・速度を実機へ流用しないでください．

```python
from roboloom import InProcessSession
from roboloom.drivers.mock import MockBus

with InProcessSession.from_components(
    robot="my-mock",
    bus=MockBus(dimension=2),
    joint_names=["j1", "j2"],
    unit="count",
    limits=[
        {"name": "j1", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
        {"name": "j2", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
    ],
    controller=lambda obs: [2048, 2048],
    output="datasets/my-mock",
    repo_id="local/my-mock",
) as session:
    session.start_episode("handover")
    session.run(3.0)
    session.stop_episode()
    session.save_episode()
```

実機の収集手順は [Rakuda2：teleopで収集](../../tutorials/rakuda2/collect.md) を参照してください．

## API { #api }

::: roboloom.Session
    options:
      heading_level: 3

::: roboloom.EpisodeInfo
    options:
      heading_level: 3

::: roboloom.EpisodeResult
    options:
      heading_level: 3

::: roboloom.EpisodeFailed
    options:
      heading_level: 3

::: roboloom.SessionError
    options:
      heading_level: 3

::: roboloom.InProcessSession
    options:
      heading_level: 3

::: roboloom.load_config
    options:
      heading_level: 3

::: roboloom.resolve_config
    options:
      heading_level: 3

::: roboloom.init_project
    options:
      heading_level: 3

::: roboloom.Sample
    options:
      heading_level: 3

## 例外 { #errors }

::: roboloom.RoboloomError
    options:
      heading_level: 3

::: roboloom.ConfigError
    options:
      heading_level: 3

::: roboloom.HardwareError
    options:
      heading_level: 3

::: roboloom.SetupError
    options:
      heading_level: 3

::: roboloom.errors.Cancelled
    options:
      heading_level: 3
