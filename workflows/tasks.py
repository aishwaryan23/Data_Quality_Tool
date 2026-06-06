"""
Celery tasks for workflow execution.
"""
import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger('workflows')


@shared_task(bind=True)
def execute_workflow_task(self, workflow_id):
    """Execute a scheduled workflow — creates and runs a validation."""
    from .models import Workflow
    from validations.models import ValidationRun
    from validations.engine import ValidationEngine

    try:
        workflow = Workflow.objects.select_related('mapping').get(id=workflow_id)

        if not workflow.is_active:
            logger.info(f"Workflow '{workflow.name}' is inactive, skipping.")
            return

        # Create validation run
        run = ValidationRun.objects.create(
            mapping=workflow.mapping,
            trigger_type='scheduled',
            status='pending',
            selected_columns=workflow.selected_columns,
        )

        # Execute validation
        engine = ValidationEngine(run)
        engine.execute()

        # Update workflow
        workflow.last_run = timezone.now()
        workflow.save(update_fields=['last_run'])

        logger.info(f"Workflow '{workflow.name}' executed successfully. Run #{run.id}")

        if workflow.created_by:
            try:
                from dashboard.models import Notification
                status_text = "Passed" if run.failed_checks == 0 else "Failed"
                Notification.objects.create(
                    user=workflow.created_by,
                    title=f"Workflow '{workflow.name}' Completed",
                    message=f"Validation Run #{run.id} finished.\nStatus: {status_text} ({run.passed_checks}/{run.total_checks} checks passed)",
                    level='success' if run.failed_checks == 0 else 'warning'
                )
            except Exception:
                pass

        try:
            from logs.models import AuditLog
            AuditLog.objects.create(
                action=f'Workflow Executed: {workflow.name}',
                entity_type='Workflow',
                entity_id=workflow.id,
                details={
                    'run_id': run.id,
                    'passed': run.passed_checks,
                    'failed': run.failed_checks,
                },
                level='info',
            )
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Workflow {workflow_id} execution failed: {e}")
        try:
            workflow = Workflow.objects.get(id=workflow_id)
            if workflow.created_by:
                from dashboard.models import Notification
                Notification.objects.create(
                    user=workflow.created_by,
                    title=f"Workflow '{workflow.name}' Failed",
                    message=f"Execution failed due to error: {e}",
                    level='error'
                )
        except Exception:
            pass
        raise
