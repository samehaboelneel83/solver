from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import api_keys
from app.core.db import enter_tenant, get_db
from app.core.security import decode_access_token
from app.models.iam import UserAccount

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> UserAccount:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    key = None
    if api_keys.is_api_key(token):
        # A program's key (migration 0035): it acts as the user who made it,
        # with at most the capabilities it was given.
        key = api_keys.resolve(db, token)
        if key is None:
            raise credentials_exception
        user = db.get(UserAccount, key.user_id)
    else:
        try:
            payload = decode_access_token(token)
            username = payload.get("sub")
            if username is None:
                raise credentials_exception
        except JWTError:
            raise credentials_exception
        user = db.query(UserAccount).filter(UserAccount.username == username).first()
        if user is not None and int(payload.get("tv", 0)) != int(getattr(user, "token_version", 0) or 0):
            raise credentials_exception
    if user is None or not user.is_active:
        raise credentials_exception

    # Counted per key, or per person signed in, against the organization's
    # `requests_per_minute` -- before anything else is done for the request.
    try:
        api_keys.take_token(db, f"key:{key.id}" if key else f"user:{user.id}", user.organization_id)
    except api_keys.RateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    # From here on the request sees only its own organization's rows: the
    # database enforces it (migration 0032), not each route.
    enter_tenant(db, user.organization_id)
    # Who a record's history names (migration 0100): the account, or the key it acts through.
    db.execute(text("SELECT set_config('app.actor', :a, false)"),
               {"a": f"{user.username} (API key {key.id[:8]})" if key is not None else user.username})
    db.commit()
    # For the request's log line (`app.main.log_request`): a dependency runs
    # in a copied context, so a context variable set here would not reach it.
    request.state.org_id = str(user.organization_id)
    request.state.username = user.username
    # The commit that switched tenant expired the user; load it again now,
    # as the tenant, so a caller holding it after the session closes can
    # still read it.
    db.refresh(user)
    # Not mapped columns: what this request may do if it came with a key.
    user.api_key_id = key.id if key else None  # type: ignore[attr-defined]
    user.api_key_capabilities = key.capabilities if key else None  # type: ignore[attr-defined]
    return user


# -- capabilities -----------------------------------------------------------
#
# A role is a bag of capabilities (migration 0013), and the API checks for a
# capability by name rather than for a role. Checking for a role would put the
# policy in two places: "who may publish" would be spelled out at every route,
# and adding a fifth role would mean editing all of them.


def capabilities_of(db: Session, user: UserAccount) -> set[str]:
    """Everything this user may do, from every role they hold -- and, for a
    request made with an API key, only what the key was also given. The
    intersection is taken now, not when the key was made, so a key loses a
    capability the moment its user does."""
    rows = db.execute(
        text(
            "SELECT DISTINCT rc.capability_code"
            "  FROM iam.user_role ur"
            "  JOIN iam.role_capability rc ON rc.role_id = ur.role_id"
            " WHERE ur.user_id = :u"
        ),
        {"u": str(user.id)},
    ).scalars().all()
    held = set(rows)
    limit = getattr(user, "api_key_capabilities", None)
    return held & limit if limit is not None else held


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
