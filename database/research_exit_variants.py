"""Additive paired research observations; never broker orders or old-row rewrites."""
from strategy_health.momentum_exit import PROTOCOL, LOW_WATER_PROTOCOL, STRATEGY_ID

CREATE_TABLE = """CREATE TABLE IF NOT EXISTS research_strategy_exit_variants (
    candidate_id TEXT NOT NULL REFERENCES shadow_candidates(candidate_id),
    protocol TEXT NOT NULL, contract_symbol TEXT NOT NULL,
    entry_ask REAL NOT NULL, entry_quote_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'collecting', decision_at TEXT, reason TEXT,
    detected_at TEXT, bid REAL, bid_at TEXT, received_at TEXT,
    PRIMARY KEY(candidate_id, protocol)
)"""
CREATE_INDEX = "CREATE INDEX IF NOT EXISTS idx_exit_variants_pending ON research_strategy_exit_variants(status)"


def pending_variants(conn, account, cutoff):
    conn.execute("""INSERT OR IGNORE INTO research_strategy_exit_variants
        (candidate_id,protocol,contract_symbol,entry_ask,entry_quote_at)
        SELECT e.candidate_id,?,e.contract_symbol,e.entry_ask,e.entry_quote_at
        FROM research_strategy_exits e JOIN shadow_candidates s ON s.candidate_id=e.candidate_id
        WHERE e.protocol=? AND s.strategy_id=? AND s.direction='bearish'
        AND COALESCE(s.broker_account_id,'')=? AND s.observed_at>=?""",
        (LOW_WATER_PROTOCOL, PROTOCOL, STRATEGY_ID, account or '', cutoff))
    return [dict(row, evidence_table="research_strategy_exit_variants") for row in conn.execute("""
        SELECT e.*,s.ticker,s.trigger_bar,s.direction,s.metadata_json
        FROM research_strategy_exit_variants e JOIN shadow_candidates s ON s.candidate_id=e.candidate_id
        WHERE e.protocol=? AND e.status IN ('collecting','pending_quote')
        AND COALESCE(s.broker_account_id,'')=? ORDER BY s.trigger_bar""", (LOW_WATER_PROTOCOL, account or ''))]


def attach_variants(conn, exits, account, cutoff):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_strategy_exit_variants'").fetchone():
        return
    for row in conn.execute("""SELECT e.* FROM research_strategy_exit_variants e
        JOIN shadow_candidates s ON s.candidate_id=e.candidate_id
        WHERE e.protocol=? AND COALESCE(s.broker_account_id,'')=? AND s.observed_at>=?""",
        (LOW_WATER_PROTOCOL, account or '', cutoff)):
        if row['candidate_id'] in exits:
            exits[row['candidate_id']]['low_water_variant'] = dict(row)
