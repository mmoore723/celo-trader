"""Explicit hypothetical fee schedules. No broker access or production defaults."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json


def decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('invalid_fee_number') from None
    if not result.is_finite() or result < 0:
        raise ValueError('invalid_fee_number')
    return result


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('fee_timestamp_requires_timezone')
    return value


@dataclass(frozen=True)
class FeeComponent:
    name: str
    side: str
    per_contract: Decimal
    notional_rate: Decimal


@dataclass(frozen=True)
class ModeledFeeSchedule:
    version: str
    source: str
    source_sha256: str
    account_profile: str
    effective_from: datetime
    known_at: datetime
    components: tuple[FeeComponent, ...]

    def validate(self, entry_at):
        aware(entry_at)
        if any(not isinstance(v, str) or not v.strip()
               for v in (self.version, self.source, self.account_profile)):
            raise ValueError('missing_fee_provenance')
        if (not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64
                or any(c not in '0123456789abcdef' for c in self.source_sha256)):
            raise ValueError('invalid_fee_source_hash')
        if aware(self.effective_from) > entry_at or aware(self.known_at) > entry_at:
            raise ValueError('fee_schedule_not_available_at_entry')
        if not isinstance(self.components, tuple) or not self.components:
            raise ValueError('explicit_fee_components_required')
        names = set()
        for item in self.components:
            if not isinstance(item, FeeComponent) or not isinstance(item.name, str) or not item.name.strip():
                raise ValueError('invalid_fee_component')
            if item.name in names or item.side not in ('buy', 'sell', 'both'):
                raise ValueError('duplicate_or_invalid_fee_component')
            names.add(item.name)
            decimal(item.per_contract); decimal(item.notional_rate)

    def fingerprint(self):
        payload = dict(version=self.version, source=self.source, source_sha256=self.source_sha256,
                       account_profile=self.account_profile, effective_from=self.effective_from.isoformat(),
                       known_at=self.known_at.isoformat(), components=[
                           dict(name=c.name, side=c.side, per_contract=str(decimal(c.per_contract)),
                                notional_rate=str(decimal(c.notional_rate))) for c in self.components])
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def charge(self, *, side, contracts, premium, rounding, entry_at):
        """Standard 100-multiplier option model, not actual account-day billing.

        Per-fill ceiling is a sensitivity, not a broker fee allocation. Caller
        must verify account/product applicability and freeze the schedule.
        """
        self.validate(entry_at)
        if side not in ('buy', 'sell') or isinstance(contracts, bool) or not isinstance(contracts, int) or contracts < 1:
            raise ValueError('invalid_fee_fill')
        if rounding not in ('unrounded', 'per_fill_ceiling'):
            raise ValueError('invalid_fee_rounding')
        premium = decimal(premium)
        parts = {}
        for component in self.components:
            if component.side not in (side, 'both'):
                continue
            fee = contracts * (decimal(component.per_contract) + premium * 100 * decimal(component.notional_rate))
            parts[component.name] = fee.quantize(Decimal('.01'), rounding=ROUND_CEILING) if rounding == 'per_fill_ceiling' else fee
        return dict(total=sum(parts.values(), Decimal(0)), components=parts,
                    provenance='modeled_not_broker_charged', rounding=rounding,
                    schedule_version=self.version, schedule_hash=self.fingerprint())
