# Runbook — Ledger verification

**When.** An audit asks for evidence of what an agent did; tampering is suspected; after restoring a ledger from backup; on a schedule (weekly).

## Steps

1. Verify the chain:

    ```bash
    regent ledger verify .regent/ledger.jsonl
    # ✓ 1342 event(s), chain intact
    ```

    Exit code 1 and a message such as `event 812 was modified after being written` or `event 813 links to 3f9a…, expected 71c0…` means an edit, a removal or a reorder at that point.

2. Compare with the shipped copy (SIEM / object storage with object lock): the shipped copy is the reference; a local file that differs is the suspect.
3. Extract the evidence for one run:

    ```bash
    regent ledger show .regent/ledger.jsonl --run <run_id>
    jq -c 'select(.run_id=="<run_id>")' .regent/ledger.jsonl > evidence-<run_id>.jsonl
    ```

4. Answer the audit questions from the events: **what it saw** (`tool.call` outputs, redacted), **under which rules** (`run.started.mandate`, `tool.decision.rule`), **which model and prompt** (`llm.call.prompt_id`, `model`), **who approved** (`approval.approver`), **what it did** (`tool.call` in the act phase), **what it cost** (`run.finished.usage`).

## Verification

`regent ledger verify` exits 0 on both the local and the shipped copy and they have the same last hash:

```bash
tail -n1 .regent/ledger.jsonl | jq -r .hash
```

## Rollback

Not applicable. If the chain is broken, preserve the file as evidence, restore from the shipped copy, and open a security incident: a broken chain is a finding, not a bug.
