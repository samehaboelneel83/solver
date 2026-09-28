"""Create private offline reference-source credentials and TLS material once.

Usage: python scripts/prepare-ingestion-reference.py D:/solver-private/ingestion
Protect the destination directory with OS permissions before running this file.
No credentials are printed; existing material is never overwritten.
"""
import base64
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

root = Path(sys.argv[1]).resolve()
if any(root.iterdir()):
    raise SystemExit("Destination must be empty; existing credentials will not be replaced")
for name in ("trust", "server", "authority"):
    (root / name).mkdir()
now = datetime.now(timezone.utc)
ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "OaaS local reference CA")])
ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
      .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
      .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=825))
      .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
      .sign(ca_key, hashes.SHA256()))
server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ingestion-reference")])
server = (x509.CertificateBuilder().subject_name(server_name).issuer_name(ca.subject)
          .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=365))
          .add_extension(x509.SubjectAlternativeName([x509.DNSName("ingestion-reference")]), critical=False)
          .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
          .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
          .sign(ca_key, hashes.SHA256()))
for path, key in [(root / "authority/ca.key", ca_key), (root / "server/server.key", server_key)]:
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
(root / "trust/source-ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
(root / "server/server.crt").write_bytes(server.public_bytes(serialization.Encoding.PEM))
keyring = json.dumps({"local-1": base64.b64encode(secrets.token_bytes(32)).decode()}, separators=(",", ":"))
(root / "integration.env").write_text(
    "OAAS_INTEGRATION_KEYS='" + keyring + "'\nOAAS_INTEGRATION_ACTIVE_KEY=local-1\n"
    "OAAS_INTEGRATION_NETWORKS=172.29.89.2/32\nOAAS_INTEGRATION_CA=/integration-certs/source-ca.pem\n", encoding="utf-8")
(root / "source.env").write_text("POSTGRES_DB=ingestion_reference\nPOSTGRES_USER=reference_owner\nPOSTGRES_PASSWORD=" + secrets.token_urlsafe(32) + "\n", encoding="utf-8")
(root / "reader.json").write_text(json.dumps({"password": secrets.token_urlsafe(32)}), encoding="utf-8")
print("Private keyring, source credentials and TLS certificates created; no secrets printed.")
