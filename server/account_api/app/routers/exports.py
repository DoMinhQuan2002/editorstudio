from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import get_db
from ..deps import CurrentUser, get_current_user
from ..entitlements import entitlements_for
from ..models import Template, User
from ..schemas import ExportCheck, ExportDecision

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post("/check", response_model=ExportDecision)
def check_export(body: ExportCheck, current: CurrentUser = Depends(get_current_user), db: DbSession = Depends(get_db)):
    """Called by the app when the user presses "Xuất video" (step 6).

    Free (or unlisted) templates: always allowed. Premium templates: steps 1-6 work for everyone, but
    exporting needs a plan with 'export_premium_templates'; otherwise 402 and the app
    shows the plan picker.
    """
    template = db.scalar(select(Template).where(Template.slug == body.template_slug))
    # Only premium templates need to be listed on the server; anything else is free.
    if template is None or not template.is_premium:
        return ExportDecision(allowed=True, template_slug=body.template_slug, is_premium=False)
    ent = entitlements_for(db, db.get(User, current.user.id))
    if "export_premium_templates" in ent.features:
        return ExportDecision(allowed=True, template_slug=template.slug, is_premium=True)
    raise HTTPException(402, {"code": "plan_required",
                              "message": "Mẫu này cần gói trả phí để xuất video hoàn chỉnh.",
                              "template_slug": template.slug})
