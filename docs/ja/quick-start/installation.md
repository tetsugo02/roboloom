# Installation

Python **3.12** とuv，Gitを使います．roboloomは，自分のプロジェクトの依存としてGitHubから追加します．以下のコマンドは自分のプロジェクトルートで実行します．

## uvでインストール

新しくプロジェクトを作る場合：

```bash
uv init --python '>=3.12,<3.13' my-robot
cd my-robot
uv add git+https://github.com/tetsugo02/roboloom.git
uv run roboloom --help
```

既存のプロジェクトでは，そのルートで `uv add` から実行します．先に `pyproject.toml` の `project.requires-python` を `">=3.12,<3.13"` に設定してください．Python 3.12の環境を選ぶだけでは，uvが解決するPythonの対応範囲は限定されません．

用途に応じてextrasを追加します．以下は同じ依存に対する構成例です．

| 構成 | コマンド | 用途 |
| --- | --- | --- |
| 基本 | `uv add git+https://github.com/tetsugo02/roboloom.git` | 設定の読み込み，CLI，Dynamixelドライバ |
| 記録 | `uv add git+https://github.com/tetsugo02/roboloom.git --extra record` | LeRobotDatasetへの保存，模擬収集 |
| 実機収集 | `uv add git+https://github.com/tetsugo02/roboloom.git --extra record --extra hardware` | 記録に加えRealSense・DIGITのSDK |

`hardware` extraには音声用ライブラリも含まれますが，このガイドではRealSenseとDIGITを扱います．USBデバイスへのアクセス権，RealSenseのシステム側のドライバ・USB 3接続は実機を接続する環境で確認してください．

`uv add` は自分の `pyproject.toml` に依存とGitソースを登録し，`uv.lock` に解決したcommitを記録します．両方をGitで管理し，別の環境では `uv sync --locked` で再現します．詳細は [uvのGit依存の説明](https://docs.astral.sh/uv/concepts/projects/dependencies/#git) を参照してください．

## 更新とcommitの固定

既定ブランチの新しいcommitへ更新する場合：

```bash
uv lock --upgrade-package roboloom
uv sync --locked
```

特定のcommitを使う場合は，`<commit-sha>` を実際のcommit SHAへ置き換えます．記録用extrasを使う例です．

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --extra record --rev <commit-sha>
```

パッケージを更新しても，生成済みの `.roboloom/` の設定は書き換わりません．

## デバイスなしで確かめる

基本構成だけで，次を自分の `main.py` に保存して実行できます．`MockBus` を使い，データセットは保存しません．

```python
from roboloom import Experiment
from roboloom.drivers.mock import MockBus

with Experiment.from_components(
    robot_id="my-mock",
    robot=MockBus(dimension=2),
    joint_names=["j1", "j2"],
    limits=[
        {"name": "j1", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
        {"name": "j2", "min": 0, "max": 4095, "max_speed": 3000, "max_jump": 400},
    ],
    controller=lambda obs: [2048, 2048],
) as experiment:
    experiment.start_inference()
    print(experiment.step())
    experiment.stop_inference()
```

```bash
uv run python main.py
uv run roboloom init rakuda2
```

`init` はインストール済みパッケージのテンプレートから，自分のプロジェクト内に `.roboloom/rakuda2/` を生成します．デバイスを開きません．`SET_...` の値を埋めるまでは `validate` が設定不足を報告します．生成した設定を使う実機の手順は [Rakuda2 Quick start](rakuda2.md) に続きます．模擬例の値を実機の安全値として使わないでください．

roboloomのソース変更・テスト・docsのビルドは [Contribution](../contribution.md) を参照してください．リポジトリ直下の `examples/` や `scripts/` は，Git依存としてインストールしたパッケージの利用ファイルには含まれません．
