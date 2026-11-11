CREATE TABLE IF NOT EXISTS restaurants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  currency TEXT NOT NULL DEFAULT 'USD',
  currency_symbol TEXT NOT NULL DEFAULT '$',
  currency_decimals INTEGER NOT NULL DEFAULT 2,
  tax_rate REAL NOT NULL DEFAULT 0,
  service_charge_rate REAL NOT NULL DEFAULT 0,
  tz_offset_minutes INTEGER NOT NULL DEFAULT 0,
  address TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('owner','manager','cashier','waiter','kitchen')),
  active INTEGER NOT NULL DEFAULT 1,
  token_version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_restaurant ON users(restaurant_id);

CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE (restaurant_id, name)
);

CREATE TABLE IF NOT EXISTS menu_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  price BIGINT NOT NULL CHECK (price >= 0),
  available INTEGER NOT NULL DEFAULT 1,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_menu_restaurant_cat ON menu_items(restaurant_id, category_id);

CREATE TABLE IF NOT EXISTS dining_tables (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  capacity INTEGER NOT NULL CHECK (capacity > 0),
  status TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available','occupied','reserved')),
  UNIQUE (restaurant_id, label)
);

CREATE TABLE IF NOT EXISTS reservations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  table_id INTEGER NOT NULL REFERENCES dining_tables(id),
  customer_name TEXT NOT NULL,
  phone TEXT NOT NULL DEFAULT '',
  party_size INTEGER NOT NULL CHECK (party_size > 0),
  reserved_for TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','seated','cancelled','completed')),
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resv_restaurant_time ON reservations(restaurant_id, reserved_for);
CREATE INDEX IF NOT EXISTS idx_resv_table ON reservations(table_id);

CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  table_id INTEGER REFERENCES dining_tables(id),
  waiter_id INTEGER NOT NULL REFERENCES users(id),
  order_type TEXT NOT NULL CHECK (order_type IN ('dine_in','takeaway')),
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','preparing','ready','served','paid','cancelled')),
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_restaurant_status ON orders(restaurant_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_restaurant_created ON orders(restaurant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_table ON orders(table_id);

CREATE TABLE IF NOT EXISTS order_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  menu_item_id INTEGER NOT NULL REFERENCES menu_items(id),
  name TEXT NOT NULL,
  unit_price BIGINT NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_menu ON order_items(menu_item_id);

CREATE TABLE IF NOT EXISTS bills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  restaurant_id INTEGER NOT NULL REFERENCES restaurants(id) ON DELETE CASCADE,
  order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
  seq INTEGER NOT NULL,
  number TEXT NOT NULL,
  subtotal BIGINT NOT NULL,
  discount_type TEXT NOT NULL DEFAULT 'none',
  discount_value REAL NOT NULL DEFAULT 0,
  discount BIGINT NOT NULL DEFAULT 0,
  tax_rate REAL NOT NULL DEFAULT 0,
  tax BIGINT NOT NULL DEFAULT 0,
  service_rate REAL NOT NULL DEFAULT 0,
  service_charge BIGINT NOT NULL DEFAULT 0,
  total BIGINT NOT NULL,
  payment_method TEXT NOT NULL CHECK (payment_method IN ('cash','card','upi','other')),
  amount_tendered BIGINT NOT NULL DEFAULT 0,
  change_due BIGINT NOT NULL DEFAULT 0,
  paid_at TEXT NOT NULL,
  created_by INTEGER NOT NULL REFERENCES users(id),
  UNIQUE (restaurant_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_bills_restaurant_paid ON bills(restaurant_id, paid_at);

CREATE TABLE IF NOT EXISTS revoked_tokens (
  jti TEXT PRIMARY KEY,
  expires_at INTEGER NOT NULL
);
