import os
import uuid

from typing import Annotated, List, Optional

from sqlalchemy import asc, desc

from routers.auth import get_current_user
from routers.products import similarity_score
from schemas import (
    ProductResponse,
    UserOut,
    UserProfileResponse,
    BusinessType
)

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    UploadFile,
    File
)

from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import Product, Users


# =========================================
# ROUTER
# =========================================
router = APIRouter(
    prefix="/users",
    tags=["users"]
)


# =========================================
# DEPENDENCIES
# =========================================
user_dependency = Annotated[
    Users,
    Depends(get_current_user)
]

db_dependency = Annotated[
    Session,
    Depends(get_db)
]


# =========================================
# UPLOAD CONFIG
# =========================================
UPLOAD_DIR = "uploads/profiles"

MAX_FILE_SIZE = 5 * 1024 * 1024

ALLOWED_EXTENSIONS = [
    "jpg",
    "jpeg",
    "png",
    "webp"
]

os.makedirs(UPLOAD_DIR, exist_ok=True)


# =========================================
# VALID BUSINESS TYPES
# =========================================
VALID_BUSINESS_TYPES = [
    "supplier",
    "buyer",
    "mining_site_owner",
    "exporter",
    "investor",
    "transporter",
    "broker",
    "equipment_seller",
    "refinery_owner",
    "geologist"
]


# =========================================
# FIX INVALID SQLITE VALUES
# =========================================
def clean_user_business_type(user):
    if user.business_type not in VALID_BUSINESS_TYPES:
        user.business_type = None
    return user


# =========================================
# GET MY PROFILE
# =========================================
@router.get(
    "/me",
    response_model=UserProfileResponse
)
async def get_my_profile(
    current_user: user_dependency
):
    current_user = clean_user_business_type(current_user)
    return current_user


# =========================================
# EDIT PROFILE
# =========================================
@router.put(
    "/edit-profile",
    response_model=UserProfileResponse
)
async def edit_profile(
    db: db_dependency,
    current_user: user_dependency,

    # BASIC
    username: Optional[str] = Form(None),
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),

    # BUSINESS
    business_type: Optional[str] = Form(None),
    company_name: Optional[str] = Form(None),

    # PROFILE
    bio: Optional[str] = Form(None),

    # IMAGE
    profile_image: Optional[UploadFile] = File(None),

    # SOCIAL
    whatsapp_number: Optional[str] = Form(None),
    telegram_username: Optional[str] = Form(None),
    website: Optional[str] = Form(None),

    # LOCATION
    country: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    city: Optional[str] = Form(None),

    # MINERALS
    mineral_specialization: Optional[str] = Form(None),
):

    user = db.query(Users).filter(
        Users.id == current_user.id
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # =========================================
    # USERNAME CHECK
    # =========================================
    if username:
        existing_user = db.query(Users).filter(
            Users.username == username,
            Users.id != current_user.id
        ).first()

        if existing_user:
            raise HTTPException(
                status_code=400,
                detail="Username already taken"
            )

        user.username = username

    # =========================================
    # BASIC INFO
    # =========================================
    if first_name:
        user.first_name = first_name

    if last_name:
        user.last_name = last_name

    if phone_number:
        user.phone_number = phone_number

    # =========================================
    # BUSINESS TYPE VALIDATION
    # =========================================
    if business_type:
        if business_type not in VALID_BUSINESS_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Invalid business type"
            )

        user.business_type = business_type

    if company_name:
        user.company_name = company_name

    # =========================================
    # PROFILE
    # =========================================
    if bio:
        user.bio = bio

    # =========================================
    # PROFILE IMAGE
    # =========================================
    if profile_image:
        ext = profile_image.filename.split(".")[-1].lower()

        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail="Invalid image type"
            )

        content = await profile_image.read()

        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail="Image too large"
            )

        user_folder = os.path.join(
            UPLOAD_DIR,
            user.id
        )

        os.makedirs(user_folder, exist_ok=True)

        filename = f"{uuid.uuid4()}.{ext}"

        file_path = os.path.join(
            user_folder,
            filename
        )

        with open(file_path, "wb") as f:
            f.write(content)

        # delete old image
        if user.profile_image:
            try:
                old_path = user.profile_image.replace(
                    "/uploads/",
                    "uploads/"
                )

                if os.path.exists(old_path):
                    os.remove(old_path)
            except:
                pass

        user.profile_image = (
            f"/uploads/profiles/{user.id}/{filename}"
        )

    # =========================================
    # SOCIAL
    # =========================================
    if whatsapp_number:
        user.whatsapp_number = whatsapp_number

    if telegram_username:
        user.telegram_username = telegram_username

    if website:
        user.website = website

    # =========================================
    # LOCATION
    # =========================================
    if country:
        user.country = country

    if region:
        user.region = region

    if city:
        user.city = city

    # =========================================
    # MINERAL
    # =========================================
    if mineral_specialization:
        user.mineral_specialization = mineral_specialization

    # =========================================
    # SAVE
    # =========================================
    db.commit()
    db.refresh(user)

    user = clean_user_business_type(user)

    return user


