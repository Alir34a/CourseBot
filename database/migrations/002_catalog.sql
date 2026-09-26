-- 002: multi-course catalog + course-scoped offers (applied once via schema_version).
ALTER TABLE users ADD COLUMN current_course_id INTEGER REFERENCES courses(id);
ALTER TABLE offers ADD COLUMN course_id INTEGER REFERENCES courses(id);
CREATE INDEX IF NOT EXISTS idx_users_current_course ON users(current_course_id);
CREATE INDEX IF NOT EXISTS idx_offers_course ON offers(course_id);
