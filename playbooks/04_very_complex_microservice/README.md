# Playbook 04: Very Complex - REST API Microservice

## Level: Very Complex

## Goal
Implement a full REST API microservice with database, authentication, and comprehensive testing.

## Initial State
- Package structure with stub files
- Database schema definitions
- API endpoint stubs
- Test infrastructure

## Task
Implement a REST API microservice with the following components:

### `models/`:
- `User` model (id, username, email, hashed_password, created_at, is_active)
- `Product` model (id, name, description, price, stock, category_id)
- `Category` model (id, name, slug)
- `Order` model (id, user_id, status, total, created_at)
- `OrderItem` model (id, order_id, product_id, quantity, price)

### `database/`:
- Database connection pooling
- Repository pattern for each model
- Transaction management
- Migration support

### `api/`:
- RESTful endpoints with proper HTTP status codes
- Input validation with `pydantic`
- Error handling with custom exception classes
- Request/response models

### `auth/`:
- JWT-based authentication
- Password hashing (bcrypt)
- Token refresh mechanism
- Role-based authorization (admin, user, guest)

### `tests/`:
- Unit tests for models and repositories
- Integration tests for API endpoints
- Performance tests for database operations
- Security tests for authentication

### `config/`:
- Configuration management
- Environment-based settings
- Secret management

## API Endpoints Required:

**Auth**:
- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/login` - Login and get JWT
- `POST /api/v1/auth/refresh` - Refresh JWT
- `POST /api/v1/auth/logout` - Logout

**Products**:
- `GET /api/v1/products` - List all products (with pagination)
- `GET /api/v1/products/{id}` - Get product details
- `POST /api/v1/products` - Create product (admin only)
- `PUT /api/v1/products/{id}` - Update product (admin only)
- `DELETE /api/v1/products/{id}` - Delete product (admin only)

**Orders**:
- `POST /api/v1/orders` - Create order (authenticated)
- `GET /api/v1/orders` - List user orders (authenticated)
- `GET /api/v1/orders/{id}` - Get order details (authenticated)
- `PATCH /api/v1/orders/{id}/status` - Update order status (admin)

## Constraints
- Use FastAPI or Flask
- PostgreSQL or SQLite for database
- Async/await for database operations
- All API calls must be authenticated (except login/register)
- Proper HTTP status codes (200, 201, 400, 401, 403, 404, 409, 500)
- Request rate limiting
- Input sanitization to prevent injection attacks

## Success Criteria
- All API endpoints functional
- All tests pass (unit, integration, performance, security)
- Code coverage > 85%
- API documentation (Swagger/OpenAPI)
- No security vulnerabilities (SQL injection, XSS, CSRF)

## Validation
```bash
# Run all tests
pytest tests/ -v --cov=. --cov-report=html

# Security scan
bandit -r .

# Run API server
uvicorn main:app --reload

# Load test
locust -f tests/load_test.py
```

## Expected File Structure
```
04_very_complex_microservice/
├── README.md
├── main.py
├── config.py
├── models/
│   ├── user.py
│   ├── product.py
│   └── order.py
├── database/
│   ├── connection.py
│   └── repositories.py
├── api/
│   ├── routes/
│   │   ├── auth.py
│   │   ├── products.py
│   │   └── orders.py
│   └── schemas.py
├── auth/
│   ├── jwt.py
│   └── security.py
└── tests/
    ├── unit/
    ├── integration/
    └── load_test.py
```