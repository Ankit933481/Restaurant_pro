"""Independent starter menu and tables copied to each newly registered restaurant."""
from .db import db
from .util import now_iso

STARTER_CATEGORIES = (
    ('Main Course', ('Fresh Garden Bowl', 'Chicken Biryani', 'Summer Salad')),
    ('Pizza & Pasta', ('Margherita Pizza', 'Pasta Alfredo', 'Spicy Pizza')),
    ('Burgers', ('Classic Cheeseburger',)),
    ('Desserts', ('Chocolate Dessert',)),
)
STARTER_ITEMS = {
    'Fresh Garden Bowl': ('Seasonal greens, avocado and house dressing', 29900),
    'Chicken Biryani': ('Fragrant basmati rice and aromatic spices', 39900),
    'Summer Salad': ('Crisp fresh greens and citrus vinaigrette', 27900),
    'Margherita Pizza': ('Pizza with basil and mozzarella', 44900),
    'Pasta Alfredo': ('Creamy sauce and freshly cooked pasta', 37900),
    'Spicy Pizza': ('Spicy topping with melted cheese', 46900),
    'Classic Cheeseburger': ('Grilled patty with cheddar and fresh vegetables', 34900),
    'Chocolate Dessert': ('Rich chocolate with a creamy finish', 24900),
}


def seed_restaurant(restaurant_id):
    """Seed ONLY this restaurant. Runs in the registration transaction."""
    timestamp = now_iso()
    for sort_order, (category, names) in enumerate(STARTER_CATEGORIES):
        category_id = db().insert(
            'INSERT INTO categories(restaurant_id,name,sort_order) VALUES (?,?,?)',
            (restaurant_id, category, sort_order))
        for name in names:
            description, price = STARTER_ITEMS[name]
            db().insert(
                'INSERT INTO menu_items(restaurant_id,category_id,name,description,price,available,created_at) '
                'VALUES (?,?,?,?,?,?,?)',
                (restaurant_id, category_id, name, description, price, 1, timestamp))
    for i in range(1, 17):
        db().insert('INSERT INTO dining_tables(restaurant_id,label,capacity,status) VALUES (?,?,?,?)',
                    (restaurant_id, f'T{i:02d}', 6 if (i - 1) % 3 == 0 else 4, 'available'))