# =========================================
# MY PRODUCTS
# =========================================
@router.get(
    "/my_posts",
    response_model=List[ProductResponse]
)
def get_my_products(
    db: db_dependency,
    current_user: user_dependency
):
    return db.query(Product).options(
        joinedload(Product.images)
    ).filter(
        Product.owner_id == current_user.id
    ).all()


# =========================================
# GET ALL USERS
# =========================================
@router.get(
    "/",
    response_model=list[UserOut]
)
def get_users(db: db_dependency):
    users = db.query(Users).all()
    cleaned_users = []

    for user in users:
        cleaned_users.append(
            clean_user_business_type(user)
        )

    return cleaned_users


# =========================================
# SEARCH USERS - IMPORTANT: This must be BEFORE /{user_id}
# =========================================
@router.get("/search", response_model=List[UserOut])
def search_users(
    db: db_dependency,
    
    # SEARCH
    search: Optional[str] = None,
    
    # FILTERS
    business_type: Optional[BusinessType] = None,
    is_verified: Optional[bool] = None,
    
    # SORT
    sort_by: Optional[str] = Query("created_at", description="Sort by field"),
    sort_order: Optional[str] = Query("desc", description="asc or desc"),
    
    # PAGINATION
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
):
    query = db.query(Users)
    
    # =========================================
    # SMART SEARCH (Python ranking)
    # =========================================
    if search:
        all_users = query.all()
        
        scored_users = []
        search_lower = search.lower()
        
        for user in all_users:
            # =============================
            # MULTI-FIELD MATCHING
            # =============================
            username_score = similarity_score(user.username or "", search_lower)
            company_score = similarity_score(user.company_name or "", search_lower)
            first_name_score = similarity_score(user.first_name or "", search_lower)
            last_name_score = similarity_score(user.last_name or "", search_lower)
            bio_score = similarity_score(user.bio or "", search_lower)
            mineral_score = similarity_score(user.mineral_specialization or "", search_lower)
            
            location_text = " ".join([
                user.country or "",
                user.region or "",
                user.city or ""
            ])
            
            location_score = similarity_score(location_text, search_lower)
            
            # =============================
            # BEST SCORE PICK
            # =============================
            best_score = max(
                username_score,
                company_score,
                first_name_score,
                last_name_score,
                bio_score,
                mineral_score,
                location_score
            )
            
            # =============================
            # BOOST FOR EXACT MATCHES
            # =============================
            if (
                search_lower in (user.username or "").lower() or
                search_lower in (user.company_name or "").lower() or
                search_lower in (user.first_name or "").lower() or
                search_lower in (user.last_name or "").lower() or
                search_lower in (user.bio or "").lower() or
                search_lower in (user.mineral_specialization or "").lower() or
                search_lower in location_text.lower()
            ):
                best_score = max(best_score, 0.7)
            
            # =============================
            # KEEP ONLY RELEVANT USERS
            # =============================
            if best_score > 0.25:
                scored_users.append((user, best_score))
        
        # =============================
        # SORT BY RELEVANCE
        # =============================
        scored_users.sort(key=lambda x: x[1], reverse=True)
        
        filtered_users = [u[0] for u in scored_users]
        
        # =============================
        # PAGINATION
        # =============================
        offset = (page - 1) * limit
        paginated = filtered_users[offset:offset + limit]
        
        return [clean_user_business_type(u) for u in paginated]
    
    # =========================================
    # NORMAL FILTERING (NO SEARCH)
    # =========================================
    if business_type:
        query = query.filter(Users.business_type == business_type)
    
    if is_verified is not None:
        query = query.filter(Users.is_verified == is_verified)
    
    # =========================================
    # SORTING (when no search)
    # =========================================
    if sort_by and hasattr(Users, sort_by):
        sort_column = getattr(Users, sort_by)
        
        if sort_order == "asc":
            query = query.order_by(asc(sort_column))
        else:
            query = query.order_by(desc(sort_column))
    else:
        # Default sort by created_at desc
        query = query.order_by(desc(Users.created_at))
    
    # =========================================
    # PAGINATION
    # =========================================
    offset = (page - 1) * limit
    
    users = query.offset(offset).limit(limit).all()
    
    return [clean_user_business_type(u) for u in users]


# =========================================
# GET SINGLE USER - This must be AFTER /search
# =========================================
@router.get(
    "/{user_id}",
    response_model=UserProfileResponse
)
def get_user(
    user_id: str,
    db: db_dependency
):
    user = db.query(Users).filter(
        Users.id == user_id
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    user = clean_user_business_type(user)
    return user


# =========================================
# GET USER POSTS (TikTok STYLE FEED)
# =========================================
@router.get("/{user_id}/posts", response_model=List[ProductResponse])
def get_user_posts(
    user_id: str,
    db: db_dependency,

    # pagination (IMPORTANT for production)
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
):
    # =========================================
    # CHECK USER EXISTS
    # =========================================
    user = db.query(Users).filter(Users.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # =========================================
    # PAGINATION
    # =========================================
    offset = (page - 1) * limit

    # =========================================
    # GET USER POSTS (PRODUCTS)
    # =========================================
    posts = (
        db.query(Product)
        .options(joinedload(Product.images))
        .filter(Product.owner_id == user_id)
        .order_by(Product.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return posts