import pytest

from toknx_coordinator.api.routes import account as account_routes
from toknx_coordinator.services.credit_units import credits_to_subcredits
from toknx_coordinator.services.credits import ensure_credit_balance
from toknx_coordinator.core.config import get_settings


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
    signup_bonus = get_settings().coordinator_signup_bonus

    assert payload["balance"] == str(signup_bonus)
    assert payload["balance_subcredits"] == credits_to_subcredits(signup_bonus)
    assert payload["total_earned"] == str(signup_bonus)
    assert payload["total_earned_subcredits"] == credits_to_subcredits(signup_bonus)
    assert payload["total_spent"] == "0"
    assert payload["total_spent_subcredits"] == 0
    assert payload["transactions"][0]["amount"] == str(signup_bonus)
    assert payload["transactions"][0]["amount_subcredits"] == credits_to_subcredits(signup_bonus)
