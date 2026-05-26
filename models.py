import uuid
import json
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Text,
    ForeignKey,
    Boolean,
    Float,
    DateTime,
    Numeric,
    func,
    UniqueConstraint,
    Index
)

from sqlalchemy.orm import relationship


from database import Base


# =========================================
# USERS MODEL (ONLY ONE DEFINITION)
# =========================================
class Users(Base):
    __tablename__ = "users"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    last_seen = Column(DateTime, nullable=True)

    # =========================================
    # AUTH
    # =========================================
    email = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)

    # =========================================
    # BASIC INFO
    # =========================================
    first_name = Column(String)
    last_name = Column(String)

    profile_image = Column(String)
    bio = Column(Text)

    company_name = Column(String)

    # =========================================
    # BUSINESS TYPE
    # =========================================
    business_type = Column(String)

    # =========================================
    # CONTACT & SOCIAL
    # =========================================
    phone_number = Column(String)
    whatsapp_number = Column(String)
    telegram_username = Column(String)
    website = Column(String)

    # =========================================
    # LOCATION
    # =========================================
    country = Column(String)
    region = Column(String)
    city = Column(String)

    # =========================================
    # MINERAL SPECIALIZATION
    # =========================================
    mineral_specialization = Column(String)

    # =========================================
    # VERIFICATION
    # =========================================
    is_verified = Column(Boolean, default=False)
    is_email_verified = Column(Boolean, default=False)

    # =========================================
    # SYSTEM
    # =========================================
    is_active = Column(Boolean, default=True)

    role = Column(String, default="user")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # =========================================
    # PRODUCT RELATIONSHIPS
    # =========================================
    products = relationship(
        "Product",
        back_populates="owner",
        cascade="all, delete"
    )
    
    favorites = relationship(
        "Favorite",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    
    comments = relationship(
        "Comment",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # =========================================
    # CHAT RELATIONSHIPS (FIXED - NO lazy="dynamic")
    # =========================================
    sent_messages = relationship(
        "Message",
        foreign_keys="Message.sender_id",
        back_populates="sender",
        cascade="all, delete-orphan"
    )

    received_messages = relationship(
        "Message",
        foreign_keys="Message.receiver_id",
        back_populates="receiver",
        cascade="all, delete-orphan"
    )

    conversations_as_p1 = relationship(
        "Conversation",
        foreign_keys="Conversation.participant1_id",
        back_populates="participant1",
        cascade="all, delete-orphan"
    )

    conversations_as_p2 = relationship(
        "Conversation",
        foreign_keys="Conversation.participant2_id",
        back_populates="participant2",
        cascade="all, delete-orphan"
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

    category = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False, index=True)
    mineral_type = Column(String, nullable=False, index=True)

    description = Column(Text)

    price = Column(Numeric(12, 2))
    quantity = Column(Float)

    location = Column(String, index=True)

    status = Column(String, default="active")

    owner_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True  # Added index for performance
    )

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    owner = relationship("Users", back_populates="products")
    images = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete"
    )
    favorites = relationship(
        "Favorite",
        back_populates="product",
        cascade="all, delete-orphan"
    )
    comments = relationship(
        "Comment",
        back_populates="product",
        cascade="all, delete-orphan"
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

    image_url = Column(String, nullable=False)

    product_id = Column(
        String,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True  # Added index for performance
    )

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    product = relationship(
        "Product",
        back_populates="images"
    )


# =========================================
# FAVORITE MODEL
# =========================================
class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True  # Added index for performance
    )

    product_id = Column(
        String,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True  # Added index for performance
    )

    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    user = relationship("Users", back_populates="favorites")
    product = relationship("Product", back_populates="favorites")


