# 状態ラベル

機能，機体，設定のキーがどこまで確かめられているかを，次の4つのラベルで示します．ページの冒頭，見出し，表の行に付けます．ラベルのない項目は，そのページの機能と同じ状態です．

## ラベル { #labels }

| ラベル | 意味 |
| --- | --- |
| <span class="status status--verified">実機検証済み</span> | 実機で動かして確かめた |
| <span class="status status--mock">模擬のみ</span> | 実装があり，テストと模擬（`--mock`）の dataflow で確かめた．実機では確かめていない |
| <span class="status status--dev">開発中</span> | 実装の途中か，実機で一度も動かしていない |
| <span class="status status--design">設計のみ</span> | 設計の段階．使える機能として扱わない |

## 今の状態 { #current }

| 対象 | 状態 |
| --- | --- |
| Rakuda2 の teleop 収集 | <span class="status status--verified">実機検証済み</span> |
| 重力補償 | <span class="status status--verified">実機検証済み</span> |
| DIGIT を含む収集 | <span class="status status--verified">実機検証済み</span> |
| 方策の推論と介入（`policy`，`policy_teleop`） | <span class="status status--verified">実機検証済み</span> |
| RealSense | <span class="status status--verified">実機検証済み</span> |
| 非同期の推論，記録の再生（replay），別プロセスの方策（`serve-policy`） | <span class="status status--mock">模擬のみ</span> |
| PiPER，Pika（Gripper，Sense，手首カメラ），Webカメラ，音声 | <span class="status status--dev">開発中</span> |
| 力の逆送（`feedback`），推定器（`estimators`） | <span class="status status--mock">模擬のみ</span>（中断中） |
| バイラテラル制御の設計の段階 6 以降 | <span class="status status--design">設計のみ</span>（中断中） |

上の表にない実装済みの機能は，<span class="status status--mock">模擬のみ</span> として扱います．

## 書き方 { #usage }

```html
<span class="status status--verified">実機検証済み</span>
<span class="status status--mock">模擬のみ</span>
<span class="status status--dev">開発中</span>
<span class="status status--design">設計のみ</span>
```
