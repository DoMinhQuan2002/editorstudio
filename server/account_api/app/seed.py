"""Creates tables (development only) and seeds plans, features and templates.

    python -m app.seed            # seed (idempotent)
    python -m app.seed --create   # also create tables from the models (dev / SQLite)

On PostgreSQL production, create the schema from docs/database/media_studio_database.sql
(it already contains the plan seed); this script then only adds missing templates.
"""
import sys
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine
from .models import Feature, Plan, PlanFeature, PlanPrice, Template

FEATURES = {
    "export_free_templates": "Xuất video/ảnh từ mẫu miễn phí",
    "export_premium_templates": "Xuất video/ảnh từ mẫu trả phí",
}
PLANS = [("free", "Miễn phí", 0, ["export_free_templates"]),
         ("pro", "Pro", 1, ["export_free_templates", "export_premium_templates"])]
# Placeholder prices in VND; change them here or in the database.
PRO_PRICES = {"week": Decimal("29000"), "month": Decimal("79000"), "year": Decimal("599000")}
TEMPLATES = [("fall-diary", "Fall Diary", "video", False),
             ("november-dump", "November Dump", "image", False)]


def seed(db: Session) -> None:
    for code, name in FEATURES.items():
        if db.get(Feature, code) is None:
            db.add(Feature(code=code, name=name))
    db.flush()
    for code, name, order, features in PLANS:
        plan = db.scalar(select(Plan).where(Plan.code == code))
        if plan is None:
            plan = Plan(code=code, name=name, sort_order=order)
            db.add(plan)
            db.flush()
        for feature in features:
            if db.get(PlanFeature, (plan.id, feature)) is None:
                db.add(PlanFeature(plan_id=plan.id, feature_code=feature))
        if code == "pro":
            for period, amount in PRO_PRICES.items():
                price = db.scalar(select(PlanPrice).where(PlanPrice.plan_id == plan.id,
                                                          PlanPrice.billing_period == period,
                                                          PlanPrice.is_active.is_(True)))
                if price is None:
                    db.add(PlanPrice(plan_id=plan.id, billing_period=period, amount=amount, currency="VND"))
                elif price.amount == 0:
                    price.amount = amount
    for slug, name, kind, premium in TEMPLATES:
        if db.scalar(select(Template).where(Template.slug == slug)) is None:
            db.add(Template(slug=slug, name=name, output_kind=kind, is_premium=premium))
    db.commit()


if __name__ == "__main__":
    if "--create" in sys.argv:
        Base.metadata.create_all(engine)
    with SessionLocal() as session:
        seed(session)
    print("Seed done.")
