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

基本のインストールには共通の実行環境（dora，YAML，NumPy，シリアル通信，UI）が入ります．ロボットごとのextrasを選び，記録や共通のセンサーは独立したextrasで追加します．以下は同じGit依存に対する構成例です．

| 構成 | コマンド | 用途 |
| --- | --- | --- |
| 基本 | `uv add git+https://github.com/tetsugo02/roboloom.git` | 設定の読み込み，CLI，模擬デバイス |
| Rakuda2 | `uv add git+https://github.com/tetsugo02/roboloom.git --extra rakuda2` | followerとRakuda-mini leader用のDynamixel SDK |
| PiPER + Pika | `uv add git+https://github.com/tetsugo02/roboloom.git --extra piper --extra pika` | PiPER SDK，IK，Pikaのトラッカー・手首カメラ（開発中・実機未検証） |
| 記録 | `uv add git+https://github.com/tetsugo02/roboloom.git --extra record` | LeRobotDatasetへの保存，模擬収集 |
| Rakuda2実機収集 | `uv add git+https://github.com/tetsugo02/roboloom.git --extra rakuda2 --extra record --extra hardware` | Rakuda2，記録，RealSense・DIGITのSDK |

Gitソースを登録した後は，パッケージ名でextrasを追加することもできます．zshなどのシェルでは角括弧を引用符で囲みます．

```bash
uv add 'roboloom[rakuda2]'
uv add 'roboloom[piper,pika]'
uv add 'roboloom[piper,pika,record]'
```

`rakuda2` は `dynamixel-sdk`，`piper` は `piper_sdk` と `pose_ik` 用のPinocchio（`pin`），`pika` は `pysurvive` と手首カメラ用のOpenCVを追加します．`pyserial` はDynamixelとPikaの両方が使うため共通に残します．PiPER SDKなしでIKだけを使う `ik` extraも残しています．リポジトリをcloneした中では，同じextrasを `uv sync --extra rakuda2` または `uv sync --extra piper --extra pika` で選びます．

`pysurvive` が必要なのは実機のPika Senseのトラッカーの姿勢だけで，PiPERの関節制御，Pikaのシリアル通信・カメラ，模擬では使いません．`pika` extraはPika一式の依存を追加します．[PyPI](https://pypi.org/project/pysurvive/) にPython 3.12用のwheelとソース配布がないため，[libsurviveのfork](https://github.com/tetsugo02/libsurvive/tree/roboloom)がビルドしたwheel（[リリース](https://github.com/tetsugo02/libsurvive/releases)．CPython 3.12，Linux x86_64，libusb同梱）を使います．インストール時のビルドはなく，コンパイラやlibusbの開発用ファイルは要りません．forkが上流から変えたのはPythonのパッケージだけで，上流が必須にしているGooey／wxPython（roboloomは使わないGUIの起動用）を任意のextra `pysurvive[gui]` にしています．x86_64以外のLinuxやほかのOSでは `pika` extraにpysurviveは入りません．extraはOSの設定やトラッカーのudev規則（`81-vive.rules`），CANの設定までは行いません．udev規則は管理者に導入してもらいます．

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

## コーディングエージェントで使う

roboloomは [Agent Skill](https://agentskills.io)（`SKILL.md` と参照ページ）を同梱しています．Claude CodeやCodexなどのコーディングエージェントに，自分のプロジェクトからroboloomを使う方法（インストールとextras，`.roboloom/<robot>/`，`Session`，`roboloom.setup`，CLI，方策，依頼なしに実機を開かないといった安全上の規則）を伝えます．インストール済みの版のスキルを自分のプロジェクトにコピーします．

```bash
uv run roboloom skills install            # .agents/skills/roboloom（Codexなど）と .claude/skills/roboloom（Claude Code）
uv run roboloom skills install --agent claude
```

コピーしたディレクトリはプロジェクトと一緒にGitで管理します．roboloomを更新したあとは，`uv run roboloom skills check` が内容の合わなくなったコピーを報告します（終了コード1）．`uv run roboloom skills install --force` で置き換えます．置き換えるのは `roboloom/` のスキルのディレクトリだけで，ほかのスキルには触れません．別のディレクトリを読むエージェントには，`uv run roboloom skills path` が表示するディレクトリをコピーします．[skills CLI](https://github.com/vercel-labs/skills) でGitHubから入れることもできます（既定のブランチの最新版で，lockした版と異なる場合があります）：`npx skills add tetsugo02/roboloom --skill roboloom`．

## デバイスなしで確かめる

基本構成だけで，次を自分の `main.py` に保存して実行できます．`MockBus` を使い，データセットは保存しません．

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
) as session:
    session.start_inference()
    print(session.step())
    session.stop_inference()
```

```bash
uv run python main.py
uv run roboloom init rakuda2
```

`init` はインストール済みパッケージのテンプレートから，自分のプロジェクト内に `.roboloom/rakuda2/` を生成します．デバイスを開きません．`SET_...` の値を埋めるまでは `validate` が設定不足を報告します．生成した設定を使う実機の手順は [Rakuda2 Quick start](rakuda2.md) に続きます．模擬例の値を実機の安全値として使わないでください．

roboloomのソース変更・テスト・docsのビルドは [Contribution](../contribution.md) を参照してください．リポジトリ直下の `examples/` や `scripts/` は，Git依存としてインストールしたパッケージの利用ファイルには含まれません．
