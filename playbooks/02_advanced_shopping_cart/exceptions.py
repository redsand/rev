"""
Custom exceptions for the shopping cart system.
"""


class ShoppingcartError(Exception):
    """Base exception for shopping cart errors."""
    pass


class OutOfStockError(ShoppingcartError):
    """Raised when attempting to add more items than available in stock."""

    def __init__(self, product_name: str, requested: int, available: int):
        self.product_name = product_name
        self.requested = requested
        self.available = available
        super().__init__(
            f"Out of stock: {product_name}. Requested: {requested}, Available: {available}"
        )


class ItemNotFoundError(ShoppingcartError):
    """Raised when attempting to modify a non-existent cart item."""

    def __init__(self, product_id: int):
        self.product_id = product_id
        super().__init__(f"Item not found in cart: product_id={product_id}")


class InvalidQuantityError(ShoppingcartError):
    """Raised when an invalid quantity is provided."""

    def __init__(self, message: str):
        super().__init__(message)