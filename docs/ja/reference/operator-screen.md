# 操作画面

対話端末の `run`・`record`・`infer`・`tune-gravity` はTextualを使います．起動した実験を操作する画面で，実験の選択や設定編集は行いません．

## レイアウトとフォーカス

ヘッダーに実験名，モード，記録の進捗，警告を表示します．ノードを選ぶと状態，項目，単位，更新からの時間を確認できます．ノード選択は表示だけを変更し，実験操作は実験全体を対象にします．使えない操作も理由付きでメニューに残ります．初期フォーカスは操作メニューです．

Status・Details・Logsタブを常に表示します．幅100文字以上のStatusはノード一覧と詳細を左右に並べ，それ未満ではDetailsで選択ノードの詳細を確認します．Logsはタブを選ぶまで隠します．Operationsはすべてのタブの下に残し，表示領域の約半分を使います．対応する最小サイズ80×24でも10行以上を確保します．リサイズしても選択タブ・ノード・入力内容を保持します．現在，マウスで境界をドラッグしてペインを拡大縮小する機能はありません．

ログは独立してスクロールでき，非表示中の新着も保持します．過去の行を読んでいる間は新着で位置を戻しません．Ctrl-OでLogsを開いて末尾へ移動します．画面は最大10,000行を保持し，doraの全ログは実験の隣に残ります．

| キー | 動作 |
| --- | --- |
| ↑ / ↓ | 項目選択．入力欄では履歴 |
| Enter | 選択操作の実行，またはコマンド送信 |
| Tab / Shift-Tab | 入力欄ではコマンド名の補完候補を巡回．それ以外ではフォーカス移動 |
| Ctrl-N / Ctrl-P | ペイン間の移動 |
| Ctrl-L | コマンド欄へ移動 |
| Esc | 補完・確認をキャンセル |
| Ctrl-G | 確認なしで非常停止を要求 |
| Ctrl-C / Ctrl-Q | 共通の終了確認を開く |
| Ctrl-O | Logsを開いて末尾へ移動 |

入力欄はカーソル移動，Delete，Backspace，日本語入力に対応します．履歴はセッション内だけで保持します．補完だけでは操作しません．候補表示中のEnterは候補確定で，もう一度Enterを押すと送信します．複数行の貼り付けは空白でつないだ1行になり，自動送信しません．確認の回答は履歴に入りません．

入力欄・確認以外では `e`・`q`・`h`・`s`・`d` でestop・quit・home・save・discardを要求できます．入力中とダイアログ中は文字キーのショートカットを抑制します．確認中もCtrl-Gは使えます．

F2・F6 / Shift-F6・F12・Ctrl-Endも，入力欄・ペイン移動・非常停止・ログ末尾の別名として残しています．画面下の案内は主要なCtrl系の組み合わせを表示します．

## 実験操作

メニューと入力欄から `start <task>`・`stop`・`save`・`discard`・`home`・`release`・`estop`・`quit` を使います．`run` のStartはtask入力へ移動します．開始拒否は警告になり，状態更新は続くので準備後に再操作できます．Homeはcontrollerに初期姿勢がある場合だけ有効で，到着後も準備状態を再確認します．

Releaseでは支持を確認します．終了はCancel・followerの保持・支持した上での脱力（可能な場合）から選び，初期選択はCancelです．followerを保持しても，通電している入力機器は終了時に脱力します．UI異常終了時も，脱力の選択が確認済みでなければfollowerを保持します．非常停止は送信失敗・送信済みだが未確認・新しいfollower状態でのESTOP確認を区別します．バスやdataflowが切断されている場合の到達は保証できません．

`record`・`infer` は準備状態，回数，残り時間，保存結果を表示します．毎回，準備後にStartを選びます．`record --home` は毎回homeへ移動します．`record` は保存し，`infer` は `--task` がある場合だけ保存します．Stopで時間指定の記録を早く終えた場合も，同じ保存方針を適用します．指定回数が完了すると終了確認が開きます．

## 重力調整

`tune-gravity` は別コマンドのままです．同じバスを開くdataflowを先に止めます．一覧で関節を選び，Detailsで関節の説明と実測・モデル・送信電流（mA）を確認します．メニューと入力欄で次を共用します．

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

Gainは0.1刻みで[0, 3]，holdは5 mA刻みで[0, 100]です．入力欄・確認以外では `]` / `[` でgain，`=` / `-` でhold，`0` で重力の比較，`r` で支持後に通常のSTOPPEDから再開します．Ctrl-Gは次の制御処理で脱力してESTOPをラッチし，再起動までresumeでも再通電できません．

機器open・通電・読み出し・値の変更・closeは，設定周期で動く1本の制御スレッドが担当します．ファイル保存は値のスナップショットを別スレッドへ渡し，保存中の変更は未保存として残します．終了はCancel・Save and quit・Discard and quitから選び，初期選択はCancelです．実機での準備と値の読み方は [重力調整](gravity-tuning.md) を参照してください．

## PlainモードとPython API

`run --plain` は行入力を維持します．`record --plain`・`infer --plain` はキー入力なしで指定回数を実行します．非TTYでは自動でこれらの経路を選びます．`tune-gravity` はデバイスを開く前に非TTYを拒否します．

`Session.launch(..., screen="auto")` は約10 HzのRich状態表示を維持します．stdinを読まないので，`print()`・`input()` と既存の操作者向け終了確認を引き続き使えます．`screen=False` で表示，`operator=None` で操作者への確認を無効にします．CLIのTextual Backendは両方を指定し，画面内で確認します．[Python API](python-api.md) も参照してください．

## 表示の拡張

通常の拡張は，既存のrobot・input・sensor・controller登録と状態通知を使います．`StatusReporter` で標準のrole・level・timestamp・fieldsを通知し，項目名には単位を含めます．共通画面は関節数・名前・ID・単位を固定しません．未知の役割・項目も汎用key/valueで表示します．

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
