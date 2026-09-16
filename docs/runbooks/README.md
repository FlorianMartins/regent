# Runbooks

!!! tip "In plain words"
    A runbook is the page you open when something happens and you need to act *now*, without thinking about design. Each one has the same shape: when to use it, what you will see, the exact commands, how to check it worked, and how to undo it.

| Runbook | Use when |
|---|---|
| [Kill switch](kill-switch.md) | An agent must stop everywhere, immediately |
| [Agent misbehaving](agent-misbehaving.md) | Bad comments, wrong re-runs, surprising PRs |
| [Budget exceeded](budget-exceeded.md) | Runs end `budget_exceeded`, or spend alerts fire |
| [Ledger verification](ledger-verification.md) | An audit asks for evidence, or tampering is suspected |
| [Rotate credentials](rotate-credentials.md) | A key or token may be exposed, or on schedule |
| [Approve a run](approve-a-run.md) | A run is `awaiting_approval` |
| [Onboard a repository](onboard-a-repository.md) | A team wants Regent on their repository |
| [Add an agent](add-an-agent.md) | A new workflow is needed |
| [Change a mandate](change-a-mandate.md) | Widen or narrow what an agent may do |

All commands assume the repository root as working directory and `regent` on the `PATH` (`pip install -e .`).
