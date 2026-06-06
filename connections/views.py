import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone

from .models import DataConnection
from .forms import DataConnectionForm
from .connector import ConnectorEngine
from accounts.decorators import contributor_or_admin_required

logger = logging.getLogger('connections')


@login_required
def connection_list_view(request):
    """List all data connections."""
    connections = DataConnection.objects.filter(is_active=True).order_by('-created_at')
    return render(request, 'connections/list.html', {'connections': connections})


@login_required
@contributor_or_admin_required
def connection_create_view(request):
    """Create a new data connection."""
    form = DataConnectionForm()

    if request.method == 'POST':
        form = DataConnectionForm(request.POST, request.FILES)
        if form.is_valid():
            conn = form.save(commit=False)
            conn.created_by = request.user
            conn.save()

            logger.info(f"Connection '{conn.name}' created by {request.user.username}")

            try:
                from dashboard.models import FormDraft
                FormDraft.objects.filter(user=request.user, page_key='connection_create', status='draft').update(status='completed')
            except Exception:
                pass

            try:
                from logs.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action=f'Created Connection: {conn.name}',
                    entity_type='DataConnection',
                    entity_id=conn.id,
                    details={'type': conn.connection_type},
                    ip_address=request.META.get('REMOTE_ADDR'),
                    level='info',
                )
                from dashboard.models import Notification
                Notification.objects.create(
                    user=request.user,
                    title="Connection Created",
                    message=f"Data connection '{conn.name}' ({conn.get_connection_type_display()}) was created successfully.",
                    level='success'
                )
            except Exception:
                pass

            messages.success(request, f'Connection "{conn.name}" created successfully.')
            return redirect('connections:list')

    return render(request, 'connections/create.html', {'form': form})


@login_required
@contributor_or_admin_required
def connection_edit_view(request, conn_id):
    """Edit an existing data connection."""
    conn = get_object_or_404(DataConnection, id=conn_id)
    if request.method == 'POST':
        form = DataConnectionForm(request.POST, request.FILES, instance=conn)
        if form.is_valid():
            conn = form.save(commit=False)
            conn.save()

            logger.info(f"Connection '{conn.name}' edited by {request.user.username}")

            try:
                from logs.models import AuditLog
                AuditLog.objects.create(
                    user=request.user,
                    action=f'Edited Connection: {conn.name}',
                    entity_type='DataConnection',
                    entity_id=conn.id,
                    details={'type': conn.connection_type},
                    ip_address=request.META.get('REMOTE_ADDR'),
                    level='info',
                )
                from dashboard.models import Notification
                Notification.objects.create(
                    user=request.user,
                    title="Connection Updated",
                    message=f"Data connection '{conn.name}' was updated successfully.",
                    level='info'
                )
            except Exception:
                pass

            messages.success(request, f'Connection "{conn.name}" updated successfully.')
            return redirect('connections:list')
    else:
        form = DataConnectionForm(instance=conn)

    return render(request, 'connections/create.html', {'form': form, 'is_edit': True, 'connection': conn})


@login_required
@contributor_or_admin_required
def connection_delete_view(request, conn_id):
    """Delete (deactivate) a connection."""
    conn = get_object_or_404(DataConnection, id=conn_id)
    if request.method == 'POST':
        conn.is_active = False
        conn.save()
        messages.success(request, f'Connection "{conn.name}" deleted.')
    return redirect('connections:list')


# ─── API Endpoints ───────────────────────────────────────────────────────────

@login_required
def api_test_connection(request, conn_id):
    """Test a database/file connection."""
    if hasattr(request.user, 'profile') and request.user.profile.role == 'auditor':
        return JsonResponse({'success': False, 'message': 'Permission denied: Auditor cannot test connections.'}, status=403)
    conn = get_object_or_404(DataConnection, id=conn_id)
    engine = ConnectorEngine(conn)
    success, message = engine.test_connection()

    conn.last_tested = timezone.now()
    conn.last_test_success = success
    conn.save(update_fields=['last_tested', 'last_test_success'])

    return JsonResponse({'success': success, 'message': message})


@login_required
def api_get_schemas(request):
    """Get schemas for a connection."""
    conn_id = request.GET.get('connection_id')
    if not conn_id:
        return JsonResponse({'error': 'connection_id required'}, status=400)

    conn = get_object_or_404(DataConnection, id=conn_id)
    engine = ConnectorEngine(conn)

    if conn.is_file:
        return JsonResponse({'schemas': [], 'is_file': True})

    schemas = engine.get_schemas()
    return JsonResponse({'schemas': schemas, 'is_file': False})


@login_required
def api_get_tables(request):
    """Get tables for a connection and schema."""
    conn_id = request.GET.get('connection_id')
    schema = request.GET.get('schema', '')

    if not conn_id:
        return JsonResponse({'error': 'connection_id required'}, status=400)

    conn = get_object_or_404(DataConnection, id=conn_id)
    engine = ConnectorEngine(conn)
    tables = engine.get_tables(schema=schema if schema != 'file' else None)
    return JsonResponse({'tables': tables})


@login_required
def api_get_columns(request):
    """Get columns for a connection, schema, and table."""
    conn_id = request.GET.get('connection_id')
    schema = request.GET.get('schema', '')
    table = request.GET.get('table', '')

    if not conn_id:
        return JsonResponse({'error': 'connection_id required'}, status=400)

    conn = get_object_or_404(DataConnection, id=conn_id)
    engine = ConnectorEngine(conn)
    columns = engine.get_columns(
        schema=schema if schema != 'file' else None,
        table=table
    )
    return JsonResponse({'columns': columns})
