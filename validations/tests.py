import json
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from connections.models import DataConnection
from mappings.models import Mapping, ColumnMapping, ValidationRule
from validations.models import ValidationRun
from validations.views import get_datatype_category, get_applicable_operations

class ValidationWorkspaceEnhancementsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123')
        # Ensure user has a profile with contributor/admin role if required
        from accounts.models import UserProfile
        profile, created = UserProfile.objects.get_or_create(user=self.user)
        profile.role = 'contributor'
        profile.save()

        self.source_conn = DataConnection.objects.create(
            name='Dummy Source',
            connection_type='postgresql',
            host='dummy-host',
            database_name='source_db',
            created_by=self.user
        )
        self.target_conn = DataConnection.objects.create(
            name='Dummy Target',
            connection_type='postgresql',
            host='dummy-host',
            database_name='target_db',
            created_by=self.user
        )

    def test_datatype_categorization(self):
        self.assertEqual(get_datatype_category('INTEGER'), 'INTEGER')
        self.assertEqual(get_datatype_category('varchar(255)'), 'VARCHAR')
        self.assertEqual(get_datatype_category('DATE'), 'DATE')
        self.assertEqual(get_datatype_category('boolean'), 'BOOLEAN')
        self.assertEqual(get_datatype_category('FLOAT8'), 'INTEGER')
        self.assertEqual(get_datatype_category('TIMESTAMP WITH TIME ZONE'), 'DATE')
        self.assertEqual(get_datatype_category(None), 'VARCHAR')
        self.assertEqual(get_datatype_category('object', 'created_at'), 'DATE')
        self.assertEqual(get_datatype_category('object', 'closed_on'), 'DATE')
        self.assertEqual(get_datatype_category('string', 'my_date_dt'), 'DATE')

    def test_applicable_operations_by_category(self):
        int_ops = get_applicable_operations('INTEGER')
        self.assertIn('sum', int_ops)
        self.assertIn('avg', int_ops)
        self.assertNotIn('length_sum_check', int_ops)

        str_ops = get_applicable_operations('VARCHAR')
        self.assertIn('length_sum_check', str_ops)
        self.assertIn('regex_check', str_ops)
        self.assertNotIn('sum', str_ops)

        date_ops = get_applicable_operations('DATE')
        self.assertIn('min_date', date_ops)
        self.assertIn('max_date', date_ops)
        self.assertNotIn('sum', date_ops)

    def test_quick_validate_with_all_columns(self):
        # Authenticate client
        self.client.login(username='testuser', password='password123')
        
        # Build JSON column mapping representing "__all__" columns selection
        column_mappings_json = json.dumps([
            {
                "source_column": "__all__",
                "source_datatype": "unknown",
                "target_column": "__all__",
                "target_datatype": "unknown",
                "operations": []
            }
        ])

        response = self.client.post(reverse('validations:quick'), {
            'source_connection': self.source_conn.id,
            'source_schema': 'public',
            'source_table': 'customers',
            'target_connection': self.target_conn.id,
            'target_schema': 'public',
            'target_table': 'customers',
            'column_mappings_json': column_mappings_json,
            # Source Date Filter
            'source_date_column': 'created_at',
            'source_date_filter_type': 'specific',
            'source_date_single': '2026-06-05',
            # Target Date Filter
            'target_date_column': 'created_at',
            'target_date_filter_type': 'range',
            'target_date_filter_start': '2026-06-01',
            'target_date_filter_end': '2026-06-10',
        })

        # Should redirect to validation progress
        self.assertEqual(response.status_code, 302)
        
        # Verify mapping and validation run were created correctly
        mapping = Mapping.objects.first()
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.source_date_column, 'created_at')
        self.assertEqual(mapping.source_date_filter_type, 'specific')
        self.assertEqual(str(mapping.source_date_filter_start), '2026-06-05')
        self.assertEqual(str(mapping.source_date_filter_end), '2026-06-05') # Equal bounds for specific

        self.assertEqual(mapping.target_date_column, 'created_at')
        self.assertEqual(mapping.target_date_filter_type, 'range')
        self.assertEqual(str(mapping.target_date_filter_start), '2026-06-01')
        self.assertEqual(str(mapping.target_date_filter_end), '2026-06-10')

        run = ValidationRun.objects.first()
        self.assertIsNotNone(run)
        self.assertEqual(str(run.source_date_filter_start), '2026-06-05')
        self.assertEqual(str(run.source_date_filter_end), '2026-06-05')
        self.assertEqual(str(run.target_date_filter_start), '2026-06-01')
        self.assertEqual(str(run.target_date_filter_end), '2026-06-10')

        # Since it was '__all__', check if column mappings were automatically expanded based on mock columns
        col_mappings = ColumnMapping.objects.filter(mapping=mapping)
        self.assertTrue(col_mappings.exists())
        
        # Check that rules were created for the mock columns (e.g. customer_id, first_name)
        customer_id_mapping = col_mappings.filter(source_column='customer_id').first()
        self.assertIsNotNone(customer_id_mapping)
        # Check INTEGER operations were created for customer_id
        rules = customer_id_mapping.rules.all()
        operations = [r.operation for r in rules]
        self.assertIn('sum', operations)
        self.assertIn('avg', operations)
        self.assertIn('null_check', operations)

    def test_pipeline_mapping_creation_view(self):
        # Authenticate client
        self.client.login(username='testuser', password='password123')
        
        column_mappings_json = json.dumps([
            {
                "source_column": "first_name",
                "source_datatype": "VARCHAR(100)",
                "target_column": "first_name",
                "target_datatype": "VARCHAR(100)",
                "operations": ["null_check", "length_sum_check"]
            },
            {
                "source_column": "customer_id",
                "source_datatype": "INTEGER",
                "target_column": "customer_id",
                "target_datatype": "INTEGER",
                "operations": ["sum", "avg"]
            }
        ])

        response = self.client.post(reverse('mappings:create'), {
            'name': 'Test Pipeline',
            'description': 'My E2E Pipeline',
            'source_connection': self.source_conn.id,
            'source_schema': 'public',
            'source_table': 'customers',
            'target_connection': self.target_conn.id,
            'target_schema': 'public',
            'target_table': 'customers',
            'column_mappings_json': column_mappings_json,
            # Source Date Filter
            'source_date_column': 'created_at',
            'source_date_filter_type': 'specific',
            'source_date_single': '2026-06-05',
            # Target Date Filter
            'target_date_column': 'created_at',
            'target_date_filter_type': 'range',
            'target_date_filter_start': '2026-06-01',
            'target_date_filter_end': '2026-06-10',
        })

        self.assertEqual(response.status_code, 302)
        
        mapping = Mapping.objects.first()
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.name, 'Test Pipeline')
        self.assertEqual(mapping.source_date_column, 'created_at')
        
        col_mappings = ColumnMapping.objects.filter(mapping=mapping)
        self.assertEqual(col_mappings.count(), 2)

        fn_mapping = col_mappings.filter(source_column='first_name').first()
        self.assertIsNotNone(fn_mapping)
        self.assertEqual(fn_mapping.source_datatype, 'VARCHAR(100)')
        self.assertEqual(fn_mapping.rules.count(), 2)
        self.assertListEqual(
            sorted([r.operation for r in fn_mapping.rules.all()]),
            sorted(['null_check', 'length_sum_check'])
        )

    def test_monitor_runs_list_search(self):
        # Authenticate client
        self.client.login(username='testuser', password='password123')
        
        # Create mapping and validation run
        mapping_match = Mapping.objects.create(
            name='My Searchable Pipeline',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            created_by=self.user
        )
        mapping_mismatch = Mapping.objects.create(
            name='Other Pipeline',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            created_by=self.user
        )
        
        run_match = ValidationRun.objects.create(
            mapping=mapping_match,
            status='completed',
            triggered_by=self.user
        )
        run_mismatch = ValidationRun.objects.create(
            mapping=mapping_mismatch,
            status='completed',
            triggered_by=self.user
        )
        
        # Test loading monitor list with query matching mapping_match name
        response = self.client.get(reverse('validations:list') + '?query=Searchable')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'My Searchable Pipeline')
        self.assertNotContains(response, 'Other Pipeline')
        
        # Test loading monitor list without query
        response_all = self.client.get(reverse('validations:list'))
        self.assertEqual(response_all.status_code, 200)
        self.assertContains(response_all, 'My Searchable Pipeline')
        self.assertContains(response_all, 'Other Pipeline')

    def test_description_length_limit(self):
        from django.core.exceptions import ValidationError
        
        # Test DataConnection description validator
        invalid_conn = DataConnection(
            name='Invalid Conn',
            connection_type='postgresql',
            description='x' * 1001,
            created_by=self.user
        )
        with self.assertRaises(ValidationError):
            invalid_conn.full_clean()
            
        # Test Mapping description validator
        invalid_mapping = Mapping(
            name='Invalid Mapping',
            description='x' * 1001,
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            created_by=self.user
        )
        with self.assertRaises(ValidationError):
            invalid_mapping.full_clean()

        # Test Workflow description validator
        from workflows.models import Workflow
        dummy_map = Mapping.objects.create(
            name='Dummy Map',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            created_by=self.user
        )
        invalid_workflow = Workflow(
            name='Invalid Workflow',
            description='x' * 1001,
            mapping=dummy_map,
            created_by=self.user
        )
        with self.assertRaises(ValidationError):
            invalid_workflow.full_clean()

    def test_relative_date_resolution_on_run_save(self):
        import datetime
        mapping = Mapping.objects.create(
            name='Relative Date Map',
            source_connection=self.source_conn,
            target_connection=self.target_conn,
            created_by=self.user,
            source_date_column='created_at',
            source_date_filter_type='specific',
            source_date_value_type='relative',
            source_date_relative_operator='+',
            source_date_relative_value=3,
            
            target_date_column='updated_at',
            target_date_filter_type='specific',
            target_date_value_type='relative',
            target_date_relative_operator='-',
            target_date_relative_value=5
        )
        
        run = ValidationRun.objects.create(
            mapping=mapping,
            triggered_by=self.user
        )
        
        today = datetime.date.today()
        self.assertEqual(run.source_date_filter_start, today + datetime.timedelta(days=3))
        self.assertEqual(run.source_date_filter_end, today + datetime.timedelta(days=3))
        self.assertEqual(run.target_date_filter_start, today - datetime.timedelta(days=5))
        self.assertEqual(run.target_date_filter_end, today - datetime.timedelta(days=5))

    def test_date_comparison_operators(self):
        import pandas as pd
        # Create a dummy dataset
        df_data = pd.DataFrame({
            'date_col': ['2026-06-05', '2026-06-06', '2026-06-07'],
            'val': [10, 20, 30]
        })
        
        # Create a dummy CSV connection so is_mocked() returns False
        csv_conn = DataConnection.objects.create(
            name='Test CSV',
            connection_type='csv',
            host='dummy_folder_path',
            created_by=self.user
        )
        from connections.connector import ConnectorEngine
        engine = ConnectorEngine(csv_conn)
        
        # Monkeypatch read_file to return our dummy dataframe
        original_read_file = engine.read_file
        engine.read_file = lambda limit=None, table=None: df_data.copy()
        
        try:
            # Test '=' operator
            res_eq = engine.get_aggregation(
                schema='file', table='dummy', column='val', operation='sum',
                date_column='date_col', date_start='2026-06-06', date_operator='='
            )
            self.assertEqual(res_eq, 20)
            
            # Test '>' operator
            res_gt = engine.get_aggregation(
                schema='file', table='dummy', column='val', operation='sum',
                date_column='date_col', date_start='2026-06-05', date_operator='>'
            )
            self.assertEqual(res_gt, 50)  # 20 + 30
            
            # Test '<=' operator
            res_le = engine.get_aggregation(
                schema='file', table='dummy', column='val', operation='sum',
                date_column='date_col', date_start='2026-06-06', date_operator='<='
            )
            self.assertEqual(res_le, 30)  # 10 + 20
            
        finally:
            engine.read_file = original_read_file

