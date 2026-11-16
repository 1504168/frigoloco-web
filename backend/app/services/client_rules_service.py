"""Client rules: which (fridge, product) pairs break an ``exclude_tag`` rule of the client.

The menu and dispatch screens only warn on a violation; nothing here blocks an allocation.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.master import ClientRule, ClientRuleType, Fridge, ProductTag


@dataclass(frozen=True)
class RuleViolation:
    fridge_id: int
    product_id: int
    rule_id: int
    tag: str
    note: str | None


def find_rule_violations(
    session: Session,
    product_ids: list[int],
    fridge_ids: list[int],
    on_date: datetime.date,
) -> list[RuleViolation]:
    """Every (fridge, product, rule) where an exclude_tag rule valid on ``on_date`` matches."""
    client_id_by_fridge = _client_id_by_fridge(session, fridge_ids)
    client_ids = set(client_id_by_fridge.values())
    if not product_ids or not client_ids:
        return []
    rules = _exclude_tag_rules_valid_on(session, client_ids, on_date)
    tags_by_product = _tags_by_product(session, product_ids)
    return match_rule_violations(client_id_by_fridge, rules, tags_by_product)


def find_allocated_rule_violations(
    session: Session,
    allocated_pairs: set[tuple[int, int]],
    on_date: datetime.date,
) -> list[RuleViolation]:
    """Violations limited to the (fridge_id, product_id) pairs that actually got units."""
    fridge_ids = sorted({fridge_id for fridge_id, _ in allocated_pairs})
    product_ids = sorted({product_id for _, product_id in allocated_pairs})
    violations = find_rule_violations(session, product_ids, fridge_ids, on_date)
    return [
        violation
        for violation in violations
        if (violation.fridge_id, violation.product_id) in allocated_pairs
    ]


def match_rule_violations(
    client_id_by_fridge: dict[int, int],
    rules: list[ClientRule],
    tags_by_product: dict[int, set[str]],
) -> list[RuleViolation]:
    """Pure matching step: a rule hits every fridge of its client, or only its own fridge."""
    violations: list[RuleViolation] = []
    for fridge_id, client_id in client_id_by_fridge.items():
        fridge_rules = [rule for rule in rules if _rule_applies_to(rule, client_id, fridge_id)]
        for rule in fridge_rules:
            for product_id, product_tags in tags_by_product.items():
                if rule.tag in product_tags:
                    violations.append(
                        RuleViolation(
                            fridge_id=fridge_id,
                            product_id=product_id,
                            rule_id=rule.id,
                            tag=rule.tag,
                            note=rule.note,
                        )
                    )
    return violations


def _rule_applies_to(rule: ClientRule, client_id: int, fridge_id: int) -> bool:
    is_client_rule = rule.client_id == client_id
    covers_fridge = rule.fridge_id is None or rule.fridge_id == fridge_id
    return is_client_rule and covers_fridge


def _client_id_by_fridge(session: Session, fridge_ids: list[int]) -> dict[int, int]:
    """Fridges without a client cannot have client rules and are left out."""
    if not fridge_ids:
        return {}
    rows = session.execute(
        select(Fridge.id, Fridge.client_id)
        .where(Fridge.id.in_(fridge_ids))
        .where(Fridge.client_id.is_not(None))
    ).all()
    return {row.id: row.client_id for row in rows}


def _exclude_tag_rules_valid_on(
    session: Session,
    client_ids: set[int],
    on_date: datetime.date,
) -> list[ClientRule]:
    rules = session.execute(
        select(ClientRule)
        .where(ClientRule.client_id.in_(client_ids))
        .where(ClientRule.rule_type == ClientRuleType.exclude_tag.value)
        .where(or_(ClientRule.valid_from.is_(None), ClientRule.valid_from <= on_date))
        .where(or_(ClientRule.valid_to.is_(None), ClientRule.valid_to >= on_date))
    ).scalars()
    return list(rules)


def _tags_by_product(session: Session, product_ids: list[int]) -> dict[int, set[str]]:
    rows = session.execute(
        select(ProductTag.product_id, ProductTag.tag).where(
            ProductTag.product_id.in_(product_ids)
        )
    ).all()
    tags_by_product: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        tags_by_product[row.product_id].add(row.tag)
    return tags_by_product
