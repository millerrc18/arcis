"""System monitoring — GPU, CPU, RAM, disk, Ollama health tracking.

C4 addition: manual_intervention_drift — detects divergence between broker
state and local DB intent (operator closes Alpaca position but shadow_trade
row still says active). See src/monitoring/manual_intervention_drift.py.
"""
