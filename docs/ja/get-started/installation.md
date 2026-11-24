# Installation

Python **3.12〜3.14** とuv，Gitを使います．roboloomは，自分のprojectの依存としてGitHubから追加します．以下のcommandは自分のproject rootで実行します．

## uvでinstall

新しくprojectを作る場合：

```bash
uv init --python '>=3.12,<3.15' my-robot
cd my-robot
uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.2.0
uv run roboloom --version
```

既存のprojectでは，そのrootで `uv add` から実行します．先に `pyproject.toml` の `project.requires-python` を `">=3.12,<3.15"` の範囲内に設定してください．Pythonの環境を選ぶだけでは，uvが解決するPythonの対応範囲は限定されません．

`record`・`viz`・`policy`・`train` を使うときは，自分の `pyproject.toml` に次も書きます（Python 3.14 では必須，3.12・3.13 では NumPy 2.3 以上を使うために必要）．LeRobot 0.7.0 は NumPy を `<2.3` に制限していますが（opencv-python-headless 4.12 から引き継いだ上限で，4.13 では外れています），NumPy 2.3 未満には Python 3.14 用の wheel がありません．uv の override は依存先のmetadataでは伝わらないため，roboloom の側では代わりに設定できません．LeRobot の方策の読み込み（`policy.lerobot`）と `lerobot-train` は，LeRobot の設定の解析に使う draccus が Python 3.14 に対応していないため，Python 3.12・3.13 で使います．自作の方策は 3.14 でも使えます．

```toml
[tool.uv]
override-dependencies = [
    "numpy>=2.0,<3; python_version < '3.14'",
    "numpy>=2.3.3,<3; python_version >= '3.14'",
]
```

基本のinstallには共通の実行環境（dora，YAML，NumPy，OpenCV，serial通信，UI）が入ります．robotごとのextrasを選び，記録，live表示，RealSense，DIGITは独立したextrasで追加します．以下は同じGit依存に対する構成例です．

| 構成 | command | 用途 |
| --- | --- | --- |
| 基本 | `uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.2.0` | 設定の読み込み，CLI，模擬device |
| Rakuda2 | `uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.2.0 --extra rakuda2` | followerとRakuda-mini leader用のDynamixel SDK |
| PiPER + Pika | `uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.2.0 --extra piper --extra pika` | PiPER SDK，IK，Pikaのtracker・手首camera（開発中・実機未検証） |
| 記録 | `uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.2.0 --extra record` | LeRobotDatasetへの保存，模擬収集 |
| Live viewer | `uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.2.0 --extra viz` | Rerunでのlive表示（`lerobot[viz]` により `rerun-sdk` と `foxglove-sdk` を導入，模擬のみ） |
| Rakuda2実機収集 | `uv add git+https://github.com/tetsugo02/roboloom.git --tag v0.2.0 --extra rakuda2 --extra record --extra hardware --extra digit` | Rakuda2，記録，RealSense（`hardware`），DIGIT（`digit`） |

Git sourceを登録した後は，package名でextrasを追加することもできます．zshなどのshellでは角括弧を引用符で囲みます．

```bash
uv add 'roboloom[rakuda2]'
uv add 'roboloom[piper,pika]'
uv add 'roboloom[piper,pika,record]'
uv add 'roboloom[viz]'
```

`rakuda2` は `dynamixel-sdk`，`piper` は `piper_sdk` と `pose_ik` 用のPinocchio（`pin`），`pika` は `pysurvive`，`viz` は `lerobot[viz]==0.7.0` を通じて `rerun-sdk` と `foxglove-sdk` を追加します（任意の [viewer](../reference/configuration/viewer.md) node が使います．viewer が無効な設定では Rerun は不要です）．OpenCVと `pyserial` は画像処理・camera取得やserial機器で共有する共通依存です．OpenCVは，`record` のLeRobotと同じGUIなしの `opencv-python-headless` を入れます．DIGITの `digit` extraもheadlessを使います（下記）．PiPER SDKなしでIKだけを使う `ik` extraも残しています．repositoryをcloneした中では，同じextrasを `uv sync --extra rakuda2` または `uv sync --extra piper --extra pika`（viewer を使う場合は `--extra viz`）で選びます．

