"""The tool catalog. Adding a tool is adding a ``ToolSpec`` here; the contract does not change."""

from tool_service.tools.base import Env, Outcome, ToolSpec
from tool_service.tools.pqr import WRITE_TOOLS
from tool_service.tools.read import READ_TOOLS

CATALOG: dict[str, ToolSpec] = {spec.id: spec for spec in (*READ_TOOLS, *WRITE_TOOLS)}

__all__ = ["CATALOG", "Env", "Outcome", "ToolSpec"]
