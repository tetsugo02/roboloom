# Installation

Python **3.12** を使います．以下はリポジトリを取得し，そのルートディレクトリで実行する手順です．`robopy` は実行時依存ではありません．

## uvでインストール

```bash
git clone https://github.com/tetsugo02/roboloom.git
cd roboloom
uv sync --extra record --extra hardware
uv run roboloom --help
```

| 構成 | コマンド | 用途 |
| --- | --- | --- |
| 基本 | `uv sync` | 設定の読み込み，CLI，Dynamixelドライバ |
| 記録 | `uv sync --extra record` | LeRobotDatasetへの保存，模擬収集 |
| 実機収集 | `uv sync --extra record --extra hardware` | 記録に加えRealSense・DIGITのSDK |
| ドキュメント | `uv sync --group docs` | Zensicalのプレビューとビルド |

`hardware` extraには音声用ライブラリも含まれますが，このガイドではRealSenseとDIGITを扱います．USBデバイスへのアクセス権，RealSenseのシステム側のドライバ・USB 3接続は実機を接続する環境で確認してください．

## pipでインストール

同じcheckoutを使う場合は，Python 3.12の仮想環境にeditable installできます．

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[record,hardware]'
roboloom --help
```

以降のガイドは `uv run roboloom ...` と表記します．pip環境では，有効化した仮想環境の `roboloom ...` に読み替えてください．

## デバイスなしで確かめる

`record` extraを入れた環境で，模擬設定を検証できます．`validate` は実機を開きません．

```bash
uv run roboloom validate examples/mock/experiment.yaml
uv run roboloom run examples/mock/experiment.yaml
```

操作画面で `start test` → `stop` → `save` → `quit` と入力すると模擬エピソードを保存します．保存先は `examples/mock/experiment.yaml` の `output` で確認できます．

実機の手順は [Rakuda2 Quick start](rakuda2.md) に続きます．
