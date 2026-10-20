-- Yarlagadda Feeds Factory Management Schema (PostgreSQL)
-- Currency: INR | Single factory | Own fish tanks

CREATE EXTENSION IF NOT EXISTS "pgcrypto";


-- ---------------------------------------------------------------------------
-- Master: material types & suppliers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS material_types (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128) NOT NULL UNIQUE,
    unit            VARCHAR(32) NOT NULL DEFAULT 'tonne', -- tonne, kg, bag, etc.
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS suppliers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128) NOT NULL,
    phone           VARCHAR(32),
    address         TEXT,
    notes           TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Raw material purchases & inventory
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS material_purchases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    supplier_id     UUID NOT NULL REFERENCES suppliers(id),
    material_type_id UUID NOT NULL REFERENCES material_types(id),
    purchase_date   DATE NOT NULL,
    quantity        NUMERIC(14, 3) NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(14, 2) NOT NULL CHECK (unit_price >= 0),
    total_amount    NUMERIC(14, 2) NOT NULL CHECK (total_amount >= 0),
    paid_amount     NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (paid_amount >= 0),
    balance_amount  NUMERIC(14, 2) NOT NULL DEFAULT 0,
    payment_status  VARCHAR(32) NOT NULL DEFAULT 'unpaid'
        CHECK (payment_status IN ('unpaid', 'partial', 'paid')),
    invoice_ref     VARCHAR(64),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS material_payments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purchase_id     UUID NOT NULL REFERENCES material_purchases(id) ON DELETE CASCADE,
    payment_date    DATE NOT NULL,
    amount          NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    payment_mode    VARCHAR(32) NOT NULL DEFAULT 'cash'
        CHECK (payment_mode IN ('cash', 'upi', 'bank', 'cheque', 'other')),
    reference_no    VARCHAR(64),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS material_inventory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_type_id UUID NOT NULL UNIQUE REFERENCES material_types(id),
    quantity_on_hand NUMERIC(14, 3) NOT NULL DEFAULT 0 CHECK (quantity_on_hand >= 0),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory_transactions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_type_id UUID NOT NULL REFERENCES material_types(id),
    txn_type        VARCHAR(32) NOT NULL
        CHECK (txn_type IN ('purchase_in', 'feed_out', 'adjustment', 'wastage')),
    quantity        NUMERIC(14, 3) NOT NULL,
    reference_type  VARCHAR(64),
    reference_id    UUID,
    notes           TEXT,
    txn_date        DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Labour & salary
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS labourers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128) NOT NULL,
    phone           VARCHAR(32),
    role_title      VARCHAR(64),
    monthly_wage    NUMERIC(14, 2) NOT NULL DEFAULT 0,
    join_date       DATE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS labour_advances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    labourer_id     UUID NOT NULL REFERENCES labourers(id),
    advance_date    DATE NOT NULL,
    amount          NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    advance_type    VARCHAR(32) NOT NULL DEFAULT 'weekly'
        CHECK (advance_type IN ('weekly', 'adhoc', 'festival', 'other')),
    salary_month    DATE NOT NULL, -- first day of month this advance applies to
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS labour_salary_payments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    labourer_id     UUID NOT NULL REFERENCES labourers(id),
    salary_month    DATE NOT NULL, -- first day of month
    gross_wage      NUMERIC(14, 2) NOT NULL,
    advances_deducted NUMERIC(14, 2) NOT NULL DEFAULT 0,
    net_paid        NUMERIC(14, 2) NOT NULL,
    payment_date    DATE NOT NULL,
    payment_mode    VARCHAR(32) NOT NULL DEFAULT 'cash',
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (labourer_id, salary_month)
);

-- ---------------------------------------------------------------------------
-- Fish tanks, catch events, vehicle sales
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fish_tanks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128) NOT NULL UNIQUE,
    location        VARCHAR(128),
    capacity_notes  TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fish_types (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128) NOT NULL UNIQUE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS buyers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128) NOT NULL,
    phone           VARCHAR(32),
    address         TEXT,
    notes           TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One catching event per tank / period (every 3, 4, or 6 months)
