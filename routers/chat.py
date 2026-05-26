# routers/chat.py
import json
from typing import Annotated, List, Optional
from datetime import datetime

from fastapi import (
    APIRouter, 
    Depends, 
    HTTPException, 
    Query, 
    status,
    WebSocket,
    WebSocketDisconnect,
    BackgroundTasks
)
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc, func
from sqlalchemy.exc import IntegrityError

from database import get_db, SessionLocal
from models import Users, Conversation, Message
from schemas import (
    MessageCreate,
    MessageEdit,
    MessageReaction,
    MessageResponse,
    ConversationResponse,
    ConversationDetailResponse,
    StartConversationResponse,
    MarkAsReadRequest,
    UnreadCountResponse,
    MessageType
)
from routers.auth import get_current_user


# =========================================
# ROUTER
# =========================================
router = APIRouter(
    prefix="/chat",
    tags=["Chat"]
)

# =========================================
# DEPENDENCIES
# =========================================
db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[Users, Depends(get_current_user)]


# =========================================
# WEBSOCKET MANAGER (Multi-device support)
# =========================================
class ConnectionManager:
    def __init__(self):
        # Store active connections: {user_id: [websocket1, websocket2, ...]}
        self.active_connections: dict[str, list[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        
        self.active_connections[user_id].append(websocket)
        print(f"✅ User {user_id} connected. Total devices: {len(self.active_connections[user_id])}. Online users: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        
        print(f"❌ User {user_id} disconnected. Online users: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: dict, user_id: str) -> int:
        """Send message to all devices of a user. Returns number of successful sends."""
        if user_id not in self.active_connections:
            return 0
        
        disconnected = []
        success_count = 0
        
        for ws in self.active_connections[user_id]:
            try:
                await ws.send_json(message)
                success_count += 1
            except Exception:
                disconnected.append(ws)
        
        # Clean up disconnected websockets
        for ws in disconnected:
            self.disconnect(ws, user_id)
        
        return success_count
    
    def is_user_online(self, user_id: str) -> bool:
        """Check if user has any active connection"""
        return user_id in self.active_connections and len(self.active_connections[user_id]) > 0
    
    def get_device_count(self, user_id: str) -> int:
        """Get number of devices connected for a user"""
        return len(self.active_connections.get(user_id, []))

manager = ConnectionManager()


# =========================================
# HELPER FUNCTIONS
# =========================================
def get_or_create_conversation(db: Session, user1_id: str, user2_id: str):
    """Get existing conversation or create a new one (prevents duplicates)"""
    
    # Sort IDs to ensure consistent order
    participant1_id, participant2_id = sorted([user1_id, user2_id])
    
    # Check if conversation already exists
    conversation = db.query(Conversation).filter(
        Conversation.participant1_id == participant1_id,
        Conversation.participant2_id == participant2_id
    ).first()
    
    is_new = False
    
    if not conversation:
        try:
            # Create new conversation
            conversation = Conversation(
                participant1_id=participant1_id,
                participant2_id=participant2_id
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
            is_new = True
        except IntegrityError:
            db.rollback()
            # Concurrently created by another request, fetch it
            conversation = db.query(Conversation).filter(
                Conversation.participant1_id == participant1_id,
                Conversation.participant2_id == participant2_id
            ).first()
            is_new = False
    
    return conversation, is_new


def verify_conversation_access(db: Session, conversation_id: str, user_id: str) -> Conversation:
    """Verify user has access to conversation"""
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        or_(
            Conversation.participant1_id == user_id,
            Conversation.participant2_id == user_id
        )
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )
    
    return conversation


# =========================================
# REST ENDPOINTS (ALL CONVERTED TO SYNC)
# =========================================

# =========================================
# 1. START/CREATE CONVERSATION
# =========================================
@router.post("/start/{user_id}", response_model=StartConversationResponse)
def start_conversation(
    user_id: str,
    db: db_dependency,
    current_user: user_dependency
):
    """Start a new conversation with another user"""
    try:
        # Check if target user exists
        other_user = db.query(Users).filter(Users.id == user_id).first()
        if not other_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Don't allow self-conversation
        if user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot start conversation with yourself"
            )
        
        # Get or create conversation (prevents duplicates)
        conversation, is_new = get_or_create_conversation(db, current_user.id, user_id)
        
        return StartConversationResponse(
            conversation_id=conversation.id,
            is_new=is_new,
            other_user_id=other_user.id,
            other_user_name=f"{other_user.first_name or ''} {other_user.last_name or ''}".strip() or other_user.username
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error starting conversation: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


# =========================================
# 2. SEND MESSAGE (REST API - for history)
# =========================================
@router.post("/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def send_message(
    message_data: MessageCreate,
    db: db_dependency,
    current_user: user_dependency,
    background_tasks: BackgroundTasks
):
    """Send a message to another user (REST fallback)"""
    try:
        # Rate limiting: max 1 message per second
        last_msg = db.query(Message).filter(Message.sender_id == current_user.id).order_by(desc(Message.created_at)).first()
        if last_msg and (datetime.utcnow() - last_msg.created_at).total_seconds() < 1.0:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded. Please wait before sending another message.")
            
        # Check if receiver exists
        receiver = db.query(Users).filter(Users.id == message_data.receiver_id).first()
        if not receiver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Receiver not found"
            )
        
        # Don't allow sending messages to yourself
        if message_data.receiver_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot send message to yourself"
            )
        
        # Validate content
        if not message_data.content or not message_data.content.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message content cannot be empty"
            )
            
        if len(message_data.content) > 5000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message content exceeds maximum length of 5000 characters"
            )
        
        # Get or create conversation
        conversation, _ = get_or_create_conversation(db, current_user.id, message_data.receiver_id)
        
        # Handle reply to message if provided
        reply_to = None
        if message_data.reply_to_id:
            reply_to = db.query(Message).filter(
                Message.id == message_data.reply_to_id,
                Message.conversation_id == conversation.id
            ).first()
        
        # Create message
        message = Message(
            conversation_id=conversation.id,
            sender_id=current_user.id,
            receiver_id=message_data.receiver_id,
            content=message_data.content.strip(),
            message_type=message_data.message_type.value,
            attachment_url=message_data.attachment_url,
            reply_to_id=reply_to.id if reply_to else None
        )
        
        # Update conversation last message
        conversation.last_message = message_data.content[:255]
        conversation.last_message_time = datetime.utcnow()
        conversation.last_message_sender_id = current_user.id
        
        db.add(message)
        db.commit()
        db.refresh(message)
        
        # Send real-time notification using BackgroundTasks
        background_tasks.add_task(manager.send_personal_message, {
            "type": "new_message",
            "data": {
                "id": message.id,
                "conversation_id": conversation.id,
                "sender_id": current_user.id,
                "sender_name": current_user.first_name or current_user.username,
                "content": message_data.content,
                "created_at": message.created_at.isoformat()
            }
        }, message_data.receiver_id)
        
        return message
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error sending message: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


