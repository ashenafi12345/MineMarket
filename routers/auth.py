from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from passlib.context import CryptContext
from jose import jwt, JWTError

from models import Users
from database import get_db


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

bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_bearer = OAuth2PasswordBearer(tokenUrl="/auth/token")

# =========================
# DB DEPENDENCY
# =========================
db_dependency = Annotated[Session, Depends(get_db)]


# =========================
# SCHEMAS
# =========================
class CreateUserRequest(BaseModel):
    username: str
    email: str
    first_name: str
    last_name: str
    password: str
    role: str
    phone_number: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


# =========================
# PASSWORD HELPERS
# =========================
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return bcrypt_context.hash(password)


# =========================
# AUTH HELPERS
# =========================
def authenticate_user(username: str, password: str, db: Session):
    user = db.query(Users).filter(Users.username == username).first()

    if not user:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user


def create_access_token(data: dict, expires_delta: timedelta):
    to_encode = data.copy()

    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": int(expire.timestamp())})

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# =========================
# GET CURRENT USER (FIXED)
# =========================
async def get_current_user(
    token: Annotated[str, Depends(oauth2_bearer)],
    db: db_dependency
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        username: str = payload.get("sub")
        user_id: str = payload.get("id")   # FIX: keep as str (UUID safe)
        role: str = payload.get("role")

        if username is None or user_id is None:
            raise credentials_exception

    except JWTError:
        raise credentials_exception

    user = db.query(Users).filter(Users.id == user_id).first()

    if user is None:
        raise credentials_exception

    return user


# =========================
# REGISTER USER
# =========================
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def create_user(
    db: db_dependency,
    user: CreateUserRequest
):
    existing_user = db.query(Users).filter(
        Users.username == user.username
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )

    new_user = Users(
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role,
        phone_number=user.phone_number,
        hashed_password=hash_password(user.password),
        is_active=True
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
@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: db_dependency
):

    user = authenticate_user(form_data.username, form_data.password, db)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = {
        "sub": user.username,
        "id": str(user.id),   # FIX: ensure JSON safe
        "role": user.role,
    }

    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)    
    )

    return {
        "access_token": access_token,
        "token_type": "bearer"
    }
