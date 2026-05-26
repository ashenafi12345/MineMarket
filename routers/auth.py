from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
import secrets

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from passlib.context import CryptContext
from jose import jwt, JWTError

from models import Users, RefreshToken
from database import get_db

from schemas import (
    CreateUserRequest,
    Token,
    LogoutResponse,
    SessionInfo,
    SessionsListResponse,
    ChangePasswordRequest,
    ChangePasswordResponse
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
# IMPORTANT: Move SECRET_KEY to environment variable in production
SECRET_KEY = "CHANGE_THIS_TO_ENV_SECRET_KEY"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 14
REFRESH_TOKEN_ROTATION = True

bcrypt_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

oauth2_bearer = OAuth2PasswordBearer(
    tokenUrl="/auth/login"
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
    return bcrypt_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return bcrypt_context.hash(password)


# =========================
# REFRESH TOKEN HELPERS
# =========================
def generate_refresh_token() -> str:
    """Generate a cryptographically secure random refresh token"""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Hash the refresh token using bcrypt for consistency"""
    return bcrypt_context.hash(token)


def verify_refresh_token(raw_token: str, hashed_token: str) -> bool:
    """Verify a refresh token against its hash"""
    try:
        return bcrypt_context.verify(raw_token, hashed_token)
    except Exception:
        return False


def create_refresh_token(
    user_id: str,
    db: Session,
    device_info: Optional[str] = None,
    ip_address: Optional[str] = None
) -> str:
    """Create a new refresh token for a user"""
    
    # Generate new token
    raw_token = generate_refresh_token()
    token_hash = hash_refresh_token(raw_token)
    
    # Calculate expiry
    expires_at = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    
    # Create database entry
    refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        device_info=device_info,
        ip_address=ip_address,
        expires_at=expires_at
    )
    
    db.add(refresh_token)
    db.commit()
    db.refresh(refresh_token)
    
    return raw_token


def validate_refresh_token(
    raw_token: str,
    db: Session
) -> Optional[RefreshToken]:
    """
    Validate a refresh token efficiently.
    Uses direct hash lookup - O(1) performance!
    """
    
    # Hash the token for lookup
    token_hash = hash_refresh_token(raw_token)
    
    # Direct lookup by hash (uses index for fast performance)
    token_entry = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash,
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.utcnow()
    ).first()
    
    if not token_entry:
        return None
    
    # Double-check with bcrypt verify (defense in depth)
    if not verify_refresh_token(raw_token, token_entry.token_hash):
        return None
    
    # Update last used timestamp
    token_entry.mark_as_used()
    db.commit()
    
    return token_entry


def revoke_refresh_token(token_entry: RefreshToken, db: Session):
    """Revoke a specific refresh token"""
    token_entry.revoke()
    db.commit()


def revoke_all_user_tokens(user_id: str, db: Session, keep_current_id: Optional[str] = None):
    """Revoke all refresh tokens for a user, optionally keeping one"""
    query = db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.is_revoked == False
    )
    
    if keep_current_id:
        query = query.filter(RefreshToken.id != keep_current_id)
    
    revoked_count = query.update({"is_revoked": True}, synchronize_session=False)
    db.commit()
    
    return revoked_count


def cleanup_expired_tokens(db: Session):
    """Delete expired tokens from database (call periodically)"""
    deleted_count = db.query(RefreshToken).filter(
        RefreshToken.expires_at <= datetime.utcnow()
    ).delete()
    db.commit()
    return deleted_count


# =========================
# AUTH HELPERS
# =========================
def authenticate_user(
    username: str,
    password: str,
    db: Session
):
    user = db.query(Users).filter(Users.username == username).first()

    if not user:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user


def create_access_token(
    data: dict,
    expires_delta: timedelta
):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": int(expire.timestamp())})
    
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_device_info(request: Request) -> str:
    """Extract device information from request headers"""
    user_agent = request.headers.get("user-agent", "Unknown")
    return user_agent[:200]  # Limit length to prevent oversized entries


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
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_id: str = payload.get("id")

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
    # Check username
    existing_username = db.query(Users).filter(Users.username == user.username).first()
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already exists")

    # Check email
    existing_email = db.query(Users).filter(Users.email == user.email).first()
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already exists")

    # Password validation
    if len(user.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # Create user
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
        raise HTTPException(status_code=500, detail="Error creating user")

    return {"message": "User created successfully", "user_id": new_user.id}


# =========================
# LOGIN
# =========================
@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    response: Response,
    db: db_dependency
):
    # Authenticate user
    user = authenticate_user(form_data.username, form_data.password, db)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    token_data = {
        "sub": user.username,
        "id": str(user.id),
        "role": user.role,
    }

    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    # Create refresh token
    device_info = get_device_info(request)
    ip_address = request.client.host if request.client else None
    
    refresh_token = create_refresh_token(
        user_id=user.id,
        db=db,
        device_info=device_info,
        ip_address=ip_address
    )

    # Set refresh token as httpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="strict",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/auth",
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


# =========================
# REFRESH TOKEN ENDPOINT
# =========================
@router.post("/refresh", response_model=Token)
async def refresh_access_token(
    request: Request,
    response: Response,
    db: db_dependency
):
    # Get refresh token from cookie
    refresh_token = request.cookies.get("refresh_token")
    
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token provided"
        )
    
    # Validate refresh token (efficient O(1) lookup)
    token_entry = validate_refresh_token(refresh_token, db)
    
    if not token_entry:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )
    
    # Get user
    user = token_entry.user
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    
    # Create new access token
    token_data = {
        "sub": user.username,
        "id": str(user.id),
        "role": user.role,
    }
    
    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    # Handle token rotation if enabled
    if REFRESH_TOKEN_ROTATION:
        # Revoke the old token
        revoke_refresh_token(token_entry, db)
        
        # Create new refresh token
        device_info = get_device_info(request)
        ip_address = request.client.host if request.client else None
        
        new_refresh_token = create_refresh_token(
            user_id=user.id,
            db=db,
            device_info=device_info,
            ip_address=ip_address
        )
        
        # Set new refresh token cookie
        response.set_cookie(
            key="refresh_token",
            value=new_refresh_token,
            httponly=True,
            secure=False,
            samesite="strict",
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            path="/auth",
        )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


# =========================
# LOGOUT (CURRENT DEVICE)
# =========================
@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    db: db_dependency,
    current_user: Annotated[Users, Depends(get_current_user)]
):
    # Get refresh token from cookie
    refresh_token = request.cookies.get("refresh_token")
    
    if refresh_token:
        # Find and revoke the token using efficient lookup
        token_hash = hash_refresh_token(refresh_token)
        token_entry = db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash,
            RefreshToken.user_id == current_user.id
        ).first()
        
        if token_entry:
            revoke_refresh_token(token_entry, db)
    
    # Clear the cookie
    response.delete_cookie(key="refresh_token", path="/auth")
    
    return LogoutResponse(
        message="Successfully logged out from this device",
        revoked_count=1
    )


# =========================
# LOGOUT FROM ALL DEVICES
# =========================
@router.post("/logout-all", response_model=LogoutResponse)
async def logout_all_devices(
    request: Request,
    response: Response,
    db: db_dependency,
    current_user: Annotated[Users, Depends(get_current_user)]
):
    # Revoke all tokens
    revoked_count = revoke_all_user_tokens(current_user.id, db, keep_current_id=None)
    
    # Clear cookie
    response.delete_cookie(key="refresh_token", path="/auth")
    
    return LogoutResponse(
        message=f"Logged out from {revoked_count} device(s)",
        revoked_count=revoked_count
    )


# =========================
# GET ACTIVE SESSIONS
# =========================
@router.get("/sessions", response_model=SessionsListResponse)
async def get_active_sessions(
    db: db_dependency,
    current_user: Annotated[Users, Depends(get_current_user)]
):
    # Get all active refresh tokens for this user
    active_tokens = db.query(RefreshToken).filter(
        RefreshToken.user_id == current_user.id,
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.utcnow()
    ).order_by(RefreshToken.created_at.desc()).all()
    
    sessions = []
    for token in active_tokens:
        sessions.append(SessionInfo(
            id=token.id,
            device_info=token.device_info or "Unknown device",
            ip_address=token.ip_address,
            created_at=token.created_at,
            last_used_at=token.last_used_at,
            expires_at=token.expires_at,
            is_current=False
        ))
    
    return SessionsListResponse(sessions=sessions, total=len(sessions))


# =========================
# REVOKE SPECIFIC SESSION
# =========================
@router.post("/sessions/{session_id}/revoke", response_model=LogoutResponse)
async def revoke_session(
    session_id: str,
    db: db_dependency,
    current_user: Annotated[Users, Depends(get_current_user)]
):
    # Find the token
    token_entry = db.query(RefreshToken).filter(
        RefreshToken.id == session_id,
        RefreshToken.user_id == current_user.id,
        RefreshToken.is_revoked == False
    ).first()
    
    if not token_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    # Revoke it
    revoke_refresh_token(token_entry, db)
    
    return LogoutResponse(
        message="Session revoked successfully",
        revoked_count=1
    )


# =========================
# CHANGE PASSWORD (KILLS ALL SESSIONS)
# =========================
@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    password_data: ChangePasswordRequest,
    db: db_dependency,
    current_user: Annotated[Users, Depends(get_current_user)]
):
    # Verify old password
    if not verify_password(password_data.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect current password"
        )
    
    # Validate new password
    if len(password_data.new_password) < 8:
        raise HTTPException(
            status_code=400,
            detail="New password must be at least 8 characters"
        )
    
    # Update password
    current_user.hashed_password = hash_password(password_data.new_password)
    
    # Revoke ALL refresh tokens (force re-login on all devices)
    revoke_all_user_tokens(current_user.id, db, keep_current_id=None)
    
    db.commit()
    
    return ChangePasswordResponse(
        message="Password changed successfully. Please login again on all devices."
    )


# =========================
# LEGACY TOKEN ENDPOINT (DEPRECATED - KEPT FOR COMPATIBILITY)
# =========================
@router.post("/token", response_model=Token)
async def login_for_access_token_legacy(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
    response: Response,
    db: db_dependency
):
    """Legacy endpoint - use /login instead"""
    return await login(form_data, request, response, db)


# =========================
# WEBSOCKET AUTHENTICATION
# =========================
def get_current_user_ws(token: str, db: Session) -> Optional[Users]:
    """Authenticate WebSocket connections with JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_id: str = payload.get("id")

        if username is None or user_id is None:
            return None

    except JWTError:
        return None

    user = db.query(Users).filter(Users.id == user_id).first()
    return user


# =========================
# CLEANUP FUNCTION (Call periodically via background task)
# =========================
def cleanup_expired_refresh_tokens(db: Session):
    """Delete expired tokens - call this from a background task"""
    deleted = cleanup_expired_tokens(db)
    return {"deleted_count": deleted}