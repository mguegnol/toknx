from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toknx_coordinator.api.deps import get_api_account, get_db_session
from toknx_coordinator.db.models import Account, CreditBalance, CreditTransaction
from toknx_coordinator.services.credits import ensure_credit_balance, lock_stake

router = APIRouter(tags=["account"])


@router.get("/account/balance")
async def account_balance(
    account: Account = Depends(get_api_account),
    session: AsyncSession = Depends(get_db_session),
):
    balance = await ensure_credit_balance(session, account)
    transactions = (
        await session.execute(
            select(CreditTransaction)
            .where(CreditTransaction.account_id == account.id)
            .order_by(CreditTransaction.created_at.desc())
            .limit(20)
        )
    ).scalars()
    return {
        "account_id": account.id,
        "github_username": account.github_username,
        "balance": balance.balance,
        "total_earned": balance.total_earned,
        "total_spent": balance.total_spent,
        "transactions": [
            {
                "id": tx.id,
                "amount": tx.amount,
                "type": tx.tx_type,
                "job_id": tx.job_id,
                "node_id": tx.node_id,
                "balance_after": tx.balance_after,
                "created_at": tx.created_at.isoformat(),
            }
            for tx in transactions
        ],
    }


@router.post("/account/stake")
async def create_stake(
    account: Account = Depends(get_api_account),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        stake = await lock_stake(session, account)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    return {
        "stake_id": stake.id,
        "amount": stake.amount,
        "status": stake.status,
    }

