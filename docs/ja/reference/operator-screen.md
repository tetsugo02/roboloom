# Operator screen

| Detail | 説明 |
| --- | --- |
| — | 対話端末の `run`・`record`・`infer`・`tune-gravity` はTextualを使います．起動の前に操作と起動optionを選ぶlauncherと，起動したdataflowを操作する操作画面があります．操作画面では設定の編集やoptionの切り替えは行いません．optionはdataflowの実行中には切り替えません（制御modeが変わるためです）． |

## Launcher { #launcher }

| Detail | 説明 |
| --- | --- |
| — | `roboloom`（または `roboloom launch`）で開きます．`roboloom rakuda2` のようにrobotを指定した場合は一覧を出しません．`run`・`record`・`infer` も，対話端末では `--with`・`--without`・`--plain` を指定しなければ先にlauncherを開き，commandの引数を初期値にします． |

### Screens { #launcher-screens }

| 画面・欄 | 内容 |
| --- | --- |
| robotの一覧 | 左に `.roboloom/` の下で `config.yaml` を持つrobot（dataset名と既定で有効なoptionつき），右に選択中のrobotの設定（file，dataset名，各optionの説明・`requires`・競合・dataset名，既定で有効か）．前回のrobotにcursorがある |
| Operation | `run`・`record`・`infer` から選ぶ．`record` と `infer` ではtask・seconds・episodesを入力し，毎回初期姿勢へ動かすか（「move home before every episode」）も選べる |
| Options | 設定の `options:` を `help` の説明付きのカードで並べる（有効は緑，競合で外れるものは黄の線と理由）．チェックを入れると `requires` のoptionも有効になり，`conflicts` のoptionは外れる．外すと，それを必要とするoptionも外れる．競合の理由はtooltipに出る．`infer` を選ぶと，`policy` という名前のoptionがあれば自動で有効になる |
| Devices | 「mock devices (no hardware)」でmock deviceを使う．「Video codec (storage: video)」で動画の codec（`YAML / dataset`・`AV1`・`H.264`）を選ぶ．`YAML / dataset` は recorder の YAML の指定（追記では保存済みの動画の codec，どちらもなければ H.264．[Video codec](configuration/recorder.md#video-codec)） |
| 要約 | 操作，`mock` か `HARDWARE` か（チェックを入れなくても YAML が `mode: mock` なら `mock (mode: mock in config.yaml)`），有効なoption，dataset名，動画の codec，置き換わるnode file（削除は `(removed)`）．起動できない組み合わせや入力の不足は，理由を表示してLaunchを無効にする |
| sensorと方策の観測 | sensor起動と方策の観測の独立したチェック欄．方策の観測の欄は，推論への切り替えなどで起動optionを変更すると，選択された policy YAML の既定値に更新される．観測を明示的に選択した後は，空の選択も含め，modeやoptionを変更しても保持する（[sensor選択](cli.md#sensor-selection)） |
| Detail | 説明 |
| --- | --- |
| — | 2つ目の画面は，左の操作panel（Operation・Devices），右のoption panel，下の要約panelに分かれます．幅が90桁未満の端末ではpanelを縦に並べます． |

### Keys { #launcher-keys }

| key・操作 | 動作 |
| --- | --- |
| Enter（robotの一覧） | 選んで次の画面へ進む |
| Esc（robotの一覧） | 何も起動せずに終了する |
| Launch（Ctrl-S） | 起動する |
| Cancel | 何も起動せずに終了する |
| Back（Esc） | robotの一覧から来た場合は一覧へ戻る．それ以外ではEscはCancelと同じ |
| 境界のdrag，focusして矢印key | panelの大きさを変える（操作画面と同じ） |
| 境界のdouble-click，Ctrl-R | panelの大きさを元に戻す |

### Saved choices { #launcher-files }

| file | 内容 |
| --- | --- |
| `.roboloom/logs/last_robot` | 選んだrobot．次回の一覧のcursorの位置 |
| `.roboloom/<robot>/logs/last_launch.yaml` | 操作・option・device・sensorと観測の選択．次回の初期値．観測は，YAML の既定値を使うか，明示指定かを区別して残す |

## Layout { #layout }

| 領域 | 内容 |
| --- | --- |
| header | 機体名，mode（操作・mockか実機か・有効なoption），記録の進捗，警告 |
| Status tab | node一覧と詳細．幅100文字以上では左右に並べ，それ未満ではDetailsで選択nodeの詳細を確認する |
| Details tab | 選択nodeの状態，項目，単位，更新からの時間．node選択は表示だけを変更し，操作はdataflow全体を対象にする |
| Logs tab | tabを選ぶまで隠す．独立してscrollでき，非表示中の新着も保持する．過去の行を読んでいる間は新着で位置を戻さない．画面は最大10,000行を保持し，doraの全logは設定の隣の `logs/` に残る |
| Operations | すべてのtabの下に残り，表示領域の約半分を使う．対応する最小サイズ80×24でも，既定では10行以上を確保する（最小6行）．使えない操作も理由付きでmenuに残る．初期focusは操作menu |
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
| Emergency stop | 赤 |
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
| — | 入力欄・確認以外では，次の文字keyで操作を要求できます．入力中とdialog中は文字keyのshortcutを抑制します． |

| key | 操作 |
| --- | --- |
| `e` | estop |
| `q` | quit |
| `h` | home |
| `s` | save |
| `d` | discard |
| `t` | teleop（leaderに切り替える．方策に `teleop:` がある構成だけ） |
| `p` | policy（方策に戻す．方策に `teleop:` がある構成だけ） |
| Detail | 説明 |
| --- | --- |
| — | `t`・`p` は録画中も使え，使えないときは理由を表示します（[teleopと介入](../policy/intervention.md#teleop)）． |

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
| — | menuと入力欄から次の操作を使います．各操作の意味は [runの操作](cli.md#run-operations) にあります． |

| 操作 | 画面での扱い |
| --- | --- |
| `start <task>` | `run` のStartはtask入力へ移動する．開始拒否は警告になり，状態更新は続くので準備後に再操作できる |
| `stop` | 追従・記録を止める |
| `save` | 入力欄で `save success`・`save failure` と書くと，評価の成否を付けて保存する（[episodeごとの記録](../data/recording.md#episode-records)）．`success`・`failure` 以外は拒否し，episodeは保存前のまま残る |
| `discard` | episodeを破棄する |
| `home` | controllerに初期姿勢がある場合だけ有効．到着後も準備状態を再確認する |
| `release` | 機器の性質（[脱力したときと放置したときの性質](configuration/followers.md#torque-off-and-unattended)）から，支える機器と物を外す機器を示して確認する |
| `estop` | 非常停止．送信失敗・送信済みだが未確認・新しいfollower状態でのESTOP確認を区別する．busやdataflowが切断されている場合の到達は保証できない |
| `quit` | 終了確認を開く |

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
| — | roboloomのprocessごと止まった場合（強制終了，端末を閉じた）も，dataflowは記録中のepisodeを破棄し，followerを保持させて終わります． |

## record and infer { #record-and-infer }

| Detail | 説明 |
| --- | --- |
| — | `record`・`infer` は準備状態，回数，残り時間，保存結果を表示します． |

| 項目 | 動作 |
| --- | --- |
| 開始 | 毎回，準備後にStartを選ぶ．`record --home` は毎回homeへ移動する |
| 保存 | `record` は保存し，`infer` は `--task` がある場合だけ保存する．Stopで時間指定の記録を早く終えた場合も，同じ保存方針を適用する |
| 回数 | 指定回数が完了すると終了確認が開く．回数は目安で，終了確認を閉じると，HomeやTeleopでrobotを動かし，Startで次のepisodeを続けられる（表示は `episode 3 (2 planned)`）．`--plain` は指定回数で終わる |
| Detail | 説明 |
| --- | --- |
| — | episode中は，上部に進み具合が出ます． |
| — | `episode 2/10  step 137/500  [█████░░░░░░░░░░░░░░░] 27%  at most 72.6 s left` |
| — | `step` は方策が実行した行動の数で，長さをstep数で決めたとき（`infer --steps`，実験fileの `steps`）に出ます．そのepisodeは，方策が指定の手数を実行した時点で終わります．秒数で決めたときは，経過時間の割合が出ます． |

## Gravity tuning { #gravity-tuning }

| Detail | 説明 |
| --- | --- |
| — | `tune-gravity` は別commandのままです（[`roboloom tune-gravity`](cli.md#tune-gravity)）．同じbusを開くdataflowを先に止めます．一覧で関節を選び，Detailsで関節の説明と実測・model・送信電流（mA）を確認します．menuと入力欄で次を共用します． |
| — | `joint <name>`<br>`gain +`<br>`gain -`<br>`hold +`<br>`hold -`<br>`compare`<br>`resume`<br>`save`<br>`estop`<br>`quit` |

| key | 動作 | 範囲 |
| --- | --- | --- |
| `]` / `[` | 選んだ関節のgainを上げる・下げる | 0.1刻みで[0, 3] |
| `=` / `-` | holdを上げる・下げる | 5 mA刻みで[0, 100] |
| `0` | 重力の比較 | — |
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
