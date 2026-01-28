#!/usr/bin/env python3
"""
Tests for the shopping cart system.
"""

import pytest
import threading
from product import Product
from cart import ShoppingCart, CartItem
from exceptions import OutOfStockError, ItemNotFoundError, InvalidQuantityError


class TestProduct:
    """Test Product class."""

    def test_product_initialization(self):
        """Test creating a valid product."""
        product = Product(id=1, name="Test Product", price=10.99, stock_quantity=100)
        assert product.id == 1
        assert product.name == "Test Product"
        assert product.price == 10.99
        assert product.stock_quantity == 100

    def test_product_validate_negative_price(self):
        """Test that negative price raises ValueError."""
        product = Product(id=1, name="Test", price=-10.0, stock_quantity=10)
        with pytest.raises(ValueError, match="price"):
            product.validate()

    def test_product_validate_negative_stock(self):
        """Test that negative stock raises ValueError."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=-5)
        with pytest.raises(ValueError, match="stock"):
            product.validate()

    def test_product_validate_valid(self):
        """Test validation passes for valid product."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        assert product.validate() is True

    def test_product_apply_discount_valid(self):
        """Test applying valid discount."""
        product = Product(id=1, name="Test", price=100.0, stock_quantity=10)
        product.apply_discount(10.0)
        assert product.price == 90.0

    def test_product_apply_discount_invalid(self):
        """Test applying invalid discount."""
        product = Product(id=1, name="Test", price=100.0, stock_quantity=10)
        with pytest.raises(ValueError):
            product.apply_discount(-10.0)
        with pytest.raises(ValueError):
            product.apply_discount(101.0)

    def test_product_is_in_stock_true(self):
        """Test in stock when quantity available."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        assert product.is_in_stock(5) is True
        assert product.is_in_stock(10) is True

    def test_product_is_in_stock_false(self):
        """Test not in stock when quantity exceeds stock."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        assert product.is_in_stock(11) is False

    def test_product_is_in_stock_negative_quantity(self):
        """Test in stock with negative quantity raises error."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        with pytest.raises(ValueError):
            product.is_in_stock(-1)


class TestCartItem:
    """Test CartItem class."""

    def test_cart_item_subtotal(self):
        """Test cart item subtotal calculation."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        item = CartItem(product, quantity=3)
        assert item.subtotal == 30.0


class TestShoppingCart:
    """Test ShoppingCart class."""

    def test_cart_initialization(self):
        """Test creating empty cart."""
        cart = ShoppingCart()
        assert cart.is_empty() is True
        assert cart.get_total() == 0.0

    def test_cart_add_item(self):
        """Test adding item to cart."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        cart = ShoppingCart()
        cart.add_item(product, 3)
        assert cart.is_empty() is False
        assert cart.get_item_count(1) == 3

    def test_cart_add_item_invalid_quantity(self):
        """Test adding item with invalid quantity."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        cart = ShoppingCart()
        with pytest.raises(InvalidQuantityError):
            cart.add_item(product, 0)
        with pytest.raises(InvalidQuantityError):
            cart.add_item(product, -1)

    def test_cart_add_item_out_of_stock(self):
        """Test adding item exceeds stock."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=5)
        cart = ShoppingCart()
        with pytest.raises(OutOfStockError):
            cart.add_item(product, 10)

    def test_cart_add_same_item_twice(self):
        """Test adding same item increments quantity."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        cart = ShoppingCart()
        cart.add_item(product, 2)
        cart.add_item(product, 3)
        assert cart.get_item_count(1) == 5

    def test_cart_remove_item(self):
        """Test removing item from cart."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        cart = ShoppingCart()
        cart.add_item(product, 5)
        cart.remove_item(1, 2)
        assert cart.get_item_count(1) == 3

    def test_cart_remove_item_not_found(self):
        """Test removing non-existent item."""
        cart = ShoppingCart()
        with pytest.raises(ItemNotFoundError):
            cart.remove_item(999, 1)

    def test_cart_remove_item_invalid_quantity(self):
        """Test removing invalid quantity."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        cart = ShoppingCart()
        cart.add_item(product, 5)
        with pytest.raises(InvalidQuantityError):
            cart.remove_item(1, 0)
        with pytest.raises(InvalidQuantityError):
            cart.remove_item(1, -1)

    def test_cart_update_quantity(self):
        """Test updating item quantity."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        cart = ShoppingCart()
        cart.add_item(product, 2)
        cart.update_quantity(1, 5)
        assert cart.get_item_count(1) == 5

    def test_cart_update_quantity_to_zero_removes(self):
        """Test updating quantity to zero removes item."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        cart = ShoppingCart()
        cart.add_item(product, 5)
        cart.update_quantity(1, 0)
        assert cart.is_empty() is True

    def test_cart_update_quantity_out_of_stock(self):
        """Test updating quantity exceeds stock."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=5)
        cart = ShoppingCart()
        cart.add_item(product, 2)
        with pytest.raises(OutOfStockError):
            cart.update_quantity(1, 10)

    def test_cart_get_total(self):
        """Test calculating cart total."""
        product1 = Product(id=1, name="Test1", price=10.0, stock_quantity=10)
        product2 = Product(id=2, name="Test2", price=20.0, stock_quantity=10)
        cart = ShoppingCart()
        cart.add_item(product1, 2)
        cart.add_item(product2, 3)
        assert cart.get_total() == 80.0

    def test_cart_clear(self):
        """Test clearing cart."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=10)
        cart = ShoppingCart()
        cart.add_item(product, 5)
        cart.clear()
        assert cart.is_empty() is True
        assert cart.get_total() == 0.0

    def test_cart_get_items(self):
        """Test getting all items."""
        product1 = Product(id=1, name="Test1", price=10.0, stock_quantity=10)
        product2 = Product(id=2, name="Test2", price=20.0, stock_quantity=10)
        cart = ShoppingCart()
        cart.add_item(product1, 2)
        cart.add_item(product2, 3)
        items = cart.get_items()
        assert len(items) == 2

    def test_cart_get_item_count_total(self):
        """Test getting total item count."""
        product1 = Product(id=1, name="Test1", price=10.0, stock_quantity=10)
        product2 = Product(id=2, name="Test2", price=20.0, stock_quantity=10)
        cart = ShoppingCart()
        cart.add_item(product1, 2)
        cart.add_item(product2, 3)
        assert cart.get_item_count_total() == 5


class TestShoppingCartThreadSafety:
    """Test ShoppingCart thread safety."""

    def test_concurrent_add_items(self):
        """Test adding items from multiple threads."""
        product = Product(id=1, name="Test", price=10.0, stock_quantity=100)
        cart = ShoppingCart()

        def add_items():
            for _ in range(10):
                cart.add_item(product, 1)

        threads = [threading.Thread(target=add_items) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert cart.get_item_count(1) == 50
        assert cart.get_total() == 500.0