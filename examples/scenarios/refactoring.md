# Code Refactoring with rev.py

Safely refactor code with automated testing to prevent regressions.

## Scenario 1: Extract Function

### Problem
Large function with multiple responsibilities.

### Command
```bash
python rev.py "Extract validation logic from createUser function into separate validator functions"
```

### Before
```python
def create_user(data):
    # Validation
    if not data.get('email'):
        raise ValueError('Email required')
    if '@' not in data['email']:
        raise ValueError('Invalid email')
    if len(data.get('password', '')) < 8:
        raise ValueError('Password too short')
    if not any(c.isupper() for c in data['password']):
        raise ValueError('Password needs uppercase')

    # Create user
    user = User(
        email=data['email'],
        password=hash_password(data['password'])
    )
    db.session.add(user)
    db.session.commit()
    return user
```

### After
```python
def validate_email(email):
    """Validate email format"""
    if not email:
        raise ValueError('Email required')
    if '@' not in email:
        raise ValueError('Invalid email')
    return email

def validate_password(password):
    """Validate password strength"""
    if len(password) < 8:
        raise ValueError('Password too short')
    if not any(c.isupper() for c in password):
        raise ValueError('Password needs uppercase')
    return password

def create_user(data):
    """Create a new user"""
    email = validate_email(data.get('email'))
    password = validate_password(data.get('password'))

    user = User(email=email, password=hash_password(password))
    db.session.add(user)
    db.session.commit()
    return user
```

## Scenario 2: Repository Pattern

### Problem
Database queries scattered throughout controllers.

### Command
```bash
python rev.py "Refactor to repository pattern - extract all database queries into repository classes"
```

### Before
```python
# In controller
@app.route('/users/<int:user_id>')
def get_user(user_id):
    user = db.session.query(User).filter_by(id=user_id).first()
    if not user:
        return {'error': 'Not found'}, 404
    return jsonify(user.to_dict())

@app.route('/users')
def list_users():
    users = db.session.query(User).order_by(User.created_at.desc()).all()
    return jsonify([u.to_dict() for u in users])
```

### After
```python
# Repository
class UserRepository:
    def find_by_id(self, user_id):
        """Find user by ID"""
        return db.session.query(User).filter_by(id=user_id).first()

    def find_all(self, order_by='created_at'):
        """Find all users"""
        return db.session.query(User).order_by(
            getattr(User, order_by).desc()
        ).all()

    def save(self, user):
        """Save user to database"""
        db.session.add(user)
        db.session.commit()
        return user

# In controller
user_repo = UserRepository()

@app.route('/users/<int:user_id>')
def get_user(user_id):
    user = user_repo.find_by_id(user_id)
    if not user:
        return {'error': 'Not found'}, 404
    return jsonify(user.to_dict())

@app.route('/users')
def list_users():
    users = user_repo.find_all()
    return jsonify([u.to_dict() for u in users])
```

## Scenario 3: Dependency Injection

### Problem
Hard-coded dependencies make testing difficult.

### Command
```bash
python rev.py "Refactor to use dependency injection for EmailService and PaymentService"
```

### Before
```python
class OrderService:
    def create_order(self, user_id, items):
        order = Order(user_id, items)
        db.save(order)

        # Hard-coded dependencies
        EmailService().send_confirmation(order)
        PaymentService().charge(order.total)

        return order
```

### After
```python
class OrderService:
    def __init__(self, email_service=None, payment_service=None):
        self.email_service = email_service or EmailService()
        self.payment_service = payment_service or PaymentService()

    def create_order(self, user_id, items):
        order = Order(user_id, items)
        db.save(order)

        # Injected dependencies (mockable for testing)
        self.email_service.send_confirmation(order)
        self.payment_service.charge(order.total)

        return order

# Testing becomes easy
def test_create_order():
    mock_email = Mock()
    mock_payment = Mock()
    service = OrderService(mock_email, mock_payment)

    order = service.create_order(1, ['item1'])

    mock_email.send_confirmation.assert_called_once()
    mock_payment.charge.assert_called_with(order.total)
```

## Scenario 4: Remove Code Duplication

### Problem
Same logic repeated in multiple places.

### Command
```bash
python rev.py "Remove duplication in error handling across all API endpoints"
```

### Before
```python
@app.route('/users')
def get_users():
    try:
        users = User.query.all()
        return jsonify([u.to_dict() for u in users])
    except Exception as e:
        logger.error(f'Error in get_users: {e}')
        return {'error': 'Internal server error'}, 500

@app.route('/posts')
def get_posts():
    try:
        posts = Post.query.all()
        return jsonify([p.to_dict() for p in posts])
    except Exception as e:
        logger.error(f'Error in get_posts: {e}')
        return {'error': 'Internal server error'}, 500
```

