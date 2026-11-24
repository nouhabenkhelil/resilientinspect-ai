"""One-time least-privilege provisioning with no password in process arguments/logs."""
import os
from pathlib import Path
import psycopg
from psycopg import sql


def main():
    password = Path('/run/secrets/observer_password').read_text().strip()
    if len(password) < 43: raise RuntimeError('Strong observer credential required')
    url = os.environ['MIGRATION_DATABASE_URL'].replace('postgresql+psycopg:', 'postgresql:', 1)
    try:
        with psycopg.connect(url) as db:
            db.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='ri_observer') THEN CREATE ROLE ri_observer LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT; END IF; END $$")
            db.execute(sql.SQL('ALTER ROLE ri_observer PASSWORD {}').format(sql.Literal(password)))
            db.execute('GRANT CONNECT ON DATABASE portal TO ri_observer')
            db.execute('GRANT USAGE ON SCHEMA public TO ri_observer')
            db.execute('GRANT SELECT ON inspection_batches,batch_items,batch_events,service_heartbeats TO ri_observer')
        print('Read-only observer role provisioned; credential withheld.')
    except Exception:
        raise SystemExit('Observer provisioning failed; details withheld') from None


if __name__ == '__main__': main()
