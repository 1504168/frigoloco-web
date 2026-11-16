-- ============================================================================
-- Migration 0026 - supplier payment terms, agreements and delivery schedule;
-- product tags, client rules and fridge delivery window; equipment register
-- ============================================================================
-- suppliers.payment_terms_days / payment_terms_end_of_month: payment conditions
-- (30 or 60 days, optionally counted from the end of the invoice month).
-- supplier_agreements: yearly negotiated discount (year-end rebate or price
-- discount) with a review date. Reference data only: no price or P&L effect.
-- supplier_delivery_schedules: one row per delivery weekday with the order
-- cutoff weekday and time (e.g. Monday delivery, order by Friday 12:00).
-- product_tags: dietary / content tags (contains_pork, vegan, ...).
-- client_rules: per client (fridge_id NULL) or per fridge: exclude products
-- with a tag, or a free note. The menu only warns, it never blocks.
-- fridges.delivery_time_from / delivery_time_to / night_delivery_ok: delivery
-- window; from > to means a window across midnight. Local-only.
-- equipment: register of coffee machines, water filters, vending machines.
-- Reference data only: monthly_fee_cents is NOT added to finance (see the
-- open question vs client_fees).
--
-- Idempotent: re-running is a no-op.
-- ============================================================================

BEGIN;

ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS payment_terms_days INTEGER;
ALTER TABLE suppliers
    ADD COLUMN IF NOT EXISTS payment_terms_end_of_month BOOLEAN NOT NULL DEFAULT FALSE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_suppliers_payment_terms_days_nonneg'
    ) THEN
        ALTER TABLE suppliers
            ADD CONSTRAINT chk_suppliers_payment_terms_days_nonneg
            CHECK (payment_terms_days >= 0);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS supplier_agreements (
    id            INTEGER       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_id   INTEGER       NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    year          INTEGER       NOT NULL,
    -- A percentage, 2.5 = 2.5 %.
    discount_pct  NUMERIC(5,2)  NOT NULL
                                CONSTRAINT chk_supplier_agreements_discount_pct_range
                                CHECK (discount_pct >= 0 AND discount_pct <= 100),
    basis         TEXT          NOT NULL
                                CONSTRAINT chk_supplier_agreements_basis
                                CHECK (basis IN ('year_end_rebate', 'price_discount')),
    review_date   DATE,
    notes         TEXT,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS supplier_delivery_schedules (
    supplier_id       INTEGER   NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    delivery_weekday  SMALLINT  NOT NULL
                                CONSTRAINT chk_supplier_delivery_schedules_delivery_weekday_iso
                                CHECK (delivery_weekday BETWEEN 1 AND 7),
    -- Same weekday as the delivery = order the same day before cutoff_time.
    cutoff_weekday    SMALLINT  NOT NULL
                                CONSTRAINT chk_supplier_delivery_schedules_cutoff_weekday_iso
                                CHECK (cutoff_weekday BETWEEN 1 AND 7),
    cutoff_time       TIME      NOT NULL,
    PRIMARY KEY (supplier_id, delivery_weekday)
);

CREATE TABLE IF NOT EXISTS product_tags (
    product_id  INTEGER  NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    tag         TEXT     NOT NULL
                         CONSTRAINT chk_product_tags_tag_format
                         CHECK (tag ~ '^[a-z0-9_]+$'),
    PRIMARY KEY (product_id, tag)
);

CREATE TABLE IF NOT EXISTS client_rules (
    id          INTEGER      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id   INTEGER      NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    -- NULL = the rule applies to every fridge of the client.
    fridge_id   INTEGER      REFERENCES fridges(id) ON DELETE CASCADE,
    rule_type   TEXT         NOT NULL
                             CONSTRAINT chk_client_rules_rule_type
                             CHECK (rule_type IN ('exclude_tag', 'note')),
    tag         TEXT,
    note        TEXT,
    valid_from  DATE,
    valid_to    DATE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT chk_client_rules_exclude_tag_has_tag
        CHECK (rule_type <> 'exclude_tag' OR tag IS NOT NULL),
    CONSTRAINT chk_client_rules_valid_range
        CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

ALTER TABLE fridges ADD COLUMN IF NOT EXISTS delivery_time_from TIME;
ALTER TABLE fridges ADD COLUMN IF NOT EXISTS delivery_time_to TIME;
ALTER TABLE fridges ADD COLUMN IF NOT EXISTS night_delivery_ok BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS equipment (
    id                       INTEGER       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    machine_type             TEXT          NOT NULL,
    equipment_category       TEXT          NOT NULL
                                           CONSTRAINT chk_equipment_category
                                           CHECK (equipment_category IN
                                               ('coffee', 'water_filter', 'vending', 'fridge', 'other')),
    machine_code             TEXT          NOT NULL UNIQUE,
    supplier_id              INTEGER       REFERENCES suppliers(id),
    client_id                INTEGER       REFERENCES clients(id),
    fridge_id                INTEGER       REFERENCES fridges(id),
    ownership                TEXT          NOT NULL
                                           CONSTRAINT chk_equipment_ownership
                                           CHECK (ownership IN ('bought', 'rent')),
    purchase_price_cents     BIGINT        CONSTRAINT chk_equipment_purchase_price_nonneg
                                           CHECK (purchase_price_cents >= 0),
    -- What we pay the supplier each month for a rented machine.
    monthly_rent_cost_cents  BIGINT        CONSTRAINT chk_equipment_monthly_rent_cost_nonneg
                                           CHECK (monthly_rent_cost_cents >= 0),
    -- What we charge the client each month for this machine.
    monthly_fee_cents        BIGINT        CONSTRAINT chk_equipment_monthly_fee_nonneg
                                           CHECK (monthly_fee_cents >= 0),
    purchase_date            DATE,
    financing_years          INTEGER       CONSTRAINT chk_equipment_financing_years_positive
                                           CHECK (financing_years > 0),
    -- A fraction, 0.04 = 4 %.
    financing_rate           NUMERIC(6,4)  CONSTRAINT chk_equipment_financing_rate_fraction
                                           CHECK (financing_rate >= 0 AND financing_rate < 1),
    financed_by              TEXT,
    is_active                BOOLEAN       NOT NULL DEFAULT TRUE,
    notes                    TEXT,
    created_at               TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_supplier_agreements_supplier
    ON supplier_agreements (supplier_id, year);
CREATE INDEX IF NOT EXISTS ix_product_tags_tag
    ON product_tags (tag);
CREATE INDEX IF NOT EXISTS ix_client_rules_client
    ON client_rules (client_id);
CREATE INDEX IF NOT EXISTS ix_equipment_client
    ON equipment (client_id);

COMMIT;
