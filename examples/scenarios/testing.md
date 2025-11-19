# Testing with rev.py

Improve test coverage and quality using rev.py's autonomous testing capabilities.

## Scenario 1: Add Unit Tests

### Task
Add unit tests for a service class.

### Command
```bash
python rev.py "Add comprehensive unit tests for UserService class"
```

### Generated Tests
```python
# tests/test_user_service.py
import pytest
from unittest.mock import Mock, patch
from services.user_service import UserService

class TestUserService:
    def setup_method(self):
        """Setup test fixtures"""
        self.user_service = UserService()
        self.mock_db = Mock()

    def test_create_user_success(self):
        """Test successful user creation"""
        user_data = {
            'email': 'test@example.com',
            'password': 'SecurePass123'
        }
        user = self.user_service.create_user(user_data)

        assert user.email == 'test@example.com'
        assert user.password_hash is not None

    def test_create_user_duplicate_email(self):
        """Test user creation with duplicate email"""
        user_data = {'email': 'existing@example.com', 'password': 'pass'}

        with pytest.raises(ValueError, match='Email already exists'):
            self.user_service.create_user(user_data)

    def test_create_user_invalid_email(self):
        """Test user creation with invalid email"""
        user_data = {'email': 'invalid', 'password': 'pass'}

        with pytest.raises(ValueError, match='Invalid email'):
            self.user_service.create_user(user_data)

    def test_get_user_by_id(self):
        """Test fetching user by ID"""
        user = self.user_service.get_user(1)
        assert user.id == 1

    def test_get_user_not_found(self):
        """Test fetching non-existent user"""
        with pytest.raises(NotFoundError):
            self.user_service.get_user(999)
```

## Scenario 2: Improve Test Coverage

### Problem
Test coverage is only 45%.

### Command
```bash
python rev.py "Analyze test coverage and add tests to reach 80% coverage"
```

### Process
```
Step 1: Running coverage analysis...
  Current coverage: 45%
  Missing coverage:
    - auth.py: 12 uncovered lines
    - user_service.py: 8 uncovered lines
    - payment.py: 15 uncovered lines

Step 2: Adding tests for auth.py...
  ✓ Added test_login_invalid_password
  ✓ Added test_login_user_not_found
  ✓ Added test_register_weak_password
  ✓ Added test_token_expiration

Step 3: Adding tests for user_service.py...
  ✓ Added test_update_user_not_found
  ✓ Added test_delete_user
  ✓ Added test_list_users_pagination

Step 4: Adding tests for payment.py...
  ✓ Added test_charge_failed
  ✓ Added test_refund_success
  ✓ Added test_webhook_handling

Step 5: Verifying coverage...
  New coverage: 82%
  ✓ Coverage goal reached
```

## Scenario 3: Integration Tests

### Task
Add integration tests for API endpoints.

### Command
```bash
python rev.py "Add integration tests for all /api/users endpoints"
```

### Generated Tests
```python
# tests/integration/test_users_api.py
import pytest
from flask import json

class TestUsersAPI:
    def test_create_user(self, client):
        """Test POST /api/users"""
        response = client.post('/api/users', json={
            'email': 'new@example.com',
            'password': 'SecurePass123'
        })

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['email'] == 'new@example.com'
        assert 'id' in data

    def test_get_users(self, client):
        """Test GET /api/users"""
        response = client.get('/api/users')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert isinstance(data['users'], list)
        assert data['total'] > 0

    def test_get_user_by_id(self, client, sample_user):
        """Test GET /api/users/<id>"""
        response = client.get(f'/api/users/{sample_user.id}')

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['id'] == sample_user.id

    def test_update_user(self, client, auth_token, sample_user):
        """Test PUT /api/users/<id>"""
        response = client.put(
            f'/api/users/{sample_user.id}',
            json={'bio': 'Updated bio'},
            headers={'Authorization': f'Bearer {auth_token}'}
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['bio'] == 'Updated bio'

    def test_delete_user(self, client, auth_token, sample_user):
        """Test DELETE /api/users/<id>"""
        response = client.delete(
            f'/api/users/{sample_user.id}',
            headers={'Authorization': f'Bearer {auth_token}'}
        )

        assert response.status_code == 204

    def test_unauthorized_access(self, client, sample_user):
        """Test authentication required"""
        response = client.put(
            f'/api/users/{sample_user.id}',
            json={'bio': 'Hacked'}
        )

        assert response.status_code == 401
```

## Scenario 4: Test-Driven Development (TDD)

### Task
Add a feature using TDD approach.

### Command
```bash
python rev.py "Use TDD to add password reset functionality - write tests first"
```

### Process

**Step 1: Write failing tests**
```python
def test_request_password_reset():
    """Test requesting password reset"""
    response = client.post('/api/password-reset/request', json={
        'email': 'user@example.com'
    })
    assert response.status_code == 200
    # Test fails - endpoint doesn't exist yet

def test_reset_password_with_token():
    """Test resetting password with token"""
    response = client.post('/api/password-reset/confirm', json={
        'token': 'valid-token',
        'new_password': 'NewSecure123'
    })
    assert response.status_code == 200
    # Test fails - endpoint doesn't exist yet
```

**Step 2: Implement to make tests pass**
```python
@app.route('/api/password-reset/request', methods=['POST'])
def request_password_reset():
    email = request.json['email']
    user = User.query.filter_by(email=email).first()

    if user:
        token = generate_reset_token(user)
        send_reset_email(user.email, token)

    # Always return 200 (security - don't reveal if email exists)
    return {'message': 'If email exists, reset link sent'}

@app.route('/api/password-reset/confirm', methods=['POST'])
def confirm_password_reset():
    token = request.json['token']
    new_password = request.json['new_password']

    user = verify_reset_token(token)
    if not user:
        return {'error': 'Invalid or expired token'}, 400

    user.set_password(new_password)
    db.session.commit()

    return {'message': 'Password reset successful'}
```

