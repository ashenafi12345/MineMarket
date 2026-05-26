from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from passlib.context import CryptContext
from jose import jwt, JWTError

from models import Users
from database import get_db

from schemas import (
    CreateUserRequest,
    Token
)


# =========================
# ROUTER
# =========================
router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)


# =========================
# SECURITY CONFIG
# =========================
SECRET_KEY = "CHANGE_THIS_TO_ENV_SECRET_KEY"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

bcrypt_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

oauth2_bearer = OAuth2PasswordBearer(
    tokenUrl="/auth/token"
)


# =========================
# DB DEPENDENCY
# =========================
db_dependency = Annotated[
    Session,
    Depends(get_db)
]


# =========================
# PASSWORD HELPERS
# =========================
def verify_password(
    plain_password: str,
    hashed_password: str
) -> bool:
    return bcrypt_context.verify(
        plain_password,
        hashed_password
    )


def hash_password(password: str) -> str:
    return bcrypt_context.hash(password)


# =========================
# AUTH HELPERS
# =========================
def authenticate_user(
    username: str,
    password: str,
    db: Session
):
    user = db.query(Users).filter(
        Users.username == username
    ).first()

    if not user:
        return None

    if not verify_password(
        password,
        user.hashed_password
    ):
        return None

    return user


def create_access_token(
    data: dict,
    expires_delta: timedelta
):
    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + expires_delta

    to_encode.update({
        "exp": int(expire.timestamp())
    })

    return jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


# =========================
# GET CURRENT USER (REST)
# =========================
async def get_current_user(
    token: Annotated[str, Depends(oauth2_bearer)],
    db: db_dependency
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={
            "WWW-Authenticate": "Bearer"
        },
    )

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        username: str = payload.get("sub")
        user_id: str = payload.get("id")

        if username is None or user_id is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    user = db.query(Users).filter(
        Users.id == user_id
    ).first()

    if user is None:
        raise credentials_exception

    return user


# =========================
# REGISTER USER
# =========================
@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED
)
async def create_user(
    db: db_dependency,
    user: CreateUserRequest
):

    # =========================
    # CHECK USERNAME
    # =========================
    existing_username = db.query(Users).filter(
        Users.username == user.username
    ).first()

    if existing_username:
        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )

    # =========================
    # CHECK EMAIL
    # =========================
    existing_email = db.query(Users).filter(
        Users.email == user.email
    ).first()

    if existing_email:
        raise HTTPException(
            status_code=400,
            detail="Email already exists"
        )

    # =========================
    # PASSWORD VALIDATION
    # =========================
    if len(user.password) < 8:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 8 characters"
        )

    # =========================
    # CREATE USER
    # =========================
    new_user = Users(
        username=user.username,
        email=user.email,

        first_name=user.first_name,
        last_name=user.last_name,
        phone_number=user.phone_number,

        business_type=user.business_type,
        company_name=user.company_name,

        country=user.country,
        region=user.region,
        city=user.city,

        hashed_password=hash_password(user.password),

        role="user",

        is_active=True,
        is_verified=False,
        is_email_verified=False
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Error creating user"
        )

    return {
        "message": "User created successfully",
        "user_id": new_user.id
    }


# =========================
# LOGIN (TOKEN)
# =========================
@router.post(
    "/token",
    response_model=Token
)
async def login_for_access_token(
    form_data: Annotated[
        OAuth2PasswordRequestForm,
        Depends()
    ],
    db: db_dependency
):

    user = authenticate_user(
        form_data.username,
        form_data.password,
        db
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )

    token_data = {
        "sub": user.username,
        "id": str(user.id),
        "role": user.role,
    }

    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }


# =========================
# WEBSOCKET AUTHENTICATION
# =========================
def get_current_user_ws(token: str, db: Session) -> Optional[Users]:
    """Authenticate WebSocket connections with JWT token"""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        username: str = payload.get("sub")
        user_id: str = payload.get("id")

        if username is None or user_id is None:
            return None

    except JWTError:
        return None

    user = db.query(Users).filter(
        Users.id == user_id
    ).first()

    return user