# =========================================
# 3. GET ALL CONVERSATIONS
# =========================================
@router.get("/conversations", response_model=List[ConversationResponse])
def get_conversations(
    db: db_dependency,
    current_user: user_dependency,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=50)
):
    """Get all conversations for the current user"""
    try:
        # Get all conversations where user is participant
        conversations = db.query(Conversation).filter(
            or_(
                Conversation.participant1_id == current_user.id,
                Conversation.participant2_id == current_user.id
            )
        ).order_by(
            desc(Conversation.last_message_time)
        ).offset((page - 1) * limit).limit(limit).all()
        
        if not conversations:
            return []
            
        # Get other users in ONE query (Fix N+1)
        conversation_ids = [c.id for c in conversations]
        other_user_ids = [c.get_other_participant(current_user.id) for c in conversations]
        other_users = db.query(Users).filter(Users.id.in_(other_user_ids)).all()
        user_map = {u.id: u for u in other_users}
        
        # Get unread counts in ONE query (Fix N+1)
        unread_counts = db.query(
            Message.conversation_id, 
            func.count(Message.id)
        ).filter(
            Message.conversation_id.in_(conversation_ids),
            Message.receiver_id == current_user.id,
            Message.is_read == False,
            Message.is_deleted == False
        ).group_by(Message.conversation_id).all()
        unread_map = {conv_id: count for conv_id, count in unread_counts}
        
        result = []
        for conv in conversations:
            other_user_id = conv.get_other_participant(current_user.id)
            other_user = user_map.get(other_user_id)
            
            if not other_user:
                continue
            
            unread_count = unread_map.get(conv.id, 0)
            
            result.append(ConversationResponse(
                id=conv.id,
                other_user_id=other_user.id,
                other_user_name=f"{other_user.first_name or ''} {other_user.last_name or ''}".strip() or other_user.username,
                other_user_username=other_user.username,
                other_user_profile_image=other_user.profile_image,
                other_user_business_type=other_user.business_type,
                last_message=conv.last_message,
                last_message_time=conv.last_message_time,
                last_message_sender_id=conv.last_message_sender_id,
                unread_count=unread_count
            ))
        
        return result
    except Exception as e:
        print(f"Error getting conversations: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


# =========================================
# 4. GET CONVERSATION MESSAGES
# =========================================
@router.get("/conversations/{conversation_id}/messages", response_model=ConversationDetailResponse)
def get_conversation_messages(
    conversation_id: str,
    db: db_dependency,
    current_user: user_dependency,
    background_tasks: BackgroundTasks,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    mark_as_read: bool = Query(True, description="Automatically mark messages as read")
):
    """Get all messages in a conversation"""
    try:
        # Verify user has access
        conversation = verify_conversation_access(db, conversation_id, current_user.id)
        
        # Get messages with pagination (exclude soft-deleted)
        offset = (page - 1) * limit
        
        total_messages = db.query(func.count(Message.id)).filter(
            Message.conversation_id == conversation_id,
            Message.is_deleted == False
        ).scalar() or 0
        
        messages = db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.is_deleted == False
        ).order_by(
            desc(Message.created_at)
        ).offset(offset).limit(limit).all()
        
        # Reverse to get chronological order (oldest first)
        messages.reverse()
        
        # Mark messages as read if requested
        if mark_as_read:
            unread_messages = db.query(Message).filter(
                Message.conversation_id == conversation_id,
                Message.receiver_id == current_user.id,
                Message.is_read == False
            ).all()
            
            if unread_messages:
                unread_ids = [msg.id for msg in unread_messages]
                db.query(Message).filter(Message.id.in_(unread_ids)).update(
                    {"is_read": True, "read_at": datetime.utcnow()},
                    synchronize_session=False
                )
                db.commit()
                
                # Send read receipt to sender via WebSocket using BackgroundTasks
                background_tasks.add_task(manager.send_personal_message, {
                    "type": "messages_read",
                    "data": {
                        "conversation_id": conversation_id,
                        "message_ids": unread_ids,
                        "read_by": current_user.id
                    }
                }, unread_messages[0].sender_id)
                
                # Also update the fetched messages in memory so they appear as read in the response
                for msg in messages:
                    if msg.id in unread_ids:
                        msg.is_read = True
        
        # Get other user info
        other_user_id = conversation.get_other_participant(current_user.id)
        other_user = db.query(Users).filter(Users.id == other_user_id).first()
        
        total_pages = (total_messages + limit - 1) // limit if limit > 0 else 1
        
        return ConversationDetailResponse(
            id=conversation.id,
            messages=messages,
            other_user_id=other_user.id,
            other_user_name=f"{other_user.first_name or ''} {other_user.last_name or ''}".strip() or other_user.username,
            other_user_username=other_user.username,
            other_user_profile_image=other_user.profile_image,
            page=page,
            total_pages=total_pages,
            has_next=page < total_pages,
            total_messages=total_messages
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error getting conversation messages: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


# =========================================
# 5. EDIT MESSAGE
# =========================================
@router.put("/messages/{message_id}", response_model=MessageResponse)
def edit_message(
    message_id: str,
    edit_data: MessageEdit,
    db: db_dependency,
    current_user: user_dependency,
    background_tasks: BackgroundTasks
):
    """Edit a message (only sender can edit within 1 hour)"""
    try:
        # Validate content
        if not edit_data.content or not edit_data.content.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Message content cannot be empty"
            )
        
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.sender_id == current_user.id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found or you don't have permission to edit it"
            )
        
        # Check if message is too old to edit (1 hour window)
        time_since_sent = (datetime.utcnow() - message.created_at).total_seconds()
        if time_since_sent > 3600:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Message can only be edited within 1 hour of sending"
            )
        
        # Mark as edited with history
        message.mark_as_edited(edit_data.content.strip())
        
        # Update conversation last message if this was the last message
        conversation = db.query(Conversation).filter(Conversation.id == message.conversation_id).first()
        if conversation and conversation.last_message_time == message.created_at:
            conversation.last_message = edit_data.content[:255]
        
        db.commit()
        db.refresh(message)
        
        # Notify receiver about edit via WebSocket
        background_tasks.add_task(manager.send_personal_message, {
            "type": "message_edited",
            "data": {
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "new_content": edit_data.content,
                "edited_at": datetime.utcnow().isoformat()
            }
        }, message.receiver_id)
        
        return message
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error editing message: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


