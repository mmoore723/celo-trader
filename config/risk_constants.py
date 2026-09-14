"""
config/risk_constants.py — Capital/risk constants, the 4-tier risk ladder,
R:R threshold tiers, and get_risk_tier().

Split out of the old single config.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import math

STARTING_CAPITAL = 5000.0

# ── Concurrent position limit ─────────────────────────────────────────────────
# Maximum number of option positions the bot will hold open at the same time.
# Chosen by the user (2026-06-15) for a ~$5,000 account — lets the bot diversify
MAX_CONCURRENT_POSITIONS = 2

# ── 4-Tier Risk System ────────────────────────────────────────────────────────
# Growth mode ON:
#   balance < $5k   → Tier 4: 5%  (bootstrap — floors at 2 contracts when in this zone)

DAILY_LOSS_HARD_CAP_PCT   = 0.10   # 10% hard cap — fallback default only. As of
                                    # 2026-07-24 this is user-configurable via
                                    # Settings ("daily_loss_hard_cap_pct", stored as
                                    # a UI percentage e.g. 10.0 = 10%). risk.py reads
                                    # the settings value first and only falls back to
                                    # this constant if the key is somehow missing.
                                    # Small accounts trip this fast on normal option
                                    # premium swings — see the 7/21 + 7/22 back-to-back
                                    # kill-lock incident that motivated exposing it.
BOOTSTRAP_RISK_PCT        = 0.05   # Tier 4: bootstrap 5% sub-$5k (reference constant)
GROWTH_MODE_RISK_PCT      = 0.03   # Tier 3: aggressive growth $5k–$25k
MID_TIER_RISK_PCT         = 0.02   # Tier 2: transition $25k–$50k
CONSERVATIVE_RISK_PCT     = 0.01   # Tier 1: capital preservation ≥$50k / growth OFF
GROWTH_RISK_BOUNDARY_BOOT = 5_000  # Tier 4 → Tier 3 boundary
GROWTH_RISK_BOUNDARY_LOW  = 25_000 # Tier 3 → Tier 2 boundary
GROWTH_RISK_BOUNDARY      = 50_000 # Tier 2 → Tier 1 boundary (auto-downgrade)
KILL_LOCK_HOURS           = 24     # hours to lock trading after daily hard cap fires

# ── R:R (Reward:Risk) Threshold Tiers ─────────────────────────────────────────
# The pre-entry R:R gate (RiskManager.evaluate_rr) compares the trade's computed
# reward:risk ratio against a minimum threshold. With the bot's fixed exit
#   "auto"          → (DEFAULT) balance-based switch — uses MIN_RR_RATIO_SMALL_ACCOUNT
#   "small_account" → always use MIN_RR_RATIO_SMALL_ACCOUNT (1.2), regardless of balance.
#   "professional"  → always use MIN_RR_RATIO_PROFESSIONAL (1.6), regardless of balance.
MIN_RR_RATIO_SMALL_ACCOUNT = 1.2   # relaxed gate for sub-$5k bootstrap accounts
MIN_RR_RATIO_PROFESSIONAL  = 1.6   # standard gate once account graduates past bootstrap tier

# ── Manual risk override ──────────────────────────────────────────────────────
# When risk_per_trade is present in user_settings.json this value takes
# precedence over the automatic balance-based tier logic in get_risk_tier().
RISK_PER_TRADE: float | None = None


def get_risk_tier(balance: float) -> float:
    """
    Return the effective risk % for a given account balance.

    Manual override (highest priority):
      If 'risk_per_trade' is set in user_settings.json (0 < val <= 1),
      that value is returned immediately — balance and growth_mode are ignored.
      The Settings page saves risk_pct (e.g. 10) and converts to risk_per_trade
      (0.10) on POST so both keys are always in sync.

    Automatic tier logic (used when risk_per_trade is None / missing):
      Growth mode ON:
        balance < $5k    → 5%  (Tier 4, bootstrap)
        $5k ≤ bal < $25k → 3%  (Tier 3, aggressive growth)
        $25k ≤ bal < $50k→ 2%  (Tier 2, transition)
        balance ≥ $50k   → 1%  (Tier 1, auto-downgrade to preservation)
      Growth mode OFF → 1% always.
    """
    # Lazy import: settings_store.get_settings needs nothing from this module,
    # but this module is imported early by paths.get_db_path's lazy chain —
    # keeping this import lazy too avoids any ordering surprises.
    from config.settings_store import get_settings
    settings = get_settings()

    # ── Manual override: risk_per_trade (decimal) written by settings POST ────
    # Manual risk is the user's choice, not an automatic-tier ceiling.
    # Reject invalid saved values instead of silently switching to another risk.
    _override = settings.get("risk_per_trade")
    if _override is not None:
        try:
            _override_f = float(_override)
            if not isinstance(_override, bool) and math.isfinite(_override_f) and 0 < _override_f <= 1:
                return _override_f
        except (TypeError, ValueError):
            pass
        raise ValueError("Manual risk must be greater than 0% and at most 100%; update Settings")

    # ── Automatic tier logic ──────────────────────────────────────────────────
    if not settings.get("growth_mode", False):
        return CONSERVATIVE_RISK_PCT
    boundary_boot = float(settings.get("growth_risk_boundary_boot", GROWTH_RISK_BOUNDARY_BOOT))
    boundary_low  = float(settings.get("growth_risk_boundary_low",  GROWTH_RISK_BOUNDARY_LOW))
    boundary_high = float(settings.get("growth_risk_boundary",      GROWTH_RISK_BOUNDARY))
    if balance < boundary_boot:
        return BOOTSTRAP_RISK_PCT      # 5%  — sub-$5k bootstrap
    elif balance < boundary_low:
        return GROWTH_MODE_RISK_PCT    # 3%  — $5k–$25k growth
    elif balance < boundary_high:
        return MID_TIER_RISK_PCT       # 2%  — $25k–$50k transition
    else:
        return CONSERVATIVE_RISK_PCT   # 1%  — ≥$50k preservation
