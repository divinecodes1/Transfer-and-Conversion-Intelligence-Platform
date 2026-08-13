"""Grant the first verified operator without exposing the private database."""
import argparse
import os

import psycopg2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    args = parser.parse_args()
    username = os.environ.get("TRANSFEROPS_OPERATOR", "").strip()
    if not username:
        print("No TRANSFEROPS_OPERATOR supplied; entitlement grant skipped.")
        return
    with psycopg2.connect(args.dsn) as con, con.cursor() as cur:
        cur.execute("SELECT set_config('transferops.portfolios','*',false)")
        cur.execute("INSERT INTO tr_gov.app_user (username, display_name, email) VALUES (%s,%s,%s) ON CONFLICT (username) DO NOTHING", (username, username, username))
        cur.execute("INSERT INTO tr_gov.user_role (username, role_code) SELECT %s,'PLATFORM_ADMIN' WHERE NOT EXISTS (SELECT 1 FROM tr_gov.user_role WHERE username=%s AND role_code='PLATFORM_ADMIN')", (username, username))
        cur.execute("INSERT INTO tr_gov.data_entitlement (username,dimension_type,dimension_value,valid_from,valid_to) SELECT %s,'PORTFOLIO','*',DATE '2020-01-01',NULL WHERE NOT EXISTS (SELECT 1 FROM tr_gov.data_entitlement WHERE username=%s AND dimension_type='PORTFOLIO')", (username, username))
    print(f"{username} -> PLATFORM_ADMIN, all portfolios")


if __name__ == "__main__":
    main()
