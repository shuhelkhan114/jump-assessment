"""
Proactive AI Router
API endpoints for proactive workflows and AI agent functionality
"""
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
import structlog
from datetime import datetime
from routers.auth import get_current_user
from services.workflow_engine import proactive_workflow_engine
from services.openai_service import openai_service
from services.ai_tools import ai_tools_service, AI_TOOLS_DEFINITIONS
from services.rag_service import rag_service

logger = structlog.get_logger()
router = APIRouter(prefix="/proactive", tags=["proactive"])

# Request models
class ProactiveRequest(BaseModel):
    request: str
    workflow_type: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

class AppointmentRequest(BaseModel):
    contact_name: str
    preferred_date: Optional[str] = None
    duration_minutes: Optional[int] = 60
    message: Optional[str] = None

class FollowUpRequest(BaseModel):
    contact_email: str
    context: Optional[str] = None
    custom_message: Optional[str] = None

class WorkflowContinueRequest(BaseModel):
    workflow_id: str
    response_data: Dict[str, Any]

# Response models
class WorkflowResponse(BaseModel):
    workflow_id: Optional[str]
    status: str
    message: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

@router.post("/execute", response_model=WorkflowResponse)
async def execute_proactive_request(
    request: ProactiveRequest,
    current_user: dict = Depends(get_current_user)
):
    """Execute a proactive AI request with automatic workflow determination"""
    try:
        user_id = current_user["id"]
        
        logger.info(f"Executing proactive request for user {user_id}: {request.request}")
        
        # Check if this is a complex workflow that needs persistence FIRST
        if "appointment" in request.request.lower() or "schedule" in request.request.lower():
            logger.info(f"Detected appointment scheduling request, starting enhanced workflow")
            # Start a persistent workflow for complex scheduling
            workflow_result = await proactive_workflow_engine.start_workflow(
                workflow_type="schedule_appointment",
                user_id=user_id,
                input_data={
                    "user_request": request.request,
                    "contact_name": _extract_contact_name(request.request),
                    "preferred_date": _extract_date(request.request),
                    "tool_results": []
                }
            )
            
            return WorkflowResponse(
                workflow_id=workflow_result.get("workflow_id"),
                status=workflow_result.get("status", "started"),
                message=workflow_result.get("message", "Enhanced appointment scheduling workflow started"),
                result={
                    "workflow_started": True,
                    "workflow_type": "schedule_appointment",
                    "ai_response": "I'm starting the appointment scheduling process. Let me search for the contact and check your availability to send them time options."
                }
            )
        
        # Get RAG context for the request
        context, rag_results = await rag_service.get_context_for_query(request.request, user_id)
        
        # For non-workflow requests, let AI analyze the request
        analysis_result = await openai_service.execute_proactive_workflow(
            user_request=request.request,
            context=context,
            tools=AI_TOOLS_DEFINITIONS
        )
        
        # If AI wants to use tools immediately, execute them
        if analysis_result.get("tool_calls"):
            tool_results = []
            for tool_call in analysis_result["tool_calls"]:
                tool_name = tool_call["function"]["name"]
                import json
                arguments = json.loads(tool_call["function"]["arguments"])
                
                tool_result = await ai_tools_service.execute_tool(
                    tool_name, arguments, user_id
                )
                tool_results.append({
                    "tool_name": tool_name,
                    **tool_result
                })
            
            # Continue workflow with tool results
            conversation_history = [{"role": "user", "content": request.request}]
            if analysis_result.get("content"):
                conversation_history.append({
                    "role": "assistant", 
                    "content": analysis_result["content"]
                })
            
            final_result = await openai_service.continue_workflow(
                conversation_history=conversation_history,
                tool_results=tool_results,
                context=context,
                tools=AI_TOOLS_DEFINITIONS
            )
            
            # For simple requests, return immediate results
            return WorkflowResponse(
                workflow_id=None,
                status="completed",
                message="Request completed successfully",
                result={
                    "ai_response": final_result.get("content"),
                    "tool_results": tool_results,
                    "immediate_completion": True
                }
            )
        
        # If no tools needed, return AI response
        return WorkflowResponse(
            workflow_id=None,
            status="completed", 
            message="Request completed",
            result={
                "ai_response": analysis_result.get("content"),
                "immediate_completion": True
            }
        )
        
    except Exception as e:
        logger.error(f"Proactive request failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute proactive request: {str(e)}"
        )

