# Playbook 05: Integration - E2E Multi-Service Application

## Level: Integration / End-to-End

## Goal
Implement a multi-service distributed application with networking, state management, message passing, and comprehensive E2E testing.

## Initial State
- Multi-project structure
- Service interfaces defined
- Docker Compose configuration
- Integration test framework

## Task
Implement a distributed e-commerce system with the following services:

### **Services:**

1. **User Service** (user-service/):
   - User registration and authentication
   - Profile management
   - gRPC/REST API
   - PostgreSQL database

2. **Product Service** (product-service/):
   - Product catalog management
   - Inventory tracking
   - Category management
   - Elasticsearch for search

3. **Order Service** (order-service/):
   - Order creation and management
   - Payment processing integration
   - Order status tracking
   - MongoDB for orders

4. **Notification Service** (notification-service/):
   - Email notifications (SMTP)
   - Push notifications
   - Webhook delivery
   - RabbitMQ message queue

5. **API Gateway** (api-gateway/):
   - Service routing and load balancing
   - Request aggregation
   - Authentication/authorization
   - Rate limiting

### **Infrastructure:**

1. **Message Queue** (RabbitMQ):
   - Async event publishing/consuming
   - Event types: OrderCreated, OrderStatusChanged, PaymentFailed

2. **Service Discovery** (Consul or custom):
   - Service registration
   - Health checks
   - Load balancing

3. **Monitoring** (Prometheus + Grafana):
   - Metrics collection
   - Service health dashboard
   - Alerting rules

4. **Logging** (ELK Stack):
   - Centralized logging
   - Log aggregation
   - Search and visualization

### **E2E Test Scenarios:**

1. **User Registration to Purchase Flow**:
   - Register user → Login → Browse products → Add to cart → Create order → Payment confirmation → Email notification

2. **Order Status Tracking**:
   - Create order → Process payment → Ship product → Deliver → Mark complete

3. **Concurrent Orders**:
   - Multiple users creating orders simultaneously with stock validation

4. **Failure Scenarios**:
   - Payment failure → Order cancellation
   - Out of stock → Waitlist handling
   - Service unavailability → Graceful degradation

5. **Performance Testing**:
   - Load test with 1000+ concurrent users
   - Measure latency, throughput, error rates

## Constraints
- All services must be containerized (Docker)
- Use gRPC for inter-service communication
- Implement circuit breakers for service-to-service calls
- Implement retry policies with exponential backoff
- All API calls must be traced (Distributed tracing)
- Implement idempotency for critical operations (order creation, payment)

## Success Criteria
- All E2E test scenarios pass
- Services can scale horizontally
- System handles 1000+ concurrent requests
- End-to-end latency < 500ms for 95th percentile
- Zero data loss during failures
- System can recover from service outages

## Validation

### **Start services:**
```bash
docker-compose up -d
docker-compose logs -f
```

### **Run E2E tests:**
```bash
pytest tests/e2e/ -v --tb=short
```

### **Load test:**
```bash
k6 run tests/load_test.js
```

### **Health check:**
```bash
# Check all services
./scripts/health-check.sh

# Check service dependencies
curl http://localhost:3001/health
curl http://localhost:3002/health
curl http://localhost:3003/health
curl http://localhost:3004/health
curl http://localhost:8080/health
```

## Expected File Structure
```
05_integration_e2e_multi_service/
├── README.md
├── docker-compose.yml
├── scripts/
│   ├── build.sh
│   ├── deploy.sh
│   └── health-check.sh
├── shared/
│   ├── proto/
│   │   ├── user.proto
│   │   ├── product.proto
│   │   └── order.proto
│   └── common/
│       └── exceptions.py
├── user-service/
│   ├── main.py
│   ├── models/
│   ├── api/
│   ├── repository/
│   └── Dockerfile
├── product-service/
│   ├── main.py
│   ├── models/
│   ├── api/
│   ├── repository/
│   └── Dockerfile
├── order-service/
│   ├── main.py
│   ├── models/
│   ├── api/
│   ├── repository/
│   └── Dockerfile
├── notification-service/
│   ├── main.py
│   ├── email/
│   ├── webhook/
│   └── Dockerfile
├── api-gateway/
│   ├── main.py
│   ├── middleware/
│   ├── routing/
│   └── Dockerfile
├── monitoring/
│   ├── prometheus.yml
│   └── grafana-dashboard.json
└── tests/
    ├── unit/
    ├── integration/
    ├── e2e/
    │   ├── test_user_registration_to_purchase.py
    │   ├── test_order_tracking.py
    │   ├── test_concurrent_orders.py
    │   └── test_failure_scenarios.py
    └── load_test.js
```

## Key Technical Challenges

1. **Distributed Transactions**:
   - Implement Saga pattern for order creation
   - Compensating transactions for failures

2. **Eventual Consistency**:
   - Handle out-of-order events
   - Event replay mechanism

3. **Service-to-Service Communication**:
   - Implement retry with backoff
   - Circuit breaker for failing services
   - Timeout handling

4. **Observability**:
   - Distributed tracing across all services
   - Correlation IDs for request tracking
   - Metrics collection and alerting

5. **Data Consistency**:
   - Eventual consistency across services
   - Database migrations without downtime
   - Backup and recovery strategies