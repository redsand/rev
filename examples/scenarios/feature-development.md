# Feature Development with rev.py

Learn how to develop new features iteratively using rev.py's **6-agent autonomous system**.

## Agent-Assisted Development

rev.py v2.0.1 uses 6 specialized agents that work together:

| Phase | Agent | What It Does |
|-------|-------|--------------|
| 1 | **Learning** | Recalls similar past tasks, suggests approaches |
| 2 | **Research** | Explores codebase for context |
| 3 | **Planning** | Breaks down into atomic tasks |
| 4 | **Review** | Validates plan, checks security |
| 5 | **Execution** | Runs tasks in parallel or sequentially |
| 6 | **Validation** | Runs tests, linting, semantic checks |

## Scenario 1: Add Simple Feature

### Task
Add rate limiting to API endpoints.

### Command (Standard)
```bash
python rev.py "Add rate limiting middleware to API with 100 requests per minute limit"
```

### Command (With Research Agent)
```bash
# Research agent finds existing middleware patterns first
python rev.py --research "Add rate limiting middleware to API with 100 requests per minute limit"
```

### Command (Full Orchestration)
```bash
# All 6 agents coordinate for maximum autonomy
python rev.py --orchestrate --learn --research "Add rate limiting middleware"
```

### Generated Plan
```
1. [REVIEW] Analyze current middleware structure
2. [ADD] Install rate-limiting package (express-rate-limit)
3. [ADD] Create rate limiter middleware
4. [EDIT] Integrate rate limiter into app
5. [ADD] Add tests for rate limiting
6. [TEST] Verify rate limiting works
```

### Example Implementation

**Step 1-2: Install dependency**
```bash
npm install express-rate-limit
```

**Step 3: Create middleware**
```javascript
// src/middleware/rateLimiter.js
const rateLimit = require('express-rate-limit');

const limiter = rateLimit({
  windowMs: 60 * 1000, // 1 minute
  max: 100, // 100 requests per windowMs
  message: 'Too many requests, please try again later.',
  standardHeaders: true,
  legacyHeaders: false,
});

module.exports = limiter;
```

**Step 4: Integrate**
```javascript
// src/app.js
const rateLimiter = require('./middleware/rateLimiter');

app.use('/api/', rateLimiter);
```

**Step 5-6: Add tests**
```javascript
// tests/rateLimiter.test.js
describe('Rate Limiter', () => {
  it('should allow 100 requests per minute', async () => {
    for (let i = 0; i < 100; i++) {
      const res = await request(app).get('/api/users');
      expect(res.status).toBe(200);
    }
  });

  it('should block 101st request', async () => {
    for (let i = 0; i < 100; i++) {
      await request(app).get('/api/users');
    }
    const res = await request(app).get('/api/users');
    expect(res.status).toBe(429);
  });
});
```

## Scenario 2: Multi-Step Feature with Orchestrator

### Task
Add user authentication system with JWT.

### Command (Recommended: Full Orchestration)
```bash
python rev.py --orchestrate --learn --research "Implement JWT authentication with login, register, and protected routes"
```

### What Each Agent Does

**1. Learning Agent:**
```
============================================================
LEARNING AGENT - INSIGHTS
============================================================
Similar past tasks: authentication, feature_add
Estimated time: 12.5 minutes
Likely files: auth.py, models/user.py, middleware/
Warnings from past experience:
   - Ensure JWT secrets use environment variables
============================================================
```

**2. Research Agent:**
```
============================================================
RESEARCH AGENT - CODEBASE EXPLORATION
============================================================
Searching for: authentication, jwt, login, user
Relevant Files (8):
   - src/middleware/auth.py
   - src/models/user.py
   - src/routes/api.py
Similar Implementations:
   - src/middleware/rate_limiter.py: Middleware pattern
Suggested Approach:
   Follow existing middleware pattern in rate_limiter.py
Estimated Complexity: HIGH
============================================================
```

**3. Review Agent:**
```
============================================================
REVIEW AGENT - PLAN REVIEW
============================================================
Decision: APPROVED WITH SUGGESTIONS
Confidence: 85%

Suggestions (3):
  - Add rate limiting to prevent brute force attacks
  - Include password reset functionality
  - Add integration tests for authentication flow

Security Concerns (1):
  - Ensure JWT secrets are stored in environment variables
============================================================
```

**4. Validation Agent (after execution):**
```
============================================================
VALIDATION AGENT - RESULTS
============================================================
Syntax Check: PASSED
Test Suite: PASSED (24/24 tests)
Linter: PASSED_WITH_WARNINGS (2 minor issues)
Semantic Check: PASSED - changes match request
Auto-fixed: 2 linting issues
============================================================
```

