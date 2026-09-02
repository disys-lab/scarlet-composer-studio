#!/bin/bash
set -e

# Kerberos ticket acquisition for the mssql connector's Windows/AD
# Integrated auth - a no-op when KEYTAB_PATH/KRB5_PRINCIPAL aren't set, so
# a future connector type that doesn't need Kerberos at all isn't forced
# through this step. KEYTAB_PATH is a mounted volume path (the keytab file
# itself is provisioned once, out of band, by whoever owns the AD service
# account - not something this repo generates).
if [ -n "$KEYTAB_PATH" ] && [ -n "$KRB5_PRINCIPAL" ]; then
    echo "Acquiring Kerberos ticket for ${KRB5_PRINCIPAL}..."
    kinit -kt "$KEYTAB_PATH" "$KRB5_PRINCIPAL"
    echo "Kerberos ticket acquired."
else
    echo "KEYTAB_PATH/KRB5_PRINCIPAL not set - skipping kinit (fine for a connector that doesn't need Kerberos)."
fi

exec /opt/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8090
