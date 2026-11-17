"""The Meko adapter: the only package that talks to Meko (REVIEW.md rule 9).

`adapter.py` is the interface, `mcp.py` its MCP implementation, `fake.py` an in-memory one for unit
tests, `quota.py` the call counter and quota guard every call goes through, and `client.py` the MCP
client underneath. `health.py` is the handshake probe.
"""
