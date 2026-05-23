from datetime import datetime
from typing import List, Optional
from enum import Enum

from pydantic import BaseModel, ConfigDict


class MineralCategory(str, Enum):
    metallic = "Metallic minerals"
    industrial = "Industrial minerals"
    energy = "Energy minerals"
    gemstones = "Gemstones"


# =========================================
# PRODUCT IMAGE SCHEMA
# =========================================
class ProductImageResponse(BaseModel):
    id: str
    image_url: str

    model_config = ConfigDict(from_attributes=True)


# =========================================
# PRODUCT RESPONSE SCHEMA
# =========================================
class ProductResponse(BaseModel):
    id: str
    category: MineralCategory
    title: str
    mineral_type: str
    description: Optional[str]
    price: float
    quantity: float
    location: str
    status: str
    owner_id: str
    created_at: datetime
    updated_at: datetime

    images: List[ProductImageResponse] = []

    model_config = ConfigDict(from_attributes=True)


# =========================================
# USER RESPONSE SCHEMA
# =========================================
class UserProfileResponse(BaseModel):
    id: str
    email: str
    username: str

    first_name: Optional[str]
    last_name: Optional[str]
    phone_number: Optional[str]

    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)