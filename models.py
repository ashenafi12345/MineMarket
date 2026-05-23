import uuid

from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Text,
    ForeignKey,
    Boolean,
    Float,
    DateTime,
    Numeric
)

from sqlalchemy.orm import relationship

from database import Base


# =========================================
# USERS MODEL
# =========================================
class Users(Base):
    __tablename__ = "users"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    email = Column(
        String,
        unique=True,
        nullable=False,
        index=True
    )

    username = Column(
        String,
        unique=True,
        nullable=False,
        index=True
    )

    first_name = Column(String)

    last_name = Column(String)

    hashed_password = Column(
        String,
        nullable=False
    )

    is_active = Column(
        Boolean,
        default=True
    )

    role = Column(
        String,
        default="user"
    )

    phone_number = Column(String)

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relationships
    products = relationship(
        "Product",
        back_populates="owner",
        cascade="all, delete"
    )


# =========================================
# PRODUCT MODEL
# =========================================
class Product(Base):
    __tablename__ = "products"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    # NEW CATEGORY FIELD
    category = Column(
        String,
        nullable=False,
        index=True
    )

    title = Column(
        String,
        nullable=False,
        index=True
    )

    mineral_type = Column(
        String,
        nullable=False,
        index=True
    )

    description = Column(Text)

    price = Column(
        Numeric(12, 2)
    )

    quantity = Column(
        Float
    )

    location = Column(
        String,
        index=True
    )

    status = Column(
        String,
        default="active"
    )

    owner_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relationships
    owner = relationship(
        "Users",
        back_populates="products"
    )

    images = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete"
    )


# =========================================
# PRODUCT IMAGE MODEL
# =========================================
class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    image_url = Column(
        String,
        nullable=False
    )

    product_id = Column(
        String,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )

    # Relationships
    product = relationship(
        "Product",
        back_populates="images"
    )