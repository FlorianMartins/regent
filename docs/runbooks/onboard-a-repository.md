# Runbook — Onboard a repository

**When.** A team wants Regent agents on `acme/<repo>`.

## Steps

1. **Choose the topology**: CI job (add a workflow calling `regent run …`) or control plane (install the GitHub App on the repository; webhooks reach `POST /webhooks/github`).
2. **Add an override** at observe/advise level in `policies/mandates/` (one document per agent wanted):

    ```yaml
    - agent: pr-reviewer
      scopes: ["acme/<repo>"]
      autonomy: L1_ADVISE
      model_tier: balanced
      allowed_tools: ["github.get_pr", "github.get_pr_diff", "github.list_pr_files",
                      "github.create_review", "github.add_labels"]
      max_remote_class: CONFIDENTIAL      # or INTERNAL if diffs must not leave
      verification: required
      budget: { max_llm_calls: 4, max_usd: 1.0, max_duration_s: 600 }
    ```

3. Validate locally and open the PR (CODEOWNERS routes it to platform + security):

    ```bash
    regent policy-check
    regent mandates --agent pr-reviewer --repo acme/<repo>
    ```

4. **CI topology**: add to the repository's workflow:

    ```yaml
    - name: Regent review
      if: github.event_name == 'pull_request'
      run: regent run pr-reviewer --repo "$GITHUB_REPOSITORY" --payload "{\"number\": ${{ github.event.number }}}"
      env:
        ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        GITHUB_TOKEN: ${{ github.token }}
    ```

    with `permissions: { contents: read, pull-requests: write, issues: write }`.
5. **Dry-run first** (`--dry-run`) for a few PRs and read the ledger; then remove the flag.
6. Tell the team: the reviews are advisory, how to dismiss with a reason, that the agent never approves.
7. After two weeks, measure acceptance and rejection rates; propose the next autonomy rung per agent with the numbers.

## Verification

The first real run ends `succeeded`; the review appears; `regent_runs_total{agent="pr-reviewer",status="succeeded"}` increments; the ledger's `run.started.mandate.source` is the override file.

## Rollback

Remove the override (or set `kill_switch: true`) and merge; no other system holds state for the repository.
