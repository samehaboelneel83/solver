from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app import audit
from app.core.db import get_db
from app.core.security import create_access_token, verify_password
from app.models.iam import UserAccount

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> dict:
    from app import sso

    if sso.sso_required_for_user(db, form_data.username):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="this organization requires single sign-on; password login is disabled",
        )
    user = db.query(UserAccount).filter(UserAccount.username == form_data.username).first()
    if user is None or not user.is_active or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="incorrect username or password")
    token = create_access_token(subject=user.username, token_version=getattr(user, "token_version", 0) or 0)
    try:
        audit.record(
            db,
            organization_id=user.organization_id,
            actor_id=user.id,
            action="auth.login",
            object_type="user",
            object_id=user.username,
            after={"username": user.username},
            ip=request.client.host if request.client else None,
        )
        db.commit()
    except Exception:
        db.rollback()
        # Login must still succeed if the audit write fails; the password was right.
        import logging
        logging.getLogger(__name__).exception("audit auth.login failed")
    return {"access_token": token, "token_type": "bearer"}
