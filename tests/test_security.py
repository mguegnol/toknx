from toknx_coordinator.services.security import decode_node_jwt, derive_stable_token, issue_node_jwt


def test_derive_stable_token_is_repeatable_for_same_subject_and_secret():
    first = derive_stable_token("toknx_node", subject="github-123", secret="secret-value")
    second = derive_stable_token("toknx_node", subject="github-123", secret="secret-value")

    assert first == second
    assert first.startswith("toknx_node_")


def test_derive_stable_token_changes_when_subject_changes():
    first = derive_stable_token("toknx_node", subject="github-123", secret="secret-value")
    second = derive_stable_token("toknx_node", subject="github-456", secret="secret-value")

    assert first != second


def test_issue_and_decode_node_jwt_round_trip():
    secret = "jwt-secret-with-sufficient-length"
    token = issue_node_jwt(node_id="node-1", account_id="acct-1", secret=secret, ttl_seconds=300)
    payload = decode_node_jwt(token, secret)

    assert payload["sub"] == "node-1"
    assert payload["account_id"] == "acct-1"
    assert payload["exp"] > payload["iat"]
