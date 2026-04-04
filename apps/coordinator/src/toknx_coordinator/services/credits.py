from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toknx_coordinator.core.config import get_settings
from toknx_coordinator.db.models import Account, CreditBalance, CreditTransaction, Job, Stake


settings = get_settings()


async def ensure_credit_balance(session: AsyncSession, account: Account) -> CreditBalance:
    balance = await session.get(CreditBalance, account.id)
    if balance:
        return balance
    balance = CreditBalance(
        account_id=account.id,
        balance=settings.coordinator_signup_bonus,
        total_earned=settings.coordinator_signup_bonus,
        total_spent=0,
    )
    session.add(balance)
    session.add(
        CreditTransaction(
            account_id=account.id,
            amount=settings.coordinator_signup_bonus,
            tx_type="signup_bonus",
            balance_after=settings.coordinator_signup_bonus,
        )
    )
    await session.flush()
    return balance


async def _get_credit_balance_for_update(session: AsyncSession, account_id: str) -> CreditBalance:
    balance = (
        await session.execute(
            select(CreditBalance).where(CreditBalance.account_id == account_id).with_for_update()
        )
    ).scalar_one_or_none()
    if balance is None:
        raise ValueError("credit balance missing")
    return balance


async def lock_stake(session: AsyncSession, account: Account, *, node_id: str | None = None) -> Stake:
    await ensure_credit_balance(session, account)
    balance = await _get_credit_balance_for_update(session, account.id)
    if balance.balance < settings.node_stake_credits:
        raise ValueError("insufficient credits for stake")

    active_stake = (
        await session.execute(
            select(Stake).where(
                Stake.account_id == account.id,
                Stake.node_id == node_id,
                Stake.status == "active",
            )
        )
    ).scalar_one_or_none()
    if active_stake:
        return active_stake

    balance.balance -= settings.node_stake_credits
    balance.total_spent += settings.node_stake_credits
    stake = Stake(account_id=account.id, node_id=node_id, amount=settings.node_stake_credits, status="active")
    session.add(stake)
    session.add(
        CreditTransaction(
            account_id=account.id,
            amount=-settings.node_stake_credits,
            tx_type="stake_lock",
            node_id=node_id,
            balance_after=balance.balance,
        )
    )
    await session.flush()
    return stake


async def refund_stake(session: AsyncSession, stake: Stake) -> None:
    if stake.status != "active":
        return
    balance = await session.get(CreditBalance, stake.account_id)
    if balance is None:
        return
    balance.balance += stake.amount
    stake.status = "withdrawn"
    session.add(
        CreditTransaction(
            account_id=stake.account_id,
            amount=stake.amount,
            tx_type="stake_refund",
            node_id=stake.node_id,
            balance_after=balance.balance,
        )
    )
    await session.flush()


async def settle_job(
    session: AsyncSession,
    *,
    job: Job,
    credits_per_1k: int,
    contributor_account_id: str,
) -> None:
    consumer_balance = await _get_credit_balance_for_update(session, job.account_id)
    contributor_balance = await _get_credit_balance_for_update(session, contributor_account_id)

    output_tokens = max(job.output_tokens, 0)
    total_credits = max(1, round((output_tokens / 1000) * credits_per_1k))
    coordinator_credits = round(total_credits * (settings.fee_percent / 100))
    contributor_credits = total_credits - coordinator_credits

    if consumer_balance.balance < total_credits:
        raise ValueError("insufficient credits to settle job")

    consumer_balance.balance -= total_credits
    consumer_balance.total_spent += total_credits
    contributor_balance.balance += contributor_credits
    contributor_balance.total_earned += contributor_credits

    job.credits_consumer = total_credits
    job.credits_contributor = contributor_credits
    job.credits_coordinator = coordinator_credits

    session.add_all(
        [
            CreditTransaction(
                account_id=job.account_id,
                amount=-total_credits,
                tx_type="job_spent",
                job_id=job.id,
                node_id=job.node_id,
                balance_after=consumer_balance.balance,
            ),
            CreditTransaction(
                account_id=contributor_account_id,
                amount=contributor_credits,
                tx_type="job_earned",
                job_id=job.id,
                node_id=job.node_id,
                balance_after=contributor_balance.balance,
            ),
        ]
    )
    await session.flush()
