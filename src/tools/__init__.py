"""Tool foundation infrastructure — config, safety primitives, execution log.

Per #104 (v0.36.57): this package holds the shared infrastructure that all
future tools (#105 Tier 1 onward) import. NO tools themselves live here —
this is pure foundation:

- `_config`         arcis_config.yaml loader (paths, ports, services, safety windows)
- `_safety`         SafeOp (dry_run), SafetyWindowGuard, ProdGuard primitives
- `_execution_log`  JSON-lines tool-call audit log at data/logs/tool-execution.log

Future tools (DBQuery, LogTail, CIInvestigate, SymbolFind, TradingState,
ProcessManager, HealthProbe, etc.) live in subpackages that import from
these private modules. The leading underscore on each module name is
deliberate — the tool API surface (what agents call) lives in the
subpackages; these are the private plumbing.
"""
