# Contribution

## 開発環境とチェック

通常利用は [インストール](../get-started/installation.md) の `uv add git+https://github.com/tetsugo02/roboloom.git` を使います．以下はroboloom本体やdocsを変更する開発者向けです．Python 3.12とuvを使い，リポジトリをcloneしてそのルートで実行します．

```bash
git clone https://github.com/tetsugo02/roboloom.git
cd roboloom
uv sync --extra rakuda2 --extra test --group dev --group docs
uv run ruff format .
uv run ruff check .
uv run mypy src
uv run pyright
uv run pytest
uv run --group docs python scripts/docs.py build
```

Pull Requestと `main` へのpushでは，GitHub Actions（`.github/workflows/test.yml`）が `ruff check .`・`mypy src`・`pytest` を実行します．dataflowのテストはmockデバイスでdoraのプロセスを起動するもので，実機は使いません．

checkout内の模擬dataflowは `uv run roboloom validate examples/mock/config.yaml` と `uv run roboloom run examples/mock/config.yaml` で確認できます．保存には `record` または `test` extraが必要です．`examples/` と `scripts/` はcheckout用で，Git依存の利用者は自身の設定やPythonスクリプトを使います．

模擬の設定の保存先は `datasets/rakuda-mock` です（オプション `bilateral` では `datasets/rakuda-mock-bilateral`）．記録の形（featureの名前や形）を変えた後は，古いデータへ追記できません．古いデータは移すか，`output` を変えてください．画面確認のために既存データを削除しないでください．

変更と無関係な整形差分は含めないでください．模擬試験・実データ・実機検証は区別して報告します．

パッケージの著者・キーワード・プロジェクトURLは `pyproject.toml` の `project.authors`，`project.keywords`，`project.urls` で管理します．docsの著者とリポジトリリンクは `docs/base.yml` の `site_author`，`repo_name`，`repo_url` に設定します．著者情報や公開先を変更するときは，両方を揃えて更新してください．

## 機能とdocsを一緒に更新する

機能追加・動作変更と同じ変更で，影響する `docs/` を更新します．日本語（`docs/ja/`）と英語（`docs/en/`）の両方を同じ変更で更新し，ページ構成・見出し・コード例・リンク先を揃えます．設定・既定値・CLI・Python API・制限事項と，実際の実装を揃えます．

| 変更 | 更新するページ |
| --- | --- |
| インストールや初回操作 | Get started と関係するチュートリアル |
| 機体や対応する組み合わせ | `robots/<機体>/` のページ，対応表（`get-started/support-matrix.md`），機体のチュートリアル |
| センサーの設定・形式 | Sensors と対応機体の `sensors.md` |
| 操作入力・開始条件 | Controllers と対応機体の `controllers.md` |
| 方策・推論 | Policy |
| 記録の形式・データセット | Data と `reference/dataset-features.md` |
| API・CLI・設定の変更 | Reference（表の形）と関連するサンプル |
| 機能の検証の状態 | `reference/status-labels.md` と，そのラベルを付けたページ |
| 公開API・CLI・設定・対応機器の変更 | `src/roboloom/agent_skills/roboloom/` のスキル（`SKILL.md` と `references/`） |

新しいページは両言語の同じパスに置き，`mkdocs.yml`（日本語）と `mkdocs.en.yml`（英語）の `nav` に登録します．READMEと `roboloom init` が配布するテンプレートのREADMEも，手順に影響があれば同時に更新します．現行コードとドキュメントが食い違っていた場合は，コードの規約を基準に修正し，食い違いを変更報告に記載します．

ページを移したり消したりしたら，`docs/base.yml` の `redirect_maps` に旧パスを登録します．Tutorials は手順，Reference は表による記述だけ，Explanation は背景と理由，と書き分けます．実機で確かめていない機能も載せますが，ページの冒頭か表の行に [状態ラベル](../reference/status-labels.md) を付けます．設計案や過去の調査メモを，実機検証済みの仕様として案内しないでください．

## docsの編集とプレビュー

