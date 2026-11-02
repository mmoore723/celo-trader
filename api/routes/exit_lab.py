"""Read-only persisted Exit Lab endpoints. No worker or broker imports."""
from fastapi import APIRouter, HTTPException, Query
from strategy_health.exit_lab import read

router = APIRouter(prefix='/api/exit-lab', tags=['exit-lab'])


def scope():
    from config import get_settings
    from config.paths import get_user_data_dir
    settings = get_settings()
    return (get_user_data_dir(create=False) / 'exit_lab.sqlite3',
            settings.get('active_broker_account_id'),
            'paper' if settings.get('paper_trading', True) else 'live')


@router.get('')
def summaries():
    return read(*scope())


@router.get('/{identity}')
def detail(identity: str):
    result = read(*scope(), identity=identity)
    if result is None:
        raise HTTPException(404, 'Bucket not found for this account and mode')
    return result


@router.get('/{identity}/trades')
def trades(identity: str, page: int = Query(1, ge=1, le=100000)):
    result = read(*scope(), identity=identity, page=page)
    if result is None:
        raise HTTPException(404, 'Bucket not found for this account and mode')
    return result
