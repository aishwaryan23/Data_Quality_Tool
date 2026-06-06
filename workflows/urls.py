from django.urls import path
from . import views

app_name = 'workflows'

urlpatterns = [
    path('', views.workflow_list_view, name='list'),
    path('create/', views.workflow_create_view, name='create'),
    path('<int:workflow_id>/', views.workflow_detail_view, name='detail'),
    # API
    path('api/trigger/<int:workflow_id>/', views.api_trigger_workflow, name='api_trigger'),
    path('api/toggle/<int:workflow_id>/', views.api_toggle_workflow, name='api_toggle'),
]
