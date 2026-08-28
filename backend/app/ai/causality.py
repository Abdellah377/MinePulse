"""Small deterministic guards for causal, rather than circular, diagnoses."""

from __future__ import annotations

import re
import unicodedata

from app.ai.contracts import InvestigationTrigger, TriggerType

_WORD = re.compile(r"[a-z0-9]+")
_GENERIC = {
    "a", "an", "and", "as", "at", "because", "best", "by", "cause", "caused",
    "condition", "contributed", "contributing", "de", "des", "du", "en", "est",
    "explanation", "for", "from", "is", "la", "le", "les", "likely", "of", "par",
    "probable", "probably", "que", "resulted", "supports", "the", "to", "un", "une",
}
_SYMPTOMS = {
    "congestion": {
        "attente", "congestion", "idle", "long", "prolongee", "prolonged", "risk",
        "waiting",
    },
    "production": {
        "deviation", "ecart", "faible", "low", "production", "shortfall", "target",
        "tonnage", "underperformance",
    },
    "fuel": {
        "anomalie", "anomaly", "carburant", "consommation", "consumption", "fuel", "high",
        "rate",
    },
    "connectivity": {
        "communication", "connectivity", "connexion", "data", "loss", "missing", "perte",
        "signal", "telemetry", "telemetrie",
    },
    "equipment": {
        "anomalie", "anomaly", "arret", "breakdown", "equipment", "failure", "mechanical",
        "mecanique", "panne", "stop", "stopped",
    },
}
_MECHANISMS = {
    "congestion": {
        "assignment", "capacity", "downstream", "dump", "haul", "loader", "loading cycle",
        "loading point", "queue", "road", "service delay", "service rate", "travel",
    },
    "production": {
        "availability", "bottleneck", "cycle", "downtime", "fleet", "loader", "loading",
        "payload", "queue", "service rate", "travel", "waiting",
    },
    "fuel": {
        "cycle", "engine load", "idle", "load", "output", "payload", "productive", "speed",
        "thermal", "travel",
    },
    "connectivity": {
        "gateway", "gaps", "intermittent", "link quality", "network", "quality", "stale",
    },
    "equipment": {
        "coolant", "cooling", "diagnostic", "engine load", "lubrication", "maintenance condition",
        "oil pressure", "temperature", "thermal", "tyre", "tire", "pressure", "voltage",
    },
}
_DEPTH_TWO = {
    "assignment ratio", "cooling degradation", "degraded loader", "engine load imbalance",
    "loader service rate", "lubrication", "oil pressure", "road restriction", "thermal degradation",
}
_CIRCULAR_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"wait\w*.*caus\w*.*wait\w*",
        r"attent\w*.*caus\w*.*attent\w*",
        r"low production.*caus\w*.*low production",
        r"production faible.*caus\w*.*production faible",
        r"high fuel.*caus\w*.*high fuel",
        r"consommation.*caus\w*.*consommation",
        r"mechanical stop.*caus\w*.*mechanical stop",
        r"communication loss.*caus\w*.*communication loss",
    )
)


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(_WORD.findall("".join(c for c in decomposed if not unicodedata.combining(c))))


def _payload_text(value) -> list[str]:
    if isinstance(value, dict):
        return [text for item in value.values() for text in _payload_text(item)]
    if isinstance(value, list):
        return [text for item in value for text in _payload_text(item)]
    return [str(value)] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else []


def trigger_observation(trigger: InvestigationTrigger) -> str:
    """Return concise operator-visible trigger wording without inventing a cause."""
    for key in ("reason", "description", "title"):
        value = trigger.payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"Observed operational condition: {trigger.trigger_type.value}."


def _family(trigger: InvestigationTrigger) -> str:
    text = _normalise(" ".join([trigger.trigger_type.value, trigger.source or "", *_payload_text(trigger.payload)]))
    if any(term in text for term in ("fuel", "carburant", "consommation")):
        return "fuel"
    if any(term in text for term in ("wait", "attente", "congestion", "idle", "queue")):
        return "congestion"
    if any(term in text for term in ("production", "tonnage", "shortfall")):
        return "production"
    if any(term in text for term in ("communication", "connectivity", "connexion", "telemetry")):
        return "connectivity"
    return {
        TriggerType.CONGESTION_RISK: "congestion",
        TriggerType.PRODUCTION_DEVIATION: "production",
        TriggerType.CONNECTIVITY_ISSUE: "connectivity",
    }.get(trigger.trigger_type, "equipment")


def is_symptom_restatement(statement: str, trigger: InvestigationTrigger) -> bool:
    """Conservatively reject a statement that names no mechanism beyond the trigger."""
    normalised = _normalise(statement)
    if any(pattern.search(normalised) for pattern in _CIRCULAR_PATTERNS):
        return True
    family = _family(trigger)
    if (
        family == "equipment"
        and any(term in normalised for term in ("communication", "connectivity", "telemetry loss"))
        and not any(term in normalised for term in _MECHANISMS["equipment"])
    ):
        # Loss of visibility alone does not explain a physical/mechanical stop.
        return True
    mechanisms = _MECHANISMS[family]
    if any(term in normalised for term in mechanisms):
        return False
    tokens = set(normalised.split()) - _GENERIC
    symptom_tokens = _SYMPTOMS[family]
    if tokens and tokens.issubset(symptom_tokens):
        return True
    trigger_tokens = set(_normalise(" ".join(_payload_text(trigger.payload))).split()) - _GENERIC
    meaningful = tokens - symptom_tokens - trigger_tokens
    return bool(tokens & symptom_tokens) and len(meaningful) < 2


def validated_causal_depth(statement: str, claimed_depth: int, trigger: InvestigationTrigger) -> int:
    """Validate the model's bounded depth claim without inferring a cause ourselves."""
    if claimed_depth <= 0 or is_symptom_restatement(statement, trigger):
        return 0
    normalised = _normalise(statement)
    if claimed_depth >= 2 and any(term in normalised for term in _DEPTH_TWO):
        return 2
    return 1
