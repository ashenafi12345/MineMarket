import os
import uuid
import shutil

from typing import Annotated, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    File,
    Form,
    HTTPException,
    Query
)

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import asc, desc, func

from database import get_db

from models import Product, ProductImage, Users

from schemas import ProductResponse, MineralCategory

from routers.auth import get_current_user


# =========================================
# ROUTER
# =========================================
router = APIRouter(
    prefix="/products",
    tags=["Products"]
)

# =========================================
# DEPENDENCIES
# =========================================
db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[Users, Depends(get_current_user)]

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# =========================================
# HELPER: Simple Levenshtein distance for SQLite
# =========================================
def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein distance between two strings"""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def similarity_score(s1: str, s2: str) -> float:
    """Calculate similarity score between 0 and 1"""
    if not s1 or not s2:
        return 0.0
    
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    
    distance = levenshtein_distance(s1.lower(), s2.lower())
    return 1.0 - (distance / max_len)


# =========================================
# CREATE PRODUCT
# =========================================
@router.post("/create", response_model=ProductResponse)
async def create_product(
    db: db_dependency,
    current_user: user_dependency,

    category: MineralCategory = Form(...),
    title: str = Form(...),
    mineral_type: str = Form(...),
    description: Optional[str] = Form(None),
    price: float = Form(...),
    quantity: float = Form(...),
    location: str = Form(...),

    images: List[UploadFile] = File(...)
):
    # Validate at least one image
    if not images or len(images) == 0:
        raise HTTPException(
            status_code=400,
            detail="At least one product image is required"
        )
    
    # Create product
    product = Product(
        category=category,
        title=title,
        mineral_type=mineral_type,
        description=description,
        price=price,
        quantity=quantity,
        location=location,
        owner_id=current_user.id
    )

    db.add(product)
    db.commit()
    db.refresh(product)

    # Save images
    for image in images:
        if not image.filename:
            continue

        ext = image.filename.split(".")[-1].lower()
        
        # Validate image extension
        if ext not in ["jpg", "jpeg", "png", "webp", "gif"]:
            continue
            
        filename = f"{uuid.uuid4()}.{ext}"
        path = os.path.join(UPLOAD_DIR, filename)

        with open(path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)

        db.add(ProductImage(
            image_url=f"/uploads/{filename}",
            product_id=product.id
        ))

    db.commit()
    db.refresh(product)

    # Load images before returning
    product = db.query(Product).options(
        joinedload(Product.images)
    ).filter(Product.id == product.id).first()

    return product


# =========================================
# GET ALL PRODUCTS (with pagination)
# =========================================
@router.get("", response_model=List[ProductResponse])
def get_products(
    db: db_dependency,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    offset = (page - 1) * limit
    
    products = db.query(Product).options(
        joinedload(Product.images)
    ).order_by(
        desc(Product.created_at)
    ).offset(offset).limit(limit).all()
    
    return products


# =========================================
# SEARCH + FILTER + SORT + PAGINATION
# =========================================
@router.get("/search", response_model=List[ProductResponse])
def search_products(
    db: db_dependency,

    # SEARCH
    search: Optional[str] = None,

    # FILTERS
    category: Optional[MineralCategory] = None,
    mineral_type: Optional[str] = None,
    location: Optional[str] = None,
    
    # PRICE RANGE
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,

    # SORT
    sort_by: Optional[str] = Query("created_at", description="created_at, price, title, quantity"),
    sort_order: Optional[str] = Query("desc", description="asc or desc"),

    # PAGINATION
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    # =========================================
    # SMART SEARCH FOR SQLITE
    # =========================================
    if search:
        # First, get all products with basic filters
        base_query = db.query(Product)
        
        if category:
            base_query = base_query.filter(Product.category == category)
        if mineral_type:
            base_query = base_query.filter(Product.mineral_type == mineral_type)
        if location:
            base_query = base_query.filter(Product.location.ilike(f"%{location}%"))
        if min_price is not None:
            base_query = base_query.filter(Product.price >= min_price)
        if max_price is not None:
            base_query = base_query.filter(Product.price <= max_price)
            
        all_products = base_query.all()
        
        # Calculate similarity scores in Python
        scored_products = []
        search_lower = search.lower()
        
        for product in all_products:
            # Check multiple fields for matching
            title_score = similarity_score(product.title, search_lower)
            desc_score = similarity_score(product.description or "", search_lower)
            mineral_score = similarity_score(product.mineral_type, search_lower)
            location_score = similarity_score(product.location, search_lower)
            
            # Use best score from any field
            best_score = max(title_score, desc_score, mineral_score, location_score)
            
            # Also check for partial matches (boost)
            if (search_lower in product.title.lower() or 
                search_lower in (product.description or "").lower() or
                search_lower in product.mineral_type.lower() or
                search_lower in product.location.lower()):
                best_score = max(best_score, 0.6)  # Boost partial matches
            
            if best_score > 0.25:  # Only keep products with >25% similarity
                scored_products.append((product, best_score))
        
        # Sort by similarity score
        scored_products.sort(key=lambda x: x[1], reverse=True)
        
        # Extract just the products
        filtered_products = [p[0] for p in scored_products]
        
        # Apply pagination
        offset = (page - 1) * limit
        paginated_products = filtered_products[offset:offset + limit]
        
        # Load images for these products
        product_ids = [p.id for p in paginated_products]
        if product_ids:
            result = db.query(Product).options(
                joinedload(Product.images)
            ).filter(Product.id.in_(product_ids)).all()
            
            # Preserve order
            product_dict = {p.id: p for p in result}
            return [product_dict[pid] for pid in product_ids if pid in product_dict]
        
        return []
    
    # =========================================
    # IF NO SEARCH TERM, USE REGULAR FILTERING
    # =========================================
    query = db.query(Product).options(joinedload(Product.images))
    
    if category:
        query = query.filter(Product.category == category)

    if mineral_type:
        query = query.filter(Product.mineral_type == mineral_type)

    if location:
        query = query.filter(Product.location.ilike(f"%{location}%"))
        
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
        
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    # SORTING
    if sort_by and hasattr(Product, sort_by):
        sort_column = getattr(Product, sort_by)
        if sort_order == "asc":
            query = query.order_by(asc(sort_column))
        else:
            query = query.order_by(desc(sort_column))
    else:
        # Default sort by created_at desc
        query = query.order_by(desc(Product.created_at))

    # PAGINATION
    offset = (page - 1) * limit
    
    return query.offset(offset).limit(limit).all()


# =========================================
# GET SEARCH SUGGESTIONS (AUTOCOMPLETE)
# =========================================
@router.get("/suggestions")
def get_search_suggestions(
    partial: str,
    db: db_dependency,
    limit: int = Query(5, ge=1, le=20)
):
    """Get autocomplete suggestions based on partial input"""
    
    all_titles = db.query(Product.title).distinct().all()
    
    suggestions = []
    partial_lower = partial.lower()
    
    for (title,) in all_titles:
        score = similarity_score(title, partial_lower)
        if score > 0.2:
            suggestions.append({"title": title, "score": float(score)})
    
    suggestions.sort(key=lambda x: x["score"], reverse=True)
    
    return suggestions[:limit]


# =========================================
# SINGLE PRODUCT
# =========================================
@router.get("/{product_id}", response_model=ProductResponse)
def get_single_product(
    product_id: str, 
    db: db_dependency
):
    product = db.query(Product).options(
        joinedload(Product.images)
    ).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return product


# =========================================
# GET PRODUCTS BY USER
# =========================================
@router.get("/user/{user_id}", response_model=List[ProductResponse])
def get_user_products(
    user_id: str,
    db: db_dependency,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    # Check if user exists
    user = db.query(Users).filter(Users.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    offset = (page - 1) * limit
    
    products = db.query(Product).options(
        joinedload(Product.images)
    ).filter(
        Product.owner_id == user_id
    ).order_by(
        desc(Product.created_at)
    ).offset(offset).limit(limit).all()
    
    return products


# =========================================
# EDIT PRODUCT
# =========================================
@router.put("/{product_id}", response_model=ProductResponse)
async def edit_product(
    product_id: str,
    db: db_dependency,
    current_user: user_dependency,

    category: Optional[MineralCategory] = Form(None),
    title: Optional[str] = Form(None),
    mineral_type: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    price: Optional[float] = Form(None),
    quantity: Optional[float] = Form(None),
    location: Optional[str] = Form(None),

    images: Optional[List[UploadFile]] = File(None)
):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.owner_id == current_user.id
    ).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found or you don't own it")

    # Update fields if provided
    if category is not None:
        product.category = category

    if title is not None:
        product.title = title

    if mineral_type is not None:
        product.mineral_type = mineral_type

    if description is not None:
        product.description = description

    if price is not None:
        product.price = price

    if quantity is not None:
        product.quantity = quantity

    if location is not None:
        product.location = location

    # UPDATE IMAGES (if new images provided)
    if images and len(images) > 0:
        # Delete old images
        for old in product.images:
            old_path = old.image_url.replace("/uploads/", "uploads/")
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except:
                    pass
            db.delete(old)

        db.commit()

        # Add new images
        for image in images:
            if not image.filename:
                continue
                
            ext = image.filename.split(".")[-1].lower()
            if ext not in ["jpg", "jpeg", "png", "webp", "gif"]:
                continue
                
            filename = f"{uuid.uuid4()}.{ext}"
            path = os.path.join(UPLOAD_DIR, filename)

            with open(path, "wb") as buffer:
                shutil.copyfileobj(image.file, buffer)

            db.add(ProductImage(
                image_url=f"/uploads/{filename}",
                product_id=product.id
            ))

    db.commit()
    db.refresh(product)
    
    # Load images before returning
    product = db.query(Product).options(
        joinedload(Product.images)
    ).filter(Product.id == product.id).first()

    return product


# =========================================
# DELETE PRODUCT
# =========================================
@router.delete("/{product_id}")
async def delete_product(
    product_id: str,
    db: db_dependency,
    current_user: user_dependency
):
    product = db.query(Product).filter(
        Product.id == product_id,
        Product.owner_id == current_user.id
    ).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found or you don't own it")

    # Delete all associated images from filesystem
    for img in product.images:
        img_path = img.image_url.replace("/uploads/", "uploads/")
        if os.path.exists(img_path):
            try:
                os.remove(img_path)
            except:
                pass

    # Delete product (images will be deleted automatically due to cascade)
    db.delete(product)
    db.commit()

    return {"message": "Product deleted successfully"}


# =========================================
# GET PRODUCT STATISTICS
# =========================================
@router.get("/stats/count")
def get_product_stats(db: db_dependency):
    """Get product statistics"""
    
    total_products = db.query(func.count(Product.id)).scalar()
    
    stats_by_category = db.query(
        Product.category,
        func.count(Product.id)
    ).group_by(Product.category).all()
    
    return {
        "total_products": total_products,
        "by_category": [{"category": cat, "count": count} for cat, count in stats_by_category]
    }