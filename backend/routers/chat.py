from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import structlog
from datetime import datetime
import uuid
import json

from auth import get_current_user
from database import AsyncSessionLocal, Conversation, ChatSession, OngoingInstruction, select
from services.openai_service import openai_service
from services.rag_service import rag_service
from services.tools_service import tools_service
from tasks.ai_tasks import execute_ai_action

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
    tool_results: Optional[List[Dict[str, Any]]] = None

class ConversationHistory(BaseModel):
    id: str
    message: str
    response: str
    created_at: datetime

class ChatSessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

class CreateChatSessionRequest(BaseModel):
    title: Optional[str] = None

class UpdateChatSessionRequest(BaseModel):
    title: str

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
        system_prompt = build_system_prompt(ongoing_instructions, current_user["name"])
        
        # Get available tools for function calling
        available_tools = tools_service.get_tools()
        
        # Generate response using OpenAI with RAG context and tools
        openai_response = await openai_service.chat_completion(
            messages=messages,
            system_prompt=system_prompt,
            context=context,
            tools=available_tools
        )
        
        response_content = openai_response.get("content", "")
        tool_calls = openai_response.get("tool_calls")
        
        # Initialize tool_results as empty list
        tool_results = []
        
        # Handle tool calls if present
        if tool_calls:
            logger.info(f"AI requested {len(tool_calls)} tool calls")
            
            # Execute each tool call
            for tool_call in tool_calls:
                try:
                    function_name = tool_call["function"]["name"]
                    function_args = json.loads(tool_call["function"]["arguments"])
                    
                    logger.info(f"Executing tool: {function_name} with args: {function_args}")
                    
                    # Queue tool execution
                    task_result = execute_ai_action.delay(
                        current_user["id"],
                        function_name,
                        function_args
                    )
                    
                    # Wait for the task to complete with shorter timeout and better error handling
                    try:
                        execution_result = task_result.get(timeout=35)  # Increased timeout for HubSpot API calls
                        tool_results.append({
                            "tool": function_name,
                            "status": "success",
                            "result": execution_result
                        })
                    except Exception as task_error:
                        # Handle task execution errors immediately
                        logger.error(f"Task execution error: {str(task_error)}")
                        tool_results.append({
                            "tool": function_name,
                            "status": "error",
                            "error": str(task_error)
                        })
                    
                except Exception as e:
                    logger.error(f"Tool parsing failed: {str(e)}")
                    tool_results.append({
                        "tool": function_name,
                        "status": "error",
                        "error": f"Tool parsing error: {str(e)}"
                    })
            
            # Create detailed summary for system message with actual data
            detailed_summary = []
            for result in tool_results:
                if result['status'] == 'success':
                    result_data = result.get('result', {})
                    if isinstance(result_data, dict):
                        tool_name = result['tool']
                        message = result_data.get('message', f"{tool_name} completed successfully")
                        
                        # Include detailed data for specific functions
                        if tool_name == 'get_calendar_schedule' and 'details' in result_data:
                            details = result_data['details']
                            if 'events' in details and details['events']:
                                events_summary = f"✅ {message}\n\nACTUAL CALENDAR EVENTS:\n"
                                for event in details['events']:
                                    events_summary += f"- {event.get('title', 'No title')}\n"
                                    events_summary += f"  Time: {event.get('time', 'No time')}\n"
                                    if event.get('location'):
                                        events_summary += f"  Location: {event.get('location')}\n"
                                    if event.get('description'):
                                        events_summary += f"  Description: {event.get('description')[:100]}...\n"
                                    if event.get('organizer'):
                                        events_summary += f"  Organizer: {event.get('organizer')}\n"
                                    events_summary += "\n"
                                detailed_summary.append(events_summary)
                            else:
                                detailed_summary.append(f"✅ {message}")
                        elif tool_name == 'create_calendar_event' and 'details' in result_data:
                            details = result_data['details']
                            event_summary = f"✅ {message}\n\nCALENDAR EVENT CREATED:\n"
                            event_summary += f"- Title: {details.get('title', 'No title')}\n"
                            event_summary += f"- Start: {details.get('start', 'No start time')}\n"
                            event_summary += f"- End: {details.get('end', 'No end time')}\n"
                            event_summary += f"- Attendees: {details.get('attendees', [])}\n"
                            event_summary += f"- Location: {details.get('location', 'No location')}\n"
                            if details.get('link'):
                                event_summary += f"- Calendar Link: {details.get('link')}\n"
                            if details.get('id'):
                                event_summary += f"- Event ID: {details.get('id')}\n"
                            detailed_summary.append(event_summary)
                        elif tool_name == 'send_email' and 'details' in result_data:
                            details = result_data['details']
                            email_summary = f"✅ {message}\n\nEMAIL SENT:\n"
                            email_summary += f"- To: {details.get('to', 'Unknown')}\n"
                            email_summary += f"- Subject: {details.get('subject', 'No subject')}\n"
                            email_summary += f"- Body: {details.get('body', 'No body')[:100]}...\n"
                            detailed_summary.append(email_summary)
                        elif tool_name == 'create_hubspot_contact' and 'details' in result_data:
                            details = result_data['details']
                            contact_summary = f"✅ {message}\n\nCONTACT CREATED:\n"
                            contact_summary += f"- Name: {details.get('name', 'Unknown')}\n"
                            contact_summary += f"- Email: {details.get('email', 'Unknown')}\n"
                            contact_summary += f"- Company: {details.get('company', 'N/A')}\n"
                            detailed_summary.append(contact_summary)
                        else:
                            detailed_summary.append(f"✅ {message}")
                    else:
                        detailed_summary.append(f"✅ {result['tool']} completed successfully")
                else:
                    detailed_summary.append(f"❌ {result['tool']} failed: {result.get('error', 'Unknown error')}")
            
            tool_summary_message = "Tool execution results:\n" + "\n".join(detailed_summary)
            
            # Present tool results directly to the AI without forcing summarization
            messages.append({"role": "system", "content": tool_summary_message})
            messages.append({"role": "system", "content": "The above tool execution results contain the actual data requested by the user. Answer the user's original question using this exact data. Present the information clearly and accurately without unnecessary summarization. Only organize or format the data to make it more readable - do not change, omit, or add any information."})
            
            final_response = await openai_service.chat_completion(
                messages=messages,
                system_prompt=system_prompt,
                context=context
            )
            
            response_content = final_response.get("content", "Actions completed successfully!")
        
        # Ensure we have some response content
        if not response_content:
            response_content = "I'm sorry, I couldn't generate a response."
        
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
            sources=sources,
            tool_results=tool_results
        )
        
    except Exception as e:
        logger.error(f"Chat message failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process chat message"
        )

