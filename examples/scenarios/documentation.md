# Documentation with rev

Generate and maintain comprehensive documentation automatically.

## Scenario 1: API Documentation

### Task
Generate API documentation from code.

### Command
```bash
rev "Generate API documentation for all endpoints in routes/ directory"
```

### Generated Documentation
```markdown
# API Documentation

## Authentication

### POST /api/auth/register
Register a new user account.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123",
  "username": "johndoe"
}
```

**Response:** 201 Created
```json
{
  "id": 1,
  "email": "user@example.com",
  "username": "johndoe",
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Errors:**
- `400 Bad Request` - Invalid input data
- `409 Conflict` - Email already registered

### POST /api/auth/login
Authenticate user and receive JWT token.

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "SecurePass123"
}
```

**Response:** 200 OK
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "username": "johndoe"
  }
}
```

**Errors:**
- `401 Unauthorized` - Invalid credentials

## Users

### GET /api/users
List all users with pagination.

**Query Parameters:**
- `page` (optional) - Page number (default: 1)
- `per_page` (optional) - Items per page (default: 20)
- `sort` (optional) - Sort field (default: created_at)

**Response:** 200 OK
```json
{
  "users": [...],
  "total": 150,
  "page": 1,
  "pages": 8
}
```
```

## Scenario 2: Code Comments and Docstrings

### Task
Add comprehensive docstrings to all functions.

### Command
```bash
rev "Add docstrings to all functions in services/ directory following Google style"
```

### Before
```python
def create_user(data):
    user = User(**data)
    db.session.add(user)
    db.session.commit()
    return user
```

### After
```python
def create_user(data):
    """Create a new user account.

    Args:
        data (dict): User data containing email, password, and optional fields
            - email (str): User's email address (required)
            - password (str): User's password (required, min 8 chars)
            - username (str): Display name (optional)
            - bio (str): User biography (optional)

    Returns:
        User: Created user object with generated ID

    Raises:
        ValueError: If email is invalid or already exists
        ValueError: If password doesn't meet requirements

    Example:
        >>> user_data = {'email': 'john@example.com', 'password': 'SecurePass123'}
        >>> user = create_user(user_data)
        >>> print(user.id)
        1
    """
    user = User(**data)
    db.session.add(user)
    db.session.commit()
    return user
```

## Scenario 3: README Generation

### Task
Create comprehensive README for a new project.

### Command
```bash
rev "Generate a comprehensive README.md with installation, usage, and examples"
```

### Generated README
```markdown
# Project Name

Brief description of what this project does.

## Features

- Feature 1: Description
- Feature 2: Description
- Feature 3: Description

## Installation

### Prerequisites
- Python 3.8+
- PostgreSQL 12+
- Redis 6+

### Setup
```bash
# Clone repository
git clone https://github.com/user/project.git
cd project

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Run migrations
python manage.py migrate

# Start development server
python manage.py runserver
```

## Usage

### Basic Example
```python
from project import Client

client = Client(api_key='your-key')
result = client.process(data)
```

### Advanced Example
```python
# With custom configuration
client = Client(
    api_key='your-key',
    timeout=30,
    retry_count=3
)

# Batch processing
results = client.batch_process(items)
```

## API Documentation

See [API.md](docs/API.md) for detailed API documentation.

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=project --cov-report=html

# Run specific test file
pytest tests/test_client.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) for details
```

## Scenario 4: Architecture Documentation

### Task
Document system architecture and design decisions.

### Command
```bash
rev "Create ARCHITECTURE.md documenting the system design and key decisions"
```

### Generated Architecture Doc
```markdown
# Architecture

## System Overview

This application follows a layered architecture pattern:

```
┌─────────────────────────────────────────┐
│          Presentation Layer             │
│         (API Routes/Controllers)        │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│          Business Logic Layer           │
│              (Services)                 │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│          Data Access Layer              │
│          (Repositories/Models)          │
└──────────────┬──────────────────────────┘
               │
┌──────────────▼──────────────────────────┐
│            Database                     │
│          (PostgreSQL)                   │
└─────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Repository Pattern
**Decision:** Use repository pattern for data access
**Rationale:** Separates business logic from data access, makes testing easier
**Trade-offs:** More code, but better maintainability

### 2. JWT Authentication
**Decision:** Use JWT tokens for authentication
**Rationale:** Stateless, scalable, works well with SPAs
**Trade-offs:** Cannot easily revoke tokens, larger request size

