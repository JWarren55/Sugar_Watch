"""Keep static bootstrap access and verified database approvals consistent."""

from app.db import models


def email_allowed(db, email, policy):
    if policy.permits_email(email):
        return True
    if not isinstance(email, str):
        return False
    approval = db.get(models.EmailApproval, email.strip().casefold())
    return bool(
        approval
        and approval.verified_at
        and approval.approved_at
        and not approval.revoked_at
    )
