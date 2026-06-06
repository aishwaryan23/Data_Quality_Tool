from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q

from connections.models import DataConnection
from mappings.models import Mapping, ValidationRule
from validations.models import ValidationRun
from workflows.models import Workflow
from logs.models import AuditLog


@login_required
def dashboard_view(request):
    """Main dashboard with summary statistics and recent activity."""

    # Stats
    total_connections = DataConnection.objects.filter(is_active=True).count()
    total_mappings = Mapping.objects.filter(is_active=True).count()
    active_workflows = Workflow.objects.filter(is_active=True).count()

    # Recent validation runs
    recent_runs = ValidationRun.objects.select_related('mapping', 'triggered_by').all()[:10]

    # Overall completed vs failed workflow/validation runs
    workflows_completed = ValidationRun.objects.filter(status='completed').count()
    workflows_failed = ValidationRun.objects.filter(status='failed').count()

    # Recent logs
    recent_logs = AuditLog.objects.select_related('user').all()[:10]

    # Connections list for quick access and dropdowns
    connections = DataConnection.objects.filter(is_active=True)
    operations = ValidationRule.OPERATION_CHOICES

    context = {
        'total_connections': total_connections,
        'total_mappings': total_mappings,
        'active_workflows': active_workflows,
        'workflows_completed': workflows_completed,
        'workflows_failed': workflows_failed,
        'recent_runs': recent_runs,
        'recent_logs': recent_logs,
        'connections': connections,
        'operations': operations,
    }
    return render(request, 'dashboard/index.html', context)


import json
from django.http import JsonResponse
from .models import FormDraft

@login_required
def api_save_draft(request):
    """Save (create or update) form progress draft."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        page_key = data.get('page_key')
        form_data = data.get('data')
        
        if not page_key or form_data is None:
            return JsonResponse({'success': False, 'error': 'Missing page_key or data'}, status=400)
            
        draft, created = FormDraft.objects.get_or_create(
            user=request.user,
            page_key=page_key,
            status='draft',
            defaults={'data': form_data}
        )
        if not created:
            draft.data = form_data
            draft.save()
            
        return JsonResponse({'success': True, 'message': 'Draft saved successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_get_draft(request):
    """Retrieve active form progress draft."""
    page_key = request.GET.get('page_key')
    if not page_key:
        return JsonResponse({'success': False, 'error': 'Missing page_key'}, status=400)
        
    draft = FormDraft.objects.filter(user=request.user, page_key=page_key, status='draft').first()
    if draft:
        return JsonResponse({'success': True, 'data': draft.data})
    return JsonResponse({'success': True, 'data': None})


@login_required
def api_cancel_draft(request):
    """Cancel (discard) form progress draft."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
        
    try:
        data = json.loads(request.body)
        page_key = data.get('page_key')
        if not page_key:
            return JsonResponse({'success': False, 'error': 'Missing page_key'}, status=400)
            
        FormDraft.objects.filter(user=request.user, page_key=page_key, status='draft').update(status='cancelled')
        return JsonResponse({'success': True, 'message': 'Draft cancelled successfully'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def api_get_notifications(request):
    """Retrieve the latest 10 notifications for the current user."""
    notifications = request.user.notifications.all()[:10]
    unread_count = request.user.notifications.filter(is_read=False).count()
    
    data = []
    for notif in notifications:
        data.append({
            'id': notif.id,
            'title': notif.title,
            'message': notif.message,
            'level': notif.level,
            'is_read': notif.is_read,
            'created_at': notif.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        })
        
    return JsonResponse({
        'success': True,
        'notifications': data,
        'unread_count': unread_count
    })


@login_required
def api_clear_notifications(request):
    """Mark all notifications for the current user as read."""
    if request.method != 'POST':
         return JsonResponse({'success': False, 'error': 'Method not allowed'}, status=405)
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return JsonResponse({'success': True, 'message': 'All notifications marked as read'})