# =========================================
# 6. DELETE MESSAGE (Soft Delete)
# =========================================
@router.delete("/messages/{message_id}")
def delete_message(
    message_id: str,
    db: db_dependency,
    current_user: user_dependency,
    background_tasks: BackgroundTasks
):
    """Soft delete a message (only sender can delete)"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.sender_id == current_user.id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found or you don't have permission to delete it"
            )
        
        # Soft delete
        message.soft_delete(current_user.id)
        
        # Update conversation last message if this was the last message
        conversation = db.query(Conversation).filter(Conversation.id == message.conversation_id).first()
        if conversation and conversation.last_message_time == message.created_at:
            # Find the most recent non-deleted message
            last_message = db.query(Message).filter(
                Message.conversation_id == conversation.id,
                Message.is_deleted == False
            ).order_by(desc(Message.created_at)).first()
            
            if last_message:
                conversation.last_message = last_message.content[:255]
                conversation.last_message_time = last_message.created_at
                conversation.last_message_sender_id = last_message.sender_id
            else:
                conversation.last_message = None
                conversation.last_message_sender_id = None
        
        db.commit()
        
        # Notify receiver about deletion via WebSocket
        background_tasks.add_task(manager.send_personal_message, {
            "type": "message_deleted",
            "data": {
                "message_id": message_id,
                "conversation_id": message.conversation_id
            }
        }, message.receiver_id)
        
        return {"message": "Message deleted successfully"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error deleting message: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


# =========================================
# 7. MARK MESSAGES AS READ
# =========================================
@router.post("/messages/read", response_model=UnreadCountResponse)
def mark_messages_as_read(
    read_request: MarkAsReadRequest,
    db: db_dependency,
    current_user: user_dependency,
    background_tasks: BackgroundTasks
):
    """Mark specific messages as read"""
    try:
        if not read_request.message_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No message IDs provided"
            )
        
        # Get messages to notify senders
        messages = db.query(Message).filter(
            Message.id.in_(read_request.message_ids),
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).all()
        
        if not messages:
            conversations_unread = db.query(
                Message.conversation_id,
                func.count(Message.id)
            ).filter(
                Message.receiver_id == current_user.id,
                Message.is_read == False,
                Message.is_deleted == False
            ).group_by(Message.conversation_id).all()
            
            return UnreadCountResponse(
                unread_count=sum(count for _, count in conversations_unread),
                conversations_with_unread={conv_id: count for conv_id, count in conversations_unread}
            )
            
        # Update messages where current user is the receiver
        updated_count = db.query(Message).filter(
            Message.id.in_(read_request.message_ids),
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).update(
            {"is_read": True, "read_at": datetime.utcnow()},
            synchronize_session=False
        )
        
        db.commit()
        
        # Send read receipts to senders via WebSocket
        for message in messages:
            background_tasks.add_task(manager.send_personal_message, {
                "type": "messages_read",
                "data": {
                    "conversation_id": message.conversation_id,
                    "message_ids": [message.id],
                    "read_by": current_user.id
                }
            }, message.sender_id)
        
        # Get updated unread count directly (optimized 1 query)
        conversations_unread = db.query(
            Message.conversation_id,
            func.count(Message.id)
        ).filter(
            Message.receiver_id == current_user.id,
            Message.is_read == False,
            Message.is_deleted == False
        ).group_by(Message.conversation_id).all()
        
        return UnreadCountResponse(
            unread_count=sum(count for _, count in conversations_unread),
            conversations_with_unread={conv_id: count for conv_id, count in conversations_unread}
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error marking messages as read: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


# =========================================
# 8. MARK ENTIRE CONVERSATION AS READ
# =========================================
@router.post("/conversations/{conversation_id}/read")
def mark_conversation_as_read(
    conversation_id: str,
    db: db_dependency,
    current_user: user_dependency,
    background_tasks: BackgroundTasks
):
    """Mark all messages in a conversation as read"""
    try:
        # Verify access
        verify_conversation_access(db, conversation_id, current_user.id)
        
        # Get unread messages to notify senders
        unread_messages = db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).all()
        
        if not unread_messages:
            return {"message": "0 messages marked as read"}
            
        # Update all unread messages
        updated_count = db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).update(
            {"is_read": True, "read_at": datetime.utcnow()},
            synchronize_session=False
        )
        
        db.commit()
        
        # Send read receipts to senders via WebSocket
        for message in unread_messages:
            background_tasks.add_task(manager.send_personal_message, {
                "type": "messages_read",
                "data": {
                    "conversation_id": conversation_id,
                    "message_ids": [message.id],
                    "read_by": current_user.id
                }
            }, message.sender_id)
        
        return {"message": f"{updated_count} messages marked as read"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error marking conversation as read: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


# =========================================
# 9. GET UNREAD COUNT
# =========================================
@router.get("/unread/count", response_model=UnreadCountResponse)
def get_unread_count(
    db: db_dependency,
    current_user: user_dependency
):
    """Get total unread message count"""
    try:
        # Get unread count per conversation (optimized to 1 query)
        conversations_unread = db.query(
            Message.conversation_id,
            func.count(Message.id)
        ).filter(
            Message.receiver_id == current_user.id,
            Message.is_read == False,
            Message.is_deleted == False
        ).group_by(Message.conversation_id).all()
        
        return UnreadCountResponse(
            unread_count=sum(count for _, count in conversations_unread),
            conversations_with_unread={conv_id: count for conv_id, count in conversations_unread}
        )
    except Exception as e:
        db.rollback()
        print(f"Error getting unread count: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


# =========================================
# 10. ADD REACTION TO MESSAGE
# =========================================
@router.post("/messages/{message_id}/reactions")
def add_reaction(
    message_id: str,
    reaction: MessageReaction,
    db: db_dependency,
    current_user: user_dependency,
    background_tasks: BackgroundTasks
):
    """Add a reaction to a message"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        
        # Verify user is participant in conversation
        verify_conversation_access(db, message.conversation_id, current_user.id)
        
        # Add reaction
        message.add_reaction(reaction.reaction, current_user.id)
        db.commit()
        
        # Notify other user about reaction via WebSocket
        other_user_id = message.sender_id if message.receiver_id == current_user.id else message.receiver_id
        background_tasks.add_task(manager.send_personal_message, {
            "type": "reaction_added",
            "data": {
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "reaction": reaction.reaction,
                "user_id": current_user.id
            }
        }, other_user_id)
        
        return {"message": "Reaction added"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error adding reaction: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


# =========================================
# 11. REMOVE REACTION FROM MESSAGE
# =========================================
@router.delete("/messages/{message_id}/reactions/{reaction}")
def remove_reaction(
    message_id: str,
    reaction: str,
    db: db_dependency,
    current_user: user_dependency,
    background_tasks: BackgroundTasks
):
    """Remove a reaction from a message"""
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.is_deleted == False
        ).first()
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        
        # Verify user is participant in conversation
        verify_conversation_access(db, message.conversation_id, current_user.id)
        
        # Remove reaction
        message.remove_reaction(reaction, current_user.id)
        db.commit()
        
        # Notify other user about reaction removal via WebSocket
        other_user_id = message.sender_id if message.receiver_id == current_user.id else message.receiver_id
        background_tasks.add_task(manager.send_personal_message, {
            "type": "reaction_removed",
            "data": {
                "message_id": message_id,
                "conversation_id": message.conversation_id,
                "reaction": reaction,
                "user_id": current_user.id
            }
        }, other_user_id)
        
        return {"message": "Reaction removed"}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"Error removing reaction: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")