### Alternative: Standard Mode
```bash
python rev.py "Implement JWT authentication with login, register, and protected routes"
```

### Generated Plan
```
1. [REVIEW] Analyze current auth setup
2. [ADD] Install JWT dependencies (jsonwebtoken, bcrypt)
3. [ADD] Create User model with password hashing
4. [ADD] Create auth controller (register, login)
5. [ADD] Create JWT middleware
6. [EDIT] Add auth routes
7. [EDIT] Protect existing routes with auth middleware
8. [ADD] Add comprehensive auth tests
9. [TEST] Run all tests
```

### Key Components Created

**User Model:**
```python
# models/user.py
from werkzeug.security import generate_password_hash, check_password_hash

class User:
    def __init__(self, username, email, password):
        self.username = username
        self.email = email
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
```

**Auth Controller:**
```python
# controllers/auth.py
import jwt
from datetime import datetime, timedelta

def register(username, email, password):
    user = User(username, email, password)
    db.save(user)
    return {'message': 'User registered successfully'}

def login(email, password):
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        raise AuthError('Invalid credentials')

    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=1)
    }, SECRET_KEY)

    return {'token': token}
```

**Auth Middleware:**
```python
# middleware/auth.py
def require_auth(f):
    def wrapper(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return {'error': 'No token provided'}, 401

        try:
            payload = jwt.decode(token, SECRET_KEY)
            request.user_id = payload['user_id']
        except jwt.InvalidTokenError:
            return {'error': 'Invalid token'}, 401

        return f(*args, **kwargs)
    return wrapper
```

## Scenario 3: Feature with Database Migration

### Task
Add user profile fields (bio, avatar, location).

### Command
```bash
python rev.py "Add user profile fields: bio, avatar_url, location with database migration"
```

### Process
```
1. [ADD] Create database migration
2. [EDIT] Update User model
3. [EDIT] Update user API endpoints
4. [ADD] Add validation for new fields
5. [ADD] Add tests for profile updates
6. [TEST] Run migration and tests
```

### Migration Created
```python
# migrations/add_user_profile_fields.py
def upgrade():
    op.add_column('users',
        sa.Column('bio', sa.String(500), nullable=True))
    op.add_column('users',
        sa.Column('avatar_url', sa.String(255), nullable=True))
    op.add_column('users',
        sa.Column('location', sa.String(100), nullable=True))

def downgrade():
    op.drop_column('users', 'bio')
    op.drop_column('users', 'avatar_url')
    op.drop_column('users', 'location')
```

## Scenario 4: API Endpoint Development

### Task
Create RESTful CRUD endpoints for blog posts.

### Command
```bash
python rev.py "Create REST API for blog posts with CRUD operations and tests"
```

### Generated Endpoints
```python
# routes/posts.py
@app.route('/api/posts', methods=['GET'])
def get_posts():
    """List all posts with pagination"""
    page = request.args.get('page', 1, type=int)
    posts = Post.query.paginate(page=page, per_page=10)
    return jsonify({
        'posts': [p.to_dict() for p in posts.items],
        'total': posts.total,
        'pages': posts.pages
    })

@app.route('/api/posts', methods=['POST'])
@require_auth
def create_post():
    """Create a new post"""
    data = request.get_json()
    post = Post(
        title=data['title'],
        content=data['content'],
        author_id=request.user_id
    )
    db.session.add(post)
    db.session.commit()
    return jsonify(post.to_dict()), 201

@app.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post(post_id):
    """Get a single post"""
    post = Post.query.get_or_404(post_id)
    return jsonify(post.to_dict())

@app.route('/api/posts/<int:post_id>', methods=['PUT'])
@require_auth
def update_post(post_id):
    """Update a post"""
    post = Post.query.get_or_404(post_id)
    if post.author_id != request.user_id:
        return {'error': 'Unauthorized'}, 403

    data = request.get_json()
    post.title = data.get('title', post.title)
    post.content = data.get('content', post.content)
    db.session.commit()
    return jsonify(post.to_dict())

@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
@require_auth
def delete_post(post_id):
    """Delete a post"""
    post = Post.query.get_or_404(post_id)
    if post.author_id != request.user_id:
        return {'error': 'Unauthorized'}, 403

    db.session.delete(post)
    db.session.commit()
    return '', 204
```

### Tests Created
```python
# tests/test_posts.py
class TestPostsAPI:
    def test_create_post(self, client, auth_token):
        res = client.post('/api/posts',
            json={'title': 'Test', 'content': 'Content'},
            headers={'Authorization': auth_token})
        assert res.status_code == 201
        assert res.json['title'] == 'Test'

    def test_get_posts(self, client):
        res = client.get('/api/posts')
        assert res.status_code == 200
        assert 'posts' in res.json

    def test_update_post_requires_auth(self, client):
        res = client.put('/api/posts/1',
            json={'title': 'Updated'})
        assert res.status_code == 401
```

