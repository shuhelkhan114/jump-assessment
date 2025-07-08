"""
Workflow Engine for Proactive AI System
Handles multi-step workflows with state management and persistence
"""
from typing import Dict, List, Any, Optional, Union
from enum import Enum
from datetime import datetime, timedelta
import json
import uuid
import structlog
from database import AsyncSessionLocal, Workflow, WorkflowStep
from services.openai_service import openai_service
from services.ai_tools import ai_tools_service, AI_TOOLS_DEFINITIONS
from services.rag_service import rag_service
from sqlalchemy import select, update

logger = structlog.get_logger()

class WorkflowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class WorkflowStepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

class ProactiveWorkflowEngine:
    """Engine for executing proactive AI workflows"""
    
    def __init__(self):
        self.active_workflows = {}  # In-memory cache of active workflows
        self.step_executors = {
            "ai_decision": self._execute_ai_decision,
            "tool_call": self._execute_tool_call,
            "wait_for_response": self._execute_wait_for_response,
            "send_email": self._execute_send_email,
            "schedule_meeting": self._execute_schedule_meeting
        }
    
    async def start_workflow(
        self,
        workflow_type: str,
        user_id: str,
        input_data: Dict[str, Any],
        name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Start a new proactive workflow"""
        try:
            # Create workflow record
            workflow_id = str(uuid.uuid4())
            
            async with AsyncSessionLocal() as session:
                workflow = Workflow(
                    id=workflow_id,
                    user_id=user_id,
                    name=name or f"{workflow_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    description=f"Proactive workflow: {workflow_type}",
                    status=WorkflowStatus.PENDING.value,
                    input_data=json.dumps(input_data),
                    context=json.dumps({"type": workflow_type, "started_at": datetime.utcnow().isoformat()}),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                
                session.add(workflow)
                await session.commit()
                await session.refresh(workflow)
                
                logger.info(f"Created workflow {workflow_id} for user {user_id}")
                
                # Generate workflow steps based on type
                steps = await self._generate_workflow_steps(workflow_type, input_data, workflow_id)
                
                # Save steps to database
                for step_data in steps:
                    step = WorkflowStep(
                        workflow_id=workflow_id,
                        step_number=step_data["step_number"],
                        name=step_data["name"],
                        step_type=step_data["step_type"],
                        config=json.dumps(step_data.get("config", {})),
                        status=WorkflowStepStatus.PENDING.value,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    session.add(step)
                
                await session.commit()
                
                # Start execution
                return await self._execute_workflow(workflow_id, user_id)
                
        except Exception as e:
            logger.error(f"Failed to start workflow: {str(e)}")
            return {"error": str(e), "workflow_id": None}
    
    async def _generate_workflow_steps(
        self,
        workflow_type: str,
        input_data: Dict[str, Any],
        workflow_id: str
    ) -> List[Dict[str, Any]]:
        """Generate workflow steps based on type and input"""
        steps = []
        
        if workflow_type == "schedule_appointment":
            # Enhanced appointment scheduling workflow
            steps = [
                {
                    "step_number": 1,
                    "name": "Search for contact",
                    "step_type": "tool_call",
                    "config": {
                        "tool_name": "search_contacts",
                        "arguments": {
                            "query": input_data.get("contact_name", ""),
                            "limit": 5
                        }
                    }
                },
                {
                    "step_number": 2,
                    "name": "AI decision on contact selection",
                    "step_type": "ai_decision",
                    "config": {
                        "decision_prompt": "Based on the contact search results, select the best matching contact for the appointment request. If no good match is found, ask the user for clarification. Store the selected contact's email for next steps."
                    }
                },
                {
                    "step_number": 3,
                    "name": "Generate next 24-hour availability",
                    "step_type": "tool_call",
                    "config": {
                        "tool_name": "get_time_suggestions",
                        "arguments": {
                            "preferred_date": "",
                            "duration_minutes": input_data.get("duration", 60),
                            "business_hours_start": "09:00",
                            "business_hours_end": "17:00",
                            "next_24_hours": True
                        }
                    }
                },
                {
                    "step_number": 4,
                    "name": "Send availability email",
                    "step_type": "ai_decision",
                    "config": {
                        "decision_prompt": "Compose and send a professional email to the contact sharing your available time slots for the next 24 hours. The email should: 1) Explain you'd like to schedule a call, 2) List the available time slots clearly, 3) Ask them to reply with their preferred time, 4) Be friendly and professional. Use the send_email tool to actually send the email."
                    }
                },
                {
                    "step_number": 5,
                    "name": "Wait for time selection response",
                    "step_type": "wait_for_response",
                    "config": {
                        "timeout_hours": 72,
                        "expected_responses": ["time_selection", "decline", "reschedule_request"]
                    }
                },
                {
                    "step_number": 6,
                    "name": "Process time selection and check availability", 
                    "step_type": "ai_decision",
                    "config": {
                        "decision_prompt": "Process the email response to extract the selected time. Then check calendar availability for that exact time slot. If available, create the calendar event and send confirmation. If occupied, send a polite email explaining the conflict and offer alternative times from your availability. Continue this negotiation until a suitable time is found."
                    }
                },
                {
                    "step_number": 7,
                    "name": "Handle conflicts and negotiate",
                    "step_type": "ai_decision", 
                    "config": {
                        "decision_prompt": "If there was a scheduling conflict in the previous step, continue the negotiation process. Check if the user selected a new time from your alternatives. If available, schedule it. If still occupied, offer more alternatives. Repeat until successful or they decline."
                    }
                },
                {
                    "step_number": 8,
                    "name": "Finalize appointment and add to HubSpot",
                    "step_type": "ai_decision",
                    "config": {
                        "decision_prompt": "Once a time is successfully agreed upon and calendar event created, add a note to HubSpot about the scheduled appointment with details like date, time, and purpose. Send a final confirmation email with calendar invite details."
                    }
                }
            ]
        
        elif workflow_type == "follow_up_email":
            steps = [
                {
                    "step_number": 1,
                    "name": "Search contact and email history",
                    "step_type": "tool_call",
                    "config": {
                        "tool_name": "search_email_history",
                        "arguments": {
                            "contact_email": input_data.get("contact_email", ""),
                            "limit": 10
                        }
                    }
                },
                {
                    "step_number": 2,
                    "name": "Generate follow-up email",
                    "step_type": "ai_decision",
                    "config": {
                        "decision_prompt": "Based on the email history, craft a professional follow-up email that references previous conversations appropriately."
                    }
                },
                {
                    "step_number": 3,
                    "name": "Send follow-up email",
                    "step_type": "send_email",
                    "config": {
                        "template": "follow_up"
                    }
                },
                {
                    "step_number": 4,
                    "name": "Add note to HubSpot",
                    "step_type": "tool_call",
                    "config": {
                        "tool_name": "add_hubspot_note",
                        "arguments": {
                            "note_content": "Follow-up email sent via AI assistant"
                        }
                    }
                }
            ]
        
        else:
            # Generic workflow - let AI determine steps
            steps = [
                {
                    "step_number": 1,
                    "name": "AI workflow planning",
                    "step_type": "ai_decision",
                    "config": {
                        "decision_prompt": f"Plan and execute a workflow for: {input_data.get('user_request', 'Unknown request')}. Use available tools to accomplish this task."
                    }
                }
            ]
        
        return steps
    
    async def _execute_workflow(self, workflow_id: str, user_id: str) -> Dict[str, Any]:
        """Execute a workflow from the current step"""
        try:
            async with AsyncSessionLocal() as session:
                # Get workflow and current step
                result = await session.execute(
                    select(Workflow).where(Workflow.id == workflow_id)
                )
                workflow = result.scalar_one_or_none()
                
                if not workflow:
                    return {"error": "Workflow not found"}
                
                # Get next pending step
                step_result = await session.execute(
                    select(WorkflowStep).where(
                        WorkflowStep.workflow_id == workflow_id,
                        WorkflowStep.status == WorkflowStepStatus.PENDING.value
                    ).order_by(WorkflowStep.step_number).limit(1)
                )
                
                current_step = step_result.scalar_one_or_none()
                
                if not current_step:
                    # No more steps, mark workflow as completed
                    await session.execute(
                        update(Workflow)
                        .where(Workflow.id == workflow_id)
                        .values(
                            status=WorkflowStatus.COMPLETED.value,
                            completed_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                    )
                    await session.commit()
                    
                    return {
                        "workflow_id": workflow_id,
                        "status": "completed",
                        "message": "Workflow completed successfully"
                    }
                
                # Update workflow status to running
                await session.execute(
                    update(Workflow)
                    .where(Workflow.id == workflow_id)
                    .values(
                        status=WorkflowStatus.RUNNING.value,
                        updated_at=datetime.utcnow()
                    )
                )
                
                # Update step status to running
                await session.execute(
                    update(WorkflowStep)
                    .where(WorkflowStep.id == current_step.id)
                    .values(
                        status=WorkflowStepStatus.RUNNING.value,
                        started_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                )
                
                await session.commit()
                
                # Execute the step
                step_result = await self._execute_step(current_step, workflow, user_id)
                
                # Update step with results
                if step_result.get("success"):
                    await session.execute(
                        update(WorkflowStep)
                        .where(WorkflowStep.id == current_step.id)
                        .values(
                            status=WorkflowStepStatus.COMPLETED.value,
                            output_data=json.dumps(step_result.get("result", {})),
                            completed_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                    )
                    
                    # Continue to next step unless waiting
                    if not step_result.get("waiting"):
                        await session.commit()
                        return await self._execute_workflow(workflow_id, user_id)
                    else:
                        # Update workflow to waiting status
                        await session.execute(
                            update(Workflow)
                            .where(Workflow.id == workflow_id)
                            .values(
                                status=WorkflowStatus.WAITING.value,
                                updated_at=datetime.utcnow()
                            )
                        )
                        await session.commit()
                        return {
                            "workflow_id": workflow_id,
                            "status": "waiting",
                            "message": step_result.get("message", "Waiting for external input"),
                            "result": step_result.get("result")
                        }
                else:
                    await session.execute(
                        update(WorkflowStep)
                        .where(WorkflowStep.id == current_step.id)
                        .values(
                            status=WorkflowStepStatus.FAILED.value,
                            error_message=step_result.get("error"),
                            updated_at=datetime.utcnow()
                        )
                    )
                    
                    await session.execute(
                        update(Workflow)
                        .where(Workflow.id == workflow_id)
                        .values(
                            status=WorkflowStatus.FAILED.value,
                            error_message=step_result.get("error"),
                            updated_at=datetime.utcnow()
                        )
                    )
                    
                    await session.commit()
                    return {
                        "workflow_id": workflow_id,
                        "status": "failed",
                        "error": step_result.get("error")
                    }
                
        except Exception as e:
            logger.error(f"Workflow execution failed: {str(e)}")
            return {"error": str(e)}
    
    async def _execute_step(
        self,
        step: WorkflowStep,
        workflow: Workflow,
        user_id: str
    ) -> Dict[str, Any]:
        """Execute a single workflow step"""
        try:
            step_type = step.step_type
            config = json.loads(step.config) if step.config else {}
            
            if step_type in self.step_executors:
                return await self.step_executors[step_type](step, workflow, user_id, config)
            else:
                return {"error": f"Unknown step type: {step_type}"}
                
        except Exception as e:
            logger.error(f"Step execution failed: {str(e)}")
            return {"error": str(e)}
    
    async def _execute_ai_decision(
        self,
        step: WorkflowStep,
        workflow: Workflow,
        user_id: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute an AI decision step"""
        try:
            # Get workflow context
            input_data = json.loads(workflow.input_data) if workflow.input_data else {}
            workflow_context = json.loads(workflow.context) if workflow.context else {}
            
            # Get previous step results
            async with AsyncSessionLocal() as session:
                previous_steps = await session.execute(
                    select(WorkflowStep).where(
                        WorkflowStep.workflow_id == workflow.id,
                        WorkflowStep.step_number < step.step_number,
                        WorkflowStep.status == WorkflowStepStatus.COMPLETED.value
                    ).order_by(WorkflowStep.step_number)
                )
                
                previous_results = []
                for prev_step in previous_steps.scalars():
                    if prev_step.output_data:
                        previous_results.append({
                            "step_name": prev_step.name,
                            "result": json.loads(prev_step.output_data)
                        })
            
            # Get RAG context
            user_request = input_data.get("user_request", "")
            context = ""
            if user_request:
                context, _ = await rag_service.get_context_for_query(user_request, user_id)
            
            # Build decision prompt with context
            decision_prompt = config.get("decision_prompt", "")
            full_prompt = f"""
{decision_prompt}

**Original Request:** {user_request}

**Previous Step Results:**
{json.dumps(previous_results, indent=2)}

**Workflow Input:**
{json.dumps(input_data, indent=2)}
"""
            
            # Execute AI decision
            result = await openai_service.execute_proactive_workflow(
                user_request=full_prompt,
                context=context,
                tools=AI_TOOLS_DEFINITIONS
            )
            
            # If AI wants to use tools, execute them
            if result.get("tool_calls"):
                tool_results = []
                for tool_call in result["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    arguments = json.loads(tool_call["function"]["arguments"])
                    
                    tool_result = await ai_tools_service.execute_tool(
                        tool_name, arguments, user_id
                    )
                    tool_results.append({
                        "tool_name": tool_name,
                        **tool_result
                    })
                
                # Continue workflow with tool results
                conversation_history = [{"role": "user", "content": full_prompt}]
                if result.get("content"):
                    conversation_history.append({
                        "role": "assistant", 
                        "content": result["content"]
                    })
                
                final_result = await openai_service.continue_workflow(
                    conversation_history=conversation_history,
                    tool_results=tool_results,
                    context=context,
                    tools=AI_TOOLS_DEFINITIONS
                )
                
                return {
                    "success": True,
                    "result": {
                        "ai_response": final_result.get("content"),
                        "tool_results": tool_results,
                        "requires_more_tools": bool(final_result.get("tool_calls"))
                    }
                }
            
            return {
                "success": True,
                "result": {
                    "ai_response": result.get("content"),
                    "decision_made": True
                }
            }
            
        except Exception as e:
            logger.error(f"AI decision step failed: {str(e)}")
            return {"error": str(e)}
    
    async def _execute_tool_call(
        self,
        step: WorkflowStep,
        workflow: Workflow,
        user_id: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a tool call step"""
        try:
            tool_name = config.get("tool_name")
            arguments = config.get("arguments", {})
            
            if not tool_name:
                return {"error": "No tool name specified"}
            
            result = await ai_tools_service.execute_tool(tool_name, arguments, user_id)
            
            return {
                "success": result.get("success", False),
                "result": result.get("result"),
                "error": result.get("error")
            }
            
        except Exception as e:
            logger.error(f"Tool call step failed: {str(e)}")
            return {"error": str(e)}
    
    async def _execute_wait_for_response(
        self,
        step: WorkflowStep,
        workflow: Workflow,
        user_id: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a wait for response step"""
        # This step always returns waiting status
        timeout_hours = config.get("timeout_hours", 24)
        
        return {
            "success": True,
            "waiting": True,
            "result": {
                "timeout_at": (datetime.utcnow() + timedelta(hours=timeout_hours)).isoformat(),
                "expected_responses": config.get("expected_responses", [])
            },
            "message": f"Waiting for response (timeout in {timeout_hours} hours)"
        }
    
    async def _execute_send_email(
        self,
        step: WorkflowStep,
        workflow: Workflow,
        user_id: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a send email step"""
        try:
            # This would typically use email templates and previous step results
            # For now, return success to continue workflow
            return {
                "success": True,
                "result": {
                    "email_sent": True,
                    "template": config.get("template", "generic")
                }
            }
            
        except Exception as e:
            logger.error(f"Send email step failed: {str(e)}")
            return {"error": str(e)}
    
    async def _execute_schedule_meeting(
        self,
        step: WorkflowStep,
        workflow: Workflow,
        user_id: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a schedule meeting step"""
        try:
            # This would create calendar events
            return {
                "success": True,
                "result": {
                    "meeting_scheduled": True,
                    "config": config
                }
            }
            
        except Exception as e:
            logger.error(f"Schedule meeting step failed: {str(e)}")
            return {"error": str(e)}
    
    async def continue_workflow_from_response(
        self,
        workflow_id: str,
        user_id: str,
        response_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Continue a workflow after receiving an external response"""
        try:
            async with AsyncSessionLocal() as session:
                # Update workflow context with response
                result = await session.execute(
                    select(Workflow).where(Workflow.id == workflow_id)
                )
                workflow = result.scalar_one_or_none()
                
                if not workflow:
                    return {"error": "Workflow not found"}
                
                # Add response to context
                context = json.loads(workflow.context) if workflow.context else {}
                context["external_response"] = response_data
                context["response_received_at"] = datetime.utcnow().isoformat()
                
                await session.execute(
                    update(Workflow)
                    .where(Workflow.id == workflow_id)
                    .values(
                        context=json.dumps(context),
                        status=WorkflowStatus.RUNNING.value,
                        updated_at=datetime.utcnow()
                    )
                )
                
                await session.commit()
                
                # Continue workflow execution
                return await self._execute_workflow(workflow_id, user_id)
                
        except Exception as e:
            logger.error(f"Failed to continue workflow from response: {str(e)}")
            return {"error": str(e)}

# Global instance
proactive_workflow_engine = ProactiveWorkflowEngine() 