CREATE TABLE IF NOT EXISTS catch_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tank_id         UUID NOT NULL REFERENCES fish_tanks(id),
    catch_start_date DATE NOT NULL,
    catch_end_date  DATE,
    cycle_months    SMALLINT CHECK (cycle_months IN (3, 4, 6) OR cycle_months IS NULL),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS catch_vehicle_sales (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    catch_event_id  UUID NOT NULL REFERENCES catch_events(id) ON DELETE CASCADE,
    buyer_id        UUID REFERENCES buyers(id),
    vehicle_number  VARCHAR(64) NOT NULL,
    sale_date       DATE NOT NULL,
    driver_name     VARCHAR(128),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS catch_sale_line_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vehicle_sale_id UUID NOT NULL REFERENCES catch_vehicle_sales(id) ON DELETE CASCADE,
    fish_type_id    UUID NOT NULL REFERENCES fish_types(id),
    weight_kg       NUMERIC(14, 3) NOT NULL CHECK (weight_kg >= 0),
    fish_count      INTEGER NOT NULL DEFAULT 0 CHECK (fish_count >= 0),
    rate_per_kg     NUMERIC(14, 2) NOT NULL CHECK (rate_per_kg >= 0),
    line_amount     NUMERIC(14, 2) NOT NULL CHECK (line_amount >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Feed preparation (inventory out → tanks)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feed_batches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_date      DATE NOT NULL,
    total_qty_kg    NUMERIC(14, 3) NOT NULL DEFAULT 0,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feed_batch_materials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id        UUID NOT NULL REFERENCES feed_batches(id) ON DELETE CASCADE,
    material_type_id UUID NOT NULL REFERENCES material_types(id),
    quantity_used   NUMERIC(14, 3) NOT NULL CHECK (quantity_used > 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS feed_tank_deliveries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id        UUID NOT NULL REFERENCES feed_batches(id) ON DELETE CASCADE,
    tank_id         UUID NOT NULL REFERENCES fish_tanks(id),
    quantity_kg     NUMERIC(14, 3) NOT NULL CHECK (quantity_kg > 0),
    delivery_date   DATE NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Expenses, income, investments (monthly tracking)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expense_categories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(128) NOT NULL UNIQUE,
    is_system       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS expenses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id     UUID REFERENCES expense_categories(id),
    expense_date    DATE NOT NULL,
    amount          NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    description     TEXT,
    source_module   VARCHAR(64), -- material_payment, labour_salary, manual, etc.
    source_id       UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS incomes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    income_date     DATE NOT NULL,
    amount          NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    description     TEXT,
    source_module   VARCHAR(64), -- catch_sale, manual, etc.
    source_id       UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS investments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investment_date DATE NOT NULL,
    amount          NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    investor_name   VARCHAR(128),
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_purchases_date ON material_purchases(purchase_date);
CREATE INDEX IF NOT EXISTS idx_purchases_supplier ON material_purchases(supplier_id);
CREATE INDEX IF NOT EXISTS idx_payments_purchase ON material_payments(purchase_id);
CREATE INDEX IF NOT EXISTS idx_advances_labour_month ON labour_advances(labourer_id, salary_month);
CREATE INDEX IF NOT EXISTS idx_catch_events_tank ON catch_events(tank_id);
CREATE INDEX IF NOT EXISTS idx_vehicle_sales_event ON catch_vehicle_sales(catch_event_id);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_incomes_date ON incomes(income_date);

-- Seed expense categories
INSERT INTO expense_categories (name, is_system) VALUES
    ('Raw Material', TRUE),
    ('Labour Salary', TRUE),
    ('Labour Advance', TRUE),
    ('Utilities', FALSE),
    ('Transport', FALSE),
    ('Maintenance', FALSE),
    ('Other', FALSE)
ON CONFLICT (name) DO NOTHING;