# =========================================
# WEBSOCKET HELPER FUNCTIONS (Sync functions for threadpool)
# =========================================
def _ws_update_last_seen(db: Session, current_user: Users):
    current_user.last_seen = datetime.utcnow()
    db.commit()

def _ws_get_conversations(db: Session, user_id: str):
    return db.query(Conversation).filter(
        or_(
            Conversation.participant1_id == user_id,
            Conversation.participant2_id == user_id
        )
    ).all()

def _ws_check_rate_limit(db: Session, user_id: str) -> bool:
    last_msg = db.query(Message).filter(
        Message.sender_id == user_id
    ).order_by(desc(Message.created_at)).first()
    return last_msg and (datetime.utcnow() - last_msg.created_at).total_seconds() < 1.0

def _ws_verify_receiver(db: Session, receiver_id: str) -> bool:
    return db.query(Users).filter(Users.id == receiver_id).first() is not None

def _ws_process_new_message(db: Session, user_id: str, receiver_id: str, content: str, message_type_enum: str, reply_to_id: str):
    conversation, _ = get_or_create_conversation(db, user_id, receiver_id)
    
    reply_to = None
    if reply_to_id:
        reply_to = db.query(Message).filter(
            Message.id == reply_to_id,
            Message.conversation_id == conversation.id
        ).first()
    
    message = Message(
        conversation_id=conversation.id,
        sender_id=user_id,
        receiver_id=receiver_id,
        content=content.strip(),
        message_type=message_type_enum,
        reply_to_id=reply_to.id if reply_to else None
    )
    
    conversation.last_message = content[:255]
    conversation.last_message_time = datetime.utcnow()
    conversation.last_message_sender_id = user_id
    
    db.add(message)
    db.commit()
    db.refresh(message)
    
    message_data_to_send = {
        "id": message.id,
        "conversation_id": conversation.id,
        "sender_id": user_id,
        "content": content,
        "message_type": message_type_enum,
        "created_at": message.created_at.isoformat(),
        "reply_to": {
            "id": reply_to.id,
            "content": reply_to.content[:100]
        } if reply_to else None
    }
    return message_data_to_send, conversation.id

