"""
Shopping cart module.

Implements the ShoppingCart class with thread-safe operations.
"""

import threading
from typing import Dict, List
from product import Product
from exceptions import OutOfStockError, ItemNotFoundError, InvalidQuantityError


class CartItem:
    """Represents an item in the shopping cart."""

    def __init__(self, product: Product, quantity: int):
        self.product = product
        self.quantity = quantity

    @property
    def subtotal(self) -> float:
        """Calculate subtotal for this item."""
        # TODO: Implement
        pass


class ShoppingCart:
    """Thread-safe shopping cart implementation."""

    def __init__(self):
        """Initialize an empty shopping cart."""
        # TODO: Implement
        pass

    def add_item(self, product: Product, quantity: int) -> None:
        """Add an item to the cart.

        Args:
            product: The product to add
            quantity: Quantity to add

        Raises:
            InvalidQuantityError: If quantity is <= 0
            OutOfStockError: If insufficient stock
        """
        # TODO: Implement with thread locking
        pass

    def remove_item(self, product_id: int, quantity: int) -> None:
        """Remove items from the cart.

        Args:
            product_id: ID of the product to remove
            quantity: Quantity to remove

        Raises:
            InvalidQuantityError: If quantity is <= 0
            ItemNotFoundError: If item not in cart
        """
        # TODO: Implement with thread locking
        pass

    def update_quantity(self, product_id: int, quantity: int) -> None:
        """Update the quantity of a cart item.

        Args:
            product_id: ID of the product
            quantity: New quantity (0 removes the item)

        Raises:
            InvalidQuantityError: If quantity is negative
            ItemNotFoundError: If item not in cart
            OutOfStockError: If new quantity exceeds available stock
        """
        # TODO: Implement with thread locking
        pass

    def get_total(self) -> float:
        """Calculate the total price of all items in the cart.

        Returns:
            Total price
        """
        # TODO: Implement
        pass

    def get_item_count(self, product_id: int) -> int:
        """Get the quantity of a specific item in the cart.

        Args:
            product_id: ID of the product

        Returns:
            Quantity in cart (0 if not found)
        """
        # TODO: Implement
        pass

    def get_items(self) -> List[CartItem]:
        """Get all items in the cart.

        Returns:
            List of cart items
        """
        # TODO: Implement
        pass

    def clear(self) -> None:
        """Clear all items from the cart."""
        # TODO: Implement
        pass

    def is_empty(self) -> bool:
        """Check if the cart is empty.

        Returns:
            True if cart has no items
        """
        # TODO: Implement
        pass

    def get_item_count_total(self) -> int:
        """Get the total number of items in the cart.

        Returns:
            Total quantity of all items
        """
        # TODO: Implement
        pass