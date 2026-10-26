"""Bounded-memory file operations for large game libraries."""
import hashlib


def sha256_file(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
