# 自作の方策

roboloomはモデルの形を決めません．方策は `reset()` と `infer(observation)` を持つオブジェクトで，記録と同じ観測を受け取り，関節の絶対目標を返します．LeRobotのチェックポイントを使うときは [LeRobotの方策](lerobot.md) を参照してください．

## 方策の形 { #interface }

`reset()` と `infer(observation)` を持つオブジェクトを返す関数を書きます（`roboloom.Policy`）．

```python
# .roboloom/<robot>/my_policy.py か，インストールしたパッケージ
import numpy as np


class MyPolicy:
    def __init__(self, checkpoint: str): ...

    def bind(self, spec):  # 任意．読み込みの直後に1回呼ばれる
        if "observation.images.left_wrist" not in spec.observation:
            raise ValueError("left_wrist を observe に加えてください")

    def reset(self): ...  # エピソードの始めに呼ばれる

    def infer(self, observation) -> np.ndarray:
        state = observation["observation.state"]  # float32 [n]
        image = observation["observation.images.left_wrist"]  # uint8 [h, w, 3]，RGB
        task = observation["task"]
        return self.model(state, image, task)  # [n] か [H, n]


def load(checkpoint: str) -> MyPolicy:
    return MyPolicy(checkpoint)
```

- **観測**：キーは記録したデータセットの特徴量と同じです（`observation.state`，`observation.images.<名前>`，`observation.<入力の名前>` など）．値はnumpyで，画像は `[h, w, 3]` のuint8（RGB）です．`task` も渡されます．特徴量の一覧は [データセットの特徴量](../reference/dataset-features.md#observation) にあります．
- **出力**：関節の目標値を，記録した `action` と同じ並び（フォロワを設定の順につないだもの）と単位で返します．1手 `[n]` か，まとめた行動 `[H, n]` です．
- ロボットごとの観測の名前と大きさ，行動の並び・要素数・単位は，各ロボットのページにあります（[Rakuda2](../robots/rakuda2/index.md)，開発中の [PiPER](../robots/piper/index.md)）．
- **`bind(spec)`（任意）**：読み込みの直後，エピソードより前に1回呼ばれます．`spec`（`roboloom.policy.PolicySpec`）の中身は次のとおりです．
  - `observation`：観測の名前ごとの `dtype`，`shape`，`names`
  - `action`：行動の各要素の名前（`left.joint1`，…，`right_gripper.gripper`）
  - `rate_hz`，`dataset_fps`

  学習したときと違う構成なら例外を出してください．controllerは `failed` になり，理由を画面に出して，エピソードを始めません．`roboloom infer` と `Session.wait_ready` は，待たずに理由を示して終わります．`bind` を書かない方策も，これまでどおり動きます．

Pythonの型と関数は [Python API：方策](../reference/python-api/policy.md) にあります．

## 観測を選ぶ { #observations }

Rakuda2のテンプレートは，DIGITなしで関節状態とRealSenseを方策に渡します．`nodes/policy.yaml` の `observe` を，学習時に使った入力に合わせます．フォロワの関節状態は常に渡されます．

| 方策に渡す観測 | `observe` | 有効にするオプション |
| --- | --- | --- |
| 関節状態＋RealSense（既定） | `[camera]` | `policy` |
| 関節状態＋RealSense＋左右DIGIT | `[camera, digit_left, digit_right]` | `digit`，`policy` |
| 関節状態のみ | `[]` | `policy` |

`digit` を有効にするだけでは，方策の入力は変わりません．`observe` に追加したセンサーは，`sensors` にも存在する必要があります．`observe` から外しても，`sensors` にあるセンサーは開いて記録します．カメラも使わない構成では，`config.yaml` の `sensors` から `camera` を外してください．起動ごとに選ぶ方法は [センサー選択](run.md#sensor-selection) にあります．

DIGITを入力とする学習済み方策を，DIGITなしでそのまま使えるわけではありません．DIGITなしの入力で学習した方策を使います．LeRobotの読み込みは，必要な入力が足りなければ開始前に拒否します．自作の方策では `bind(spec)` で同じ検査を書けます．

既存プロジェクトの設定は，パッケージ更新では上書きされません．`roboloom init rakuda2 --update` が，足りないファイル（`nodes/policy.yaml` など）を足し，`config.yaml` に足りないオプションを一覧にします．以前のテンプレートから移行するときは，`config.yaml` の `options.policy` から `requires: [digit]` を削除し，`nodes/policy.yaml` を `observe: [camera]` に変更します．評価の保存先はDIGITなしなら `datasets/rakuda2-eval`，`digit` も有効なら `datasets/rakuda2-digit-eval` です．

## エピソードの途中で方策が失敗したとき { #failures }

- `infer` や `reset` が例外を出すと，controllerは指令を止めて `failed` になり，フォロワは保持します．理由は画面のcontrollerの行に出ます．
- `roboloom infer`，`Session.record`，操作画面の時間指定の実行は，そのエピソードを破棄します（保存しません）．`Session.record` は `EpisodeFailed` を上げます．
- `stop` か `discard` でエピソードを終えると，方策は `ready` に戻ります．再起動は要りません．次の `start` は `policy.reset()` から始めます．理由の表示は次の `start` まで残ります．
- 読み込めなかった方策（`bind` の例外を含む）は `failed` のままです．直してから起動し直してください．
- フォロワがFAULTかESTOPになったエピソードも，同じく破棄します．

## 履歴，動かさない関節，新しい観測 { #hold }

最新のフレーム以外にモデルが要るものは，controllerに頼みます．モデルを作り替えるたびに書き直す必要はありません．正規化，画像の縮小，モデル独自の行動（差分，一部の関節だけ）を関節の目標へ直す処理は，方策の側に書きます．

```yaml
observation_history: 4                       # 既定は1：最新のフレームだけ
hold: [follower.torso_yaw, follower.head_yaw, follower.head_pitch]  # 既定は []
```

- **`observation_history: N`**：観測を行動1手ごと（`1/rate_hz` ごと）に1回採ります．まとめた行動のうち推論しない手でも採ります．`infer` には `observation["history"]` も渡ります．観測の各配列を `[N, ...]` に重ねたもので，古い順に並び，最後が今のフレームです．エピソードの始めは，最初のフレームで履歴を埋めます．`history["action"]`（float32 `[N, n]`）は，各フレームの前に実行した行動です（始めはフォロワが保持していた目標）．値はフォロワへ送った指令で，recorderが `action` に書くものと同じです．方策の出力が `max_speed` を超えて削られたときは，削られたあとの値が入ります．過去の行動を読むモデルに使います．`N = 1` なら観測は今までと同じです．
- **`hold`**：行動のうち方策が動かさない要素（`<フォロワ>.<関節>`）です．方策がそこに何を返しても（NaNでも），フォロワが保持している目標に置き換えます．一部の関節だけで学習したモデルも，`[n]` か `[H, n]` を返せば済みます．ほかの要素は有限でなければならず，そうでなければエピソードを止めます．記録した `action` のその要素には，保持している目標が入ります（[データの形式](../data/format.md#by-configuration)）．
- **`options()`（任意）**：方策が自分でこれらを指定できます．YAMLより優先します．モデルを差し替えても設定を書き換えずに済みます．

    ```python
    def options(self) -> dict:
        return {"observation_history": 4, "hold": ["follower.torso_yaw"], "action_horizon": 8}
    ```

- `bind(spec)` には `spec.history`，`spec.hold`，`spec.units`（行動の各要素の単位），`spec.inference`（`sync` か `async`）も渡ります．
- **新しい観測だけを使う**：観測する入力やセンサーの最新の値が，recorderの `max_age_ms.<ノード>` より古いと，方策を止めます（controllerの行に `stale_observation`）．指令を送らず，フォロワは保持します．補間の途中でも止めます．値が新しくなると，方策を `reset()` して始め直します．`max_age_ms` は [recorderの設定](../reference/configuration/recorder.md#recorder) にあります．

## 記録から自分のモデルまで { #from-recording-to-model }

roboloomはモデルの形を決めません．方策には，記録と同じ観測，その履歴，実行した行動を渡し，関節の絶対目標を受け取ります．モデルごとに変わる処理は方策の側に書きます．

| 処理 | 書く場所 |
| --- | --- |
| モデルが動かす関節の選択 | 方策．ほかの関節には何を返してもよく（NaN），その関節を `hold` に挙げる |
| 正規化（学習データの統計） | 方策．統計はチェックポイントと一緒に保存する |
| 画像の縮小や切り出しなどの前処理 | 方策 |
| 行動の形（状態からの差分，一部の関節だけ） | 方策が `infer` の中で絶対目標に戻す |
| 観測の履歴，過去の行動 | roboloom（`observation_history`） |
| 記録より低い行動周期 | k行おきに学習し，`rate_hz` を `dataset_fps / k` にする |
| 制御周期への補間，速度の制限，安全の検査 | roboloom |

リポジトリの `examples/policies/chunk_mlp.py` は，これらを一通り行う小さなモデルです（関節状態だけを使い，CPUで数秒で学習できます）．記録したデータセットの `observation.state` と `action` の列を読んで学習し，統計・動かす関節・履歴の長さをチェックポイントに保存して，`options()` でroboloomに伝えます．

```bash
uv run python examples/policies/chunk_mlp.py train \
    --dataset .roboloom/rakuda2/datasets/rakuda2 --out outputs/chunk_mlp.pt \
    --history 4 --horizon 8 --stride 3 --exclude torso_yaw head_yaw head_pitch
PYTHONPATH=examples/policies uv run roboloom infer rakuda2 --seconds 20 \
    --policy chunk_mlp:load --policy-kwargs '{"checkpoint": "outputs/chunk_mlp.pt"}'
```

15 fpsの記録で `--stride 3` なら，方策の周期は5 Hzです．`nodes/policy.yaml` を `rate_hz: 5` にします．学習でデータセットを読むとき，表の列（`observation.state`，`action`，`action.valid`，`episode_index`，`index`）は `LeRobotDataset(...).hf_dataset` にあります．画像は `dataset[i]` で1行ずつ復号します．`action.valid` が0の行の扱いは [欠損の扱い](../data/format.md#missing-data) にあります．
