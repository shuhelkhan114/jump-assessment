from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import structlog
from datetime import datetime

from auth import get_current_user
from database import AsyncSessionLocal, Conversation, OngoingInstruction, select

logger = structlog.get_logger()

router = APIRouter()

# Pydantic models
class ChatMessage(BaseModel):
    message: str
    context: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    context_used: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None

class ConversationHistory(BaseModel):
    id: str
    message: str
    response: str
    created_at: datetime

class OngoingInstructionRequest(BaseModel):
    instruction: str

class OngoingInstructionResponse(BaseModel):
    id: str
    instruction: str
    is_active: bool
    created_at: datetime

@router.post("/message", response_model=ChatResponse)
async def send_message(
    chat_message: ChatMessage,
    current_user: dict = Depends(get_current_user)
):
    """Send a message to the AI agent"""
    try:
        # TODO: Implement RAG search and LLM response
        # For now, return a placeholder response
        response = "I'm currently being set up! I'll be able to help you with your emails and HubSpot data soon."
        
        # Save conversation to database
        conversation_id = await save_conversation(
            current_user["id"],
            chat_message.message,
            response,
            chat_message.context
        )
        
        return ChatResponse(
            response=response,
            context_used=chat_message.context,
            sources=[]
        )
        
    except Exception as e:
        logger.error(f"Chat message failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process chat message"
        )

@router.get("/history", response_model=List[ConversationHistory])
async def get_conversation_history(
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Get conversation history"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Conversation)
                .where(Conversation.user_id == current_user["id"])
                .order_by(Conversation.created_at.desc())
                .limit(limit)
            )
            conversations = result.scalars().all()
            
            return [
                ConversationHistory(
                    id=conv.id,
                    message=conv.message,
                    response=conv.response,
                    created_at=conv.created_at
                )
                for conv in conversations
            ]
        
    except Exception as e:
        logger.error(f"Failed to fetch conversation history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch conversation history"
        )

@router.post("/instructions", response_model=OngoingInstructionResponse)
async def add_ongoing_instruction(
    instruction_request: OngoingInstructionRequest,
    current_user: dict = Depends(get_current_user)
):
    """Add an ongoing instruction"""
    try:
        async with AsyncSessionLocal() as session:
            instruction_id = f"inst_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            
            instruction = OngoingInstruction(
                id=instruction_id,
                user_id=current_user["id"],
                instruction=instruction_request.instruction,
                is_active=True,
                created_at=datetime.utcnow()
            )
            
            session.add(instruction)
            await session.commit()
            await session.refresh(instruction)
            
            return OngoingInstructionResponse(
                id=instruction.id,
                instruction=instruction.instruction,
                is_active=instruction.is_active,
                created_at=instruction.created_at
            )
        
    except Exception as e:
        logger.error(f"Failed to add ongoing instruction: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add ongoing instruction"
        )

@router.get("/instructions", response_model=List[OngoingInstructionResponse])
async def get_ongoing_instructions(
    current_user: dict = Depends(get_current_user)
):
    """Get all ongoing instructions"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(OngoingInstruction)
                .where(OngoingInstruction.user_id == current_user["id"])
                .where(OngoingInstruction.is_active == True)
                .order_by(OngoingInstruction.created_at.desc())
            )
            instructions = result.scalars().all()
            
            return [
                OngoingInstructionResponse(
                    id=instruction.id,
                    instruction=instruction.instruction,
                    is_active=instruction.is_active,
                    created_at=instruction.created_at
                )
                for instruction in instructions
            ]
        
    except Exception as e:
        logger.error(f"Failed to fetch ongoing instructions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch ongoing instructions"
        )

@router.delete("/instructions/{instruction_id}")
async def delete_ongoing_instruction(
    instruction_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Deactivate an ongoing instruction"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(OngoingInstruction)
                .where(OngoingInstruction.id == instruction_id)
                .where(OngoingInstruction.user_id == current_user["id"])
            )
            instruction = result.scalar_one_or_none()
            
            if instruction:
                instruction.is_active = False
                await session.commit()
        
        return {"message": "Instruction deactivated"}
        
    except Exception as e:
        logger.error(f"Failed to deactivate instruction: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate instruction"
        )

async def save_conversation(user_id: str, message: str, response: str, context: Optional[str] = None) -> str:
    """Save conversation to database"""
    import uuid
    
    conversation_id = str(uuid.uuid4())
    
    async with AsyncSessionLocal() as session:
        conversation = Conversation(
            id=conversation_id,
            user_id=user_id,
            message=message,
            response=response,
            context_used=context,
            created_at=datetime.utcnow()
        )
        
        session.add(conversation)
        await session.commit()
    
    return conversation_id 