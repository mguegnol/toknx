import pytest

from toknx_coordinator.api.routes import account as account_routes
from toknx_coordinator.services.credit_units import credits_to_subcredits
from toknx_coordinator.services.credits import ensure_credit_balance


@pytest.mark.anyio
async def test_account_balance_returns_formatted_credit_strings(
    db_session,
    account_factory,
):
    account = await account_factory(
        db_session,
        github_id="gh-account-1",
        github_username="alice",
        api_key="toknx_api_account",
        node_token="toknx_node_account",
    )
    await ensure_credit_balance(db_session, account)
    payload = await account_routes.account_balance(account=account, session=db_session)

    assert payload["balance"] == "20000"
    assert payload["balance_subcredits"] == credits_to_subcredits(20_000)
    assert payload["total_earned"] == "20000"
    assert payload["total_earned_subcredits"] == credits_to_subcredits(20_000)
    assert payload["total_spent"] == "0"
    assert payload["total_spent_subcredits"] == 0
    assert payload["transactions"][0]["amount"] == "20000"
    assert payload["transactions"][0]["amount_subcredits"] == credits_to_subcredits(20_000)
