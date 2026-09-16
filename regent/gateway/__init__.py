"""The LLM gateway: the only door between agents and language models.

Everything that touches a model goes through :class:`~regent.gateway.gateway.Gateway`:
redaction, confidentiality checks, model routing, prompt versioning, budget
accounting and audit — none of it is optional, none of it is the agent's job.
"""