@router.post("/schedule-appointment", response_model=WorkflowResponse)
async def schedule_appointment(
    request: AppointmentRequest,
    current_user: dict = Depends(get_current_user)
):
    """Start an appointment scheduling workflow"""
    try:
        user_id = current_user["id"]
        
        logger.info(f"Starting appointment scheduling for user {user_id} with {request.contact_name}")
        
        # Start the workflow
        workflow_result = await proactive_workflow_engine.start_workflow(
            workflow_type="schedule_appointment",
            user_id=user_id,
            input_data={
                "user_request": f"Schedule an appointment with {request.contact_name}",
                "contact_name": request.contact_name,
                "preferred_date": request.preferred_date,
                "duration": request.duration_minutes,
                "message": request.message
            },
            name=f"Appointment with {request.contact_name}"
        )
        
        return WorkflowResponse(
            workflow_id=workflow_result.get("workflow_id"),
            status=workflow_result.get("status", "started"),
            message=workflow_result.get("message", "Appointment scheduling started"),
            result=workflow_result.get("result"),
            error=workflow_result.get("error")
        )
        
    except Exception as e:
        logger.error(f"Appointment scheduling failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start appointment scheduling: {str(e)}"
        )

@router.post("/follow-up", response_model=WorkflowResponse)
async def send_follow_up(
    request: FollowUpRequest,
    current_user: dict = Depends(get_current_user)
):
    """Start a follow-up email workflow"""
    try:
        user_id = current_user["id"]
        
        logger.info(f"Starting follow-up workflow for user {user_id} with {request.contact_email}")
        
        # Start the workflow
        workflow_result = await proactive_workflow_engine.start_workflow(
            workflow_type="follow_up_email",
            user_id=user_id,
            input_data={
                "user_request": f"Send follow-up email to {request.contact_email}",
                "contact_email": request.contact_email,
                "context": request.context,
                "custom_message": request.custom_message
            },
            name=f"Follow-up to {request.contact_email}"
        )
        
        return WorkflowResponse(
            workflow_id=workflow_result.get("workflow_id"),
            status=workflow_result.get("status", "started"),
            message=workflow_result.get("message", "Follow-up workflow started"),
            result=workflow_result.get("result"),
            error=workflow_result.get("error")
        )
        
    except Exception as e:
        logger.error(f"Follow-up workflow failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start follow-up workflow: {str(e)}"
        )

@router.post("/continue-workflow", response_model=WorkflowResponse)
async def continue_workflow(
    request: WorkflowContinueRequest,
    current_user: dict = Depends(get_current_user)
):
    """Continue a workflow after receiving external response"""
    try:
        user_id = current_user["id"]
        
        logger.info(f"Continuing workflow {request.workflow_id} for user {user_id}")
        
        # Continue the workflow
        result = await proactive_workflow_engine.continue_workflow_from_response(
            workflow_id=request.workflow_id,
            user_id=user_id,
            response_data=request.response_data
        )
        
        return WorkflowResponse(
            workflow_id=request.workflow_id,
            status=result.get("status", "continued"),
            message=result.get("message", "Workflow continued"),
            result=result.get("result"),
            error=result.get("error")
        )
        
    except Exception as e:
        logger.error(f"Workflow continuation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to continue workflow: {str(e)}"
        )

