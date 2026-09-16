---
name: conventional-commits
version: "1"
description: The commit and PR title convention used across the organisation.
applies_to: [release-scribe, pr-reviewer, dependency-steward]
---
Commits follow Conventional Commits: `type(scope): subject`.
Types: feat, fix, perf, refactor, docs, test, build, ci, chore, sec (security fix), revert.
`!` after the type or a `BREAKING CHANGE:` footer marks a breaking change.
Release notes group by type; the scope becomes the prefix of the line.
