"""
Workflow Engine Service for managing complex multi-step workflows
"""
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple, Union
from enum import Enum
import structlog
from sqlalchemy import select, update
from database import AsyncSessionLocal, Workflow, WorkflowStep, WorkflowTemplate, Event, OngoingInstruction
from services.openai_service import openai_service

logger = structlog.get_logger()

class WorkflowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

class StepType(Enum):
    TOOL_CALL = "tool_call"
    AI_DECISION = "ai_decision"
    CONDITION = "condition"
    WAIT = "wait"
    DELAY = "delay"
    PARALLEL = "parallel"
    BRANCH = "branch"
    MERGE = "merge"

class WorkflowEngine:
    """Core workflow engine for managing complex multi-step processes"""
    
    def __init__(self):
        self.running_workflows = {}  # Cache of active workflows
        
    async def create_workflow(
        self, 
        user_id: str, 
        name: str, 
        steps: List[Dict[str, Any]], 
        template_id: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
        triggered_by_event_id: Optional[str] = None,
        description: Optional[str] = None
    ) -> str:
        """Create a new workflow instance"""
        try:
            workflow_id = f"wf_{int(datetime.utcnow().timestamp() * 1000)}"
            
            async with AsyncSessionLocal() as session:
                # Create workflow record
                workflow = Workflow(
                    id=workflow_id,
                    user_id=user_id,
                    template_id=template_id,
                    name=name,
                    description=description,
                    status=WorkflowStatus.PENDING.value,
                    context=json.dumps({}),
                    input_data=json.dumps(input_data or {}),
                    triggered_by_event_id=triggered_by_event_id,
                    created_at=datetime.utcnow()
                )
                session.add(workflow)
                
                # Create workflow steps
                for i, step_config in enumerate(steps):
                    step = WorkflowStep(
                        workflow_id=workflow_id,
                        step_number=i + 1,
                        name=step_config.get("name", f"Step {i + 1}"),
                        step_type=step_config.get("type", StepType.TOOL_CALL.value),
                        config=json.dumps(step_config),
                        condition=json.dumps(step_config.get("condition")),
                        depends_on_steps=json.dumps(step_config.get("depends_on", [])),
                        timeout_seconds=step_config.get("timeout", 300),
                        max_retries=step_config.get("max_retries", 2)
                    )
                    session.add(step)
                
                await session.commit()
                
            logger.info(f"Created workflow {workflow_id} with {len(steps)} steps")
            return workflow_id
            
        except Exception as e:
            logger.error(f"Failed to create workflow: {str(e)}")
            raise
    
    async def start_workflow(self, workflow_id: str) -> bool:
        """Start executing a workflow"""
        try:
            async with AsyncSessionLocal() as session:
                # Get workflow
                result = await session.execute(
                    select(Workflow).where(Workflow.id == workflow_id)
                )
                workflow = result.scalar_one_or_none()
                
                if not workflow:
                    logger.error(f"Workflow {workflow_id} not found")
                    return False
                
                if workflow.status != WorkflowStatus.PENDING.value:
                    logger.warning(f"Workflow {workflow_id} is not in pending status: {workflow.status}")
                    return False
                
                # Update status to running
                workflow.status = WorkflowStatus.RUNNING.value
                workflow.started_at = datetime.utcnow()
                workflow.current_step = 1
                await session.commit()
                
            # Cache workflow for execution
            self.running_workflows[workflow_id] = workflow
            
            # Start execution
            success = await self._execute_workflow(workflow_id)
            
            logger.info(f"Workflow {workflow_id} started: {success}")
            return success
            
        except Exception as e:
            logger.error(f"Failed to start workflow {workflow_id}: {str(e)}")
            await self._mark_workflow_failed(workflow_id, str(e))
            return False
    
    async def _execute_workflow(self, workflow_id: str) -> bool:
        """Execute workflow steps with branching logic"""
        try:
            async with AsyncSessionLocal() as session:
                # Get workflow and steps
                workflow_result = await session.execute(
                    select(Workflow).where(Workflow.id == workflow_id)
                )
                workflow = workflow_result.scalar_one_or_none()
                
                if not workflow:
                    return False
                
                steps_result = await session.execute(
                    select(WorkflowStep)
                    .where(WorkflowStep.workflow_id == workflow_id)
                    .order_by(WorkflowStep.step_number)
                )
                steps = steps_result.scalars().all()
                
                context = json.loads(workflow.context or "{}")
                
                # Execute steps sequentially with branching support
                current_step_num = workflow.current_step
                
                while current_step_num <= len(steps):
                    step = next((s for s in steps if s.step_number == current_step_num), None)
                    if not step:
                        break
                    
                    # Check dependencies
                    if not await self._check_step_dependencies(step, steps):
                        logger.info(f"Step {step.step_number} dependencies not met, skipping")
                        current_step_num += 1
                        continue
                    
                    # Check conditions
                    if not await self._evaluate_step_condition(step, context):
                        logger.info(f"Step {step.step_number} condition not met, skipping")
                        step.status = StepStatus.SKIPPED.value
                        await session.commit()
                        current_step_num += 1
                        continue
                    
                    # Execute step
                    success, next_step, updated_context = await self._execute_step(step, context, workflow.user_id)
                    
                    # Update context
                    context.update(updated_context)
                    workflow.context = json.dumps(context)
                    
                    if not success:
                        if step.retry_count < step.max_retries:
                            step.retry_count += 1
                            logger.info(f"Retrying step {step.step_number}, attempt {step.retry_count}")
                            continue
                        else:
                            # Step failed permanently
                            await self._mark_workflow_failed(workflow_id, f"Step {step.step_number} failed")
                            return False
                    
                    # Handle step result and determine next step
                    if next_step is not None:
                        current_step_num = next_step
                    else:
                        current_step_num += 1
                    
                    workflow.current_step = current_step_num
                    await session.commit()
                    
                    # If step requires waiting (e.g., waiting for email response)
                    if step.step_type == StepType.WAIT.value:
                        await self._mark_workflow_waiting(workflow_id, step)
                        return True  # Workflow will be resumed later
                
                # All steps completed successfully
                await self._mark_workflow_completed(workflow_id)
                return True
                
        except Exception as e:
            logger.error(f"Error executing workflow {workflow_id}: {str(e)}")
            await self._mark_workflow_failed(workflow_id, str(e))
            return False
    
    async def _execute_step(
        self, 
        step: WorkflowStep, 
        context: Dict[str, Any], 
        user_id: str
    ) -> Tuple[bool, Optional[int], Dict[str, Any]]:
        """Execute a single workflow step"""
        try:
            logger.info(f"Executing step {step.step_number}: {step.name} ({step.step_type})")
            
            step.status = StepStatus.RUNNING.value
            step.started_at = datetime.utcnow()
            
            config = json.loads(step.config)
            updated_context = {}
            next_step = None
            
            if step.step_type == StepType.TOOL_CALL.value:
                success, result, updated_context = await self._execute_tool_call_step(config, context, user_id)
                
            elif step.step_type == StepType.AI_DECISION.value:
                success, result, updated_context, next_step = await self._execute_ai_decision_step(config, context, user_id)
                
            elif step.step_type == StepType.CONDITION.value:
                success, result, next_step = await self._execute_condition_step(config, context)
                
            elif step.step_type == StepType.WAIT.value:
                success, result = await self._execute_wait_step(config, context)
                
            elif step.step_type == StepType.DELAY.value:
                success, result = await self._execute_delay_step(config)
                
            elif step.step_type == StepType.BRANCH.value:
                success, result, next_step = await self._execute_branch_step(config, context)
                
            else:
                logger.error(f"Unknown step type: {step.step_type}")
                success = False
                result = f"Unknown step type: {step.step_type}"
            
            # Update step status
            if success:
                step.status = StepStatus.COMPLETED.value
                step.output_data = json.dumps(result)
            else:
                step.status = StepStatus.FAILED.value
                step.error_message = str(result)
            
            step.completed_at = datetime.utcnow()
            
            logger.info(f"Step {step.step_number} completed: {success}")
            return success, next_step, updated_context
            
        except Exception as e:
            logger.error(f"Error executing step {step.step_number}: {str(e)}")
            step.status = StepStatus.FAILED.value
            step.error_message = str(e)
            step.completed_at = datetime.utcnow()
            return False, None, {}
    
    async def _execute_tool_call_step(
        self, 
        config: Dict[str, Any], 
        context: Dict[str, Any], 
        user_id: str
    ) -> Tuple[bool, Any, Dict[str, Any]]:
        """Execute a tool call step"""
        try:
            from tasks.ai_tasks import execute_ai_action
            
            # Get tool configuration
            tool_name = config.get("tool")
            tool_params = config.get("params", {})
            
            # Substitute context variables in parameters
            resolved_params = self._resolve_context_variables(tool_params, context)
            
            # Execute tool via Celery
            task_result = execute_ai_action.delay(user_id, tool_name, resolved_params)
            result = task_result.get(timeout=config.get("timeout", 30))
            
            # Extract useful data for context
            updated_context = {}
            if isinstance(result, dict):
                if result.get("status") == "success":
                    updated_context[f"step_{config.get('name', 'tool')}_result"] = result.get("details", result)
                    return True, result, updated_context
            
            return False, result, {}
            
        except Exception as e:
            logger.error(f"Tool call step failed: {str(e)}")
            return False, str(e), {}
    
    async def _execute_ai_decision_step(
        self, 
        config: Dict[str, Any], 
        context: Dict[str, Any], 
        user_id: str
    ) -> Tuple[bool, Any, Dict[str, Any], Optional[int]]:
        """Execute an AI decision step"""
        try:
            # Get decision prompt and options
            prompt = config.get("prompt", "Make a decision based on the context")
            options = config.get("options", [])
            
            # Build context for AI
            context_str = json.dumps(context, indent=2)
            full_prompt = f"""
{prompt}

Context:
{context_str}

Available options:
{json.dumps(options, indent=2)}

Please respond with your decision and reasoning.
"""
            
            # Get AI decision
            response = await openai_service.chat_completion(
                messages=[{"role": "user", "content": full_prompt}],
                system_prompt="You are a workflow decision engine. Make clear, actionable decisions based on the provided context."
            )
            
            decision_text = response.get("content", "")
            
            # Parse decision and determine next step
            next_step = None
            updated_context = {
                f"ai_decision_{config.get('name', 'decision')}": {
                    "decision": decision_text,
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
            
            # If options specify next steps, try to match decision
            for option in options:
                if option.get("keyword", "").lower() in decision_text.lower():
                    next_step = option.get("next_step")
                    break
            
            return True, decision_text, updated_context, next_step
            
        except Exception as e:
            logger.error(f"AI decision step failed: {str(e)}")
            return False, str(e), {}, None
    
    async def _execute_condition_step(
        self, 
        config: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Tuple[bool, Any, Optional[int]]:
        """Execute a condition step with branching"""
        try:
            condition = config.get("condition", {})
            true_step = config.get("true_step")
            false_step = config.get("false_step")
            
            # Evaluate condition
            result = self._evaluate_condition(condition, context)
            
            next_step = true_step if result else false_step
            
            return True, {"condition_result": result, "next_step": next_step}, next_step
            
        except Exception as e:
            logger.error(f"Condition step failed: {str(e)}")
            return False, str(e), None
    
    async def _execute_wait_step(
        self, 
        config: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Tuple[bool, Any]:
        """Execute a wait step (wait for external event)"""
        try:
            wait_type = config.get("wait_type", "email_response")
            timeout_hours = config.get("timeout_hours", 24)
            
            # Calculate timeout
            timeout_at = datetime.utcnow() + timedelta(hours=timeout_hours)
            
            result = {
                "waiting_for": wait_type,
                "timeout_at": timeout_at.isoformat(),
                "context_match": config.get("context_match", {})
            }
            
            return True, result
            
        except Exception as e:
            logger.error(f"Wait step failed: {str(e)}")
            return False, str(e)
    
    async def _execute_delay_step(self, config: Dict[str, Any]) -> Tuple[bool, Any]:
        """Execute a delay step (simple sleep)"""
        try:
            delay_seconds = config.get("delay_seconds", 1)
            await asyncio.sleep(delay_seconds)
            
            return True, {"delayed_seconds": delay_seconds}
            
        except Exception as e:
            logger.error(f"Delay step failed: {str(e)}")
            return False, str(e)
    
    async def _execute_branch_step(
        self, 
        config: Dict[str, Any], 
        context: Dict[str, Any]
    ) -> Tuple[bool, Any, Optional[int]]:
        """Execute a branch step (conditional branching)"""
        try:
            branches = config.get("branches", [])
            default_step = config.get("default_step")
            
            # Evaluate each branch condition
            for branch in branches:
                condition = branch.get("condition", {})
                if self._evaluate_condition(condition, context):
                    next_step = branch.get("next_step")
                    return True, {"branch_taken": branch.get("name", "unnamed"), "next_step": next_step}, next_step
            
            # No conditions met, use default
            return True, {"branch_taken": "default", "next_step": default_step}, default_step
            
        except Exception as e:
            logger.error(f"Branch step failed: {str(e)}")
            return False, str(e), None
    
    def _evaluate_condition(self, condition: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """Evaluate a condition against context"""
        try:
            condition_type = condition.get("type", "equals")
            field = condition.get("field")
            value = condition.get("value")
            
            if not field:
                return False
            
            # Get field value from context
            field_value = self._get_nested_value(context, field)
            
            if condition_type == "equals":
                return field_value == value
            elif condition_type == "not_equals":
                return field_value != value
            elif condition_type == "contains":
                return value in str(field_value)
            elif condition_type == "exists":
                return field_value is not None
            elif condition_type == "greater_than":
                return float(field_value or 0) > float(value)
            elif condition_type == "less_than":
                return float(field_value or 0) < float(value)
            else:
                logger.warning(f"Unknown condition type: {condition_type}")
                return False
                
        except Exception as e:
            logger.error(f"Error evaluating condition: {str(e)}")
            return False
    
    def _get_nested_value(self, data: Dict[str, Any], field: str) -> Any:
        """Get nested value from dict using dot notation"""
        try:
            keys = field.split(".")
            value = data
            for key in keys:
                value = value.get(key)
                if value is None:
                    break
            return value
        except Exception:
            return None
    
    def _resolve_context_variables(self, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Replace context variables in parameters"""
        try:
            resolved = {}
            for key, value in params.items():
                if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
                    # Context variable reference
                    var_name = value[2:-2].strip()
                    resolved[key] = self._get_nested_value(context, var_name)
                else:
                    resolved[key] = value
            return resolved
        except Exception as e:
            logger.error(f"Error resolving context variables: {str(e)}")
            return params
    
    async def _check_step_dependencies(self, step: WorkflowStep, all_steps: List[WorkflowStep]) -> bool:
        """Check if step dependencies are satisfied"""
        try:
            depends_on = json.loads(step.depends_on_steps or "[]")
            if not depends_on:
                return True
            
            for dep_step_num in depends_on:
                dep_step = next((s for s in all_steps if s.step_number == dep_step_num), None)
                if not dep_step or dep_step.status != StepStatus.COMPLETED.value:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking dependencies: {str(e)}")
            return False
    
    async def _evaluate_step_condition(self, step: WorkflowStep, context: Dict[str, Any]) -> bool:
        """Evaluate if step condition is met"""
        try:
            condition = json.loads(step.condition or "null")
            if not condition:
                return True  # No condition means always execute
            
            return self._evaluate_condition(condition, context)
            
        except Exception as e:
            logger.error(f"Error evaluating step condition: {str(e)}")
            return True  # Default to execute on error
    
    async def _mark_workflow_waiting(self, workflow_id: str, step: WorkflowStep):
        """Mark workflow as waiting for external event"""
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Workflow)
                    .where(Workflow.id == workflow_id)
                    .values(
                        status=WorkflowStatus.WAITING.value,
                        next_execution_at=datetime.utcnow() + timedelta(hours=24),  # Default 24h timeout
                        updated_at=datetime.utcnow()
                    )
                )
                await session.commit()
                
            logger.info(f"Workflow {workflow_id} marked as waiting")
            
        except Exception as e:
            logger.error(f"Error marking workflow waiting: {str(e)}")
    
    async def _mark_workflow_completed(self, workflow_id: str):
        """Mark workflow as completed"""
        try:
            async with AsyncSessionLocal() as session:
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
                
            # Remove from running cache
            self.running_workflows.pop(workflow_id, None)
            
            logger.info(f"Workflow {workflow_id} completed successfully")
            
        except Exception as e:
            logger.error(f"Error marking workflow completed: {str(e)}")
    
    async def _mark_workflow_failed(self, workflow_id: str, error_message: str):
        """Mark workflow as failed"""
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Workflow)
                    .where(Workflow.id == workflow_id)
                    .values(
                        status=WorkflowStatus.FAILED.value,
                        error_message=error_message,
                        completed_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                )
                await session.commit()
                
            # Remove from running cache
            self.running_workflows.pop(workflow_id, None)
            
            logger.error(f"Workflow {workflow_id} failed: {error_message}")
            
        except Exception as e:
            logger.error(f"Error marking workflow failed: {str(e)}")
    
    async def resume_workflow(self, workflow_id: str, resume_data: Optional[Dict[str, Any]] = None) -> bool:
        """Resume a waiting workflow"""
        try:
            async with AsyncSessionLocal() as session:
                # Get workflow
                result = await session.execute(
                    select(Workflow).where(Workflow.id == workflow_id)
                )
                workflow = result.scalar_one_or_none()
                
                if not workflow:
                    logger.error(f"Workflow {workflow_id} not found")
                    return False
                
                if workflow.status != WorkflowStatus.WAITING.value:
                    logger.warning(f"Workflow {workflow_id} is not waiting: {workflow.status}")
                    return False
                
                # Update context with resume data
                context = json.loads(workflow.context or "{}")
                if resume_data:
                    context.update(resume_data)
                    workflow.context = json.dumps(context)
                
                # Change status back to running
                workflow.status = WorkflowStatus.RUNNING.value
                workflow.next_execution_at = None
                await session.commit()
                
            # Resume execution
            return await self._execute_workflow(workflow_id)
            
        except Exception as e:
            logger.error(f"Error resuming workflow {workflow_id}: {str(e)}")
            return False
    
    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get current workflow status"""
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Workflow).where(Workflow.id == workflow_id)
                )
                workflow = result.scalar_one_or_none()
                
                if not workflow:
                    return None
                
                steps_result = await session.execute(
                    select(WorkflowStep)
                    .where(WorkflowStep.workflow_id == workflow_id)
                    .order_by(WorkflowStep.step_number)
                )
                steps = steps_result.scalars().all()
                
                return {
                    "id": workflow.id,
                    "name": workflow.name,
                    "status": workflow.status,
                    "current_step": workflow.current_step,
                    "total_steps": len(steps),
                    "started_at": workflow.started_at.isoformat() if workflow.started_at else None,
                    "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None,
                    "error_message": workflow.error_message,
                    "context": json.loads(workflow.context or "{}"),
                    "steps": [
                        {
                            "number": step.step_number,
                            "name": step.name,
                            "type": step.step_type,
                            "status": step.status,
                            "started_at": step.started_at.isoformat() if step.started_at else None,
                            "completed_at": step.completed_at.isoformat() if step.completed_at else None,
                            "error_message": step.error_message
                        }
                        for step in steps
                    ]
                }
                
        except Exception as e:
            logger.error(f"Error getting workflow status: {str(e)}")
            return None
    
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running or waiting workflow"""
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(Workflow)
                    .where(Workflow.id == workflow_id)
                    .values(
                        status=WorkflowStatus.CANCELLED.value,
                        completed_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                )
                await session.commit()
                
            # Remove from running cache
            self.running_workflows.pop(workflow_id, None)
            
            logger.info(f"Workflow {workflow_id} cancelled")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling workflow: {str(e)}")
            return False

# Global workflow engine instance
workflow_engine = WorkflowEngine() 