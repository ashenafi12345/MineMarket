from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from database import get_db
from models import Comment, Product, Users
from routers.auth import get_current_user
from schemas import CommentResponse

router = APIRouter(prefix="/comments", tags=["Comments"])


db_dependency = Depends(get_db)
user_dependency = Depends(get_current_user)


# =========================
# ADD COMMENT
# =========================
@router.post("/{product_id}")
def add_comment(
    product_id: str,
    text: str,
    db: Session = db_dependency,
    current_user: Users = user_dependency
):

    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    comment = Comment(
        user_id=current_user.id,
        product_id=product_id,
        text=text
    )

    db.add(comment)
    db.commit()
    db.refresh(comment)

    return {"message": "Comment added"}



@router.get("/{product_id}", response_model=List[CommentResponse])
def get_comments(
    product_id: str,
    db: Session = db_dependency
):

    comments = db.query(Comment).options(
        joinedload(Comment.user)
    ).filter(
        Comment.product_id == product_id
    ).order_by(
        Comment.created_at.asc()
    ).all()

    return comments

@router.put("/{comment_id}")
def edit_comment(
    comment_id: str,
    text: str = Form(...),
    db: Session = db_dependency,
    current_user: Users = user_dependency
):

    comment = db.query(Comment).filter(Comment.id == comment_id).first()

    if not comment:
        raise HTTPException(404, "Comment not found")

    # ONLY COMMENT OWNER CAN EDIT
    if comment.user_id != current_user.id:
        raise HTTPException(403, "Only comment owner can edit")

    comment.text = text

    db.commit()
    db.refresh(comment)

    return {"message": "Comment updated"}


@router.delete("/{comment_id}")
def delete_comment(
    comment_id: str,
    db: Session = db_dependency,
    current_user: Users = user_dependency
):

    comment = db.query(Comment).filter(Comment.id == comment_id).first()

    if not comment:
        raise HTTPException(404, "Comment not found")

    product = db.query(Product).filter(Product.id == comment.product_id).first()

    if not product:
        raise HTTPException(404, "Post not found")

    # permissions
    is_comment_owner = comment.user_id == current_user.id
    is_post_owner = product.owner_id == current_user.id

    if not (is_comment_owner or is_post_owner):
        raise HTTPException(403, "Not allowed to delete this comment")

    db.delete(comment)
    db.commit()

    return {"message": "Comment deleted"}