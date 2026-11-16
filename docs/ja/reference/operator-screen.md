# 操作画面

対話端末の `run`・`record`・`infer`・`tune-gravity` はTextualを使います．起動の前に操作と起動オプションを選ぶランチャーと，起動したdataflowを操作する操作画面があります．操作画面では設定の編集やオプションの切り替えは行いません．オプションはdataflowの実行中には切り替えません（制御モードが変わるためです）．

## ランチャー { #launcher }

`roboloom`（または `roboloom launch`）で開きます．`roboloom rakuda2` のようにロボットを指定した場合は一覧を出しません．`run`・`record`・`infer` も，対話端末では `--with`・`--without`・`--plain` を指定しなければ先にランチャーを開き，コマンドの引数を初期値にします．

### 画面 { #launcher-screens }

| 画面・欄 | 内容 |
| --- | --- |
| ロボットの一覧 | 左に `.roboloom/` の下で `config.yaml` を持つロボット（データセット名と既定で有効なオプションつき），右に選択中のロボットの設定（ファイル，データセット名，各オプションの説明・`requires`・競合・データセット名，既定で有効か）．前回のロボットにカーソルがある |
| Operation | `run`・`record`・`infer` から選ぶ．`record` と `infer` ではtask・seconds・episodesを入力し，毎回初期姿勢へ動かすか（「move home before every episode」）も選べる |
| Options | 設定の `options:` を `help` の説明付きのカードで並べる（有効は緑，競合で外れるものは黄の線と理由）．チェックを入れると `requires` のオプションも有効になり，`conflicts` のオプションは外れる．外すと，それを必要とするオプションも外れる．競合の理由はツールチップに出る．`infer` を選ぶと，`policy` という名前のオプションがあれば自動で有効になる |
| Devices | 「mock devices (no hardware)」でmockデバイスを使う．「Video codec (storage: video)」で動画の codec（`YAML / dataset`・`AV1`・`H.264`）を選ぶ．`YAML / dataset` は recorder の YAML の指定（追記では保存済みの動画の codec，どちらもなければ H.264．[Video codec](configuration/recorder.md#video-codec)） |
| 要約 | 操作，`mock` か `HARDWARE` か（チェックを入れなくても YAML が `mode: mock` なら `mock (mode: mock in config.yaml)`），有効なオプション，データセット名，動画の codec，置き換わるノードファイル（削除は `(removed)`）．起動できない組み合わせや入力の不足は，理由を表示してLaunchを無効にする |
| センサーと方策の観測 | センサー起動と方策の観測の独立したチェック欄．方策の観測の欄は，推論への切り替えなどで起動オプションを変更すると，選択された policy YAML の既定値に更新される．観測を明示的に選択した後は，空の選択も含め，モードやオプションを変更しても保持する（[センサー選択](cli.md#sensor-selection)） |

2つ目の画面は，左の操作パネル（Operation・Devices），右のオプションパネル，下の要約パネルに分かれます．幅が90桁未満の端末ではパネルを縦に並べます．

### キー { #launcher-keys }

| キー・操作 | 動作 |
| --- | --- |
| Enter（ロボットの一覧） | 選んで次の画面へ進む |
| Esc（ロボットの一覧） | 何も起動せずに終了する |
| Launch（Ctrl-S） | 起動する |
| Cancel | 何も起動せずに終了する |
| Back（Esc） | ロボットの一覧から来た場合は一覧へ戻る．それ以外ではEscはCancelと同じ |
| 境界のドラッグ，フォーカスして矢印キー | パネルの大きさを変える（操作画面と同じ） |
| 境界のダブルクリック，Ctrl-R | パネルの大きさを元に戻す |

### 保存される選択 { #launcher-files }

| ファイル | 内容 |
| --- | --- |
| `.roboloom/logs/last_robot` | 選んだロボット．次回の一覧のカーソルの位置 |
| `.roboloom/<robot>/logs/last_launch.yaml` | 操作・オプション・デバイス・センサーと観測の選択．次回の初期値．観測は，YAML の既定値を使うか，明示指定かを区別して残す |

## レイアウト { #layout }

| 領域 | 内容 |
| --- | --- |
| ヘッダー | 機体名，モード（操作・mockか実機か・有効なオプション），記録の進捗，警告 |
| Status タブ | ノード一覧と詳細．幅100文字以上では左右に並べ，それ未満ではDetailsで選択ノードの詳細を確認する |
| Details タブ | 選択ノードの状態，項目，単位，更新からの時間．ノード選択は表示だけを変更し，操作はdataflow全体を対象にする |
| Logs タブ | タブを選ぶまで隠す．独立してスクロールでき，非表示中の新着も保持する．過去の行を読んでいる間は新着で位置を戻さない．画面は最大10,000行を保持し，doraの全ログは設定の隣の `logs/` に残る |
| Operations | すべてのタブの下に残り，表示領域の約半分を使う．対応する最小サイズ80×24でも，既定では10行以上を確保する（最小6行）．使えない操作も理由付きでメニューに残る．初期フォーカスは操作メニュー |
| 境界 | 一覧と詳細の間の縦の境界で左右の幅，上段とOperationsの間の横の境界で上下の高さを変える（Logsや80×24でも上下の調整ができる）．境界のダブルクリックで，その方向を既定サイズへ戻す．最小サイズを設け，ペインと入力欄が操作できなくなるまで縮めることを防ぐ |

リサイズしても選択タブ・ノード・入力内容を保持します．幅・高さの比率はセッション内で保持し，タブ切り替えや端末のリサイズ後も引き継ぎます．ファイルには保存しません．

### 色 { #colors }

| 表示 | 色 |
| --- | --- |
| ノードの状態（一覧と詳細） | 正常は緑，注意は黄，異常は赤 |
| 2秒以上更新のないノード | 赤の `STALE` |
| 初期姿勢の名前（詳細） | マゼンタ |
| 記録中のタスク（詳細） | シアン |
| 制限・拒否・エラー（詳細） | 黄または赤 |
| ヘッダーの警告，未保存（`UNSAVED`） | 黄 |
| Emergency stop | 赤 |
| 使えない操作 | 薄く表示 |
| ログ | 記録や非常停止などの報告ごとの色を保つ |

## キー { #keys }

| キー | 動作 |
| --- | --- |
| ↑ / ↓ | 項目選択．入力欄では履歴 |
| Enter | 選択操作の実行，またはコマンド送信 |
| Tab / Shift-Tab | 入力欄ではコマンド名の補完候補を巡回．それ以外ではフォーカス移動 |
| Ctrl-N / Ctrl-P | ペイン間の移動．境界にもフォーカスできる |
| Ctrl-L | コマンド欄へ移動 |
| Esc | 補完・確認をキャンセル．境界のドラッグを解除 |
| Ctrl-G | 確認なしで非常停止を要求（確認中・ドラッグ中も使える） |
| Ctrl-C / Ctrl-Q | 共通の終了確認を開く |
| Ctrl-O | Logsを開いて末尾へ移動 |
| 矢印キー（境界にフォーカス） | 対応方向のサイズ調整 |
| Ctrl-R / Home（境界にフォーカス） | その境界を既定へ戻す |

入力欄・確認以外では，次の文字キーで操作を要求できます．入力中とダイアログ中は文字キーのショートカットを抑制します．

| キー | 操作 |
| --- | --- |
| `e` | estop |
| `q` | quit |
| `h` | home |
| `s` | save |
| `d` | discard |
| `t` | Teleop（leaderに切り替える．方策に `teleop:` がある構成だけ） |
| `p` | Policy（方策に戻す．方策に `teleop:` がある構成だけ） |

`t`・`p` は録画中も使え，使えないときは理由を表示します（[テレオペと介入](../policy/intervention.md#teleop)）．

| 別名 | 同じ動作 |
| --- | --- |
| F2 | コマンド欄へ移動 |
| F6 / Shift-F6 | ペイン移動 |
| F12 | 非常停止 |
| Ctrl-End | ログ末尾 |

画面下の案内は主要なCtrl系の組み合わせを表示します．

### 入力欄 { #command-input }

- カーソル移動，Delete，Backspace，日本語入力に対応します．
- 履歴はセッション内だけで保持します．確認の回答は履歴に入りません．
- 補完だけでは操作しません．候補表示中のEnterは候補確定で，もう一度Enterを押すと送信します．
- 複数行の貼り付けは空白でつないだ1行になり，自動送信しません．

## 操作 { #operations }

メニューと入力欄から次の操作を使います．各操作の意味は [runの操作](cli.md#run-operations) にあります．

| 操作 | 画面での扱い |
| --- | --- |
| `start <task>` | `run` のStartはtask入力へ移動する．開始拒否は警告になり，状態更新は続くので準備後に再操作できる |
| `stop` | 追従・記録を止める |
| `save` | 入力欄で `save success`・`save failure` と書くと，評価の成否を付けて保存する（[エピソードごとの記録](../data/recording.md#episode-records)）．`success`・`failure` 以外は拒否し，エピソードは保存前のまま残る |
| `discard` | エピソードを破棄する |
| `home` | controllerに初期姿勢がある場合だけ有効．到着後も準備状態を再確認する |
| `release` | 機器の性質（[脱力したときと放置したときの性質](configuration/followers.md#torque-off-and-unattended)）から，支える機器と物を外す機器を示して確認する |
| `estop` | 非常停止．送信失敗・送信済みだが未確認・新しいfollower状態でのESTOP確認を区別する．バスやdataflowが切断されている場合の到達は保証できない |
| `quit` | 終了確認を開く |

### 終了の確認 { #exit-confirmation }

初期選択はCancelです．確認文には，終了時に脱力する（またはするかもしれない）機器と，すべきことを示します．

| 選択 | 出る条件 | 動作 |
| --- | --- | --- |
| Cancel | 常に | 操作画面へ戻る |
| followerの保持 | 保持できるfollowerがある（ない場合は「脱力せずに終了」） | followerを保持したまま終了する |
| 脱力して終了 | トルクのあるfollowerがある | 支持を確認してから脱力して終了する |
| Quit and choose options again (followers hold) | CLIから起動した対話端末 | followerを保持したまま終了し，ランチャーへ戻ってオプションを選び直す |

- followerを保持しても，通電している入力機器は終了時に脱力します．
- UI異常終了時も，脱力の選択が確認済みでなければfollowerを保持します．
- roboloomのプロセスごと止まった場合（強制終了，端末を閉じた）も，dataflowは記録中のエピソードを破棄し，followerを保持させて終わります．

## recordとinfer { #record-and-infer }

`record`・`infer` は準備状態，回数，残り時間，保存結果を表示します．

| 項目 | 動作 |
| --- | --- |
| 開始 | 毎回，準備後にStartを選ぶ．`record --home` は毎回homeへ移動する |
| 保存 | `record` は保存し，`infer` は `--task` がある場合だけ保存する．Stopで時間指定の記録を早く終えた場合も，同じ保存方針を適用する |
| 回数 | 指定回数が完了すると終了確認が開く．回数は目安で，終了確認を閉じると，HomeやTeleopでロボットを動かし，Startで次のエピソードを続けられる（表示は `episode 3 (2 planned)`）．`--plain` は指定回数で終わる |

エピソード中は，上部に進み具合が出ます．

```
episode 2/10  step 137/500  [█████░░░░░░░░░░░░░░░] 27%  at most 72.6 s left
```

`step` は方策が実行した行動の数で，長さをステップ数で決めたとき（`infer --steps`，実験ファイルの `steps`）に出ます．そのエピソードは，方策が指定の手数を実行した時点で終わります．秒数で決めたときは，経過時間の割合が出ます．

## 重力調整 { #gravity-tuning }

`tune-gravity` は別コマンドのままです（[`roboloom tune-gravity`](cli.md#tune-gravity)）．同じバスを開くdataflowを先に止めます．一覧で関節を選び，Detailsで関節の説明と実測・モデル・送信電流（mA）を確認します．メニューと入力欄で次を共用します．

```text
joint <name>
gain +
gain -
hold +
hold -
compare
resume
save
estop
quit
```

| キー | 動作 | 範囲 |
| --- | --- | --- |
| `]` / `[` | 選んだ関節のgainを上げる・下げる | 0.1刻みで[0, 3] |
| `=` / `-` | holdを上げる・下げる | 5 mA刻みで[0, 100] |
| `0` | 重力の比較 | — |
| `r` | 支持後に通常のSTOPPEDから再開する | — |
| Ctrl-G | 次の制御処理で脱力してESTOPをラッチする．再起動までresumeでも再通電できない | — |

文字キーは入力欄・確認以外で使えます．機器open・通電・読み出し・値の変更・closeは，設定周期で動く1本の制御スレッドが担当します．ファイル保存は値のスナップショットを別スレッドへ渡し，保存中の変更は未保存として残します．終了はCancel・Save and quit・Discard and quitから選び，初期選択はCancelです．実機での準備と値の読み方は [重力調整](../explanation/gravity-compensation.md) を参照してください．

## PlainモードとPython API { #plain-mode }

| 起動 | 動作 |
| --- | --- |
| `run --plain` | 行入力を維持する |
| `record --plain`・`infer --plain` | キー入力なしで指定回数を実行する |
| 非TTY | 自動でこれらの経路を選ぶ |
| `tune-gravity`（非TTY） | デバイスを開く前に拒否する |

`Session.launch(..., screen="auto")` は約10 HzのRich状態表示を維持します．stdinを読まないので，`print()`・`input()` と既存の操作者向け終了確認を引き続き使えます．`screen=False` で表示，`operator=None` で操作者への確認を無効にします．CLIのTextual Backendは両方を指定し，画面内で確認します．[Session](python-api/session.md) も参照してください．

## 表示の拡張 { #extending-the-display }

通常の拡張は，既存のfollower・input・sensor・controller登録と状態通知を使います．`StatusReporter` で標準のrole・level・timestamp・fieldsを通知し，項目名には単位を含めます．共通画面は関節数・名前・ID・単位を固定しません．未知の役割・項目も汎用key/valueで表示します．

専用表示が必要な場合だけ，起動前にPresenterを明示登録します．機種（ノードYAMLの `type`），役割Presenter，既存の `ui.render.RENDERERS` の役割表示，汎用表示の順に選びます．Presenterは `NodeSnapshot` を受け取り `Presentation` を返し，Widgetやデバイスを扱いません．

```python
from roboloom.ui.models import NodeSnapshot
from roboloom.ui.presenters import Presentation, register_presenter


@register_presenter(kind="my_stage")
def stage(node: NodeSnapshot) -> Presentation:
    return Presentation(
        str(node.fields.get("state", "")),
        "Position in millimetres",
        tuple((key, str(value)) for key, value in node.fields.items()),
    )
```

役割別には `role="my_role"` を指定します．Backendは型付きの `Snapshot` / `Capabilities` / `Operation` を渡し，`ui.models.Backend` の契約で操作要求を受け取ります．Operationに利用可否・理由・確認条件をまとめ，メニューと入力欄が共用します．Backendと機器実装はTextual Widgetに依存しません．拡張は明示的なPython登録に限り，外部プラグインの自動探索や新しい設定形式はありません．

スレッド通知は [Textualのメッセージ](https://textual.textualize.io/guide/workers/) を使います．テストはfake Backend・MockBusと [run_test / Pilot](https://textual.textualize.io/guide/testing/) を使います．mock成功は実機の停止時間や収集品質を保証しません．
