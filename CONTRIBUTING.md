# Contributing to Regent

Thanks for taking the time. A sharper prompt, a new skill, a missing eval case, a
mandate that should have been narrower — all of these make the platform safer.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Where to start

| I want to… | Go to |
|---|---|
| Report an agent that did something it should not have | [Agent misbehaviour issue](https://github.com/FlorianMartins/regent/issues/new?template=agent_misbehaviour.yml) — with the run id and the ledger excerpt |
| Report a bug in the platform | [Bug report](https://github.com/FlorianMartins/regent/issues/new?template=bug_report.yml) |
| Propose a new agent | [New agent proposal](https://github.com/FlorianMartins/regent/issues/new?template=new_agent.yml) |
| Ask for a mandate to be widened or narrowed | [Mandate change request](https://github.com/FlorianMartins/regent/issues/new?template=mandate_change.yml) |
| Report a vulnerability **in Regent itself** | [Private advisory](https://github.com/FlorianMartins/regent/security/advisories/new) — never a public issue |

## Getting set up

```bash
git clone https://github.com/FlorianMartins/regent.git
cd regent
make install            # virtualenv + editable install with the dev and docs extras
make check              # every gate the pipeline runs
```

Optionally install the local guardrails so the same gates run before each commit:

```bash
pip install pre-commit && pre-commit install
```

No API key is needed for any of this: the test suite and the eval suite run against the
**replay provider**, which answers from recorded fixtures. Only `regent evals --live`
and a real `regent run --provider anthropic` talk to a model.

## The workflow

`main` is protected: it requires the **CI complete** check, refuses force pushes and
keeps a linear history. Work on a branch and open a pull request:

```bash
git switch -c feat/my-change
# … work, then …
make check
git push -u origin feat/my-change
gh pr create --fill
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):
`feat(agents): …`, `fix(gateway): …`, `sec(sandbox): …`, `docs: …`, `chore(deps): …`.
The release notes are generated from them (by `release-scribe`, naturally), so the
subject line is what users will read. A `Signed-off-by:` trailer (`git commit -s`) is
welcome but not required.

## The bar for a pull request

`make check` must be green. It runs exactly what the CI pipeline runs:

| Gate | Command | Rule |
|---|---|---|
| Lint & format | `make lint` | `ruff check`, `ruff format --check`, `actionlint` — no exception |
| Types | `make typecheck` | `mypy --strict` |
| Tests | `make test` | Every new behaviour has a test; coverage stays ≥ 80 % |
| SAST | `make sast` | `bandit` and `pip-audit` clean |
| Secrets | `make secrets` | `gitleaks` finds nothing |
| IaC | `make iac-scan` | CloudGuard-IaC accepts `infra/` and the `Dockerfile` |
| Policy | `make policy` | `regent policy-check` and the Conftest policies pass |
| Evals | `make evals` | Every eval case passes offline |
| Docs | `make docs` | `mkdocs build --strict` |

## Changing what an agent does

The platform treats prompts, skills and mandates as code. The rules:

### A prompt change (`regent/prompts/*.md`)

1. Bump `version` in the front-matter. The ledger records `name@version`, and an eval
   fixture is keyed by it — an unbumped change silently reuses the old fixtures.
2. Add or update an eval case under `evals/cases/` that shows the new behaviour. A
   prompt change without an eval case is not reviewable.
3. Run `make evals`. If you have a key, run `regent evals --live` too and paste the
   report in the PR.

### A skill change (`regent/skills/library/<name>/SKILL.md`)

1. Bump `version`. Skills are content-addressed; the hash lands in every run that
   loaded it.
2. If the skill declares `checks`, the agent that loads it must implement them in
   `checks()` — a declared check that no agent runs is a false promise.

### A mandate change (`policies/mandates/*.yaml`)

1. `regent policy-check` must pass — `L4_ACT`, wildcard tool lists and budgets above
   20 USD per run are refused.
2. Widening a mandate (higher autonomy, fewer approvals, higher `max_remote_class`)
   needs a reviewer from `CODEOWNERS`. Say in the PR what the agent could now do that it
   could not before, and what evidence supports the change (eval results, runs in
   `advisory` mode).
3. Prefer a scoped override to a change of the defaults.

### A new agent

1. Subclass `regent.agents.base.Agent`; implement `analyse`, `checks`, `act`; declare
   `highest_risk` honestly.
2. Ship a prompt (`regent/prompts/<name>.md`), a default mandate, at least two eval
   cases (one happy path, one where verification must reject), and tests.
3. Register it in `regent/bootstrap.py` and document it in `docs/03-agent-catalogue.md`.

## Releasing

Tag `vX.Y.Z` on `main`. The release workflow builds the wheel and the multi-arch image,
attaches the SBOM, signs the image with cosign (keyless) and publishes SLSA provenance.
`scripts/verify_release.sh vX.Y.Z` shows how a consumer checks all of it.