### 3. PostgreSQL Database
**Decision:** Use PostgreSQL as primary database
**Rationale:** ACID compliance, rich feature set, great for relational data
**Trade-offs:** More complex than SQLite, requires server

## Data Flow

1. Client sends request to API endpoint
2. Route validates request and calls service
3. Service implements business logic
4. Repository queries database
5. Data flows back through layers
6. Response sent to client

## Security Considerations

- All passwords hashed with bcrypt
- JWT tokens expire after 24 hours
- Rate limiting on authentication endpoints
- Input validation on all endpoints
- SQL injection prevention via parameterized queries

## Performance

- Database queries use indexes
- Caching layer with Redis
- Pagination for large result sets
- Background jobs for long-running tasks

## Scalability

- Stateless API (can run multiple instances)
- Database connection pooling
- Horizontal scaling supported
- Caching reduces database load
```

## Scenario 5: Changelog Maintenance

### Task
Generate changelog from git commits.

### Command
```bash
rev "Update CHANGELOG.md with recent changes from git history"
```

### Generated Changelog
```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [2.0.0] - 2024-01-15

### Added
- User authentication with JWT tokens
- Rate limiting on API endpoints
- Password reset functionality
- Email verification for new accounts
- Profile picture upload support

### Changed
- Improved password validation rules
- Updated API response format for consistency
- Migrated from SQLite to PostgreSQL

### Fixed
- Fixed null pointer error in login function
- Resolved N+1 query problem in user list endpoint
- Fixed race condition in concurrent user creation

### Security
- Fixed SQL injection vulnerability in search
- Added CSRF protection
- Improved password hashing with bcrypt

## [1.5.0] - 2024-01-01

### Added
- User profile editing
- Search functionality
- Export to CSV

### Fixed
- Fixed pagination bug
- Resolved memory leak in background jobs
```

## Scenario 6: Tutorial Creation

### Task
Create step-by-step tutorial for new users.

### Command
```bash
rev "Create a tutorial in docs/TUTORIAL.md for getting started with the API"
```

### Generated Tutorial
```markdown
# Getting Started Tutorial

This tutorial will walk you through using the API in 15 minutes.

## Step 1: Register an Account (2 minutes)

First, let's create a user account:

```bash
curl -X POST http://localhost:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "you@example.com",
    "password": "SecurePass123",
    "username": "yourname"
  }'
```

You should see:
```json
{
  "id": 1,
  "email": "you@example.com",
  "username": "yourname"
}
```

## Step 2: Login (1 minute)

Now let's login to get an authentication token:

```bash
curl -X POST http://localhost:5000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "you@example.com",
    "password": "SecurePass123"
  }'
```

Copy the token from the response:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs..."
}
```

## Step 3: Make Authenticated Request (2 minutes)

Use your token to access protected endpoints:

```bash
export TOKEN="your-token-here"

curl -X GET http://localhost:5000/api/users/me \
  -H "Authorization: Bearer $TOKEN"
```

## Step 4: Create a Resource (5 minutes)

Let's create a new post:

```bash
curl -X POST http://localhost:5000/api/posts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "My First Post",
    "content": "Hello, World!"
  }'
```

## Step 5: List Resources (2 minutes)

View all posts:

```bash
curl -X GET http://localhost:5000/api/posts
```

With pagination:

```bash
curl -X GET "http://localhost:5000/api/posts?page=1&per_page=10"
```

## Next Steps

- Read the [API Documentation](API.md)
- Check out [Advanced Examples](EXAMPLES.md)
- Join our [Community Forum](https://forum.example.com)
```

## Best Practices

### 1. Keep Documentation Close to Code
```bash
rev "Add inline documentation to all public APIs"
```

### 2. Include Examples
```bash
rev "Add code examples to all docstrings"
```

### 3. Document Why, Not Just What
```bash
rev "Add comments explaining the rationale for complex algorithms"
```

### 4. Keep Documentation Updated
```bash
rev "Update API docs to reflect recent changes to user endpoints"
```

## Documentation Types

### API Reference
```bash
rev "Generate OpenAPI/Swagger documentation"
```

### User Guides
```bash
rev "Create user guide for admin features"
```

### Developer Guides
```bash
rev "Create contributing guide for new developers"
```

### Deployment Docs
```bash
rev "Document deployment process for AWS"
```

## Next Steps

- **[Code Review](code-review.md)** - Review documentation quality
- **[Testing](testing.md)** - Test documentation examples
- **[CI/CD Integration](../ci-cd/)** - Auto-generate docs in CI
