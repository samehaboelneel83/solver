from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.iam import Organization, UserAccount


def seed_admin(db: Session) -> None:
    """Ensure a default organization and admin user exist. Idempotent."""
    settings = get_settings()

    org = db.query(Organization).filter(Organization.code == "default").first()
    if org is None:
        org = Organization(code="default", name="Default Organization")
        db.add(org)
        db.commit()
        db.refresh(org)

    admin = db.query(UserAccount).filter(UserAccount.username == settings.admin_username).first()
    if admin is None:
        admin = UserAccount(
            organization_id=org.id,
            username=settings.admin_username,
            display_name="Administrator",
            email=settings.admin_email,
            hashed_password=hash_password(settings.admin_password),
        )
        db.add(admin)
        db.commit()