@router.post("/sessions/{session_id}/message", response_model=ChatResponse)
async def send_message_to_session(
    session_id: str,
    chat_message: ChatMessage,
    current_user: dict = Depends(get_current_user)
):
    """Send a message to a specific chat session"""
    try:
        # Verify session belongs to user
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.user_id == current_user["id"]
                )
            )
            chat_session = result.scalar_one_or_none()
            if not chat_session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Chat session not found"
                )
        
        # Get RAG context for the query
        context, sources = await rag_service.get_context_for_query(
            chat_message.message, 
            current_user["id"]
        )
        
        # Get recent conversation history for this specific session
        conversation_history = await get_session_conversation_history(current_user["id"], session_id, limit=10)
        
        # Get ongoing instructions
        ongoing_instructions = await get_active_instructions(current_user["id"])
        
        # Build messages for OpenAI
        messages = []
        
        # Add conversation history from this session
        for conv in reversed(conversation_history):  # Reverse to get chronological order
            messages.append({"role": "user", "content": conv.message})
            messages.append({"role": "assistant", "content": conv.response})
        
        # Add current message
        messages.append({"role": "user", "content": chat_message.message})
        
        # Build system prompt
        system_prompt = build_system_prompt(ongoing_instructions, current_user["name"])
        
        # Get available tools for function calling
        available_tools = tools_service.get_tools()
        
        # Generate response using OpenAI with RAG context and tools
        openai_response = await openai_service.chat_completion(
            messages=messages,
            system_prompt=system_prompt,
            context=context,
            tools=available_tools
        )
        
        response_content = openai_response.get("content", "")
        tool_calls = openai_response.get("tool_calls")
        
        # Initialize tool_results as empty list
        tool_results = []
        
        # Handle tool calls if present
        if tool_calls:
            logger.info(f"AI requested {len(tool_calls)} tool calls")
            
            # Execute each tool call
            for tool_call in tool_calls:
                try:
                    function_name = tool_call["function"]["name"]
                    function_args = json.loads(tool_call["function"]["arguments"])
                    
                    logger.info(f"Executing tool: {function_name} with args: {function_args}")
                    
                    # Queue tool execution
                    task_result = execute_ai_action.delay(
                        current_user["id"],
                        function_name,
                        function_args
                    )
                    
                    # Wait for the task to complete with shorter timeout and better error handling
                    try:
                        execution_result = task_result.get(timeout=35)  # Increased timeout for HubSpot API calls
                        tool_results.append({
                            "tool": function_name,
                            "status": "success",
                            "result": execution_result
                        })
                    except Exception as task_error:
                        # Handle task execution errors immediately
                        logger.error(f"Task execution error: {str(task_error)}")
                        tool_results.append({
                            "tool": function_name,
                            "status": "error",
                            "error": str(task_error)
                        })
                    
                except Exception as e:
                    logger.error(f"Tool parsing failed: {str(e)}")
                    tool_results.append({
                        "tool": function_name,
                        "status": "error",
                        "error": f"Tool parsing error: {str(e)}"
                    })
            
            # Create detailed summary for system message with actual data
            detailed_summary = []
            for result in tool_results:
                if result['status'] == 'success':
                    result_data = result.get('result', {})
                    if isinstance(result_data, dict):
                        tool_name = result['tool']
                        message = result_data.get('message', f"{tool_name} completed successfully")
                        
                        # Include detailed data for specific functions
                        if tool_name == 'get_calendar_schedule' and 'details' in result_data:
                            details = result_data['details']
                            if 'events' in details and details['events']:
                                events_summary = f"✅ {message}\n\nACTUAL CALENDAR EVENTS:\n"
                                for event in details['events']:
                                    events_summary += f"- {event.get('title', 'No title')}\n"
                                    events_summary += f"  Time: {event.get('time', 'No time')}\n"
                                    if event.get('location'):
                                        events_summary += f"  Location: {event.get('location')}\n"
                                    if event.get('description'):
                                        events_summary += f"  Description: {event.get('description')[:100]}...\n"
                                    if event.get('organizer'):
                                        events_summary += f"  Organizer: {event.get('organizer')}\n"
                                    events_summary += "\n"
                                detailed_summary.append(events_summary)
                            else:
                                detailed_summary.append(f"✅ {message}")
                        elif tool_name == 'create_calendar_event' and 'details' in result_data:
                            details = result_data['details']
                            event_summary = f"✅ {message}\n\nCALENDAR EVENT CREATED:\n"
                            event_summary += f"- Title: {details.get('title', 'No title')}\n"
                            event_summary += f"- Start: {details.get('start', 'No start time')}\n"
                            event_summary += f"- End: {details.get('end', 'No end time')}\n"
                            event_summary += f"- Attendees: {details.get('attendees', [])}\n"
                            event_summary += f"- Location: {details.get('location', 'No location')}\n"
                            if details.get('link'):
                                event_summary += f"- Calendar Link: {details.get('link')}\n"
                            if details.get('id'):
                                event_summary += f"- Event ID: {details.get('id')}\n"
                            detailed_summary.append(event_summary)
                        elif tool_name == 'send_email' and 'details' in result_data:
                            details = result_data['details']
                            email_summary = f"✅ {message}\n\nEMAIL SENT:\n"
                            email_summary += f"- To: {details.get('to', 'Unknown')}\n"
                            email_summary += f"- Subject: {details.get('subject', 'No subject')}\n"
                            email_summary += f"- Body: {details.get('body', 'No body')[:100]}...\n"
                            detailed_summary.append(email_summary)
                        elif tool_name == 'create_hubspot_contact' and 'details' in result_data:
                            details = result_data['details']
                            contact_summary = f"✅ {message}\n\nCONTACT CREATED:\n"
                            contact_summary += f"- Name: {details.get('name', 'Unknown')}\n"
                            contact_summary += f"- Email: {details.get('email', 'Unknown')}\n"
                            contact_summary += f"- Company: {details.get('company', 'N/A')}\n"
                            detailed_summary.append(contact_summary)
                        else:
                            detailed_summary.append(f"✅ {message}")
                    else:
                        detailed_summary.append(f"✅ {result['tool']} completed successfully")
                else:
                    detailed_summary.append(f"❌ {result['tool']} failed: {result.get('error', 'Unknown error')}")
            
            tool_summary_message = "Tool execution results:\n" + "\n".join(detailed_summary)
            
            # Present tool results directly to the AI without forcing summarization
            messages.append({"role": "system", "content": tool_summary_message})
            messages.append({"role": "system", "content": "The above tool execution results contain the actual data requested by the user. Answer the user's original question using this exact data. Present the information clearly and accurately without unnecessary summarization. Only organize or format the data to make it more readable - do not change, omit, or add any information."})
            
            final_response = await openai_service.chat_completion(
                messages=messages,
                system_prompt=system_prompt,
                context=context
            )
            
            response_content = final_response.get("content", "Actions completed successfully!")
        
        # Ensure we have some response content
        if not response_content:
            response_content = "I'm sorry, I couldn't generate a response."
        
        # Save conversation to specific session
        conversation_id = await save_conversation_to_session(
            current_user["id"],
            session_id,
            chat_message.message,
            response_content,
            context if context else None
        )
        
        # Update session's updated_at timestamp
        await update_session_timestamp(session_id)
        
        # Auto-generate title if this is the first message in session
        if (not chat_session.title or chat_session.title == "New Chat") and len(conversation_history) == 0:
            await auto_generate_session_title(session_id, chat_message.message)
        
        logger.info(f"Generated chat response for user {current_user['id']} in session {session_id}")
        
        return ChatResponse(
            response=response_content,
            context_used=context if context else None,
            sources=sources,
            tool_results=tool_results
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat message to session failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process chat message"
        )

