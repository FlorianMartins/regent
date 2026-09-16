# ADR-0003 — No agent framework

**Status:** Accepted (2026-09)

## Context

LangChain, LlamaIndex, CrewAI, AutoGen and similar frameworks provide tool loops, memory and integrations. A governed platform needs every decision point (which tool, why allowed, what was sent, what it cost) to be readable, testable and stable across framework versions.

## Decision

Regent implements its own runtime (~1 500 lines across `core`, `gateway`, `runtime`, `tools`): a `Provider` protocol over the official Anthropic SDK and an OpenAI-compatible client, a `RunContext` that mediates every tool and model call, and a single-pass agent shape. No framework dependency.

## Consequences

- Every guard rail is a function with a test; nothing happens in a framework callback.
- No autonomous tool loop: tasks needing exploration are decomposed into explicit tools; this bounds cost and behaviour.
- We maintain integrations ourselves (GitHub, CloudGuard, Prometheus); the surface is small by design.
- Adding a provider means implementing `complete(request, model)`.

## Alternatives considered

- **LangChain / LangGraph** — rich, but the tool loop, callbacks and prompt templates hide the exact bytes sent and the decision order; frequent breaking changes.
- **CrewAI / AutoGen** — multi-agent conversation models multiply the blast radius and are hard to bound with a mandate.
- **Anthropic tool runner / Managed Agents** — attractive for the loop, but the mandate must sit between the model's request and the tool's execution in *our* process, with our ledger; revisit when a hosted runtime exposes that hook.
