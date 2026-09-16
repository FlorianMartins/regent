---
name: dependency-policy
version: "1"
description: When an automated dependency bump may be merged without a human.
applies_to: [dependency-steward]
---
Auto-merge is allowed only when ALL hold: the bump is patch or minor under semver; CI is green on the PR; the changelog has no "breaking", "deprecat" or "migration" note; the package is not on the `critical-dependencies` list (auth, crypto, database drivers, build tooling). Major bumps and anything on the critical list always go to a human, with the changelog excerpt quoted.
