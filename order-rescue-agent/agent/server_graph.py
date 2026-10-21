"""LangGraph Agent Server entry point for the local Order Rescue UI."""

from agent.graph import create_graph

graph = create_graph(use_server_persistence=True)
