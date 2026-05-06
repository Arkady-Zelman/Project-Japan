"""Shared infrastructure for ingest, stack, regime, VLSTM, LSM, backtest, agent.

Every Postgres-touching job in the worker should use `common.db` for connections,
`common.audit` for compute_runs lifecycle, and `common.lock` for advisory locks.
"""
