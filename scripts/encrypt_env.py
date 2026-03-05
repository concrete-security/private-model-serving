"""Encrypt environment variables for Phala CVM deployment.

Uses x25519 key exchange + AES-256-GCM as required by dstack.
See phala.md §Phase 2 for protocol details.

Input:
  argv[1]: server public key (32-byte hex, from provision response)
  argv[2]: JSON array of {key, value} objects

Output:
  hex string: ephemeral_pubkey(32B) + iv(12B) + ciphertext + auth_tag(16B)
"""

import json
import os
import sys

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

server_pubkey_hex = sys.argv[1]
env_pairs = json.loads(sys.argv[2])

# Load server's x25519 public key (from provision response)
server_pubkey = X25519PublicKey.from_public_bytes(bytes.fromhex(server_pubkey_hex))

# Generate ephemeral x25519 keypair
ephemeral_key = X25519PrivateKey.generate()

# ECDH: derive shared secret
shared_secret = ephemeral_key.exchange(server_pubkey)

# Get ephemeral public key bytes to send alongside ciphertext
ephemeral_pub_bytes = ephemeral_key.public_key().public_bytes_raw()

# Encode env vars as JSON: {"env": [{key, value}, ...]}
plaintext = json.dumps({"env": env_pairs}).encode()

# AES-256-GCM encrypt
iv = os.urandom(12)
aesgcm = AESGCM(shared_secret)
ciphertext_with_tag = aesgcm.encrypt(iv, plaintext, None)

# Output: ephemeral_pubkey(32) + iv(12) + ciphertext + tag(16)
result = ephemeral_pub_bytes + iv + ciphertext_with_tag
print(result.hex())