@router.post("/sessions", response_model=ChatSessionResponse)
async def create_chat_session(
    request: CreateChatSessionRequest,
    current_user: dict = Depends(get_current_user)
):
    """Create a new chat session"""
    try:
        async with AsyncSessionLocal() as session:
            session_id = str(uuid.uuid4())
            
            chat_session = ChatSession(
                id=session_id,
                user_id=current_user["id"],
                title=request.title or "New Chat",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            session.add(chat_session)
            await session.commit()
            await session.refresh(chat_session)
            
            return ChatSessionResponse(
                id=chat_session.id,
                title=chat_session.title,
                created_at=chat_session.created_at,
                updated_at=chat_session.updated_at,
                message_count=0
            )
        
    except Exception as e:
        logger.error(f"Failed to create chat session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create chat session"
        )

@router.get("/sessions", response_model=List[ChatSessionResponse])
async def get_chat_sessions(
    current_user: dict = Depends(get_current_user)
):
    """Get all chat sessions for the current user"""
    try:
        async with AsyncSessionLocal() as session:
            # Get sessions with conversation count
            result = await session.execute(
                select(ChatSession)
                .where(ChatSession.user_id == current_user["id"])
                .order_by(ChatSession.updated_at.desc())
            )
            sessions = result.scalars().all()
            
            # Get conversation counts for each session
            response_sessions = []
            for chat_session in sessions:
                # Count conversations in this session
                count_result = await session.execute(
                    select(Conversation)
                    .where(Conversation.chat_session_id == chat_session.id)
                )
                conversations = count_result.scalars().all()
                
                response_sessions.append(ChatSessionResponse(
                    id=chat_session.id,
                    title=chat_session.title or "Untitled Chat",
                    created_at=chat_session.created_at,
                    updated_at=chat_session.updated_at,
                    message_count=len(conversations)
                ))
            
            return response_sessions
        
    except Exception as e:
        logger.error(f"Failed to fetch chat sessions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch chat sessions"
        )

@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get a specific chat session"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.user_id == current_user["id"]
                )
            )
            chat_session = result.scalar_one_or_none()
            
            if not chat_session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Chat session not found"
                )
            
            # Count conversations in this session
            count_result = await session.execute(
                select(Conversation)
                .where(Conversation.chat_session_id == session_id)
            )
            conversations = count_result.scalars().all()
            
            return ChatSessionResponse(
                id=chat_session.id,
                title=chat_session.title or "Untitled Chat",
                created_at=chat_session.created_at,
                updated_at=chat_session.updated_at,
                message_count=len(conversations)
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch chat session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch chat session"
        )

