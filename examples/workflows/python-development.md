# Python Development Workflows

Common workflows for Python projects using rev.py.

## Workflow 1: New Python Project Setup

### Command
```bash
python rev.py "Setup new Python project with Flask, SQLAlchemy, and pytest"
```

### Generated Structure
```
project/
├── app/
│   ├── __init__.py
│   ├── models/
│   ├── routes/
│   └── services/
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   └── test_*.py
├── requirements.txt
├── requirements-dev.txt
├── setup.py
├── pytest.ini
├── .gitignore
└── README.md
```

### Files Created

**requirements.txt**
```
Flask==3.0.0
SQLAlchemy==2.0.23
python-dotenv==1.0.0
```

**requirements-dev.txt**
```
pytest==7.4.3
pytest-cov==4.1.0
black==23.12.0
flake8==6.1.0
mypy==1.7.1
```

**app/__init__.py**
```python
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    db.init_app(app)

    from app.routes import users
    app.register_blueprint(users.bp)

    return app
```

## Workflow 2: Add FastAPI Endpoint

### Command
```bash
python rev.py "Add FastAPI endpoint for user CRUD with Pydantic validation"
```

### Generated Code

**models/user.py**
```python
from pydantic import BaseModel, EmailStr, Field

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    username: str = Field(..., min_length=3, max_length=50)

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    username: str
    created_at: datetime

    class Config:
        from_attributes = True
```

**routes/users.py**
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

router = APIRouter(prefix="/api/users", tags=["users"])

@router.post("/", response_model=UserResponse, status_code=201)
async def create_user(
    user: UserCreate,
    db: Session = Depends(get_db)
):
    """Create a new user"""
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(400, "Email already registered")

    db_user = User(**user.dict())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@router.get("/", response_model=List[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List all users"""
    users = db.query(User).offset(skip).limit(limit).all()
    return users
```

## Workflow 3: Database Migration

### Command
```bash
python rev.py "Create Alembic migration to add user_roles table with foreign key"
```

### Generated Migration

**alembic/versions/001_add_user_roles.py**
```python
"""Add user_roles table

Revision ID: 001
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'user_roles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now())
    )
    op.create_index('idx_user_roles_user_id', 'user_roles', ['user_id'])

def downgrade():
    op.drop_index('idx_user_roles_user_id', 'user_roles')
    op.drop_table('user_roles')
```

## Workflow 4: Add Celery Task

### Command
```bash
python rev.py "Add Celery task for sending email notifications with retry logic"
```

### Generated Task

**tasks/email.py**
```python
from celery import shared_task
from celery.utils.log import get_task_logger
from app.services.email import EmailService

logger = get_task_logger(__name__)

@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3, 'countdown': 60}
)
def send_email_notification(self, user_id, template, context):
    """Send email notification with retry logic

    Args:
        user_id: ID of user to send email to
        template: Email template name
        context: Template context data

    Returns:
        bool: True if email sent successfully

    Raises:
        Exception: If email sending fails after retries
    """
    try:
        logger.info(f'Sending {template} email to user {user_id}')
        email_service = EmailService()
        result = email_service.send(user_id, template, context)
        logger.info(f'Email sent successfully to user {user_id}')
        return result
    except Exception as e:
        logger.error(f'Failed to send email: {e}')
        raise self.retry(exc=e)
```

## Workflow 5: Add Type Hints

### Command
```bash
python rev.py "Add type hints to all functions in services/ directory"
```

### Before
```python
def get_user_by_email(email):
    user = db.query(User).filter_by(email=email).first()
    if not user:
        return None
    return user
```

### After
```python
from typing import Optional
from sqlalchemy.orm import Session

def get_user_by_email(
    email: str,
    db: Session
) -> Optional[User]:
    """Get user by email address

    Args:
        email: User's email address
        db: Database session

    Returns:
        User object if found, None otherwise
    """
    user = db.query(User).filter_by(email=email).first()
    if not user:
        return None
    return user
```

## Workflow 6: Add Logging

### Command
```bash
python rev.py "Add structured logging to all service methods"
```

### Generated Code

**config/logging.py**
```python
import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_logging():
    """Configure structured JSON logging"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        '%(timestamp)s %(level)s %(name)s %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
```

**services/user.py**
```python
import logging

logger = logging.getLogger(__name__)

def create_user(data: dict) -> User:
    """Create a new user"""
    logger.info(
        'Creating user',
        extra={
            'email': data['email'],
            'username': data.get('username')
        }
    )

    try:
        user = User(**data)
        db.session.add(user)
        db.session.commit()

        logger.info(
            'User created successfully',
            extra={'user_id': user.id, 'email': user.email}
        )
        return user

    except Exception as e:
        logger.error(
            'Failed to create user',
            extra={'error': str(e), 'email': data['email']},
            exc_info=True
        )
        raise
```

## Workflow 7: Add Pytest Fixtures

### Command
```bash
python rev.py "Create pytest fixtures for database and sample data"
```

### Generated Fixtures

**tests/conftest.py**
```python
import pytest
from app import create_app, db
from app.models import User, Post

@pytest.fixture(scope='session')
def app():
    """Create application for testing"""
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()

@pytest.fixture
def client(app):
    """Create test client"""
    return app.test_client()

@pytest.fixture
def db_session(app):
    """Create database session"""
    with app.app_context():
        yield db.session
        db.session.rollback()

@pytest.fixture
def sample_user(db_session):
    """Create sample user"""
    user = User(
        email='test@example.com',
        username='testuser',
        password_hash='hashed'
    )
    db_session.add(user)
    db_session.commit()
    return user

@pytest.fixture
def auth_token(sample_user):
    """Create auth token for testing"""
    return create_access_token(identity=sample_user.id)
```

## Workflow 8: Add Docker Support

### Command
```bash
python rev.py "Add Dockerfile and docker-compose.yml for development"
```

### Generated Files

**Dockerfile**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Run application
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "app:create_app()"]
```

**docker-compose.yml**
```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/appdb
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - .:/app

  db:
    image: postgres:15
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
      - POSTGRES_DB=appdb
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

## Quick Commands

### Development Setup
```bash
python rev.py "Setup Python development environment with virtualenv and pre-commit hooks"
```

### Code Quality
```bash
python rev.py "Run black, flake8, and mypy on entire codebase"
```

### Testing
```bash
python rev.py "Add pytest tests for all services and achieve 80% coverage"
```

### Performance
```bash
python rev.py "Add caching with Redis to frequently accessed endpoints"
```

### Security
```bash
python rev.py "Add input validation and rate limiting to all API endpoints"
```

## Best Practices

1. **Virtual Environments**: Always use virtualenv or venv
2. **Type Hints**: Add type hints for better IDE support
3. **Testing**: Aim for 80%+ test coverage
4. **Logging**: Use structured logging
5. **Environment Variables**: Never commit secrets
6. **Code Quality**: Use black, flake8, mypy

## Next Steps

- **[Testing](../scenarios/testing.md)** - Add comprehensive tests
- **[API Development](api-development.md)** - Build APIs
- **[CI/CD](../ci-cd/github-actions/)** - Automate workflows
