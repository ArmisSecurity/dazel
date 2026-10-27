# Contributing to dazel

Thanks for helping improve dazel. Bug reports, fixes, documentation and feature ideas are all
welcome.

## Before you start

- **Questions and ideas** go to [Discussions](https://github.com/ArmisSecurity/dazel/discussions).
- **Bugs** go to [Issues](https://github.com/ArmisSecurity/dazel/issues/new/choose). Include your
  `.dazelrc` (with secrets removed) and the output of `dazel --dazel-version`.
- **Security problems** go through [private reporting](SECURITY.md), never a public issue.
- **Larger changes**: please open an issue or discussion first, so we can agree on the approach before
  you invest in it.

## Development setup

You need [uv](https://docs.astral.sh/uv/), [prek](https://github.com/j178/prek) and, for the
integration tests, a running Docker daemon.

```bash
git clone https://github.com/ArmisSecurity/dazel.git
cd dazel
uv sync            # creates .venv with dazel (editable) and the dev tools
prek install       # pre-commit and commit-msg hooks
```

| Task | Command |
|---|---|
| Unit tests with coverage | `uv run pytest` |
| Docker lifecycle tests | `uv run pytest -m integration --no-cov` |
| All lint, format and type checks | `prek run --all-files` |
| Build the image | `docker build -t dazel .` |

## Making a change

- **Tests.** Write a failing test first, then the fix. Tests use pytest and are parameterized where
  cases differ only in data. They must fail without your change. Unit tests never call Docker: they
  use the recording `FakeExecutor` in `tests/fake_support.py`. Anything that needs a real daemon goes in
  `tests/test_container_lifecycle_integration.py`, behind the `integration` marker.
- **Types and style.** The code is fully typed and checked with pyrefly. ruff enforces formatting and
  linting (`select = ["ALL"]`). Public functions have docstrings; private ones only when the reason
  isn't obvious.
- **No shell.** dazel builds argv lists and runs them through `dazel.executor`, the only subprocess
  boundary. Keep it that way.
- **Configuration.** A new `DAZEL_*` key needs a `Config` field, parsing in `config.resolve`, tests, and
  a row in the README's configuration tables.
- **Docs.** Update the README for user-visible behaviour and add an entry under `Unreleased` in
  [CHANGELOG.md](CHANGELOG.md).

## Commits and pull requests

Commit messages and PR titles follow [Conventional Commits](https://www.conventionalcommits.org), e.g.
`fix: keep the run file when the container fails to start`. The
[gitfluff](https://github.com/Goldziher/gitfluff) `commit-msg` hook checks them locally, and CI checks
the PR title. Pull requests are squash merged, so the PR title becomes the commit on `master`.

Keep pull requests focused on one change. CI runs the hooks, the unit tests on Python 3.11 to 3.14,
the Docker integration tests, a package build and a multi-arch image build. All of them must pass.

## Releasing

Maintainers release in four steps:

1. Bump `version` in `pyproject.toml`.
2. Move the `Unreleased` changelog entries under the new version.
3. Merge.
4. Push a `v<version>` tag.

The release workflow then publishes to PyPI (trusted publishing with attestations) and to
`ghcr.io/armissecurity/dazel`, and it creates the GitHub release.

## Code of conduct

Everyone taking part in this project is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).
