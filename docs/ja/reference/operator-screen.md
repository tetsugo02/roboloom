# Operator screen

| Detail | 説明 |
| --- | --- |
| — | 対話端末の `run`・`record`・`infer`・`tune-gravity` はTextualを使います．起動の前に操作と起動optionを選ぶlauncherと，起動したdataflowを操作する操作画面があります．操作画面では設定の編集やoptionの切り替えは行いません．optionはdataflowの実行中には切り替えません（制御modeが変わるためです）． |

## Launcher { #launcher }

| Detail | 説明 |
| --- | --- |
| — | `roboloom`（または `roboloom launch`）で開きます．`roboloom rakuda2` のようにrobotを指定した場合は一覧を出しません．`run`・`record`・`infer` も，対話端末では `--with`・`--without`・`--experiment`・`--plain` を指定しなければ先にlauncherを開き，commandの引数を初期値にします． |

### Screens { #launcher-screens }

launcher の検証・起動失敗時の復帰・姿勢選択 <span class="status status--mock">模擬のみ</span>

| 画面・欄 | 内容 |
| --- | --- |
| robotの一覧 | 左に `.roboloom/` の下で `config.yaml` を持つrobot（dataset名と既定で有効なoptionつき），右に選択中のrobotの設定（file，dataset名，各optionの説明・`requires`・競合・dataset名，既定で有効か）．前回のrobotにcursorがある |
| Operation | `run`・`record`・`infer` から選ぶ．`record` と `infer` では task・seconds・episodes を入力する |
| Home controls | `Move home before every episode` にチェックを入れ，姿勢を選ぶか既定の姿勢を使う．選択した設定に `home:` がある場合に `record` と `infer` で表示する |
| Ask to save or discard after every episode | `record` と `infer` で，episodeごとの保存確認を有効にする．選択はlauncherに記憶される <span class="status status--mock">模擬のみ</span> |
| Options | 設定の `options:` を `help` の説明付きのカードで並べる（有効は緑，競合で外れるものは黄の線と理由）．チェックを入れると `requires` のoptionも有効になり，`conflicts` のoptionは外れる．外すと，それを必要とするoptionも外れる．競合の理由はtooltipに出る．`infer` を選ぶと，`policy` という名前のoptionがあれば自動で有効になる |
| Devices | 「mock devices (no hardware)」でmock deviceを使う．「Video codec (storage: video)」で動画の codec（`YAML / dataset`・`AV1`・`H.264`）を選ぶ．`YAML / dataset` は recorder の YAML の指定（追記では保存済みの動画の codec，どちらもなければ H.264．[Video codec](configuration/recorder.md#video-codec)） |
| 要約 | 操作，`mock` か `HARDWARE` か（チェックを入れなくても YAML が `mode: mock` なら `mock (mode: mock in config.yaml)`），有効なoption，dataset名，動画の codec，置き換わるnode file（削除は `(removed)`）．Launch の前に `load_config` で選択を検証する．無効な設定（例として `infer` が未知の node を観測する場合）は理由を表示し，Launch を無効にする |
| sensorと方策の観測 | sensor起動と方策の観測の独立したチェック欄．方策の観測の欄は，推論への切り替えなどで起動optionを変更すると，選択された policy YAML の既定値に更新される．観測を明示的に選択した後は，空の選択も含め，modeやoptionを変更しても保持する（[sensor選択](cli.md#sensor-selection)） |
| Detail | 説明 |
| --- | --- |
| — | 2つ目の画面は，左の操作panel（Operation・Devices），右のoption panel，下の要約panelに分かれます．幅が90桁未満の端末ではpanelを縦に並べます． |

### Keys { #launcher-keys }

| key・操作 | 動作 |
| --- | --- |
| Enter（robotの一覧） | 選んで次の画面へ進む |
| Esc（robotの一覧） | 何も起動せずに終了する |
| Launch（Ctrl-S） | 起動する．起動時に `RoboloomError` が出ると，同じ選択を保持し，error banner を表示して launcher に戻る |
| Cancel | 何も起動せずに終了する |
| Back（Esc） | robotの一覧から来た場合は一覧へ戻る．それ以外ではEscはCancelと同じ |
| 境界のdrag，focusして矢印key | panelの大きさを変える（操作画面と同じ） |
| 境界のdouble-click，Ctrl-R | panelの大きさを元に戻す |

### Saved choices { #launcher-files }

| file | 内容 |
| --- | --- |
| `.roboloom/logs/last_robot` | 選んだrobot．次回の一覧のcursorの位置 |
| `.roboloom/<robot>/logs/last_launch.yaml` | 操作・option・device・sensor と観測の選択・選んだ `home_pose`．次回の初期値．観測は，YAML の既定値を使うか，明示指定かを区別して残す |

## Layout { #layout }

状態 banner と操作ボタン <span class="status status--mock">模擬のみ</span>

| 領域 | 内容 |
| --- | --- |
| header と状態 banner | 3行で表示する．1行目は機体名と mode，赤い `[e] ESTOP` ボタン．2行目は状態と進捗で，`run` で記録中は経過時間・行数・保存済み episode 数・task を表示する．3行目は該当する場合の `Driver: POLICY` または `Driver: LEADER` badge，警告，node の状態を表示する．`start` の準備状態は Operations に表示する |
| Status tab | node一覧と詳細．幅100文字以上では左右に並べ，それ未満ではDetailsで選択nodeの詳細を確認する |
| recorderの行 | recorderの状態を表示し，保存待ちがあれば保存中の1件を含めて `saving N queued` を表示する．Detailsには `pending_saves` と `max_pending_saves` が出る．[background保存](../data/recording.md#background-saving) <span class="status status--mock">模擬のみ</span> |
| Details tab | 選択nodeの状態，項目，単位，更新からの時間．node選択は表示だけを変更し，操作はdataflow全体を対象にする |
| Logs tab | tabを選ぶまで隠す．独立してscrollでき，非表示中の新着も保持する．過去の行を読んでいる間は新着で位置を戻さない．画面は最大10,000行を保持し，doraの全logは設定の隣の `logs/` に残る |
| Operations | どの tab でも下部に残る．状態に応じて大型の操作ボタンを切り替える．状態遷移時は主ボタンに focus を移す（command 入力中や dialog 表示中を除く）．拒否時はボタンの上にすぐ理由を表示し，ボタンを点滅させる |
| 境界 | 一覧と詳細の間の縦の境界で左右の幅，上段とOperationsの間の横の境界で上下の高さを変える（Logsや80×24でも上下の調整ができる）．境界のdouble-clickで，その方向を既定サイズへ戻す．最小サイズを設け，paneと入力欄が操作できなくなるまで縮めることを防ぐ |
| Detail | 説明 |
| --- | --- |
| — | resizeしても選択tab・node・入力内容を保持します．幅・高さの比率はsession内で保持し，tab切り替えや端末のresize後も引き継ぎます．fileには保存しません． |

### Colors { #colors }

| 表示 | 色 |
| --- | --- |
| nodeの状態（一覧と詳細） | 正常は緑，注意は黄，異常は赤 |
| 2秒以上更新のないnode | 赤の `STALE` |
| 初期姿勢の名前（詳細） | magenta |
| 記録中のtask（詳細） | cyan |
| 制限・拒否・error（詳細） | 黄または赤 |
| headerの警告，未保存（`UNSAVED`） | 黄 |
| `HOLD`・`TELEOP`・`● REC` | 順に success・accent・error の色 |
| `STOPPED`・`HOMING` | warning の色 |
| `ESTOP`・`FAULT` | `ESTOP` は赤地に白，`FAULT` は error の色 |
| 使えない操作 | 薄く表示 |
| log | 記録や非常停止などの報告ごとの色を保つ |

## Keys { #keys }

| key | 動作 |
| --- | --- |
| ↑ / ↓ | 項目選択．入力欄では履歴 |
| Enter | 選択操作の実行，またはcommand送信 |
| Tab / Shift-Tab | 入力欄ではcommand名の補完候補を巡回．それ以外ではfocus移動 |
| Ctrl-N / Ctrl-P | pane間の移動．境界にもfocusできる |
| Ctrl-L | command欄へ移動 |
| Esc | 補完・確認をcancel．境界のdragを解除 |
| Ctrl-G | 確認なしで非常停止を要求（確認中・drag中も使える） |
| Ctrl-C / Ctrl-Q | 共通の終了確認を開く |
| Ctrl-O | Logsを開いて末尾へ移動 |
| 矢印key（境界にfocus） | 対応方向のサイズ調整 |
| Ctrl-R / Home（境界にfocus） | その境界を既定へ戻す |
| Detail | 説明 |
| --- | --- |
| — | 入力欄・確認以外では，次の文字keyで操作を要求できます．入力中と dialog 中は文字 key の shortcut を抑制します（Move home 内の `e` は ESTOP）． |

| key | 操作 |
| --- | --- |
| Space | focus 中の操作ボタンを実行する．主操作は `HOLD`・`TELEOP` で開始，`● REC` で停止 |
| `e` | ESTOP |
| `q` | 終了 |
| `h` | 利用できる場合に [Move home](#move-home) を開く |
| `s` | 保存 |
| `d` | 破棄 |
| `r` | 確認後に脱力する．`tune-gravity` では再開 |
| `t` | episode の外では `TELEOP: OFF ⇄ ON`，`teleop:` がある方策の episode 中は `DRIVER: POLICY ⇄ LEADER` を切り替える．ボタンは現在の状態を表示する．[episode の外での teleop](../controllers/index.md#teleop)，[方策への介入](../policy/intervention.md#teleop) <span class="status status--mock">模擬のみ</span> |

| 別名 | 同じ動作 |
| --- | --- |
| F2 | command欄へ移動 |
| F6 / Shift-F6 | pane移動 |
| F12 | 非常停止 |
| Ctrl-End | log末尾 |
| Detail | 説明 |
| --- | --- |
| — | 画面下の案内は主要なCtrl系の組み合わせを表示します． |

### Command input { #command-input }

| Detail | 説明 |
| --- | --- |
| — | cursor移動，Delete，Backspace，日本語入力に対応します． |
| — | 履歴はsession内だけで保持します．確認の回答は履歴に入りません． |
| — | 補完だけでは操作しません．候補表示中のEnterは候補確定で，もう一度Enterを押すと送信します． |
| — | 複数行の貼り付けは空白でつないだ1行になり，自動送信しません． |

## Operations { #operations }

| Detail | 説明 |
| --- | --- |
| — | 操作ボタンか command 欄を使います．[run の操作](cli.md#run-operations) を参照してください． |

| 操作 | 画面での扱い |
| --- | --- |
| `start <task>` | `run` の Start は task 入力欄を開く．teleop 中は現在の姿勢から開始する |
| `stop` | 追従・記録を止める |
| `save` | 停止中は Save・`Save success`・`Save failure` を選ぶ．成否を付けるボタンは `save success`・`save failure` を送る（[episode ごとの記録](../data/recording.md#episode-records)） |
| `discard` | episodeを破棄する |
| `home [NAME]` | [Move home](#move-home) か command 欄を使う．`NAME` を省くと設定の既定姿勢へ動く．teleop 中は先にオフへ切り替える．到着後に準備状態を再確認する |
| `release` | 機器の性質（[脱力したときと放置したときの性質](configuration/followers.md#torque-off-and-unattended)）から，支える機器と物を外す機器を示して確認する |
| `estop` | 非常停止．送信失敗・送信済みだが未確認・新しいfollower状態でのESTOP確認を区別する．busやdataflowが切断されている場合の到達は保証できない |
| `quit` | 終了確認を開く |

| 保存のlog | 意味 |
| --- | --- |
| `queued for save (N pending)` | recorderが `save` を受け付けた <span class="status status--mock">模擬のみ</span> |
| `saved episode N 'task' (F frames)` | backgroundでの書き込みが完了した．同じ行に品質の指標が続くことがある <span class="status status--mock">模擬のみ</span> |
| `episode 'task' was not saved: ...` | backgroundでの書き込みが失敗し，そのepisodeを破棄した <span class="status status--mock">模擬のみ</span> |

### Move home { #move-home }

<span class="status status--mock">模擬のみ</span>

| 項目・key | 動作 |
| --- | --- |
| `Pose`・`worst joint`・`dist`・`time` | 姿勢，推定時間が最も長い follower のうち移動量が最大の関節，その移動量（follower の単位），推定時間．設定した timeout を超える見込みの場合は `> timeout!` が出る |
| 利用できない姿勢 | 理由を表示し，選択を無効にする |
| `Moves:` | 動く機器 |
| Enter / Esc / `e` | 選択した姿勢へ動かす / cancel / ESTOP |

### Exit confirmation { #exit-confirmation }

| Detail | 説明 |
| --- | --- |
| — | 初期選択はCancelです．確認文には，終了時に脱力する（またはするかもしれない）機器と，すべきことを示します． |

| 選択 | 出る条件 | 動作 |
| --- | --- | --- |
| Cancel | 常に | 操作画面へ戻る |
| followerの保持 | 保持できるfollowerがある（ない場合は「脱力せずに終了」） | followerを保持したまま終了する |
| 脱力して終了 | torqueのあるfollowerがある | 支持を確認してから脱力して終了する |
| Quit and choose options again (followers hold) | CLIから起動した対話端末 | followerを保持したまま終了し，launcherへ戻ってoptionを選び直す |
| Detail | 説明 |
| --- | --- |
| — | followerを保持しても，通電している入力機器は終了時に脱力します． |
| — | UI異常終了時も，脱力の選択が確認済みでなければfollowerを保持します． |
| — | <span class="status status--mock">模擬のみ</span> 終了を確定すると，[保存待ち](../data/recording.md#background-saving) の処理が終わるまで待ちます． |
| — | roboloomのprocessごと止まった場合（強制終了，端末を閉じた）も，dataflowは記録中のepisodeを破棄し，followerを保持させて終わります． |

## record and infer { #record-and-infer }

| Detail | 説明 |
| --- | --- |
| — | `record`・`infer` は準備状態，回数，残り時間，保存結果を表示します． |

| 項目 | 動作 |
| --- | --- |
| 開始 | 準備後に Start を選ぶ．`record --home [NAME]`・`infer --home [NAME]` は episode ごとに初期姿勢へ動く |
| 保存 | 既定では `record` は自動で保存し，`infer` はtaskがある場合に自動で保存する．Stopでepisodeを早く終えた場合も，同じ保存方針を適用する |
| 保存確認 | 時間・step 数・Stop で episode が止まると，`--confirm` では `STOPPED — save or discard` と表示する．Save・`Save success`・`Save failure`・Discard から選ぶ．開始や teleop の前に保存か破棄を済ませる．書き込み完了時か保存待ちに入った時点で回数に数える． <span class="status status--mock">模擬のみ</span> |
| Discard | 記録計画では，記録中も保存確認を待つ間もDiscardでepisodeを破棄できる．同じepisode番号を再び準備し，homeの指定があれば初期姿勢へ移動する <span class="status status--mock">模擬のみ</span> |
| 回数 | 指定回数が完了すると終了確認が開く．回数は目安で，終了確認を閉じると，Move home や teleop の切り替えでrobotを動かし，Startで次のepisodeを続けられる（表示は `episode 3 (2 planned)`）．`--plain` は指定回数で終わる |
| Detail | 説明 |
| --- | --- |
| — | episode 中は状態 banner の2行目に進捗が出ます． |
| — | `● REC  episode 2/10  137/500  00:27 / 01:40  [██░░░░░░░░] 27%` |
| — | step の表示は方策が実行した行動の数で，長さを step 数で決めたとき（`infer --steps`，実験fileの `steps`）に出ます．そのepisodeは，方策が指定の手数を実行した時点で終わります．秒数で決めたときは，経過時間の割合が出ます． |

## Gravity tuning { #gravity-tuning }

| Detail | 説明 |
| --- | --- |
| — | `tune-gravity` は別commandのままです（[`roboloom tune-gravity`](cli.md#tune-gravity)）．同じbusを開くdataflowを先に止めます．一覧で関節を選び，Detailsで関節の説明と実測・model・送信電流（mA）を確認します．`OptionList` と command 欄で次を共用します． |
| — | `joint <name>`<br>`gain +`<br>`gain -`<br>`hold +`<br>`hold -`<br>`compare`<br>`resume`<br>`save`<br>`estop`<br>`quit` |

| key | 動作 | 範囲 |
| --- | --- | --- |
| `]` / `[` | 選んだ関節のgainを上げる・下げる | 0.1刻みで[0, 3] |
| `=` / `-` | holdを上げる・下げる | 5 mA刻みで[0, 100] |
| `0` | 重力の比較 | — |
| `j` / `k` | 次または前の関節を選ぶ | — |
| `r` | 支持後に通常のSTOPPEDから再開する | — |
| Ctrl-G | 次の制御処理で脱力してESTOPをlatchする．再起動までresumeでも再通電できない | — |
| Detail | 説明 |
| --- | --- |
| — | 文字keyは入力欄・確認以外で使えます．機器open・通電・読み出し・値の変更・closeは，設定周期で動く1本の制御threadが担当します．file保存は値のsnapshotを別threadへ渡し，保存中の変更は未保存として残します．終了はCancel・Save and quit・Discard and quitから選び，初期選択はCancelです．実機での準備と値の読み方は [重力調整](../explanation/gravity-compensation.md) を参照してください． |

## Plain mode and Python API { #plain-mode }

| 起動 | 動作 |
| --- | --- |
| `run --plain` | 行入力を維持する |
| `record --plain`・`infer --plain` | key入力なしで指定回数を実行する |
| 非TTY | 自動でこれらの経路を選ぶ |
| `tune-gravity`（非TTY） | deviceを開く前に拒否する |
| Detail | 説明 |
| --- | --- |
| — | `Session.launch(..., screen="auto")` は約10 HzのRich状態表示を維持します．stdinを読まないので，`print()`・`input()` と既存の操作者向け終了確認を引き続き使えます．`screen=False` で表示，`operator=None` で操作者への確認を無効にします．CLIのTextual Backendは両方を指定し，画面内で確認します．[Session](python-api/session.md) も参照してください． |

## Extending the display { #extending-the-display }

| Detail | 説明 |
| --- | --- |
| — | 通常の拡張は，既存のfollower・input・sensor・controller登録と状態通知を使います．`StatusReporter` で標準のrole・level・timestamp・fieldsを通知し，項目名には単位を含めます．共通画面は関節数・名前・ID・単位を固定しません．未知の役割・項目も汎用key/valueで表示します． |
| — | 専用表示が必要な場合だけ，起動前にPresenterを明示登録します．機種（node YAMLの `type`），役割Presenter，既存の `ui.render.RENDERERS` の役割表示，汎用表示の順に選びます．Presenterは `NodeSnapshot` を受け取り `Presentation` を返し，Widgetやdeviceを扱いません． |
| — | `register_presenter(kind="my_stage")` / `register_presenter(role="my_role")`: `NodeSnapshot` → `Presentation(state, detail, fields)` |
| — | 役割別には `role="my_role"` を指定します．Backendは型付きの `Snapshot` / `Capabilities` / `Operation` を渡し，`ui.models.Backend` の契約で操作要求を受け取ります．Operationに利用可否・理由・確認条件をまとめ，menuと入力欄が共用します．Backendと機器実装はTextual Widgetに依存しません．拡張は明示的なPython登録に限り，外部pluginの自動探索や新しい設定形式はありません． |
| — | thread通知は [Textualのmessage](https://textual.textualize.io/guide/workers/) を使います．testはfake Backend・MockBusと [run_test / Pilot](https://textual.textualize.io/guide/testing/) を使います．mock成功は実機の停止時間や収集品質を保証しません． |

## Hook status { #hooks }

| Field | Unit | 意味 |
| --- | --- | --- |
| `hook_ms` <span class="status status--mock">Mock only</span> | ms | 直近の周期の step hook の合計時間 |
| `hook_max_ms` <span class="status status--mock">Mock only</span> | ms | この episode の合計時間の最大値 |
| `hook_errors` <span class="status status--mock">Mock only</span> | count | `on_error` で処理した step error と barrier failure の数 |
| `hook_over` <span class="status status--mock">Mock only</span> | count | measured budget を超えた hook call の数 |
| `filtered` <span class="status status--mock">Mock only</span> | periods | この episode で chain が変更した周期数（policy と teleop） |