@router.get("/workflow/{workflow_id}")
async def get_workflow_status(
    workflow_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get the status of a specific workflow"""
    try:
        from database import AsyncSessionLocal, Workflow, WorkflowStep
        from sqlalchemy import select
        
        user_id = current_user["id"]
        
        async with AsyncSessionLocal() as session:
            # Get workflow
            result = await session.execute(
                select(Workflow).where(
                    Workflow.id == workflow_id,
                    Workflow.user_id == user_id
                )
            )
            workflow = result.scalar_one_or_none()
            
            if not workflow:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Workflow not found"
                )
            
            # Get workflow steps
            steps_result = await session.execute(
                select(WorkflowStep).where(
                    WorkflowStep.workflow_id == workflow_id
                ).order_by(WorkflowStep.step_number)
            )
            steps = steps_result.scalars().all()
            
            steps_data = []
            for step in steps:
                steps_data.append({
                    "step_number": step.step_number,
                    "name": step.name,
                    "step_type": step.step_type,
                    "status": step.status,
                    "started_at": step.started_at.isoformat() if step.started_at else None,
                    "completed_at": step.completed_at.isoformat() if step.completed_at else None,
                    "error_message": step.error_message
                })
            
            import json
            return {
                "workflow_id": workflow.id,
                "name": workflow.name,
                "description": workflow.description,
                "status": workflow.status,
                "input_data": json.loads(workflow.input_data) if workflow.input_data else {},
                "created_at": workflow.created_at.isoformat(),
                "updated_at": workflow.updated_at.isoformat(),
                "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None,
                "steps": steps_data
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get workflow status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflow status: {str(e)}"
        )

@router.get("/workflows")
async def list_workflows(
    current_user: dict = Depends(get_current_user),
    status_filter: Optional[str] = None,
    limit: int = 20
):
    """List workflows for the current user"""
    try:
        from database import AsyncSessionLocal, Workflow
        from sqlalchemy import select, desc
        
        user_id = current_user["id"]
        
        async with AsyncSessionLocal() as session:
            query = select(Workflow).where(Workflow.user_id == user_id)
            
            if status_filter:
                query = query.where(Workflow.status == status_filter)
            
            query = query.order_by(desc(Workflow.created_at)).limit(limit)
            
            result = await session.execute(query)
            workflows = result.scalars().all()
            
            workflows_data = []
            for workflow in workflows:
                import json
                workflows_data.append({
                    "workflow_id": workflow.id,
                    "name": workflow.name,
                    "description": workflow.description,
                    "status": workflow.status,
                    "created_at": workflow.created_at.isoformat(),
                    "updated_at": workflow.updated_at.isoformat(),
                    "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None
                })
            
            return {
                "workflows": workflows_data,
                "total": len(workflows_data)
            }
            
    except Exception as e:
        logger.error(f"Failed to list workflows: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list workflows: {str(e)}"
        )

# Helper functions
def _extract_contact_name(request: str) -> str:
    """Extract contact name from natural language request"""
    # Simple extraction - could be enhanced with NLP
    words = request.lower().split()
    
    # Look for patterns like "with [Name]" or "to [Name]"
    for i, word in enumerate(words):
        if word in ["with", "to"] and i + 1 < len(words):
            # Take next 1-2 words as potential name
            if i + 2 < len(words):
                return f"{words[i+1]} {words[i+2]}"
            else:
                return words[i+1]
    
    # Fallback: look for capitalized words
    names = [word for word in request.split() if word[0].isupper() and word.lower() not in ["schedule", "appointment", "meeting"]]
    return " ".join(names[:2]) if names else ""

def _extract_date(request: str) -> Optional[str]:
    """Extract date from natural language request"""
    # Simple extraction - could be enhanced with date parsing libraries
    import re
    
    # Look for date patterns
    date_patterns = [
        r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
        r'\d{1,2}/\d{1,2}/\d{4}',  # MM/DD/YYYY
        r'tomorrow',
        r'next week',
        r'monday|tuesday|wednesday|thursday|friday|saturday|sunday'
    ]
    
    request_lower = request.lower()
    for pattern in date_patterns:
        match = re.search(pattern, request_lower)
        if match:
            return match.group(0)
    
    return None 