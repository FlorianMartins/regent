---
name: secure-review
version: "1"
description: Security lens for code review — what to flag, with the OWASP mapping.
applies_to: [pr-reviewer]
checks: [findings_cite_lines]
---
When reviewing code, treat these as findings at least at "high":
- Input reaching a shell, SQL, LDAP, XPath or template engine without parameterisation (OWASP A03).
- Credentials, tokens or private keys in code, config or tests (CWE-798).
- Deserialisation of untrusted data (pickle, yaml.load without SafeLoader, Java ObjectInputStream).
- Missing authorisation on a new endpoint or a new resource path (OWASP A01).
- TLS verification disabled, weak hashes for passwords (MD5/SHA-1), predictable randomness for tokens.
- Path built from user input without normalisation (path traversal).
For each, name the sink, the source, and the one-line fix.
