"""``regent`` — run agents, inspect mandates, verify the ledger, run evals."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from regent import __version__
from regent.core.ledger import Ledger, LedgerError
from regent.core.models import RunStatus, Trigger
from regent.core.policy import MandateStore, PolicyError

app = typer.Typer(
    help="🛡️  Regent — governed AI agents for DevOps automation.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()
err = Console(stderr=True)

EXIT_OK, EXIT_NOT_DONE, EXIT_USAGE = 0, 1, 2


def _version(value: bool) -> None:
    if value:
        console.print(f"regent {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    _version_flag: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version")
    ] = False,
) -> None:
    """Regent CLI."""


@app.command()
def run(
    agent: Annotated[str, typer.Argument(help="Agent name, e.g. pr-reviewer")],
    repository: Annotated[str, typer.Option("--repo", "-r", help="owner/name")],
    environment: Annotated[str, typer.Option("--env", "-e")] = "dev",
    payload: Annotated[
        str, typer.Option("--payload", "-p", help="JSON trigger payload, or @file.json")
    ] = "{}",
    event: Annotated[str, typer.Option("--event", help="Trigger event name")] = "manual",
    workspace: Annotated[Path, typer.Option("--workspace", "-w")] = Path(),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Describe write actions, do not perform them")
    ] = False,
    approve: Annotated[
        list[str] | None, typer.Option("--approve", help="Pre-approve a tool (glob), repeatable")
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", help="anthropic | local | replay")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the run record as JSON")
    ] = None,
) -> None:
    """Run one agent under its mandate. Exit 0 = succeeded, 1 = anything else."""
    from regent.bootstrap import ConfigError, build_platform
    from regent.runtime.runner import Runner

    try:
        platform = build_platform(provider=provider)
    except (ConfigError, PolicyError) as exc:
        err.print(f"[red]configuration error:[/red] {exc}")
        raise typer.Exit(EXIT_USAGE) from None
    data = (
        json.loads(Path(payload[1:]).read_text())
        if payload.startswith("@")
        else json.loads(payload)
    )
    trigger = Trigger(source="cli", event=event, actor=os.environ.get("USER", "cli"), payload=data)
    try:
        record = Runner(platform).run(
            agent,
            repository=repository,
            environment=environment,
            trigger=trigger,
            workspace=workspace,
            dry_run=dry_run,
            approvals=approve or (),
        )
    except KeyError as exc:
        err.print(f"[red]{exc.args[0]}[/red]")
        raise typer.Exit(EXIT_USAGE) from None
    _print_record(record)
    if output is not None:
        output.write_text(record.model_dump_json(indent=2))
    raise typer.Exit(EXIT_OK if record.status is RunStatus.SUCCEEDED else EXIT_NOT_DONE)


def _print_record(record: object) -> None:
    from regent.core.models import RunRecord

    if not isinstance(record, RunRecord):
        raise TypeError("expected a RunRecord")
    colour = {
        RunStatus.SUCCEEDED: "green",
        RunStatus.AWAITING_APPROVAL: "yellow",
        RunStatus.DENIED: "red",
        RunStatus.FAILED: "red",
        RunStatus.BUDGET_EXCEEDED: "red",
        RunStatus.RUNNING: "white",
    }[record.status]
    console.rule(f"[bold]{record.agent}[/bold] · {record.repository} · {record.environment}")
    console.print(f"run      [dim]{record.run_id}[/dim]")
    console.print(f"status   [{colour}]{record.status.value}[/{colour}]")
    console.print(
        f"mandate  {record.mandate.autonomy.name} · tier {record.mandate.model_tier} · "
        f"verification {record.mandate.verification} · from {record.mandate.source}"
    )
    u = record.usage
    console.print(
        f"usage    {u.llm_calls} llm call(s), {u.tool_calls} tool call(s), "
        f"{u.input_tokens}+{u.output_tokens} tokens, ${u.usd:.4f}"
    )
    if record.error:
        console.print(f"detail   [{colour}]{record.error}[/{colour}]")
    if record.pending_call:
        console.print(f"pending  {record.pending_call.tool} {record.pending_call.arguments}")
    if record.output and "analysis" in record.output:
        console.print(f"summary  {record.output['analysis'].get('summary', '')}")
        verdict = record.output.get("verdict") or {}
        if verdict:
            state = "accepted" if verdict.get("accepted") else "rejected"
            console.print(f"verifier {state} · issues: {len(verdict.get('issues', []))}")
        actions = record.output.get("actions")
        if actions:
            console.print(f"actions  {json.dumps(actions)[:400]}")


@app.command()
def agents() -> None:
    """List the shipped agents with their default tier and highest risk."""
    from regent.bootstrap import DEFAULT_AGENTS

    table = Table(title="Regent agents")
    table.add_column("name", style="cyan")
    table.add_column("highest risk")
    table.add_column("tier")
    table.add_column("skills")
    table.add_column("description")
    for cls in DEFAULT_AGENTS:
        table.add_row(
            cls.name,
            cls.highest_risk.name,
            cls.default_tier,
            ", ".join(cls.default_skills),
            cls.description,
        )
    console.print(table)


@app.command()
def mandates(
    directory: Annotated[Path, typer.Option("--dir", "-d")] = Path("policies/mandates"),
    agent: Annotated[str | None, typer.Option("--agent")] = None,
    repository: Annotated[str, typer.Option("--repo")] = "acme/example",
    environment: Annotated[str, typer.Option("--env")] = "dev",
) -> None:
    """Show the loaded mandates, or resolve the one that applies to an agent."""
    try:
        store = MandateStore.from_directory(directory)
    except PolicyError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_USAGE) from None
    if agent:
        mandate = store.resolve(agent, repository, environment)
        if mandate is None:
            err.print(f"[red]no mandate for {agent} on {repository} ({environment})[/red]")
            raise typer.Exit(EXIT_NOT_DONE)
        console.print_json(json.dumps(mandate.describe()))
        return
    table = Table(title=f"Mandates in {directory}")
    for col in ("agent", "autonomy", "tier", "scopes", "envs", "approval", "max remote", "verify"):
        table.add_column(col)
    for m in store.all():
        table.add_row(
            m.agent,
            m.autonomy.name,
            m.model_tier,
            ",".join(m.scopes),
            ",".join(m.environments),
            ",".join(m.requires_approval) or "—",
            m.max_remote_class.name,
            m.verification,
        )
    console.print(table)


@app.command("policy-check")
def policy_check(
    directory: Annotated[Path, typer.Option("--dir", "-d")] = Path("policies/mandates"),
) -> None:
    """Validate mandate files and the invariants no mandate may break. Exit 1 on failure."""
    from regent.bootstrap import DEFAULT_AGENTS, build_tools
    from regent.core.models import Autonomy

    try:
        store = MandateStore.from_directory(directory)
    except PolicyError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_NOT_DONE) from None
    tools = {spec.name for spec in build_tools().specs()}
    known_agents = {cls.name: cls for cls in DEFAULT_AGENTS}
    problems: list[str] = []
    for m in store.all():
        if m.autonomy >= Autonomy.L4_ACT:
            problems.append(f"{m.agent}: L4_ACT is never granted")
        if m.agent not in known_agents:
            problems.append(f"{m.agent}: unknown agent")
        for pattern in m.allowed_tools:
            if "*" not in pattern and pattern not in tools:
                problems.append(f"{m.agent}: unknown tool '{pattern}'")
        if any(p in ("*", "**") for p in m.allowed_tools):
            problems.append(f"{m.agent}: wildcard allow-list is forbidden")
        if m.budget.max_usd > 20:
            problems.append(f"{m.agent}: budget above the 20 USD per-run ceiling")
    for name in known_agents:
        if not any(m.agent == name for m in store.all()):
            problems.append(f"{name}: no mandate at all (the agent can never run)")
    if problems:
        for p in problems:
            err.print(f"[red]✗[/red] {p}")
        raise typer.Exit(EXIT_NOT_DONE)
    console.print(f"[green]✓[/green] {len(store.all())} mandate(s) valid, invariants hold")


ledger_app = typer.Typer(help="Inspect and verify the audit ledger.")
app.add_typer(ledger_app, name="ledger")


@ledger_app.command("verify")
def ledger_verify(path: Annotated[Path, typer.Argument()] = Path(".regent/ledger.jsonl")) -> None:
    """Re-hash the chain. Exit 1 if any event was altered, removed or reordered."""
    try:
        count = Ledger.verify(path)
    except (LedgerError, FileNotFoundError) as exc:
        err.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(EXIT_NOT_DONE) from None
    console.print(f"[green]✓[/green] {count} event(s), chain intact")


@ledger_app.command("show")
def ledger_show(
    path: Annotated[Path, typer.Argument()] = Path(".regent/ledger.jsonl"),
    run_id: Annotated[str | None, typer.Option("--run")] = None,
    last: Annotated[int, typer.Option("--last")] = 50,
) -> None:
    """Print events (optionally for one run)."""
    ledger = Ledger(path)
    events = ledger.events(run_id)[-last:]
    table = Table(title=str(path))
    for col in ("seq", "run", "kind", "at", "data"):
        table.add_column(col)
    for e in events:
        table.add_row(
            str(e.seq), e.run_id[:8], e.kind, e.at.strftime("%H:%M:%S"), json.dumps(e.data)[:100]
        )
    console.print(table)


@app.command()
def skills(directory: Annotated[Path | None, typer.Option("--dir")] = None) -> None:
    """List the skills available to agents."""
    from regent.skills import SkillRegistry

    registry = SkillRegistry(directory)
    table = Table(title="Skills")
    for col in ("name", "version", "applies to", "checks", "sha256", "description"):
        table.add_column(col)
    for name in registry.names():
        s = registry.get(name)
        table.add_row(
            s.name,
            s.version,
            ",".join(s.applies_to),
            ",".join(s.checks) or "—",
            s.sha256[:12],
            s.description,
        )
    console.print(table)


@app.command()
def evals(
    cases: Annotated[Path, typer.Option("--cases")] = Path("evals/cases"),
    report: Annotated[Path | None, typer.Option("--report")] = None,
    live: Annotated[bool, typer.Option("--live", help="Use the configured real provider")] = False,
) -> None:
    """Run the evaluation suite. Exit 1 when any case fails."""
    from regent.evals.runner import run_suite

    results = run_suite(cases, live=live)
    table = Table(title="Evals")
    for col in ("case", "agent", "status", "detail"):
        table.add_column(col)
    for r in results:
        table.add_row(
            r.case,
            r.agent,
            "[green]pass[/green]" if r.passed else "[red]FAIL[/red]",
            r.detail[:120],
        )
    console.print(table)
    if report is not None:
        report.write_text(json.dumps([r.model_dump() for r in results], indent=2))
    failed = sum(1 for r in results if not r.passed)
    console.print(f"{len(results) - failed}/{len(results)} passed")
    raise typer.Exit(EXIT_NOT_DONE if failed else EXIT_OK)


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8080,
) -> None:
    """Start the control-plane API (webhooks, runs, approvals, metrics)."""
    try:
        import uvicorn
    except ImportError:
        err.print("[red]install the api extra: pip install 'regent-platform[api]'[/red]")
        raise typer.Exit(EXIT_USAGE) from None
    uvicorn.run("regent.api.app:create_app", host=host, port=port, factory=True)


def main() -> None:  # pragma: no cover
    """Console-script entry point."""
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)