[ZensicalのMkDocs互換機能](https://zensical.org/docs/compatibility/mkdocs/) を使います．言語ごとに設定を分け，共通設定は `docs/base.yml` に置きます．

| 言語 | Markdown | 設定 | 出力先 |
| --- | --- | --- | --- |
| 日本語 | `docs/ja/` | `mkdocs.yml` | `site/ja/` |
| 英語 | `docs/en/` | `mkdocs.en.yml` | `site/en/` |

```bash
uv run --group docs python scripts/docs.py build   # 両言語をstrictでビルド
uv run --group docs python scripts/docs.py serve   # 両言語をビルドして http://127.0.0.1:8000 で表示
uv run --group docs zensical serve                 # 日本語だけをライブリロードで表示
uv run --group docs zensical serve -f mkdocs.en.yml  # 英語だけをライブリロードで表示
```

右上の言語切り替えは，`site/` に両言語が並んでいるときに選んだ言語のホームへ移ります．片方の言語だけを `zensical serve` で開いているときは，切り替え先が表示されません．`site/index.html` はブラウザの言語に応じて `ja/` か `en/` へ転送します．生成物はGitへ追加しません．

フォントと配色は `docs/overrides/`（`main.html` と `assets/stylesheets/roboloom.css`）で調整しています．

`docs/ja/yam-safety-and-smoothness.md` は過去の調査・設計メモとして残し，利用ガイドのビルド対象から除外しています．未実装の機能の設計案は，[バイラテラル制御の設計](bilateral.md) のように，冒頭で未実装と明示した上でContributionに置きます．

## GitHub Pagesへの公開

`.github/workflows/docs.yml` が両言語をstrictでビルドし，`site/` 全体をGitHub Pagesへ公開します．公開先は [日本語](https://tetsugo02.github.io/roboloom/ja/) と [English](https://tetsugo02.github.io/roboloom/en/) です．ルートURLではブラウザの言語に応じて転送します．

- `main` へのpush：`docs/**`，`src/**`（Python APIのページはdocstringから作る），`mkdocs*.yml`，`scripts/docs.py`，`pyproject.toml`，`uv.lock`，workflow自身の変更でビルド・公開します．
- `main` 向けのpull request：同じファイル群の変更でビルドだけを検証します．
- Actionsの `Documentation` → `Run workflow`：手動ビルドできます．公開するのは `main` を選んだ場合だけです．

Python 3.12とuvを使い，`uv sync --locked --only-group docs` でlock済みのdocs依存だけをインストールします．続いて `uv run --no-sync python scripts/docs.py build` を実行し，成功した成果物を公開します．ロボット・センサー用の依存や実機接続は不要です．

初回はリポジトリの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** に設定します（[GitHubの設定手順](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-with-a-custom-github-actions-workflow)）．workflowを `main` に反映すると公開され，URLは `github-pages` environmentとActionsのデプロイ結果に表示されます．ビルドが失敗した場合は公開しません．

## 新しいフォロワを足す { #adding-a-follower }

フォロワの機種（`Follower` のサブクラス）は，安全に関わる性質 `safety_traits`（設定で変わる場合は `declared_traits()`）を必ず宣言します．宣言のないクラスはimportの時点でTypeErrorになります．値の意味は [設定](../reference/configuration/index.md) の「脱力したときと放置したときの性質」にあります．確かめていない性質は `unknown` にします．制御則で動く入力機器（`JointInput` のサブクラス）も `safety_traits` を宣言します．姿勢で動かす（`pose_ik`）腕は，`kinematics()` でURDFの鎖（`KinematicSpec`：URDF，base，tip，関節）を返します．

### roboloomを変えずに，自分のパッケージから足す { #own-types }

roboloomに入っていないロボット，入力機器，センサー，controller，estimatorは，自分のコードに置いたまま使えます．

- ノードのYAMLの `type` に，クラスを `module:Class` で書きます．importは，インストール済みのパッケージ，次に機体のディレクトリ（`.roboloom/<robot>/`）の順に探します．
- ノードは1つずつ別のプロセスで動き，それぞれが設定を読み直します．そのため，クラスは参照（`module:Class`）で指定します．1つのプロセスの中でレジストリに登録しても，ほかのノードからは見えません．
- クラスは，その役割の基底クラス（`roboloom.robots.base.Follower`，`roboloom.inputs.base.JointInput` と `PoseInput`，`roboloom.core.source.Source`，`roboloom.controllers.base.Controller`，`roboloom.estimators.base.Estimator`）を継承します．継承していないクラスは，読み込みのときに拒否します．
- クラスが読むYAMLのキーを `keys` に書くと，それ以外のキーは読み込みのときに拒否されます（綴りの誤りが黙って無視されません）．`keys` を書かないクラスは検査しません．

    ```python
    from roboloom.robots.base import FOLLOWER_KEYS, Follower

    class MyArm(Follower):
        keys = (*FOLLOWER_KEYS, "address")
    ```

- フォロワに要るものは，関節名と単位，`safety_traits`，`open_bus(mock)` が返すバス（`read_positions`，`write_positions`，`enable_torque`，`close`．`roboloom.drivers.base.JointBus`）です．`mock` がTrueのときは模擬のバスを返します．
- シミュレーターは，同じフォロワのクラスの後ろに別のバスを置きます．実機と同じ単位で話せば，データセットと方策を共有できます．
- `control:` の制御則（`roboloom.control`）はDynamixel系のバス（カウント，mA，Operating Mode）を前提にしています．自前の位置制御を持つロボットでは使いません．

テンプレートも自分の側に置けます．`config.yaml`，ノードのYAML，クラスのモジュール，`mock.yaml` を1つのディレクトリ（またはパッケージの `template/`）にまとめ，次のようにプロジェクトを作ります．

```bash
uv run roboloom init lab_arm --template my_lab.robots.arm   # パッケージの template/
uv run roboloom init lab_arm --template path/to/template    # ディレクトリ
uv run roboloom init lab_arm --update                       # テンプレートが変わったあと
```

リポジトリの `examples/own_robot/` が，動く最小の見本です（フォロワのクラス `my_arm.py`，方策で保持するだけの構成，模擬のバス）．

```bash
uv run roboloom init lab_arm --template examples/own_robot
uv run roboloom infer lab_arm --mock --seconds 5 --plain
```

## 操作画面の拡張

新しい機種の機器アクセスはBackendへ置き，標準の状態項目を通知します．任意の機種別・役割別Presenterの明示登録，Backend契約，Pilot/MockBusでの検証は [操作画面](../reference/operator-screen.md) を参照してください．
