import pytest
from sqlalchemy import select

from toknx_coordinator.core.config import get_settings
from toknx_coordinator.db.models import CreditBalance, CreditTransaction, Job
from toknx_coordinator.services.credit_units import credits_to_subcredits, format_subcredits
from toknx_coordinator.services.credits import ensure_credit_balance, settle_job


@pytest.mark.anyio
async def test_settle_job_small_request_still_pays_coordinator_fee(
    db_session,
    account_factory,
):
    consumer = await account_factory(
        db_session,
        github_id="gh-consumer-1",
        github_username="alice",
        api_key="toknx_api_consumer",
        node_token="toknx_node_consumer",
    )
    contributor = await account_factory(
        db_session,
        github_id="gh-contributor-1",
        github_username="bob",
        api_key="toknx_api_contributor",
        node_token="toknx_node_contributor",
    )
    await ensure_credit_balance(db_session, consumer)
    await ensure_credit_balance(db_session, contributor)

    job = Job(
        account_id=consumer.id,
        node_id="node-123",
        model="mlx-community/Llama-3.2-1B-Instruct-4bit",
        output_tokens=9,
        status="completed",
    )
    db_session.add(job)
    await db_session.flush()

    await settle_job(
        db_session,
        job=job,
        credits_per_1k=1,
        contributor_account_id=contributor.id,
    )
    await db_session.commit()

    consumer_balance = await db_session.get(CreditBalance, consumer.id)
    contributor_balance = await db_session.get(CreditBalance, contributor.id)
    transactions = (
        await db_session.execute(
            select(CreditTransaction)
            .where(CreditTransaction.job_id == job.id)
            .order_by(CreditTransaction.id.asc())
        )
    ).scalars().all()
    signup_bonus = get_settings().coordinator_signup_bonus

    assert consumer_balance.balance == credits_to_subcredits(signup_bonus) - 900
    assert contributor_balance.balance == credits_to_subcredits(signup_bonus) + 810
    assert job.credits_consumer == 900
    assert job.credits_coordinator == 90
    assert job.credits_contributor == 810
    assert [(tx.tx_type, tx.amount) for tx in transactions] == [("job_spent", -900), ("job_earned", 810)]


@pytest.mark.anyio
async def test_settle_job_same_account_keeps_fee_with_no_self_refund(
    db_session,
    account_factory,
):
    account = await account_factory(db_session, github_id="gh-self-1", github_username="alice")
    await ensure_credit_balance(db_session, account)

    job = Job(
        account_id=account.id,
        node_id="node-123",
        model="mlx-community/Llama-3.2-1B-Instruct-4bit",
        output_tokens=9,
        status="completed",
    )
    db_session.add(job)
    await db_session.flush()

    await settle_job(
        db_session,
        job=job,
        credits_per_1k=1,
        contributor_account_id=account.id,
    )
    await db_session.commit()

    balance = await db_session.get(CreditBalance, account.id)
    transactions = (
        await db_session.execute(
            select(CreditTransaction)
            .where(CreditTransaction.job_id == job.id)
            .order_by(CreditTransaction.id.asc())
        )
    ).scalars().all()
    signup_bonus = get_settings().coordinator_signup_bonus

    assert balance.balance == credits_to_subcredits(signup_bonus) - 90
    assert balance.total_spent == 900
    assert balance.total_earned == credits_to_subcredits(signup_bonus) + 810
    assert job.credits_consumer == 900
    assert job.credits_coordinator == 90
    assert job.credits_contributor == 810
    assert [(tx.tx_type, format_subcredits(tx.amount)) for tx in transactions] == [
        ("job_spent", "-0.009"),
        ("job_earned", "0.0081"),
    ]
