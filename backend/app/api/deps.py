from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import enter_tenant, get_db
from app.core.security import decode_access_token
from app.models.iam import UserAccount

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> UserAccount:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        username = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(UserAccount).filter(UserAccount.username == username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    # From here on the request sees only its own organization's rows: the
    # database enforces it (migration 0032), not each route.
    enter_tenant(db, user.organization_id)
    # The commit that switched tenant expired the user; load it again now,
    # as the tenant, so a caller holding it after the session closes can
    # still read it.
    db.refresh(user)
    return user


# -- capabilities -----------------------------------------------------------
#
# A role is a bag of capabilities (migration 0013), and the API checks for a
# capability by name rather than for a role. Checking for a role would put the
# policy in two places: "who may publish" would be spelled out at every route,
# and adding a fifth role would mean editing all of them.


def capabilities_of(db: Session, user: UserAccount) -> set[str]:
    """Everything this user may do, from every role they hold."""
    rows = db.execute(
        text(
            "SELECT DISTINCT rc.capability_code"
            "  FROM iam.user_role ur"
            "  JOIN iam.role_capability rc ON rc.role_id = ur.role_id"
            " WHERE ur.user_id = :u"
        ),
        {"u": str(user.id)},
    ).scalars().all()
    return set(rows)


def requires(capability: str):
    """A dependency that refuses a request the user may not make.

    **403, not 404.** The resource exists and the caller is who they say they
    are; what is missing is permission, and saying so is what lets them ask
    for it. Hiding it behind a 404 would also lie to the UI, which needs to
    know the difference between "not there" and "not yours".
    """

    def dependency(
        db: Session = Depends(get_db), user: UserAccount = Depends(get_current_user)
    ) -> UserAccount:
        if capability not in capabilities_of(db, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"this account does not have the {capability!r} capability",
            )
        return user

    return dependency
