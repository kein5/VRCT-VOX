"""File verification shared by catalog and built-in model transactions."""
import hashlib
import os
import stat

CHUNK = 1024 * 1024


def verify_file(path, artifact, checkpoint, *, chunk_size=CHUNK):
    checkpoint()
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('unsafe_destination')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        if os.fstat(stream.fileno()).st_size != artifact.size:
            raise ValueError('size_mismatch')
        digest = hashlib.sha256()
        while block := stream.read(chunk_size):
            checkpoint()
            digest.update(block)
        checkpoint()
        if digest.hexdigest() != artifact.sha256:
            raise ValueError('hash_mismatch')
