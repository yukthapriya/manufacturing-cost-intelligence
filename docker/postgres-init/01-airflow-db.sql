-- Runs once, on first start of the postgres container (empty data dir), as the
-- superuser defined by POSTGRES_USER. Creates a separate database + role for
-- Airflow metadata so it never shares a schema with the mfg_cost warehouse.
-- Dev-only credentials; must match AIRFLOW__DATABASE__SQL_ALCHEMY_CONN in .env.
CREATE ROLE airflow WITH LOGIN PASSWORD 'airflow';
CREATE DATABASE airflow OWNER airflow;
GRANT ALL PRIVILEGES ON DATABASE airflow TO airflow;
\connect airflow
-- Postgres 15 no longer grants CREATE on public to everyone.
GRANT ALL ON SCHEMA public TO airflow;
