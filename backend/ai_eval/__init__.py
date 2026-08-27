"""Development-only evaluation harness for MinePulse investigations.

This package deliberately lives outside ``app.ai``.  It may describe known
test conditions, but production investigation code never imports it.
"""

from ai_eval.cases import EVALUATION_CASES, get_case
from ai_eval.runner import run_evaluation

__all__ = ["EVALUATION_CASES", "get_case", "run_evaluation"]
