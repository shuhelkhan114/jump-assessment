from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import structlog
from datetime import datetime
import uuid

from auth import get_current_user
from database import AsyncSessionLocal, Conversation, OngoingInstruction, select
from services.openai_service import openai_service
from services.rag_service import rag_service

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
    """Send a message to the AI agent with RAG context"""
    try:
        # Get RAG context for the query
        context, sources = await rag_service.get_context_for_query(
            chat_message.message, 
            current_user["id"]
        )
        
        # Get recent conversation history for context
        conversation_history = await get_recent_conversation_history(current_user["id"], limit=5)
        
        # Get ongoing instructions
        ongoing_instructions = await get_active_instructions(current_user["id"])
        
        # Build messages for OpenAI
        messages = []
        
        # Add conversation history
        for conv in reversed(conversation_history):  # Reverse to get chronological order
            messages.append({"role": "user", "content": conv.message})
            messages.append({"role": "assistant", "content": conv.response})
        
        # Add current message
        messages.append({"role": "user", "content": chat_message.message})
        
        # Build system prompt
        system_prompt = build_system_prompt(ongoing_instructions)
        
        # Generate response using OpenAI with RAG context
        openai_response = await openai_service.chat_completion(
            messages=messages,
            system_prompt=system_prompt,
            context=context
        )
        
        response_content = openai_response.get("content", "I'm sorry, I couldn't generate a response.")
        
        # Save conversation to database
        conversation_id = await save_conversation(
            current_user["id"],
            chat_message.message,
            response_content,
            context if context else None
        )
        
        logger.info(f"Generated chat response for user {current_user['id']} with {len(sources)} sources")
        
        return ChatResponse(
            response=response_content,
            context_used=context if context else None,
            sources=sources
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

async def get_recent_conversation_history(user_id: str, limit: int = 5) -> List[Conversation]:
    """Get recent conversation history for context"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

async def get_active_instructions(user_id: str) -> List[OngoingInstruction]:
    """Get active ongoing instructions"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(OngoingInstruction)
            .where(OngoingInstruction.user_id == user_id)
            .where(OngoingInstruction.is_active == True)
            .order_by(OngoingInstruction.created_at.desc())
        )
        return result.scalars().all()

def build_system_prompt(ongoing_instructions: List[OngoingInstruction]) -> str:
    """Build system prompt for the financial advisor AI"""
    base_prompt = """You are an intelligent AI assistant for a financial advisor. You have REAL ACCESS to the user's actual data through a knowledge base that includes:

1. Email data from Gmail (client communications, meeting requests, etc.)
2. Contact and company data from HubSpot CRM
3. Calendar information for scheduling

IMPORTANT: You are NOT a general AI assistant - you are connected to the user's actual Gmail and HubSpot accounts. When they ask about their contacts, emails, or calendar, you can access and provide real information from their accounts.

Your primary responsibilities:
- Help analyze client communications and relationships
- Provide insights about client needs and preferences
- Assist with scheduling and meeting coordination
- Answer questions about client history and interactions
- Suggest follow-up actions based on email content
- List and search through contacts, emails, and calendar events

Guidelines:
- Always be professional and maintain confidentiality
- Provide specific, actionable insights when possible
- Reference relevant emails or contact information when answering
- If you mention specific people or companies, cite your sources
- Use **bold text** for emphasis and bullet points for lists
- Format your responses with proper markdown for better readability
- Be concise but thorough in your responses
- When context is provided, USE IT to answer the user's questions
- If you don't have enough information, ask clarifying questions"""

    if ongoing_instructions:
        base_prompt += "\n\nOngoing Instructions to Remember:\n"
        for instruction in ongoing_instructions:
            base_prompt += f"- {instruction.instruction}\n"
    
    return base_prompt 