### After
```python
def handle_errors(f):
    """Decorator for consistent error handling"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f'Error in {f.__name__}: {e}')
            return {'error': 'Internal server error'}, 500
    return wrapper

@app.route('/users')
@handle_errors
def get_users():
    users = User.query.all()
    return jsonify([u.to_dict() for u in users])

@app.route('/posts')
@handle_errors
def get_posts():
    posts = Post.query.all()
    return jsonify([p.to_dict() for p in posts])
```

## Scenario 5: Modernize Legacy Code

### Problem
Old callback-based code needs modernization.

### Command
```bash
python rev.py "Refactor callback-based code to async/await in services/ directory"
```

### Before (Callbacks)
```javascript
function getUserWithPosts(userId, callback) {
  db.getUser(userId, (err, user) => {
    if (err) return callback(err);

    db.getPosts(userId, (err, posts) => {
      if (err) return callback(err);

      user.posts = posts;
      callback(null, user);
    });
  });
}
```

### After (Async/Await)
```javascript
async function getUserWithPosts(userId) {
  const user = await db.getUser(userId);
  const posts = await db.getPosts(userId);
  user.posts = posts;
  return user;
}
```

## Scenario 6: Improve Code Organization

### Problem
Large monolithic file with mixed concerns.

### Command
```bash
python rev.py "Split app.py into separate modules: models/, routes/, services/"
```

### Before
```
app.py (1500 lines)
  - Models
  - Routes
  - Business logic
  - Configuration
```

### After
```
app/
  __init__.py
  config.py
  models/
    __init__.py
    user.py
    post.py
  routes/
    __init__.py
    auth.py
    users.py
    posts.py
  services/
    __init__.py
    email.py
    payment.py
```

## Scenario 7: Performance Refactoring

### Problem
N+1 query problem slowing down API.

### Command
```bash
python rev.py "Fix N+1 query problem in getUsersWithPosts endpoint"
```

### Before (N+1 Queries)
```python
@app.route('/users-with-posts')
def get_users_with_posts():
    users = User.query.all()  # 1 query
    for user in users:
        user.posts = Post.query.filter_by(user_id=user.id).all()  # N queries
    return jsonify([u.to_dict() for u in users])
```

### After (Single Query)
```python
@app.route('/users-with-posts')
def get_users_with_posts():
    users = User.query.options(
        joinedload(User.posts)  # Single query with JOIN
    ).all()
    return jsonify([u.to_dict() for u in users])
```

## Best Practices

### 1. Run Tests Before and After
```bash
python rev.py "Run tests, then refactor auth service to use dependency injection, then run tests again"
```

### 2. Refactor in Small Steps
```bash
# Good: Small, focused refactoring
python rev.py "Extract validation logic from UserController"

# Risky: Too much at once
python rev.py "Completely rewrite the entire application"
```

### 3. Use REPL for Exploratory Refactoring
```bash
python rev.py --repl

agent> Show me the UserService class
agent> Identify code duplication in UserService
agent> Extract the duplicated logic into helper methods
agent> Run tests to verify
agent> /exit
```

### 4. Document Major Refactorings
```bash
python rev.py "Refactor to repository pattern and update ARCHITECTURE.md"
```

## Common Refactoring Patterns

### Extract Method
```bash
python rev.py "Extract repeated validation logic into separate methods"
```

### Extract Class
```bash
python rev.py "Extract payment logic from OrderService into PaymentService"
```

### Rename for Clarity
```bash
python rev.py "Rename getData() to fetchUserProfile() for clarity"
```

### Inline Unnecessary Abstractions
```bash
python rev.py "Inline single-use helper functions in utils.py"
```

### Replace Conditionals with Polymorphism
```bash
python rev.py "Replace payment type conditionals with strategy pattern"
```

## Safety Checklist

Before refactoring:
- [ ] Tests exist and pass
- [ ] Changes are version controlled
- [ ] Refactoring is small and focused

After refactoring:
- [ ] All tests still pass
- [ ] No behavior changes
- [ ] Code is clearer and simpler
- [ ] Performance is maintained or improved

## Next Steps

- **[Testing](testing.md)** - Add tests for refactored code
- **[Feature Development](feature-development.md)** - Build on refactored foundation
- **[Documentation](documentation.md)** - Update docs after refactoring
