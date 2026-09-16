"""Tools: the only way an agent touches the world.

A tool declares its *risk class* once; the policy engine, not the agent,
decides whether a mandate covers it. Tool results carry a data classification
so the gateway can keep confidential material away from remote models.
"""

from regent.tools.base import Tool, ToolContext, ToolRegistry, ToolSpec

__all__ = ["Tool", "ToolContext", "ToolRegistry", "ToolSpec"]
