"""
Product module for the shopping cart system.

Defines the Product class with validation and discount functionality.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Product:
    """Represents a product in the inventory.

    Attributes:
        id: Unique product identifier
        name: Product name
        price: Product price in currency units
        stock_quantity: Available stock quantity
    """

    id: int
    name: str
    price: float
    stock_quantity: int

    def __post_init__(self):
        """Validate product attributes after initialization."""
        # TODO: Implement validation

    def validate(self) -> bool:
        """Validate that price >= 0 and stock >= 0.

        Returns:
            True if valid

        Raises:
            ValueError: If price is negative or stock is negative
        """
        # TODO: Implement
        pass

    def apply_discount(self, discount_percent: float) -> None:
        """Apply a discount to the product price.

        Args:
            discount_percent: Discount percentage (0-100)

        Raises:
            ValueError: If discount_percent is out of range
        """
        # TODO: Implement
        pass

    def is_in_stock(self, quantity: int) -> bool:
        """Check if the requested quantity is in stock.

        Args:
            quantity: Requested quantity

        Returns:
            True if in stock, False otherwise

        Raises:
            ValueError: If quantity is negative
        """
        # TODO: Implement
        pass