# Contribution

## 開発環境とチェック

通常利用は [インストール](quick-start/installation.md) の `uv add git+https://github.com/tetsugo02/roboloom.git` を使います．以下はroboloom本体やdocsを変更する開発者向けです．Python 3.12とuvを使い，リポジトリをcloneしてそのルートで実行します．

```bash
git clone https://github.com/tetsugo02/roboloom.git
cd roboloom
uv sync --extra test --group dev --group docs
uv run ruff format .
uv run ruff check .
uv run mypy src
uv run pyright
uv run pytest
uv run --group docs python scripts/docs.py build
```

checkout内の模擬dataflowは `uv run roboloom validate examples/mock/experiment.yaml` と `uv run roboloom run examples/mock/experiment.yaml` で確認できます．保存には `record` または `test` extraが必要です．`examples/` と `scripts/` はcheckout用で，Git依存の利用者は自身の設定やPythonスクリプトを使います．

変更と無関係な整形差分は含めないでください．模擬試験・実データ・実機検証は区別して報告します．

パッケージの著者・キーワード・プロジェクトURLは `pyproject.toml` の `project.authors`，`project.keywords`，`project.urls` で管理します．docsの著者とリポジトリリンクは `docs/base.yml` の `site_author`，`repo_name`，`repo_url` に設定します．著者情報や公開先を変更するときは，両方を揃えて更新してください．

## 機能とdocsを一緒に更新する

機能追加・動作変更と同じ変更で，影響する `docs/` を更新します．日本語（`docs/ja/`）と英語（`docs/en/`）の両方を同じ変更で更新し，ページ構成・見出し・コード例・リンク先を揃えます．設定・既定値・CLI・Python API・制限事項と，実際の実装を揃えます．

| 変更 | 更新するページ |
| --- | --- |
| インストールや初回操作 | Quick start |
| 機体や対応する組み合わせ | Robotsの機体ページと機体別Quick start |
| センサーの設定・形式 | Sensorsと対応機体ページ |
| 操作入力・開始条件 | Controllersと対応機体ページ |
| API・CLI・設定の変更 | Referenceと関連するサンプル |

新しいページは両言語の同じパスに置き，`mkdocs.yml`（日本語）と `mkdocs.en.yml`（英語）の `nav` に登録します．READMEと `roboloom init` が配布するテンプレートのREADMEも，手順に影響があれば同時に更新します．現行コードとドキュメントが食い違っていた場合は，コードの規約を基準に修正し，食い違いを変更報告に記載します．

機体ページには対応センサーとcontrollerを記載し，詳しい設定をそれぞれの章へリンクします．現在のガイドの対象はRakuda2，leader，RealSense RGB，DIGITです．設計案や過去の調査メモを，実装済み・実機検証済みの仕様として案内しないでください．

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

`docs/ja/yam-safety-and-smoothness.md` は過去の調査・設計メモとして残し，利用ガイドのビルド対象から除外しています．

## GitHub Pagesへの公開

`.github/workflows/docs.yml` が両言語をstrictでビルドし，`site/` 全体をGitHub Pagesへ公開します．公開先は [日本語](https://tetsugo02.github.io/roboloom/ja/) と [English](https://tetsugo02.github.io/roboloom/en/) です．ルートURLではブラウザの言語に応じて転送します．

- `main` へのpush：`docs/**`，`mkdocs*.yml`，`scripts/docs.py`，`pyproject.toml`，`uv.lock`，workflow自身の変更でビルド・公開します．
- `main` 向けのpull request：同じファイル群の変更でビルドだけを検証します．
- Actionsの `Documentation` → `Run workflow`：手動ビルドできます．公開するのは `main` を選んだ場合だけです．

Python 3.12とuvを使い，`uv sync --locked --only-group docs` でlock済みのdocs依存だけをインストールします．続いて `uv run --no-sync python scripts/docs.py build` を実行し，成功した成果物を公開します．ロボット・センサー用の依存や実機接続は不要です．

初回はリポジトリの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** に設定します（[GitHubの設定手順](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-with-a-custom-github-actions-workflow)）．workflowを `main` に反映すると公開され，URLは `github-pages` environmentとActionsのデプロイ結果に表示されます．ビルドが失敗した場合は公開しません．
