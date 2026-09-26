-- 003: episode cover media (shown at episode entry + review list header).
ALTER TABLE episodes ADD COLUMN cover_kind TEXT;
ALTER TABLE episodes ADD COLUMN cover_file_id TEXT;
