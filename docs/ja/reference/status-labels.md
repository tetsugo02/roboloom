# Status labels

| Detail | 説明 |
| --- | --- |
| — | 機能，機体，設定のkeyがどこまで確かめられているかを，次の4つのlabelで示します．ページの冒頭，見出し，表の行に付けます．labelのない項目は，そのページの機能と同じ状態です． |

## Labels { #labels }

| label | 意味 |
| --- | --- |
| <span class="status status--verified">Hardware-verified</span> | 実機で動かして確かめた |
| <span class="status status--mock">Mock only</span> | 実装があり，testと模擬（`--mock`）の dataflow で確かめた．実機では確かめていない |
| <span class="status status--dev">In development</span> | 実装の途中か，実機で一度も動かしていない |
| <span class="status status--design">Design only</span> | 設計の段階．使える機能として扱わない |

## Current status { #current }

| 対象 | 状態 |
| --- | --- |
| Local hooks、policy teleop hooks、lifecycle events、`action.filtered` | <span class="status status--mock">Mock only</span> |
| Rakuda2 の teleop 収集 | <span class="status status--verified">Hardware-verified</span> |
| 重力補償 | <span class="status status--verified">Hardware-verified</span> |
| DIGIT を含む収集 | <span class="status status--verified">Hardware-verified</span> |
| Rakuda2 での自作の方策による推論と介入（`policy`，`policy_teleop`） | <span class="status status--verified">Hardware-verified</span> |
| LeRobot のcheckpoint（`roboloom.policy.lerobot:load`），`lerobot-train` | <span class="status status--mock">Mock only</span>（PiPER＋Pika） |
| RealSense | <span class="status status--verified">Hardware-verified</span> |
| 非同期の推論，記録の再生（replay），別processの方策（`serve-policy`） | <span class="status status--mock">Mock only</span> |
| [episodeのbackground保存](../data/recording.md#background-saving) | <span class="status status--mock">Mock only</span>（mock dataflowと合成frame） |
| [Rerun での live 表示](../reference/configuration/viewer.md)（`viewer` node，`viz` extra） | <span class="status status--mock">Mock only</span> |
| PiPER，Pika（Gripper，Sense，手首camera），Web camera，音声 | <span class="status status--dev">In development</span> |
| 力の逆送（`feedback`），推定器（`estimators`） | <span class="status status--mock">Mock only</span>（中断中） |
| bilateral制御の設計の段階 6 以降 | <span class="status status--design">Design only</span>（中断中） |
| Detail | 説明 |
| --- | --- |
| — | 上の表にない実装済みの機能は，<span class="status status--mock">Mock only</span> として扱います． |

## Writing a label { #usage }

| Detail | 説明 |
| --- | --- |
| — | `<span class="status status--verified">Hardware-verified</span>`<br>`<span class="status status--mock">Mock only</span>`<br>`<span class="status status--dev">In development</span>`<br>`<span class="status status--design">Design only</span>` |
