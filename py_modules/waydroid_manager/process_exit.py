from contextlib import ExitStack
import os
import select

from .file_events import process_handle
from .proc import process_identity


def wait_for_session_exit(guest, owner=None):
    """Return when Steam exits, or report a guest that stopped unexpectedly."""
    with ExitStack() as cleanup:
        handles = []
        identities = (guest, owner) if owner is not None else (guest,)
        for identity in identities:
            try:
                handle = process_handle(identity)
            except ProcessLookupError:
                handle = None
            if handle is not None:
                cleanup.callback(os.close, handle)
                handles.append(handle)
        while True:
            if owner is not None and process_identity(owner[0]) != owner:
                return
            if process_identity(guest[0]) != guest:
                raise RuntimeError("Waydroid session ended")
            # Older kernels without pidfds only need cheap process identity checks.
            select.select(handles, [], [], None if len(handles) == len(identities) else 1)