**Step 3: Tests pass**
```
✓ test_request_password_reset PASSED
✓ test_reset_password_with_token PASSED
```

## Scenario 5: End-to-End Tests

### Task
Add E2E tests for critical user flows.

### Command
```bash
python rev.py "Add E2E tests for user registration and login flow"
```

### Generated E2E Tests
```python
# tests/e2e/test_auth_flow.py
import pytest
from selenium import webdriver

class TestAuthFlow:
    @pytest.fixture
    def browser(self):
        driver = webdriver.Chrome()
        yield driver
        driver.quit()

    def test_complete_registration_flow(self, browser):
        """Test complete user registration flow"""
        # Navigate to registration page
        browser.get('http://localhost:5000/register')

        # Fill registration form
        browser.find_element_by_id('email').send_keys('new@example.com')
        browser.find_element_by_id('password').send_keys('SecurePass123')
        browser.find_element_by_id('confirm-password').send_keys('SecurePass123')
        browser.find_element_by_id('submit').click()

        # Verify redirect to dashboard
        assert 'dashboard' in browser.current_url

        # Verify welcome message
        welcome = browser.find_element_by_class_name('welcome-message')
        assert 'Welcome' in welcome.text

    def test_login_logout_flow(self, browser):
        """Test login and logout flow"""
        # Login
        browser.get('http://localhost:5000/login')
        browser.find_element_by_id('email').send_keys('user@example.com')
        browser.find_element_by_id('password').send_keys('password123')
        browser.find_element_by_id('login-btn').click()

        # Verify logged in
        assert browser.find_element_by_id('logout-btn').is_displayed()

        # Logout
        browser.find_element_by_id('logout-btn').click()

        # Verify logged out
        assert 'login' in browser.current_url
```

## Scenario 6: Performance Testing

### Task
Add performance tests to ensure SLAs are met.

### Command
```bash
python rev.py "Add performance tests to ensure API responds within 200ms"
```

### Performance Tests
```python
# tests/performance/test_api_performance.py
import time
import pytest

class TestAPIPerformance:
    def test_get_users_performance(self, client):
        """Test that GET /api/users responds within 200ms"""
        start = time.time()
        response = client.get('/api/users')
        duration = (time.time() - start) * 1000  # Convert to ms

        assert response.status_code == 200
        assert duration < 200, f'Response took {duration}ms (> 200ms)'

    def test_concurrent_requests(self, client):
        """Test handling 100 concurrent requests"""
        import concurrent.futures

        def make_request():
            return client.get('/api/users').status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            futures = [executor.submit(make_request) for _ in range(100)]
            results = [f.result() for f in futures]

        # All requests should succeed
        assert all(status == 200 for status in results)
```

## Scenario 7: Mocking External Services

### Task
Add tests that mock external API calls.

### Command
```bash
python rev.py "Add tests for PaymentService with mocked Stripe API calls"
```

### Mocked Tests
```python
# tests/test_payment_service.py
from unittest.mock import patch, Mock
import pytest

class TestPaymentService:
    @patch('stripe.PaymentIntent.create')
    def test_charge_success(self, mock_create):
        """Test successful payment charge"""
        # Mock Stripe response
        mock_create.return_value = Mock(
            id='pi_123',
            status='succeeded',
            amount=1000
        )

        service = PaymentService()
        result = service.charge(amount=1000, customer='cus_123')

        assert result['status'] == 'succeeded'
        mock_create.assert_called_once_with(
            amount=1000,
            currency='usd',
            customer='cus_123'
        )

    @patch('stripe.PaymentIntent.create')
    def test_charge_failure(self, mock_create):
        """Test failed payment charge"""
        # Mock Stripe error
        mock_create.side_effect = stripe.error.CardError(
            'Card declined', None, 'card_declined'
        )

        service = PaymentService()

        with pytest.raises(PaymentError, match='Card declined'):
            service.charge(amount=1000, customer='cus_123')
```

## Best Practices

### 1. Test Pyramid
```bash
# Many unit tests (fast, focused)
python rev.py "Add unit tests for all service classes"

# Some integration tests (moderate speed)
python rev.py "Add integration tests for API endpoints"

# Few E2E tests (slow, comprehensive)
python rev.py "Add E2E test for checkout flow"
```

### 2. Test Coverage Goals
```bash
# Set clear coverage targets
python rev.py "Add tests to reach 80% code coverage"

# Focus on critical paths first
python rev.py "Add tests for authentication and payment flows - aim for 95% coverage"
```

### 3. Use Fixtures
```bash
python rev.py "Create pytest fixtures for common test data and setup"
```

### 4. Test Edge Cases
```bash
python rev.py "Add tests for edge cases: empty inputs, invalid data, boundary conditions"
```

## Testing Patterns

### Arrange-Act-Assert (AAA)
```python
def test_create_user():
    # Arrange
    user_data = {'email': 'test@example.com', 'password': 'pass'}

    # Act
    user = create_user(user_data)

    # Assert
    assert user.email == 'test@example.com'
```

### Given-When-Then (BDD)
```python
def test_user_login():
    # Given a registered user
    user = create_user({'email': 'test@example.com', 'password': 'pass'})

    # When they login with correct credentials
    token = login('test@example.com', 'pass')

    # Then they receive a valid token
    assert token is not None
    assert verify_token(token) == user.id
```

## Next Steps

- **[Bug Fixing](bug-fixing.md)** - Fix bugs found by tests
- **[Refactoring](refactoring.md)** - Refactor with test safety net
- **[CI/CD Integration](../ci-cd/github-actions/)** - Automate testing
