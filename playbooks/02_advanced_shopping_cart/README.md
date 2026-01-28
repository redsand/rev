# Playbook 02: Advanced - Shopping Cart with Error Handling

## Level: Advanced

## Goal
Implement a shopping cart system with class-based design, error handling, and edge cases.

## Initial State
- Package structure with interfaces defined
- Empty implementations to fill in
- Tests that will pass after implementation

## Task
Implement a shopping cart system with the following components:

### `product.py`:
- `Product` class with `id`, `name`, `price`, `stock_quantity`
- `validate()` method to ensure price >= 0 and stock >= 0
- `apply_discount(discount_percent: float)` method
- `is_in_stock(quantity: int) -> bool` method

### `cart.py`:
- `ShoppingCart` class managing cart items
- `add_item(product: Product, quantity: int)` - raises `OutOfStockError` if insufficient stock
- `remove_item(product_id: int, quantity: int)` - raises `ItemNotFoundError`
- `update_quantity(product_id: int, quantity: int)` - handles all edge cases
- `get_total() -> float` - calculates cart total
- `get_item_count(product_id: int) -> int`
- `clear()` method

### `exceptions.py`:
- `OutOfStockError` exception
- `ItemNotFoundError` exception
- `InvalidQuantityError` exception

## Constraints
- All methods must have proper type hints
- All business logic must be validated with exceptions
- Use dataclasses where appropriate
- Thread-safety: cart operations should handle concurrent access (basic locking)
- Max complexity: O(n) for cart operations

## Success Criteria
- All tests pass
- Code coverage > 90%
- No linting errors
- Proper docstrings

## Validation
Run: `pytest test_shopping_cart.py -v --cov=. --cov-report=term-missing`