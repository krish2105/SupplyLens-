-- Container bootstrap: roles mirror scripts/dev_db.sh. Dev-only passwords; override via secrets in real deployments.
CREATE ROLE supplylens_owner LOGIN PASSWORD 'supplylens_owner_dev';
CREATE ROLE supplylens_app LOGIN PASSWORD 'supplylens_app_dev' NOBYPASSRLS;
CREATE DATABASE supplylens OWNER supplylens_owner;
\c supplylens
CREATE EXTENSION IF NOT EXISTS vector;
GRANT CONNECT ON DATABASE supplylens TO supplylens_app;