# =========================================
# COMMENT MODEL
# =========================================
class Comment(Base):
    __tablename__ = "comments"

    id = Column(
        String,
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True  # Added index for performance
    )

    product_id = Column(
        String,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True  # Added index for performance
    )

    text = Column(Text, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # relationships
    user = relationship("Users", back_populates="comments")
    product = relationship("Product", back_populates="comments")


# =========================================
# CONVERSATION MODEL (CHAT) - FIXED with UNIQUE CONSTRAINT
# =========================================
class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(
        String, 
        primary_key=True, 
        default=lambda: str(uuid.uuid4())
    )
    
    # IMPORTANT: Indexed for performance
    participant1_id = Column(
        String, 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    participant2_id = Column(
        String, 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    
    # Metadata
    last_message = Column(Text, nullable=True)
    last_message_time = Column(
        DateTime, 
        server_default=func.now(), 
        onupdate=func.now(), 
        index=True
    )
    last_message_sender_id = Column(
        String, 
        ForeignKey("users.id"), 
        nullable=True,
        index=True
    )
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # CRITICAL FIX: Add unique constraint to prevent duplicate conversations
    # This ensures database-level protection against race conditions
    __table_args__ = (
        UniqueConstraint(
            "participant1_id",
            "participant2_id",
            name="unique_conversation"
        ),
    )
    
    # Relationships
    participant1 = relationship(
        "Users", 
        foreign_keys=[participant1_id],
        back_populates="conversations_as_p1"
    )
    participant2 = relationship(
        "Users", 
        foreign_keys=[participant2_id],
        back_populates="conversations_as_p2"
    )
    messages = relationship(
        "Message", 
        back_populates="conversation", 
        cascade="all, delete-orphan"
    )
    
    def get_other_participant(self, user_id: str) -> str:
        """Get the other participant in the conversation"""
        return self.participant2_id if self.participant1_id == user_id else self.participant1_id


# =========================================
# MESSAGE MODEL (CHAT)
# =========================================
class Message(Base):
    __tablename__ = "messages"
    
    id = Column(
        String, 
        primary_key=True, 
        default=lambda: str(uuid.uuid4())
    )
    
    # Foreign keys with indexes for performance
    conversation_id = Column(
        String, 
        ForeignKey("conversations.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    
    sender_id = Column(
        String, 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    
    receiver_id = Column(
        String, 
        ForeignKey("users.id", ondelete="CASCADE"), 
        nullable=False, 
        index=True
    )
    
    # Message content
    content = Column(Text, nullable=False)
    
    # Message type for future multimedia support
    message_type = Column(String, default="text")  # text, image, audio, video, file, location
    
    # Attachment support
    attachment_url = Column(String, nullable=True)
    attachment_metadata = Column(Text, nullable=True)  # JSON string for additional data
    
    # Read status
    is_read = Column(Boolean, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    
    # Edit support
    is_edited = Column(Boolean, default=False)
    edited_at = Column(DateTime, nullable=True)
    edit_history = Column(Text, nullable=True)  # JSON string of previous versions
    
    # Soft delete
    is_deleted = Column(Boolean, default=False, index=True)
    deleted_at = Column(DateTime, nullable=True)
    deleted_by = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    
    # Reply to message
    reply_to_id = Column(String, ForeignKey("messages.id"), nullable=True, index=True)
    
    # Reactions (JSON)
    reactions = Column(Text, nullable=True)  # {"👍": ["user1", "user2"], "❤️": ["user3"]}
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now(), index=True)
    
    # Relationships
    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("Users", foreign_keys=[sender_id], back_populates="sent_messages")
    receiver = relationship("Users", foreign_keys=[receiver_id], back_populates="received_messages")
    reply_to = relationship("Message", remote_side=[id])
    deleted_by_user = relationship("Users", foreign_keys=[deleted_by])
    
    # Composite indexes
    __table_args__ = (
        Index("idx_messages_receiver_read", "receiver_id", "is_read"),
    )
    
    # =========================================
    # HELPER METHODS WITH SAFE JSON PARSING
    # =========================================
    
    def soft_delete(self, user_id: str):
        """Soft delete message"""
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()
        self.deleted_by = user_id
    
    def mark_as_edited(self, new_content: str):
        """Mark message as edited with history"""
        try:
            # Safe JSON parsing for edit history
            history = []
            if self.edit_history:
                try:
                    history = json.loads(self.edit_history)
                    if not isinstance(history, list):
                        history = []
                except (json.JSONDecodeError, TypeError):
                    history = []
            
            history.append({
                "content": self.content,
                "edited_at": datetime.utcnow().isoformat()
            })
            
            # Keep only last 10 edits
            if len(history) > 10:
                history = history[-10:]
            
            self.edit_history = json.dumps(history)
            self.content = new_content
            self.is_edited = True
            self.edited_at = datetime.utcnow()
            
        except Exception as e:
            # Fallback - at least mark as edited without history
            self.content = new_content
            self.is_edited = True
            self.edited_at = datetime.utcnow()
    
    def add_reaction(self, reaction: str, user_id: str):
        """Add reaction to message"""
        try:
            # Safe JSON parsing for reactions
            reactions = {}
            if self.reactions:
                try:
                    reactions = json.loads(self.reactions)
                    if not isinstance(reactions, dict):
                        reactions = {}
                except (json.JSONDecodeError, TypeError):
                    reactions = {}
            
            if reaction not in reactions:
                reactions[reaction] = []
            
            if user_id not in reactions[reaction]:
                reactions[reaction].append(user_id)
            
            self.reactions = json.dumps(reactions)
            
        except Exception as e:
            # If reaction fails, just ignore
            pass
    
    def remove_reaction(self, reaction: str, user_id: str):
        """Remove reaction from message"""
        try:
            # Safe JSON parsing for reactions
            reactions = {}
            if self.reactions:
                try:
                    reactions = json.loads(self.reactions)
                    if not isinstance(reactions, dict):
                        reactions = {}
                except (json.JSONDecodeError, TypeError):
                    reactions = {}
            
            if reaction in reactions and user_id in reactions[reaction]:
                reactions[reaction].remove(user_id)
                if not reactions[reaction]:
                    del reactions[reaction]
            
            self.reactions = json.dumps(reactions)
            
        except Exception as e:
            # If removal fails, just ignore
            pass
    
    def get_reactions(self) -> dict:
        """Safely get reactions as dict"""
        try:
            if self.reactions:
                reactions = json.loads(self.reactions)
                if isinstance(reactions, dict):
                    return reactions
        except (json.JSONDecodeError, TypeError):
            pass
        return {}
    
    def get_edit_history(self) -> list:
        """Safely get edit history as list"""
        try:
            if self.edit_history:
                history = json.loads(self.edit_history)
                if isinstance(history, list):
                    return history
        except (json.JSONDecodeError, TypeError):
            pass
        return []