`pysurvive` が必要なのは実機のPika Senseのtrackerの姿勢だけで，PiPERの関節制御，Pikaのserial通信・camera，模擬では使いません．`pika` extraはPika一式の依存を追加します．[PyPI](https://pypi.org/project/pysurvive/) にPython 3.12用のwheelとsource配布がないため，[libsurviveのfork](https://github.com/tetsugo02/libsurvive/tree/roboloom)がbuildしたwheel（[release](https://github.com/tetsugo02/libsurvive/releases)．CPython 3.12，Linux x86_64，libusb同梱）を使います．install時のbuildはなく，compilerやlibusbの開発用fileは要りません．forkが上流から変えたのはPythonのpackageだけで，上流が必須にしているGooey／wxPython（roboloomは使わないGUIの起動用）を任意のextra `pysurvive[gui]` にしています．Python 3.12以外，x86_64以外のLinux，ほかのOSでは `pika` extraにpysurviveは入りません．extraはOSの設定やtrackerのudev規則（`81-vive.rules`），CANの設定までは行いません．udev規則は管理者に導入してもらいます．

`hardware` extraはRealSenseと音声用のlibrary，`digit` extraはDIGITのdigit-interfaceを追加します．このガイドではRealSenseとDIGITを扱います．USB deviceへのaccess権，RealSenseのsystem側のdriver・USB 3接続は実機を接続する環境で確認してください．

DIGITの `digit` extraは，上流のdigit-interface 0.2.1（archive済み）ではなく，[digit-interfaceのfork](https://github.com/tetsugo02/digit-interface/tree/roboloom)がbuildしたwheel（[release](https://github.com/tetsugo02/digit-interface/releases)．Pythonのみ）を使います．上流はGUI付きの `opencv-python` を要求しますが，これはroboloomとLeRobotが使う `opencv-python-headless` と同じ `cv2` に入ります．両方が入ると読まれる版が定まらず，片方を消すと `cv2` が壊れます．forkが変えたのは依存の宣言だけで（`opencv-python-headless` に変更），codeは上流と同じです．GUIで表示する `Digit.show_view` はheadlessでは動きませんが，roboloomは使いません．

`uv add` は自分の `pyproject.toml` に依存とGit sourceを登録し，`uv.lock` に解決したcommitを記録します．両方をGitで管理し，別の環境では `uv sync --locked` で再現します．詳細は [uvのGit依存の説明](https://docs.astral.sh/uv/concepts/projects/dependencies/#git) を参照してください．

## 更新とversionの固定

新しいrelease tagへ切り替える場合（`<tag>` は [GitHub Releases](https://github.com/tetsugo02/roboloom/releases) のtag，例：`v0.2.0`）：

```bash
uv add git+https://github.com/tetsugo02/roboloom.git --tag <tag>
uv sync --locked
```

開発中の最新 commit を使う場合（既定branch追従・更新・commit SHA 固定）：

```bash
uv add git+https://github.com/tetsugo02/roboloom.git                      # main 追従
uv lock --upgrade-package roboloom && uv sync --locked                  # 追従先の最新へ更新
uv add git+https://github.com/tetsugo02/roboloom.git --extra record --rev <commit-sha>
```

各releaseのページには，build済み wheel（`.whl`）・source配布物（`.tar.gz`）および `SHA256SUMS.txt` を添付しています．wheel を直接使う場合はchecksumを照合してから追加します：

```bash
sha256sum -c SHA256SUMS.txt --ignore-missing
uv add ./roboloom-<version>-py3-none-any.whl
```

packageを更新しても，生成済みの `.roboloom/` の設定は書き換わりません．新しい版のtemplateに追いつかせるときは `roboloom init rakuda2 --update` を使います．projectにないfileを足し，コピーしたまま触っていないfileを置き換えます．編集したfileと測定値の入ったfileは変えず，templateだけにあるkeyとoptionを一覧にします（手で写します）．

## coding agentで使う

roboloomは [Agent Skill](https://agentskills.io)（`SKILL.md` と参照ページ）を同梱しています．Claude CodeやCodexなどのcoding agentに，自分のprojectからroboloomを使う方法（installとextras，`.roboloom/<robot>/`，`Session`，`roboloom.setup`，CLI，方策，依頼なしに実機を開かないといった安全上の規則）を伝えます．install済みの版のskillを自分のprojectにコピーします．

```bash
uv run roboloom skills install            # .agents/skills/roboloom（Codexなど）と .claude/skills/roboloom（Claude Code）
uv run roboloom skills install --agent claude
```

コピーしたdirectoryはprojectと一緒にGitで管理します．roboloomを更新したあとは，`uv run roboloom skills check` が内容の合わなくなったコピーを報告します（終了code 1）．`uv run roboloom skills install --force` で置き換えます．置き換えるのは `roboloom/` のskillのdirectoryだけで，ほかのskillには触れません．別のdirectoryを読むagentには，`uv run roboloom skills path` が表示するdirectoryをコピーします．[skills CLI](https://github.com/vercel-labs/skills) でGitHubから入れることもできます（既定のbranchの最新版で，lockした版と異なる場合があります）：`npx skills add tetsugo02/roboloom --skill roboloom`．

## deviceなしで確かめる

基本構成だけで，次を自分の `main.py` に保存して実行できます．`MockBus` を使い，datasetは保存しません．

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

`init` はinstall済みpackageのtemplateから，自分のproject内に `.roboloom/rakuda2/` を生成します．deviceを開きません．`SET_...` の値を埋めるまでは `validate` が設定不足を報告します．生成した設定を使う実機の手順は [Rakuda2：機体設定と読み取り確認](../tutorials/rakuda2/setup.md) に続きます．模擬例の値を実機の安全値として使わないでください．

roboloomのsource変更・test・docsのbuildは [Contribution](../contribution/index.md) を参照してください．repository直下の `examples/` や `scripts/` は，Git依存としてinstallしたpackageの利用fileには含まれません．
