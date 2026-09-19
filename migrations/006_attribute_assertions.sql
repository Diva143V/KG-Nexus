-- Migration 006: Add AttributeAssertion columns to assertions table
--
-- Extends the assertions table to support literal AttributeAssertion instances
-- alongside relational Assertion instances.
--
-- Columns added:
--   - literal_value: TEXT representing canonical literal serialization
--   - literal_datatype: TEXT storing LiteralType enum string ('string', 'integer', 'float', 'boolean', 'datetime')
--   - assertion_kind: TEXT NOT NULL DEFAULT 'relational' ('relational' or 'attribute')
--
-- Constraint handling:
--   Existing assertions table has object_id TEXT NOT NULL.
--   Attribute assertions store an empty string sentinel "" for object_id, avoiding table recreation
--   and preventing FOREIGN KEY errors during migration under active transactions.

ALTER TABLE assertions ADD COLUMN literal_value TEXT;
ALTER TABLE assertions ADD COLUMN literal_datatype TEXT;
ALTER TABLE assertions ADD COLUMN assertion_kind TEXT NOT NULL DEFAULT 'relational';

CREATE INDEX IF NOT EXISTS idx_assertions_kind ON assertions(assertion_kind);