@router.put("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_chat_session(
    session_id: str,
    request: UpdateChatSessionRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update a chat session (e.g., change title)"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.user_id == current_user["id"]
                )
            )
            chat_session = result.scalar_one_or_none()
            
            if not chat_session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Chat session not found"
                )
            
            # Update session
            chat_session.title = request.title
            chat_session.updated_at = datetime.utcnow()
            
            await session.commit()
            await session.refresh(chat_session)
            
            # Count conversations in this session
            count_result = await session.execute(
                select(Conversation)
                .where(Conversation.chat_session_id == session_id)
            )
            conversations = count_result.scalars().all()
            
            return ChatSessionResponse(
                id=chat_session.id,
                title=chat_session.title,
                created_at=chat_session.created_at,
                updated_at=chat_session.updated_at,
                message_count=len(conversations)
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update chat session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update chat session"
        )

@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a chat session and all its conversations"""
    try:
        async with AsyncSessionLocal() as session:
            # Verify session belongs to user
            result = await session.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.user_id == current_user["id"]
                )
            )
            chat_session = result.scalar_one_or_none()
            
            if not chat_session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Chat session not found"
                )
            
            # Delete all conversations in this session first
            conversations_result = await session.execute(
                select(Conversation).where(Conversation.chat_session_id == session_id)
            )
            conversations = conversations_result.scalars().all()
            for conversation in conversations:
                await session.delete(conversation)
            
            # Delete the session
            await session.delete(chat_session)
            await session.commit()
            
            return {"message": "Chat session deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete chat session: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete chat session"
        )

@router.get("/sessions/{session_id}/history", response_model=List[ConversationHistory])
async def get_session_conversation_history(
    session_id: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Get conversation history for a specific session"""
    try:
        async with AsyncSessionLocal() as session:
            # Verify session belongs to user
            session_result = await session.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.user_id == current_user["id"]
                )
            )
            chat_session = session_result.scalar_one_or_none()
            
            if not chat_session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Chat session not found"
                )
            
            # Get conversations for this session
            result = await session.execute(
                select(Conversation)
                .where(Conversation.chat_session_id == session_id)
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch session conversation history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch session conversation history"
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
    """Save conversation to database - creates new session if none exists"""
    conversation_id = str(uuid.uuid4())
    
    async with AsyncSessionLocal() as session:
        # Get or create a default session for legacy support
        result = await session.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(1)
        )
        chat_session = result.scalar_one_or_none()
        
        # If no session exists, create one
        if not chat_session:
            session_id = str(uuid.uuid4())
            chat_session = ChatSession(
                id=session_id,
                user_id=user_id,
                title="General Chat",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(chat_session)
            await session.flush()  # Flush to get the ID
        
        conversation = Conversation(
            id=conversation_id,
            user_id=user_id,
            chat_session_id=chat_session.id,
            message=message,
            response=response,
            context_used=context,
            created_at=datetime.utcnow()
        )
        
        # Update session timestamp
        chat_session.updated_at = datetime.utcnow()
        
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

def build_system_prompt(ongoing_instructions: List[OngoingInstruction], user_name: str = None) -> str:
    """Build system prompt for the financial advisor AI"""
    # Build user context if name is available
    user_context = ""
    if user_name:
        user_context = f"""
USER INFORMATION:
Your name when signing emails is: {user_name}
When composing emails, use this name instead of placeholders like "[Your Name]".
"""
    
    base_prompt = f"""You are an intelligent AI assistant for a financial advisor. You have REAL ACCESS to the user's actual data through a knowledge base that includes:

1. Email data from Gmail (client communications, meeting requests, etc.)
2. Contact and company data from HubSpot CRM
3. Calendar information for scheduling
{user_context}
IMPORTANT: You are NOT a general AI assistant - you are connected to the user's actual Gmail and HubSpot accounts. When they ask about their contacts, emails, or calendar, you can access and provide real information from their accounts.

Your primary responsibilities:
- Help analyze client communications and relationships
- Provide insights about client needs and preferences
- Assist with scheduling and meeting coordination
- Answer questions about client history and interactions
- Suggest follow-up actions based on email content
- List and search through contacts, emails, and calendar events
- PERFORM ACTIONS: Send emails, create calendar events, and create HubSpot contacts when requested

Available Actions:
- **Send Email**: I can send emails on your behalf using your Gmail account
- **Create Calendar Events**: I can schedule meetings and appointments in your Google Calendar
- **Create HubSpot Contacts**: I can add new contacts to your HubSpot CRM

**IMPORTANT - Calendar Event Scheduling Process:**
When a user asks to schedule a meeting/call with someone:
1. FIRST: Search for the contact using their name to find their email address
2. THEN: Create the calendar event with their email in the attendees list
3. This ensures the calendar invitation is sent to them properly

Guidelines:
- **ACCURACY FIRST**: Present data exactly as it exists - do not summarize, paraphrase, or modify information unless specifically asked to do so
- **NO UNNECESSARY SUMMARIZATION**: When showing calendar events, contacts, or emails, present the actual data without condensing or rewriting
- Only organize or format data to make it more readable - never change, omit, or add information
- **TIME ZONE HANDLING**: When mentioning specific times or dates from calendar events, emails, or schedules, note that they should be interpreted in the user's local time zone. Do not assume or mention specific timezones like UTC unless explicitly relevant.
- Always be professional and maintain confidentiality
- Provide specific, actionable insights when possible
- Reference relevant emails or contact information when answering
- If you mention specific people or companies, cite your sources
- Use **bold text** for emphasis and bullet points for lists
- Format your responses with proper markdown for better readability
- When context is provided, USE IT to answer the user's questions
- If you don't have enough information, ask clarifying questions
- When asked to perform actions (send email, schedule meeting, create contact), use the appropriate tools
- Confirm important details before taking actions that affect external systems
- When composing emails, always use your actual name ({user_name if user_name else "your name"}) instead of placeholders like "[Your Name]"
- **PRESENT EXACT DATA**: When listing calendar events, show the exact titles, times, locations, and organizers as they appear in the system
"""
    
    if ongoing_instructions:
        base_prompt += "\n\nOngoing Instructions to Remember:\n"
        for instruction in ongoing_instructions:
            base_prompt += f"- {instruction.instruction}\n"
    
    return base_prompt

async def save_conversation_to_session(user_id: str, session_id: str, message: str, response: str, context: Optional[str] = None) -> str:
    """Save conversation to a specific session"""
    conversation_id = str(uuid.uuid4())
    
    async with AsyncSessionLocal() as session:
        conversation = Conversation(
            id=conversation_id,
            user_id=user_id,
            chat_session_id=session_id,
            message=message,
            response=response,
            context_used=context,
            created_at=datetime.utcnow()
        )
        
        session.add(conversation)
        await session.commit()
    
    return conversation_id

async def get_session_conversation_history(user_id: str, session_id: str, limit: int = 10) -> List[Conversation]:
    """Get recent conversation history for a specific session"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.chat_session_id == session_id
            )
            .order_by(Conversation.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()

async def update_session_timestamp(session_id: str):
    """Update the session's updated_at timestamp"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        chat_session = result.scalar_one_or_none()
        if chat_session:
            chat_session.updated_at = datetime.utcnow()
            await session.commit()

async def auto_generate_session_title(session_id: str, first_message: str):
    """Auto-generate a title for the session based on the first message"""
    try:
        # Clean and truncate the message for a title
        cleaned_message = first_message.strip()
        
        # If message is short enough, use it as is
        if len(cleaned_message) <= 50:
            title = cleaned_message
        else:
            # Truncate at word boundary within 50 characters
            words = cleaned_message.split()
            title = ""
            for word in words:
                if len(title + " " + word) <= 47:  # Leave room for "..."
                    title = title + " " + word if title else word
                else:
                    break
            if title != cleaned_message:
                title += "..."
        
        # Ensure we have a title (fallback if something goes wrong)
        if not title:
            title = "New Chat"
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ChatSession).where(ChatSession.id == session_id)
            )
            chat_session = result.scalar_one_or_none()
            if chat_session:
                chat_session.title = title
                await session.commit()
                
    except Exception as e:
        logger.error(f"Failed to auto-generate session title: {str(e)}")
        # Don't raise error, just log it 