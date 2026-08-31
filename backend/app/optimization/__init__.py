"""Deterministic dispatch/routing optimizer. No LLM. No operational writes."""

from app.optimization.eligibility import eligibility_for_alert
from app.optimization.service import create_optimization_run, list_optimization_runs

__all__ = ["create_optimization_run", "eligibility_for_alert", "list_optimization_runs"]
