# Checks after edits

- After editing files in this repository, run `ruff check .` and `mypy src` from the repository root.
- Resolve errors caused by the edit before finishing. Report any existing errors or checks that could not run; do not claim those checks passed.
- Use `ruff format .` to fix formatting issues.

# Implementation

## Overall

- When a repository's documentation and its existing code disagree, follow the conventions used in the existing code, and in your final reply point out each inconsistency you found between the documentation and the code.
- Design and build the system to easily accommodate future additions of new robots, controller arms, or control systems such as gello.
- Implementations must not adversely affect other robots, leaders, or controllers.

## Subagent

- When using subagents, you may use another coding agent as a subagent.
  - e.g. A coding agent may delegate an implementation step to another coding agent.

## Paused work

- Bilateral control (force feedback from the follower to the leader: `feedback:`, the effort estimators, the `bilateral` option, `docs/*/contribution/bilateral.md`) is paused as of 2026-11-03 until the user says to resume it.
  - Do not extend, fix, tune, or test it on hardware, and do not propose bilateral work or ask about it.
  - Do not delete the existing bilateral code, tests, or docs. When other changes touch them (renames, signature changes), keep them compiling and their tests passing, without adding features.
  - Still design new work so that bilateral control can be added later: keep a path for effort feedback from followers to inputs (one-follower controllers, follower effort signals, input-side current laws) instead of designing it out.
  - Uncommitted bilateral files in a user's `.roboloom/<robot>/` are the user's; leave them as they are.

# Documentation

- When adding a feature or changing existing behavior, update the affected pages in `docs/` in the same change. Keep configuration examples, CLI commands, Python API examples, defaults, and limitations consistent with the implementation. Update the README and robot templates' README when their instructions are affected.
- The Agent Skill in `src/roboloom/agent_skills/roboloom/` (`SKILL.md` and `references/`) tells coding agents in downstream projects how to use roboloom. When a change affects the public Python API, CLI, configuration keys, extras, supported devices, or feature status, update the skill in the same change; `tests/test_agent_skills.py` checks its links, imports and CLI commands. `skills/roboloom` at the repository root is a symlink to it (for `npx skills add`); keep the skill in the package.
- Build documentation with Zensical using MkDocs-compatible configs. See [https://zensical.org/docs/compatibility/mkdocs/](https://zensical.org/docs/compatibility/mkdocs/).
- Documentation is bilingual: Japanese in `docs/ja/` (`mkdocs.yml`) and English in `docs/en/` (`mkdocs.en.yml`); shared settings are in `docs/base.yml`. Update both languages in the same change, keeping the same page paths, headings, code examples, and link targets. Theme fonts and colors live in `docs/overrides/`.
- Japanese notation: in `docs/ja/`, `README.ja.md`, and the Japanese `nav` titles, write English-derived technical terms in English, not katakana (follower, sensor, gripper, node, dataset, episode, checkpoint, metadata, coding agent, command, option, key, tab, focus, ...), matching the spelling of the code identifier or API term (`follower` in prose, `Follower` only for the class). Everyday loanwords stay katakana (ページ, ボタン, リスト, コピー, チェック, メモ, ガイド, ホーム, カード, サイズ, ゼロ, オン); kanji terms (方策, 入力, 記録, 校正) and product names (PiPER, Pika, Rakuda2, LeRobot) are unchanged. Keep code examples and placeholders identical to the English pages (`<follower>`, `{name: path}`). Do not introduce new katakana technical terms or long-vowel variants (センサ/センサー). The convention with examples is in `docs/*/contribution/index.md` ("Japanese notation").
- Organize documentation into Get started, Tutorials, Robots, Controllers, Sensors, Policy, Data, Reference, Explanation, and Contribution. Add new pages to `nav` in both `mkdocs.yml` and `mkdocs.en.yml`. When a page moves or is removed, add an entry to `redirect_maps` in `docs/base.yml` so published links keep working.
- Keep the page kinds apart: Tutorials are step-by-step procedures (listed as cards in the gallery `tutorials/index.md`); Reference describes only, as tables (configuration keys with type, default, unit; one entry per CLI command; the Python API generated from docstrings with mkdocstrings); Explanation holds the background and reasoning. Do not put long prose in Reference.
- Each robot has its own directory under `robots/<robot>/` with an overview and pages for the controllers and sensors it supports, including configuration combinations and limitations. Keep reusable controller/sensor details in their chapters and link them from the robot pages. Update `get-started/support-matrix.md` when support changes.
- Document unverified features too, but label them. Every page or table row for a feature that is not hardware-verified carries one of the status labels defined in `reference/status-labels.md` (hardware-verified, mock only, in development, design only); that page is the single source of truth for each feature's status. Never present design proposals or unverified hardware behavior as hardware-verified.
- Prefer diagrams (mermaid) over long explanations of flows, and short steps and tables over paragraphs.
- After documentation changes, run `uv run --group docs python scripts/docs.py build` (strict build of both languages) and resolve documentation errors before finishing. Preview both languages with `uv run --group docs python scripts/docs.py serve`, or one language with live reload via `uv run --group docs zensical serve [-f mkdocs.en.yml]`.
