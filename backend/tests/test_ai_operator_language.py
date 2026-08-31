from app.ai.llm.provider import _COMMON_POLICY, _CONCLUSION_PROMPT, _DIAGNOSIS_PROMPT, _RECOMMENDATION_PROMPT


def test_provider_prompts_require_french_operator_fields_without_translating_codes():
    assert "professional French" in _COMMON_POLICY
    assert "TRK-010" in _COMMON_POLICY
    assert "SIM-BATT-VOLT-LOW" in _COMMON_POLICY
    assert "WAITING_LOADING" in _COMMON_POLICY
    for prompt in (_DIAGNOSIS_PROMPT, _CONCLUSION_PROMPT, _RECOMMENDATION_PROMPT):
        assert prompt.startswith(_COMMON_POLICY)
        assert "Never invent values" in prompt
    assert "operational fact" in _COMMON_POLICY
    assert "map appearance" in _COMMON_POLICY
    assert "execute rerouting" in _COMMON_POLICY
    assert "ROAD_NETWORK_CONTEXT" in _DIAGNOSIS_PROMPT
    assert "advisory only" in _RECOMMENDATION_PROMPT
