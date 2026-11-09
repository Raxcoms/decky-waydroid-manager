import array
from contextlib import contextmanager
import os
from pathlib import Path
import pwd
import socket
import subprocess

def run_as_user(helper: Path, home: Path, action: str, *args: str, payload: bytes | None = None, pass_fds=()):
    uid = home.stat().st_uid
    credentials = {}
    if os.geteuid() != uid:
        account = pwd.getpwuid(uid)
        credentials = {"user": uid, "group": account.pw_gid,
                       "extra_groups": os.getgrouplist(account.pw_name, account.pw_gid)}
    result = subprocess.run(
        ["/usr/bin/python3", "-I", str(helper), str(home), action, *args],
        env={"HOME": str(home), "LANG": "C.UTF-8"}, input=payload, capture_output=True,
        pass_fds=pass_fds, timeout=15, umask=0o077, **credentials,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace").strip() or "Waydroid file operation failed")
    return result.stdout


@contextmanager
def open_as_user(helper: Path, home: Path, path: Path):
    receiver, sender = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    with receiver, sender:
        fd = sender.fileno()
        run_as_user(helper, home, "open", str(path), str(fd), pass_fds=(fd,))
        receiver.settimeout(5)
        fds = array.array("i")
        data, ancillary, flags, _ = receiver.recvmsg(1, socket.CMSG_SPACE(fds.itemsize), socket.MSG_CMSG_CLOEXEC)
        for level, kind, value in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                fds.frombytes(value)
        if data != b"F" or flags & socket.MSG_CTRUNC or len(fds) != 1:
            for fd in fds:
                os.close(fd)
            raise RuntimeError("INVALID_PACKAGE_FILE")
        with os.fdopen(fds[0], "rb", buffering=0) as source:
            yield source
