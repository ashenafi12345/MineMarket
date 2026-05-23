from typing import Annotated, List

from routers.auth import get_current_user

from schemas import (
    ProductResponse,
    UserProfileResponse
)

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException
)

from sqlalchemy.orm import Session, joinedload

from database import get_db

from models import Product, Users


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
# ROUTER
# =========================================
router = APIRouter(
    prefix="/users",
    tags=["users"]
)


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

    username: str = Form(None),

    first_name: str = Form(None),

    last_name: str = Form(None),

    phone_number: str = Form(None)
):

    user = db.query(Users).filter(
        Users.id == current_user.id
    ).first()

    # =========================================
    # CHECK USERNAME
    # =========================================
    if username is not None:

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
    # UPDATE FIELDS
    # =========================================
    if first_name is not None:
        user.first_name = first_name

    if last_name is not None:
        user.last_name = last_name

    if phone_number is not None:
        user.phone_number = phone_number

    # =========================================
    # SAVE
    # =========================================
    db.commit()

    db.refresh(user)

    return user


# =========================================
# MY PRODUCTS
# =========================================
@router.get("/my_posts", response_model=List[ProductResponse])
def get_my_products(
    db: db_dependency,
    current_user: user_dependency
):

    return db.query(Product).options(
        joinedload(Product.images)
    ).filter(
        Product.owner_id == current_user.id
    ).all()
