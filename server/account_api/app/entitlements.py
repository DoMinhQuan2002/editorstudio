from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Plan, PlanFeature, PlanPrice, Subscription, User
from .schemas import Entitlements


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def active_subscription(db: Session, user: User) -> Subscription | None:
    sub = db.scalar(select(Subscription).where(Subscription.user_id == user.id, Subscription.status == "active"))
    if sub is None:
        return None
    if _aware(sub.current_period_end) <= datetime.now(timezone.utc):
        sub.status = "expired"           # lazily expire
        db.commit()
        return None
    return sub


def plan_features(db: Session, plan_id) -> list[str]:
    return list(db.scalars(select(PlanFeature.feature_code).where(PlanFeature.plan_id == plan_id)))


def entitlements_for(db: Session, user: User) -> Entitlements:
    sub = active_subscription(db, user)
    if sub is not None:
        price = db.get(PlanPrice, sub.plan_price_id)
        plan = db.get(Plan, price.plan_id)
        return Entitlements(plan_code=plan.code, plan_name=plan.name, billing_period=price.billing_period,
                            active_until=_aware(sub.current_period_end), features=plan_features(db, plan.id))
    free = db.scalar(select(Plan).where(Plan.code == "free"))
    return Entitlements(plan_code="free", plan_name=free.name if free else "Miễn phí",
                        features=plan_features(db, free.id) if free else [])
