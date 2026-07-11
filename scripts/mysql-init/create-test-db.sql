-- Runs once on a fresh MySQL volume (docker-entrypoint-initdb.d).
-- The integration suite runs against an isolated crate_test database that the
-- test fixture creates and migrates itself; the crate user needs rights on it.
CREATE DATABASE IF NOT EXISTS crate_test;
GRANT ALL PRIVILEGES ON `crate_test`.* TO 'crate'@'%';
FLUSH PRIVILEGES;
