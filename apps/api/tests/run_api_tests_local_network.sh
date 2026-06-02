#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
API_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

cd "$API_DIR"
mkdir -p plane/static-assets/collected-static

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-plane.settings.test}
export POSTGRES_HOST=${POSTGRES_HOST:-plane-db}
export POSTGRES_PORT=${POSTGRES_PORT:-5432}
export POSTGRES_USER=${POSTGRES_USER:-plane}
export POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-plane}
BASE_DATABASE_NAME=${POSTGRES_DB:-plane}
export POSTGRES_DB=$BASE_DATABASE_NAME
export REDIS_HOST=${REDIS_HOST:-plane-redis}
export REDIS_URL=${REDIS_URL:-redis://plane-redis:6379/}
export RABBITMQ_HOST=${RABBITMQ_HOST:-plane-mq}
export RABBITMQ_PORT=${RABBITMQ_PORT:-5672}
export RABBITMQ_USER=${RABBITMQ_USER:-plane}
export RABBITMQ_PASSWORD=${RABBITMQ_PASSWORD:-plane}
export RABBITMQ_VHOST=${RABBITMQ_VHOST:-plane}
export AWS_S3_ENDPOINT_URL=${AWS_S3_ENDPOINT_URL:-http://plane-minio:9000}
export EMAIL_HOST=${EMAIL_HOST:-test-smtp.invalid}

TEST_DATABASE_NAME=${TEST_DATABASE_NAME:-test_${BASE_DATABASE_NAME}}
TEMPLATE_DATABASE_NAME=${TEMPLATE_DATABASE_NAME:-${TEST_DATABASE_NAME}_template}
export TEST_DATABASE_NAME TEMPLATE_DATABASE_NAME

build_database_url() {
  local database_name=$1
  printf "postgresql://%s:%s@%s:%s/%s" \
    "$POSTGRES_USER" "$POSTGRES_PASSWORD" "$POSTGRES_HOST" "$POSTGRES_PORT" "$database_name"
}

APP_DATABASE_URL=$(build_database_url "$BASE_DATABASE_NAME")
TEST_DATABASE_URL=$(build_database_url "$TEST_DATABASE_NAME")
TEMPLATE_DATABASE_URL=$(build_database_url "$TEMPLATE_DATABASE_NAME")
export DATABASE_URL=$APP_DATABASE_URL

TEMPLATE_CREATED=$(python3 - <<'PY'
import os
import psycopg
from psycopg import sql

base_name = os.environ["POSTGRES_DB"]
template_name = os.environ["TEMPLATE_DATABASE_NAME"]

conn = psycopg.connect(
    host=os.environ.get("POSTGRES_HOST", "plane-db"),
    port=os.environ.get("POSTGRES_PORT", "5432"),
    user=os.environ.get("POSTGRES_USER", "plane"),
    password=os.environ.get("POSTGRES_PASSWORD", "plane"),
    dbname="postgres",
    autocommit=True,
)

with conn.cursor() as cursor:
    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (base_name,))
    if cursor.fetchone() is None:
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(base_name)))

    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (template_name,))
    if cursor.fetchone() is None:
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(template_name)))
        print("1")
    else:
        print("0")

conn.close()
PY
)

if [ "$TEMPLATE_CREATED" = "1" ]; then
  echo "Created template database $TEMPLATE_DATABASE_NAME."
else
  echo "Reusing template database $TEMPLATE_DATABASE_NAME."
fi

DATABASE_URL=$TEMPLATE_DATABASE_URL python3 manage.py migrate --noinput

python3 - <<'PY'
import os
import psycopg
from psycopg import sql

test_name = os.environ["TEST_DATABASE_NAME"]
template_name = os.environ["TEMPLATE_DATABASE_NAME"]

conn = psycopg.connect(
    host=os.environ.get("POSTGRES_HOST", "plane-db"),
    port=os.environ.get("POSTGRES_PORT", "5432"),
    user=os.environ.get("POSTGRES_USER", "plane"),
    password=os.environ.get("POSTGRES_PASSWORD", "plane"),
    dbname="postgres",
    autocommit=True,
)

with conn.cursor() as cursor:
    for database_name in (test_name, template_name):
        cursor.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
            """,
            (database_name,),
        )

    cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(test_name)))
    cursor.execute(
        sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
            sql.Identifier(test_name),
            sql.Identifier(template_name),
        )
    )
    print(f"Prepared default Django test database {test_name} from {template_name}.")

conn.close()
PY

DATABASE_URL=$TEST_DATABASE_URL python3 manage.py migrate --noinput
DATABASE_URL=$APP_DATABASE_URL pytest "$@"
