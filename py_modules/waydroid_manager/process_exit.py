from contextlib import ExitStack
import os
import select

from .file_events import process_handle
from .proc import process_identity


def wait_for_session_exit(guest, owner):
    """Return when Steam exits, or report a guest that stopped unexpectedly."""
    with ExitStack() as cleanup:
        handles = []
        for identity in (guest, owner):
            if identity is None:
                return
            try:
                handle = process_handle(identity)
            except ProcessLookupError:
                handle = None
            if handle is not None:
                cleanup.callback(os.close, handle)
                handles.append(handle)
        while True:
            if process_identity(owner[0]) != owner:
                return
            if process_identity(guest[0]) != guest:
                raise RuntimeError("Waydroid session ended")
            # Older kernels without pidfds only need cheap process identity checks.
            select.select(handles, [], [], None if len(handles) == 2 else 1)
