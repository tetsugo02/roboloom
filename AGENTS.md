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
  - e.g. If you are Claude Code, you may use Codex as a subagent during the implementation step.

## Paused work

- Bilateral control (force feedback from the follower to the leader: `feedback:`, the effort estimators, the `bilateral` option, `docs/*/contribution/bilateral.md`) is paused as of 2026-11-03 until the user says to resume it.
  - Do not extend, fix, tune, or test it on hardware, and do not propose bilateral work or ask about it.
  - Do not delete the existing bilateral code, tests, or docs. When other changes touch them (renames, signature changes), keep them compiling and their tests passing, without adding features.
  - Still design new work so that bilateral control can be added later: keep a path for effort feedback from followers to inputs (one-follower controllers, follower effort signals, input-side current laws) instead of designing it out.
  - Uncommitted bilateral files in a user's `.roboloom/<robot>/` are the user's; leave them as they are.

# Documentation

- When adding a feature or changing existing behavior, update the affected pages in `docs/` in the same change. Keep configuration examples, CLI commands, Python API examples, defaults, and limitations consistent with the implementation. Update the README and robot templates' README when their instructions are affected.
- Build documentation with Zensical using MkDocs-compatible configs. See [https://zensical.org/docs/compatibility/mkdocs/](https://zensical.org/docs/compatibility/mkdocs/).
- Documentation is bilingual: Japanese in `docs/ja/` (`mkdocs.yml`) and English in `docs/en/` (`mkdocs.en.yml`); shared settings are in `docs/base.yml`. Update both languages in the same change, keeping the same page paths, headings, code examples, and link targets. Theme fonts and colors live in `docs/overrides/`.
- Organize documentation into Quick start, Robots, Sensors, Controllers, Reference, and Contribution. Add new pages to `nav` in both `mkdocs.yml` and `mkdocs.en.yml`.
- Each robot page must describe its supported sensors and controllers, including configuration combinations and limitations. Keep reusable sensor/controller details in their respective chapters and link them from the robot page.
- Quick start covers installation and a guide for each documented robot, from initial configuration through gravity compensation (where applicable) and teleoperation data collection.
- The current documented scope is Rakuda2, the leader controller, RealSense RGB, and DIGIT sensors. Do not present design proposals or unverified hardware behavior as supported features.
- After documentation changes, run `uv run --group docs python scripts/docs.py build` (strict build of both languages) and resolve documentation errors before finishing. Preview both languages with `uv run --group docs python scripts/docs.py serve`, or one language with live reload via `uv run --group docs zensical serve [-f mkdocs.en.yml]`.
