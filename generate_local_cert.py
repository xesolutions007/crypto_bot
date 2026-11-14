"""Create a self-signed HTTPS certificate for the local dashboard hostname.

The generated private key and certificate stay in the local certs/ directory.
Do not commit or share them.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parent
CERT_DIR = ROOT / "certs"
CERT_PATH = CERT_DIR / "botstrategiesmodules.crt"
KEY_PATH = CERT_DIR / "botstrategiesmodules.key"
HOSTNAME = "botstrategiesmodules"


def main():
    CERT_DIR.mkdir(exist_ok=True)
    if CERT_PATH.exists() and KEY_PATH.exists():
        print(f"Using existing local certificate: {CERT_PATH}")
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, HOSTNAME),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Local Crypto Bot Dashboard"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=730))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(HOSTNAME),
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    KEY_PATH.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    CERT_PATH.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        KEY_PATH.chmod(0o600)
    except OSError:
        pass
    print(f"Created certificate: {CERT_PATH}")
    print(f"Created private key: {KEY_PATH}")
    print("Import the .crt file into Current User > Trusted Root Certification Authorities.")
    print("Never share or upload the .key private key.")


if __name__ == "__main__":
    main()