def _ws_verify_conversation_access(db: Session, conversation_id: str, user_id: str):
    conv = verify_conversation_access(db, conversation_id, user_id)
    if conv:
        return conv.get_other_participant(user_id)
    return None

def _ws_process_read_receipts(db: Session, message_ids: list, user_id: str):
    db.query(Message).filter(
        Message.id.in_(message_ids),
        Message.receiver_id == user_id
    ).update(
        {"is_read": True, "read_at": datetime.utcnow()},
        synchronize_session=False
    )
    db.commit()
    
    first_message = db.query(Message).filter(
        Message.id == message_ids[0],
        Message.receiver_id == user_id
    ).first()
    
    if first_message:
        return first_message.conversation_id, first_message.sender_id
    return None, None


# =========================================
# WEBSOCKET REAL-TIME CHAT ENDPOINT (Token in query param, NOT in URL)
# =========================================
@router.websocket("/ws")
async def websocket_chat(
    websocket: WebSocket,
):
    """WebSocket connection for real-time messaging (token via query param)"""
    
    # Get token from query parameters (SECURE - not in URL path)
    token = websocket.query_params.get("token")
    
    if not token:
        await websocket.close(code=1008, reason="Missing authentication token")
        return
    
    # Create independent database session for WebSocket
    db = SessionLocal()
    conversations = []
    user_id = None
    
    try:
        # Authenticate user from token
        from routers.auth import get_current_user_ws
        current_user = await run_in_threadpool(get_current_user_ws, token, db)
        
        if not current_user:
            await websocket.close(code=1008, reason="Invalid authentication")
            return
        
        user_id = current_user.id
        user_name = current_user.first_name or current_user.username
        
        # Update last_seen
        await run_in_threadpool(_ws_update_last_seen, db, current_user)
        
        # Connect to manager
        await manager.connect(websocket, user_id)
        
        # Send online status to all conversations
        conversations = await run_in_threadpool(_ws_get_conversations, db, user_id)
        
        for conv in conversations:
            other_user_id = conv.get_other_participant(user_id)
            await manager.send_personal_message({
                "type": "user_online",
                "data": {
                    "user_id": user_id,
                    "user_name": user_name,
                    "conversation_id": conv.id,
                    "device_count": manager.get_device_count(user_id)
                }
            }, other_user_id)
        
        # Send initial connection confirmation with ping interval
        await websocket.send_json({
            "type": "connection_established",
            "data": {
                "user_id": user_id,
                "user_name": user_name,
                "timestamp": datetime.utcnow().isoformat()
            }
        })
        
        try:
            while True:
                # Receive message from client
                data = await websocket.receive_text()
                
                if len(data) > 10000:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "Payload too large"}
                    })
                    continue
                
                try:
                    message_data = json.loads(data)
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "Invalid JSON format"}
                    })
                    continue
                
                message_type = message_data.get("type")
                
                # Handle ping/pong heartbeat
                if message_type == "ping":
                    await websocket.send_json({"type": "pong", "data": {"timestamp": datetime.utcnow().isoformat()}})
                    continue
                
                if message_type == "message":
                    # Rate limit check (max 1 message per second)
                    is_rate_limited = await run_in_threadpool(_ws_check_rate_limit, db, user_id)
                    if is_rate_limited:
                        await websocket.send_json({
                            "type": "error",
                            "data": {
                                "message": "Rate limit exceeded. Please wait before sending another message."
                            }
                        })
                        continue
                        
                    # Handle new message
                    receiver_id = message_data.get("receiver_id")
                    content = message_data.get("content")
                    message_type_enum = message_data.get("message_type", "text")
                    reply_to_id = message_data.get("reply_to_id")
                    
                    # Validate content
                    if not receiver_id:
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": "receiver_id is required"}
                        })
                        continue
                    
                    has_receiver = await run_in_threadpool(_ws_verify_receiver, db, receiver_id)
                    if not has_receiver:
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": "Receiver not found"}
                        })
                        continue
                    
                    if not content or not content.strip():
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": "Message content cannot be empty"}
                        })
                        continue
                    
                    if len(content) > 5000:
                        await websocket.send_json({
                            "type": "error",
                            "data": {"message": "Message content exceeds maximum length of 5000 characters"}
                        })
                        continue
                    
                    # Process message in threadpool
                    message_data_to_send, conv_id = await run_in_threadpool(
                        _ws_process_new_message, db, user_id, receiver_id, content, message_type_enum, reply_to_id
                    )
                    
                    # Send REAL-TIME to all devices of receiver
                    await manager.send_personal_message({
                        "type": "new_message",
                        "data": message_data_to_send
                    }, receiver_id)
                    
                    # Confirm to sender
                    await websocket.send_json({
                        "type": "message_sent",
                        "data": {
                            "id": message_data_to_send["id"],
                            "conversation_id": conv_id,
                            "created_at": message_data_to_send["created_at"]
                        }
                    })
                
                elif message_type == "typing":
                    # Handle typing status
                    conversation_id = message_data.get("conversation_id")
                    is_typing = message_data.get("is_typing", False)
                    
                    if conversation_id:
                        other_user_id = await run_in_threadpool(_ws_verify_conversation_access, db, conversation_id, user_id)
                        
                        if other_user_id:
                            await manager.send_personal_message({
                                "type": "user_typing",
                                "data": {
                                    "conversation_id": conversation_id,
                                    "user_id": user_id,
                                    "user_name": user_name,
                                    "is_typing": is_typing
                                }
                            }, other_user_id)
                
                elif message_type == "read_receipt":
                    # Handle read receipts
                    message_ids = message_data.get("message_ids", [])
                    if message_ids:
                        conv_id, sender_id = await run_in_threadpool(_ws_process_read_receipts, db, message_ids, user_id)
                        
                        if conv_id and sender_id:
                            await manager.send_personal_message({
                                "type": "messages_read",
                                "data": {
                                    "conversation_id": conv_id,
                                    "message_ids": message_ids,
                                    "read_by": user_id,
                                    "read_by_name": user_name
                                }
                            }, sender_id)
        
        except WebSocketDisconnect:
            manager.disconnect(websocket, user_id)
            
            # Only broadcast offline if truly no devices left
            if not manager.is_user_online(user_id):
                await run_in_threadpool(_ws_update_last_seen, db, current_user)
                
                if conversations:
                    for conv in conversations:
                        other_user_id = conv.get_other_participant(user_id)
                        await manager.send_personal_message({
                            "type": "user_offline",
                            "data": {
                                "user_id": user_id,
                                "user_name": user_name,
                                "conversation_id": conv.id,
                                "last_seen": current_user.last_seen.isoformat()
                            }
                        }, other_user_id)
        
        except Exception as e:
            print(f"WebSocket error: {e}")
            if user_id:
                manager.disconnect(websocket, user_id)
    
    finally:
        db.close()