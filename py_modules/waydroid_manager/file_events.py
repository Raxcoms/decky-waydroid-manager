"""Sleep on Linux device changes and process exits instead of rescanning on a timer."""

import ctypes
import errno
import os
import select

from .proc import process_identity

IN_ATTRIB = 0x00000004
IN_CLOSE_WRITE = 0x00000008
IN_MOVED_FROM = 0x00000040
IN_MOVED_TO = 0x00000080
IN_CREATE = 0x00000100
IN_DELETE = 0x00000200
IN_DELETE_SELF = 0x00000400
IN_MOVE_SELF = 0x00000800

def process_handle(identity):
    if not hasattr(os, "pidfd_open"):
        return None
    try:
        handle = os.pidfd_open(identity[0])
    except OSError as error:
        if error.errno in (errno.ENOSYS, errno.EINVAL):
            return None
        raise
    if process_identity(identity[0]) != identity:
        os.close(handle)
        raise ProcessLookupError("The monitored process changed")
    return handle


class FileEvents:
    def __init__(self, paths):
        self.paths = paths
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.inotify_init1.argtypes = [ctypes.c_int]
        self.libc.inotify_init1.restype = ctypes.c_int
        self.libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.libc.inotify_add_watch.restype = ctypes.c_int
        self.handle = self.libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.handle < 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code))
        self.read = self.write = None
        try:
            self.read, self.write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
            self.refresh()
        except Exception:
            self.close()
            raise

    def refresh(self):
        # Metadata, create/remove, rename, and close-write cover udev publication.
        mask = (IN_ATTRIB | IN_CLOSE_WRITE | IN_MOVED_FROM | IN_MOVED_TO | IN_CREATE
                | IN_DELETE | IN_DELETE_SELF | IN_MOVE_SELF)
        for path in self.paths:
            if self.libc.inotify_add_watch(self.handle, os.fsencode(path), mask) < 0:
                code = ctypes.get_errno()
                if code != errno.ENOENT:
                    raise OSError(code, os.strerror(code), str(path))

    def wake(self):
        try:
            os.write(self.write, b"1")
        except BlockingIOError:
            pass

    def wait(self, processes=(), timeout=None):
        ready, _, _ = select.select([self.handle, self.read, *processes], [], [], timeout)
        for handle in (self.handle, self.read):
            if handle in ready:
                while True:
                    try:
                        if not os.read(handle, 65536):
                            break
                    except BlockingIOError:
                        break
        return ready

    def close(self):
        for handle in (self.handle, self.read, self.write):
            if handle is not None:
                os.close(handle)
