from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from .models import DataConnection

class ConnectionViewsTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123')
        from accounts.models import UserProfile
        profile, created = UserProfile.objects.get_or_create(user=self.user)
        profile.role = 'contributor'
        profile.save()
        
        self.connection = DataConnection.objects.create(
            name='Test Postgres',
            connection_type='postgresql',
            host='localhost',
            port=5432,
            database_name='test_db',
            username='postgres',
            created_by=self.user
        )
        self.connection.set_password('mysecretpass')
        self.connection.save()

    def test_connection_list_view(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('connections:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Postgres')
        self.assertContains(response, 'PostgreSQL')

    def test_connection_edit_get_view(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.get(reverse('connections:edit', args=[self.connection.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Data Connection')
        self.assertContains(response, 'Test Postgres')
        # Check that is_edit flag is in the template context
        self.assertTrue(response.context['is_edit'])

    def test_connection_edit_post_success(self):
        self.client.login(username='testuser', password='password123')
        # We don't submit password, so it should keep the old password
        response = self.client.post(reverse('connections:edit', args=[self.connection.id]), {
            'name': 'Updated Name',
            'connection_type': 'postgresql',
            'host': 'localhost-new',
            'port': 5433,
            'database_name': 'test_db_new',
            'username': 'postgres-new',
        })
        self.assertEqual(response.status_code, 302)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.name, 'Updated Name')
        self.assertEqual(self.connection.host, 'localhost-new')
        self.assertEqual(self.connection.port, 5433)
        self.assertEqual(self.connection.database_name, 'test_db_new')
        self.assertEqual(self.connection.username, 'postgres-new')
        # Verify the password was NOT cleared since we left password blank
        self.assertEqual(self.connection.get_password(), 'mysecretpass')

    def test_connection_edit_post_with_new_password(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.post(reverse('connections:edit', args=[self.connection.id]), {
            'name': 'Updated Name',
            'connection_type': 'postgresql',
            'host': 'localhost-new',
            'port': 5433,
            'database_name': 'test_db_new',
            'username': 'postgres-new',
            'password': 'newpassword123',
        })
        self.assertEqual(response.status_code, 302)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.get_password(), 'newpassword123')

    def test_connection_delete_post(self):
        self.client.login(username='testuser', password='password123')
        response = self.client.post(reverse('connections:delete', args=[self.connection.id]))
        self.assertEqual(response.status_code, 302)
        self.connection.refresh_from_db()
        self.assertFalse(self.connection.is_active)

    def test_file_connection_lifecycle(self):
        import os
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .connector import ConnectorEngine

        # Create a mock CSV file content
        csv_content = b"emp_id,name,salary\n101,Alice,50000\n102,Bob,60000\n103,Charlie,70000"
        uploaded_file = SimpleUploadedFile("employees.csv", csv_content, content_type="text/csv")
        
        # Create a file data connection
        file_conn = DataConnection.objects.create(
            name='File Connection',
            connection_type='csv',
            file=uploaded_file,
            created_by=self.user
        )
        
        try:
            # 1. Test engine introspection (get_tables)
            engine = ConnectorEngine(file_conn)
            tables = engine.get_tables()
            self.assertEqual(len(tables), 1)
            self.assertTrue(tables[0].endswith('employees.csv'))
            
            # 2. Test engine introspection (get_columns)
            columns = engine.get_columns(table=tables[0])
            column_names = [col['name'] for col in columns]
            self.assertIn('emp_id', column_names)
            self.assertIn('name', column_names)
            self.assertIn('salary', column_names)
            
            # 3. Test reading the file
            read_df = engine.read_file(table=tables[0])
            self.assertEqual(len(read_df), 3)
            self.assertEqual(list(read_df['emp_id']), [101, 102, 103])
            
            # 4. Test connection testing
            success, msg = engine.test_connection()
            self.assertTrue(success)
            self.assertIn('File readable', msg)
            
        finally:
            # Cleanup files
            if file_conn.file and os.path.exists(file_conn.file.path):
                try:
                    os.remove(file_conn.file.path)
                except Exception:
                    pass
