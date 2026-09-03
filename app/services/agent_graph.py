"""Backward-compatible import surface for V0.2 callers.

The implementation moved to app.workflow.multi_agent_graph in V0.3.
"""
from ..workflow.multi_agent_graph import (
    LANGGRAPH_AVAILABLE,
    MultiAgentState as AgentState,
    build_multi_agent_graph as build_agent_graph,
    execute_multi_agent_workflow as execute_agent_workflow,
)

__all__ = ["LANGGRAPH_AVAILABLE", "AgentState", "build_agent_graph", "execute_agent_workflow"]
