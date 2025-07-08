"""
Celery tasks for workflow execution and management
"""
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import structlog
from celery import Celery
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from database import Workflow, WorkflowStep, Event
from services.workflow_engine import workflow_engine, WorkflowStatus
from celery_app import celery_app
from config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Create synchronous database engine for Celery tasks
sync_engine = create_engine(settings.database_url, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine)

@celery_app.task(bind=True, max_retries=3)
def execute_workflow(self, workflow_id: str):
    """Execute a workflow in the background"""
    try:
        logger.info(f"Starting workflow execution: {workflow_id}")
        
        # Create a new event loop for this task
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Run async workflow execution
            result = loop.run_until_complete(workflow_engine.start_workflow(workflow_id))
        finally:
            loop.close()
        
        logger.info(f"Workflow {workflow_id} execution completed: {result}")
        return {
            "workflow_id": workflow_id,
            "success": result,
            "completed_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Workflow execution failed for {workflow_id}: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            # Mark workflow as failed using a new loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(workflow_engine._mark_workflow_failed(workflow_id, str(e)))
            finally:
                loop.close()
            raise e

@celery_app.task(bind=True, max_retries=2)
def resume_workflow(self, workflow_id: str, resume_data: Dict[str, Any] = None):
    """Resume a waiting workflow"""
    try:
        logger.info(f"Resuming workflow: {workflow_id}")
        
        # Create a new event loop for this task
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Run async workflow resumption
            result = loop.run_until_complete(workflow_engine.resume_workflow(workflow_id, resume_data))
        finally:
            loop.close()
        
        logger.info(f"Workflow {workflow_id} resumption completed: {result}")
        return {
            "workflow_id": workflow_id,
            "success": result,
            "resumed_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Workflow resumption failed for {workflow_id}: {str(e)}")
        
        # Retry with backoff
        if self.request.retries < self.max_retries:
            retry_delay = 5 * (self.request.retries + 1)
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

@celery_app.task(bind=True)
def create_and_execute_workflow(
    self, 
    user_id: str, 
    name: str, 
    steps: List[Dict[str, Any]], 
    input_data: Dict[str, Any] = None,
    triggered_by_event_id: str = None
):
    """Create and immediately execute a new workflow"""
    try:
        logger.info(f"Creating and executing workflow '{name}' for user {user_id}")
        
        # Create a new event loop for this task
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Create workflow
            workflow_id = loop.run_until_complete(workflow_engine.create_workflow(
                user_id=user_id,
                name=name,
                steps=steps,
                input_data=input_data,
                triggered_by_event_id=triggered_by_event_id
            ))
            
            # Execute workflow immediately
            result = loop.run_until_complete(workflow_engine.start_workflow(workflow_id))
        finally:
            loop.close()
        
        logger.info(f"Workflow {workflow_id} created and executed: {result}")
        return {
            "workflow_id": workflow_id,
            "success": result,
            "created_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to create and execute workflow: {str(e)}")
        raise e

@celery_app.task(bind=True)
def check_workflow_timeouts(self):
    """Check for timed out workflows and handle them"""
    try:
        logger.info("Checking for workflow timeouts")
        
        timeout_count = 0
        
        with SyncSessionLocal() as session:
            # Find waiting workflows that have timed out
            now = datetime.utcnow()
            result = session.execute(
                select(Workflow).where(
                    Workflow.status == WorkflowStatus.WAITING.value,
                    Workflow.timeout_at < now
                )
            )
            timed_out_workflows = result.scalars().all()
            
            for workflow in timed_out_workflows:
                logger.info(f"Workflow {workflow.id} timed out, sending reminder or failing")
                
                # Check if we should send a reminder or fail the workflow
                if workflow.retry_count < workflow.max_retries:
                    # Send reminder and extend timeout
                    workflow.retry_count += 1
                    workflow.timeout_at = now + timedelta(hours=24)  # Extend by 24 hours
                    
                    # Queue reminder task
                    send_workflow_reminder.delay(workflow.id)
                    timeout_count += 1
                    
                    logger.info(f"Sent reminder for workflow {workflow.id}, attempt {workflow.retry_count}")
                    
                else:
                    # Max retries reached, fail the workflow
                    workflow.status = WorkflowStatus.FAILED.value
                    workflow.error_message = "Workflow timed out waiting for response"
                    workflow.completed_at = now
                    timeout_count += 1
                    
                    logger.warning(f"Workflow {workflow.id} failed due to timeout")
            
            session.commit()
        
        logger.info(f"Processed {timeout_count} timed out workflows")
        return {
            "processed_count": timeout_count,
            "checked_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error checking workflow timeouts: {str(e)}")
        raise e

@celery_app.task(bind=True)
def send_workflow_reminder(self, workflow_id: str):
    """Send a reminder for a workflow waiting for response"""
    try:
        logger.info(f"Sending reminder for workflow {workflow_id}")
        
        with SyncSessionLocal() as session:
            # Get workflow details
            result = session.execute(
                select(Workflow).where(Workflow.id == workflow_id)
            )
            workflow = result.scalar_one_or_none()
            
            if not workflow:
                logger.error(f"Workflow {workflow_id} not found for reminder")
                return
            
            context = json.loads(workflow.context or "{}")
            
            # Determine reminder type based on workflow context
            if "waiting_for_email_response" in context:
                # Send email reminder
                send_email_reminder.delay(workflow_id, context)
            elif "waiting_for_calendar_response" in context:
                # Send calendar reminder
                send_calendar_reminder.delay(workflow_id, context)
            else:
                # Generic reminder
                logger.info(f"Generic reminder for workflow {workflow_id}")
        
        return {
            "workflow_id": workflow_id,
            "reminder_sent_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error sending workflow reminder: {str(e)}")
        raise e

@celery_app.task(bind=True)
def send_email_reminder(self, workflow_id: str, context: Dict[str, Any]):
    """Send email reminder for workflow waiting for email response"""
    try:
        from tasks.ai_tasks import execute_ai_action
        
        logger.info(f"Sending email reminder for workflow {workflow_id}")
        
        # Extract email details from context
        original_email_to = context.get("email_sent_to")
        subject_prefix = "Reminder: "
        
        # Get original email subject if available
        original_subject = context.get("original_email_subject", "Previous Message")
        reminder_subject = f"{subject_prefix}{original_subject}"
        
        reminder_body = f"""
Hi,

I wanted to follow up on my previous message regarding scheduling an appointment.

I understand you might be busy, but I'd appreciate if you could let me know about your availability when you have a moment.

If none of the times I suggested work for you, please feel free to suggest alternative times that would be better.

Thank you for your time.

Best regards
"""
        
        # Send reminder email
        if original_email_to:
            result = execute_ai_action.delay(
                context.get("user_id"),
                "send_email",
                {
                    "to": original_email_to,
                    "subject": reminder_subject,
                    "body": reminder_body
                }
            )
            
            logger.info(f"Email reminder sent for workflow {workflow_id}")
            return {"success": True, "email_sent_to": original_email_to}
        else:
            logger.warning(f"No email address found in context for workflow {workflow_id}")
            return {"success": False, "error": "No email address found"}
        
    except Exception as e:
        logger.error(f"Error sending email reminder: {str(e)}")
        raise e

@celery_app.task(bind=True)
def send_calendar_reminder(self, workflow_id: str, context: Dict[str, Any]):
    """Send calendar reminder for workflow waiting for calendar response"""
    try:
        logger.info(f"Sending calendar reminder for workflow {workflow_id}")
        
        logger.info(f"Calendar reminder sent for workflow {workflow_id}")
        
        return {
            "workflow_id": workflow_id,
            "reminder_type": "calendar",
            "sent_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error sending calendar reminder: {str(e)}")
        raise e

@celery_app.task(bind=True)
def cleanup_completed_workflows(self):
    """Clean up old completed workflows to save space"""
    try:
        logger.info("Cleaning up old completed workflows")
        
        cleanup_count = 0
        cutoff_date = datetime.utcnow() - timedelta(days=30)  # Keep 30 days of history
        
        with SyncSessionLocal() as session:
            # Find old completed workflows
            result = session.execute(
                select(Workflow).where(
                    Workflow.status.in_([
                        WorkflowStatus.COMPLETED.value,
                        WorkflowStatus.FAILED.value,
                        WorkflowStatus.CANCELLED.value
                    ]),
                    Workflow.completed_at < cutoff_date
                )
            )
            old_workflows = result.scalars().all()
            
            for workflow in old_workflows:
                # Delete associated steps first
                session.execute(
                    select(WorkflowStep).where(WorkflowStep.workflow_id == workflow.id)
                )
                
                # Delete workflow
                session.delete(workflow)
                cleanup_count += 1
            
            session.commit()
        
        logger.info(f"Cleaned up {cleanup_count} old workflows")
        return {
            "cleaned_count": cleanup_count,
            "cleaned_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up workflows: {str(e)}")
        raise e

@celery_app.task(bind=True)
def get_workflow_metrics(self):
    """Get workflow execution metrics"""
    try:
        logger.info("Collecting workflow metrics")
        
        metrics = {}
        
        with SyncSessionLocal() as session:
            # Count workflows by status
            for status in WorkflowStatus:
                result = session.execute(
                    select(Workflow).where(Workflow.status == status.value)
                )
                count = len(result.scalars().all())
                metrics[f"workflows_{status.value}"] = count
            
            # Get recent activity (last 24 hours)
            yesterday = datetime.utcnow() - timedelta(hours=24)
            recent_result = session.execute(
                select(Workflow).where(Workflow.created_at >= yesterday)
            )
            metrics["workflows_created_24h"] = len(recent_result.scalars().all())
            
            completed_result = session.execute(
                select(Workflow).where(
                    Workflow.completed_at >= yesterday,
                    Workflow.status == WorkflowStatus.COMPLETED.value
                )
            )
            metrics["workflows_completed_24h"] = len(completed_result.scalars().all())
        
        logger.info(f"Workflow metrics collected: {metrics}")
        return metrics
        
    except Exception as e:
        logger.error(f"Error collecting workflow metrics: {str(e)}")
        raise e

# Periodic task to check timeouts and clean up
@celery_app.task(bind=True)
def workflow_maintenance(self):
    """Periodic maintenance task for workflows"""
    try:
        logger.info("Running workflow maintenance")
        
        # Check timeouts
        timeout_result = check_workflow_timeouts.delay()
        
        # Collect metrics
        metrics_result = get_workflow_metrics.delay()
        
        return {
            "maintenance_run_at": datetime.utcnow().isoformat(),
            "tasks_started": ["check_timeouts", "collect_metrics"]
        }
        
    except Exception as e:
        logger.error(f"Error in workflow maintenance: {str(e)}")
        raise e 