## Scenario 5: Parallel Feature Development

### Task
Add multiple independent features simultaneously.

### Command
```bash
python rev.py -j 4 "Add email notifications, search functionality, and export to CSV"
```

### Parallel Execution
```
Running 3 tasks in parallel (4 workers):

Worker 1: Email Notifications
  ✓ Install email library
  ✓ Create email service
  ✓ Add notification triggers
  ✓ Add email templates

Worker 2: Search Functionality
  ✓ Add search endpoint
  ✓ Implement full-text search
  ✓ Add search filters
  ✓ Add pagination

Worker 3: CSV Export
  ✓ Create export endpoint
  ✓ Implement CSV generation
  ✓ Add download headers
  ✓ Add export tests

All features completed in 45 seconds (vs 180 seconds sequential)
```

## Scenario 6: Feature with External API

### Task
Integrate with Stripe payment processing.

### Command
```bash
python rev.py "Integrate Stripe payments with checkout, webhooks, and refunds"
```

### Implementation
```python
# services/payment.py
import stripe

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

def create_checkout_session(amount, customer_email):
    """Create Stripe checkout session"""
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': 'Product'},
                'unit_amount': amount,
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url='https://example.com/success',
        cancel_url='https://example.com/cancel',
        customer_email=customer_email,
    )
    return session

def handle_webhook(payload, sig_header):
    """Handle Stripe webhooks"""
    event = stripe.Webhook.construct_event(
        payload, sig_header, WEBHOOK_SECRET
    )

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        fulfill_order(session)

    return {'status': 'success'}

def refund_payment(payment_intent_id):
    """Refund a payment"""
    refund = stripe.Refund.create(
        payment_intent=payment_intent_id
    )
    return refund
```

## Best Practices

### 1. Use Orchestrator for Complex Features
```bash
# Let the orchestrator coordinate all agents
python rev.py --orchestrate --learn --research "Build payment processing system"

# This automatically:
# - Checks past patterns (Learning Agent)
# - Explores codebase (Research Agent)
# - Creates detailed plan (Planning Agent)
# - Validates security (Review Agent)
# - Executes in parallel (Execution Agent)
# - Verifies results (Validation Agent)
```

### 2. Enable Learning for Repeated Tasks
```bash
# First time: Agent learns from execution
python rev.py --learn "Add API endpoint for user preferences"

# Next time: Agent recalls patterns and suggests faster approach
python rev.py --learn "Add API endpoint for notifications"
```

### 3. Use Research for Unfamiliar Codebases
```bash
# Deep research for complex tasks
python rev.py --research --research-depth deep "Refactor authentication module"

# Quick research for simple context
python rev.py --research --research-depth shallow "Fix login bug"
```

### 4. Adjust Review Strictness by Risk
```bash
# Strict for sensitive operations
python rev.py --review-strictness strict "Database migration"
python rev.py --review-strictness strict --action-review "Payment processing"

# Lenient for low-risk changes
python rev.py --review-strictness lenient "Update documentation"
```

### 5. Enable Auto-Fix for Validation
```bash
# Auto-fix linting/formatting issues
python rev.py --auto-fix "Add new feature with tests"

# This automatically fixes minor validation issues
```

### 6. Break Down Large Features
```bash
# Instead of one huge task:
python rev.py "Build entire e-commerce platform"

# Break into smaller features (or let orchestrator handle):
python rev.py --orchestrate "Add product catalog with CRUD operations"
python rev.py --orchestrate "Add shopping cart functionality"
python rev.py --orchestrate "Add checkout and payment"
```

### 7. Use REPL for Iterative Development
```bash
python rev.py --repl

agent> Create the User model
agent> Now add authentication endpoints
agent> Add password reset functionality
agent> Add email verification
agent> Run all tests
agent> /exit
```

### 8. Specify Requirements Clearly
```bash
# Good: Clear requirements
python rev.py "Add pagination to /api/posts with page size 20, include total count"

# Less effective: Vague
python rev.py "Make posts better"
```

## Integration Patterns

### Feature Flags
```bash
python rev.py "Add feature flag system for gradual rollout of new features"
```

### A/B Testing
```bash
python rev.py "Add A/B testing framework for experimenting with features"
```

### Analytics Integration
```bash
python rev.py "Add analytics tracking for feature usage"
```

## Next Steps

- **[Testing](testing.md)** - Add comprehensive tests
- **[Refactoring](refactoring.md)** - Refactor after features
- **[Documentation](documentation.md)** - Document new features
