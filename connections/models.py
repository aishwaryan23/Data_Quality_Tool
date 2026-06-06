from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MaxLengthValidator
from cryptography.fernet import Fernet
from django.conf import settings
import base64


def get_fernet():
    """Get Fernet instance for encrypting/decrypting passwords."""
    key = settings.FERNET_KEY
    if not key:
        # Generate a key for development if not set
        key = base64.urlsafe_b64encode(b'hdfc-data-quality-tool-dev-key!!')
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


class DataConnection(models.Model):
    """Represents a connection to a database or file source/target."""

    CONNECTION_TYPES = [
        ('postgresql', 'PostgreSQL'),
        ('mysql', 'MySQL'),
        ('databricks', 'Databricks'),
        ('db2', 'DB2'),
        ('oracle', 'Oracle'),
        ('csv', 'Flat File (CSV)'),
        ('parquet', 'Flat File (Parquet)'),
    ]

    name = models.CharField(max_length=200, help_text='Friendly name for this connection')
    connection_type = models.CharField(max_length=20, choices=CONNECTION_TYPES)
    description = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])

    # Database connection fields
    host = models.CharField(max_length=500, blank=True)
    port = models.IntegerField(null=True, blank=True)
    database_name = models.CharField(max_length=200, blank=True)
    username = models.CharField(max_length=200, blank=True)
    encrypted_password = models.BinaryField(blank=True, default=b'')

    # File connection fields
    file = models.FileField(upload_to='uploads/connections/', blank=True)

    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='connections')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    last_tested = models.DateTimeField(null=True, blank=True)
    last_test_success = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Data Connection'

    def __str__(self):
        return f"{self.name} ({self.get_connection_type_display()})"

    @property
    def is_database(self):
        return self.connection_type in ('postgresql', 'mysql', 'databricks', 'db2', 'oracle')

    @property
    def is_file(self):
        return self.connection_type in ('csv', 'parquet', 'flat_file')

    def set_password(self, raw_password):
        """Encrypt and store the database password."""
        if raw_password:
            f = get_fernet()
            self.encrypted_password = f.encrypt(raw_password.encode())

    def get_password(self):
        """Decrypt and return the database password."""
        if self.encrypted_password:
            try:
                f = get_fernet()
                return f.decrypt(bytes(self.encrypted_password)).decode()
            except Exception:
                return ''
        return ''

    def get_connection_string(self):
        """Build SQLAlchemy connection string with URL-encoded credentials."""
        import urllib.parse
        encoded_username = urllib.parse.quote_plus(self.username)
        encoded_password = urllib.parse.quote_plus(self.get_password())
        
        if self.connection_type == 'postgresql':
            return f"postgresql+psycopg2://{encoded_username}:{encoded_password}@{self.host}:{self.port or 5432}/{self.database_name}"
        elif self.connection_type == 'mysql':
            return f"mysql+pymysql://{encoded_username}:{encoded_password}@{self.host}:{self.port or 3306}/{self.database_name}"
        elif self.connection_type == 'databricks':
            return f"databricks://token:{encoded_password}@{self.host}:{self.port or 443}/{self.database_name}"
        elif self.connection_type == 'db2':
            return f"db2+ibm_db://{encoded_username}:{encoded_password}@{self.host}:{self.port or 50000}/{self.database_name}"
        elif self.connection_type == 'oracle':
            return f"oracle+cx_oracle://{encoded_username}:{encoded_password}@{self.host}:{self.port or 1521}/{self.database_name}"
        return None
