from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field



# =========================================
# MINERAL CATEGORY ENUM
# =========================================
class MineralCategory(str, Enum):
    metallic = "Metallic minerals"
    industrial = "Industrial minerals"
    energy = "Energy minerals"
    gemstones = "Gemstones"


# =========================================
# BUSINESS TYPE ENUM
# =========================================
class BusinessType(str, Enum):
    supplier = "supplier"
    buyer = "buyer"
    mining_site_owner = "mining_site_owner"
    exporter = "exporter"
    investor = "investor"
    transporter = "transporter"
    broker = "broker"
    equipment_seller = "equipment_seller"
    refinery_owner = "refinery_owner"
    geologist = "geologist"


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
# CREATE USER SCHEMA
# =========================================
class CreateUserRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

    first_name: str
    last_name: str
    phone_number: str

    business_type: BusinessType

    company_name: Optional[str] = None

    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None


# =========================================
# LOGIN TOKEN SCHEMA (UPDATED)
# =========================================
class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int  # Seconds until token expires


# =========================================
# REFRESH TOKEN SCHEMAS (NEW)
# =========================================
class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


# =========================================
# LOGOUT SCHEMAS (NEW)
# =========================================
class LogoutResponse(BaseModel):
    message: str
    revoked_count: int


# =========================================
# SESSION MANAGEMENT SCHEMAS (NEW)
# =========================================
class SessionInfo(BaseModel):
    id: str
    device_info: Optional[str]
    ip_address: Optional[str]
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: datetime
    is_current: bool = False

    model_config = ConfigDict(from_attributes=True)


class SessionsListResponse(BaseModel):
    sessions: List[SessionInfo]
    total: int


# =========================================
# CHANGE PASSWORD SCHEMA (NEW)
# =========================================
class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class ChangePasswordResponse(BaseModel):
    message: str


# =========================================
# TOKEN DATA SCHEMA
# =========================================
class TokenData(BaseModel):
    username: Optional[str] = None


# =========================================
# USER PROFILE RESPONSE
# =========================================
class UserProfileResponse(BaseModel):
    id: str

    email: EmailStr
    username: str

    first_name: Optional[str]
    last_name: Optional[str]

    phone_number: Optional[str]

    business_type: Optional[BusinessType]

    company_name: Optional[str]

    country: Optional[str]
    region: Optional[str]
    city: Optional[str]

    profile_image: Optional[str] = None
    bio: Optional[str] = None

    whatsapp_number: Optional[str] = None
    telegram_username: Optional[str] = None
    website: Optional[str] = None

    mineral_specialization: Optional[str] = None

    is_verified: bool
    is_email_verified: bool
    is_active: bool

    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserOut(BaseModel):
    id: str   
    username: str
    profile_image: Optional[str] = None
    business_type: Optional[BusinessType]
    company_name: Optional[str]
    mineral_specialization: Optional[str] = None
    is_verified: bool
    bio: Optional[str] = None

    class Config:
        from_attributes = True


# =========================================
# FavoriteResponse
# =========================================

class FavoriteResponse(BaseModel):
    id: str
    product_id: str
    created_at: datetime

    class Config:
        from_attributes = True



# =========================================
# Comment
# =========================================
class CommentUser(BaseModel):
    id: str
    username: str
    profile_image: str | None = None

    class Config:
        from_attributes = True


class CommentResponse(BaseModel):
    id: str
    text: str
    created_at: datetime
    user: CommentUser

    class Config:
        from_attributes = True


# =========================================
# CHAT SCHEMAS
# =========================================

class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    LOCATION = "location"


class MessageCreate(BaseModel):
    receiver_id: str
    content: str = Field(..., min_length=1, max_length=5000)
    message_type: MessageType = MessageType.TEXT
    attachment_url: Optional[str] = None
    reply_to_id: Optional[str] = None


class MessageEdit(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


class MessageReaction(BaseModel):
    reaction: str = Field(..., min_length=1, max_length=10)


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    sender_id: str
    receiver_id: str
    content: str
    message_type: MessageType
    attachment_url: Optional[str]
    is_read: bool
    is_edited: bool
    is_deleted: bool
    read_at: Optional[datetime]
    edited_at: Optional[datetime]
    created_at: datetime
    reply_to: Optional['MessageResponse'] = None
    
    class Config:
        from_attributes = True


class ConversationResponse(BaseModel):
    id: str
    other_user_id: str
    other_user_name: str
    other_user_username: str
    other_user_profile_image: Optional[str]
    other_user_business_type: Optional[str]
    last_message: Optional[str]
    last_message_time: datetime
    last_message_sender_id: Optional[str]
    unread_count: int
    
    class Config:
        from_attributes = True


class ConversationDetailResponse(BaseModel):
    id: str
    messages: List[MessageResponse]
    other_user_id: str
    other_user_name: str
    other_user_username: str
    other_user_profile_image: Optional[str]
    page: int = 1
    total_pages: int = 1
    has_next: bool = False
    total_messages: int = 0
    
    class Config:
        from_attributes = True


class StartConversationResponse(BaseModel):
    conversation_id: str
    is_new: bool
    other_user_id: str
    other_user_name: str


class MarkAsReadRequest(BaseModel):
    message_ids: List[str]


class UnreadCountResponse(BaseModel):
    unread_count: int
    conversations_with_unread: Dict[str, int]


# =========================================
# UPDATE FORWARD REFERENCES
# =========================================
MessageResponse.model_rebuild()