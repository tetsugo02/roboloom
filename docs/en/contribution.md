# Contribution

## Development environment and checks

For normal use, follow `uv add git+https://github.com/tetsugo02/roboloom.git` in [Installation](quick-start/installation.md). The following is for developers changing roboloom itself or its docs. Use Python 3.12 and uv, clone the repository, and run commands from its root.

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

Check the checkout's mock dataflow with `uv run roboloom validate examples/mock/experiment.yaml` and `uv run roboloom run examples/mock/experiment.yaml`. Saving requires the `record` or `test` extra. `examples/` and `scripts/` are for the checkout; users of the Git dependency use their own configuration and Python scripts.

Do not include formatting changes unrelated to your change. Report mock tests, real-data checks, and hardware verification separately.

Package authors, keywords, and project URLs are managed in `project.authors`, `project.keywords`, and `project.urls` in `pyproject.toml`. The documentation author and repository link are configured through `site_author`, `repo_name`, and `repo_url` in `docs/base.yml`. Keep both files consistent when changing author information or published URLs.

## Update features and docs together

Update the affected pages in `docs/` in the same change that adds a feature or changes behavior. Update both Japanese (`docs/ja/`) and English (`docs/en/`) in that change, and keep page structure, headings, code examples, and link targets identical. Keep configuration, defaults, CLI, Python API, and limitations consistent with the implementation.

| Change | Pages to update |
| --- | --- |
| Installation or first-time operation | Quick start |
| Robots or supported combinations | The robot page under Robots and the robot's Quick start |
| Sensor configuration or formats | Sensors and the affected robot pages |
| Operator input or start conditions | Controllers and the affected robot pages |
| API, CLI, or configuration changes | Reference and related examples |

Put a new page at the same path in both languages and register it in the `nav` of `mkdocs.yml` (Japanese) and `mkdocs.en.yml` (English). When instructions are affected, also update the README and the README of the template that `roboloom init` distributes. If the existing code and the docs disagree, fix the docs to follow the code's conventions and list the disagreement in your change report.

Robot pages list the supported sensors and controllers and link to their chapters for detailed settings. The current guides cover Rakuda2, the leader, RealSense RGB, and DIGIT. Do not present design proposals or past investigation notes as implemented or hardware-verified behavior.

## Editing and previewing the docs

The docs use [Zensical's MkDocs compatibility](https://zensical.org/docs/compatibility/mkdocs/). Each language has its own config; shared settings live in `docs/base.yml`.

| Language | Markdown | Config | Output |
| --- | --- | --- | --- |
| Japanese | `docs/ja/` | `mkdocs.yml` | `site/ja/` |
| English | `docs/en/` | `mkdocs.en.yml` | `site/en/` |

```bash
uv run --group docs python scripts/docs.py build   # strict build of both languages
uv run --group docs python scripts/docs.py serve   # build both and serve at http://127.0.0.1:8000
uv run --group docs zensical serve                 # Japanese only, with live reload
uv run --group docs zensical serve -f mkdocs.en.yml  # English only, with live reload
```

The language switcher at the top right moves to the selected language's home page when both languages are built side by side under `site/`. When only one language is open with `zensical serve`, the other language is not available. `site/index.html` redirects to `ja/` or `en/` according to the browser language. Do not commit build output.

Fonts and colors are set in `docs/overrides/` (`main.html` and `assets/stylesheets/roboloom.css`).

`docs/ja/yam-safety-and-smoothness.md` is kept as a past investigation and design note and is excluded from the guide build.

## Publishing to GitHub Pages

`.github/workflows/docs.yml` builds both languages in strict mode and publishes the entire `site/` directory to GitHub Pages. The published URLs are [Japanese](https://tetsugo02.github.io/roboloom/ja/) and [English](https://tetsugo02.github.io/roboloom/en/). The root URL redirects according to the browser language.

- Push to `main`: changes to `docs/**`, `mkdocs*.yml`, `scripts/docs.py`, `pyproject.toml`, `uv.lock`, or the workflow itself trigger a build and deployment.
- Pull request targeting `main`: changes to the same files trigger build validation only.
- Actions → `Documentation` → `Run workflow`: starts a manual build. Deployment runs only when `main` is selected.

The workflow uses Python 3.12 and uv, installing only the locked documentation dependencies with `uv sync --locked --only-group docs`. It then runs `uv run --no-sync python scripts/docs.py build` and publishes the successful output. Robot and sensor dependencies and hardware connections are not required.

For the initial setup, set the repository's **Settings → Pages → Build and deployment → Source** to **GitHub Actions** ([GitHub setup instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-with-a-custom-github-actions-workflow)). Once the workflow reaches `main`, it publishes the site; the URL appears in the `github-pages` environment and the Actions deployment result. Failed builds are not deployed.
