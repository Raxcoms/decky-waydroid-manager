import os


def clean_env():
    # Keep Decky's bundled libraries out of system commands.
    environment = dict(os.environ)
    original = environment.pop("LD_LIBRARY_PATH_ORIG", None)
    if original:
        environment["LD_LIBRARY_PATH"] = original
    else:
        environment.pop("LD_LIBRARY_PATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    return environment
