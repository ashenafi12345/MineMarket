from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from database import get_db
from models import Favorite, Product, Users
from routers.auth import get_current_user
from schemas import FavoriteResponse, ProductResponse

from sqlalchemy.orm import joinedload

router = APIRouter(prefix="/favorites", tags=["Favorites"])


# =========================
# DEPENDENCIES
# =========================
db_dependency = Depends(get_db)
user_dependency = Depends(get_current_user)


# =========================
# ADD TO FAVORITES
# =========================
@router.post("/{product_id}")
def add_favorite(
    product_id: str,
    db: Session = db_dependency,
    current_user: Users = user_dependency
):

    # check product exists
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # prevent duplicates
    existing = db.query(Favorite).filter(
        Favorite.user_id == current_user.id,
        Favorite.product_id == product_id
    ).first()

    if existing:
        return {"message": "Already in favorites"}

    fav = Favorite(
        user_id=current_user.id,
        product_id=product_id
    )

    db.add(fav)
    db.commit()
    db.refresh(fav)

    return {"message": "Added to favorites"}


# =========================
# REMOVE FROM FAVORITES
# =========================
@router.delete("/{product_id}")
def remove_favorite(
    product_id: str,
    db: Session = db_dependency,
    current_user: Users = user_dependency
):

    fav = db.query(Favorite).filter(
        Favorite.user_id == current_user.id,
        Favorite.product_id == product_id
    ).first()

    if not fav:
        raise HTTPException(status_code=404, detail="Not in favorites")

    db.delete(fav)
    db.commit()

    return {"message": "Removed from favorites"}


# =========================
# GET MY FAVORITES (TikTok Saved Page)
# =========================
@router.get("/", response_model=List[ProductResponse])
def get_my_favorites(
    db: Session = db_dependency,
    current_user: Users = user_dependency
):

    favorites = db.query(Product).join(Favorite).options(
        joinedload(Product.images)
    ).filter(
        Favorite.user_id == current_user.id
    ).all()

    return favorites