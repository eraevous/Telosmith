"""Platform facts the tests need: which bash to run, and what Windows can't express.

The bash that hook tests run is found the way the shell that started them finds it.

On Windows, `subprocess.run(["bash", ...])` goes through CreateProcess, which searches System32
before PATH and so starts the WSL launcher (`System32\\bash.exe`), not the Git Bash on PATH. With
no distribution installed that launcher prints a UTF-16 notice and exits 1 (HO-AEC-20261123-ER2R,
Telosmith #111). Tests therefore run the absolute path that `shutil.which` gives, and treat the
WSL launcher as "no bash": a named skip, not a failure.
"""
import os
import shutil
import stat
import sys


def _find_bash():
    path = shutil.which("bash")
    if path and os.name == "nt" and os.path.basename(os.path.dirname(path)).lower() in ("system32", "sysnative"):
        return None
    return path


BASH = _find_bash()
NO_BASH = "needs bash (on Windows: Git Bash on PATH; the WSL launcher in System32 doesn't count)"


def rmtree(path):
    """shutil.rmtree that also removes read-only files (git objects on Windows)."""
    def retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def bash_native(posix_path, form="-w"):
    """What a native (non-MSYS) program started from this bash sees for `posix_path`.

    On Windows, Git Bash (MSYS) rewrites POSIX-looking paths, in arguments and environment values,
    when it starts a native program such as python: `/` becomes `C:\\Program Files\\Git`. `form` is
    cygpath's: `-w` (backslashes) or `-m` (forward slashes, as MSYS writes environment values).
    Elsewhere the path is passed through unchanged."""
    if os.name != "nt":
        return posix_path
    import subprocess
    out = subprocess.run([BASH, "-c", 'cygpath "$1" "$2"', "_", form, posix_path],
                         capture_output=True, text=True, check=True).stdout.strip()
    return os.path.normpath(out) if form == "-w" else out.rstrip("/") or "/"


def readlink(path):
    """os.readlink without Windows' extended-length prefix (`\\\\?\\`), which it adds to absolute targets."""
    target = os.readlink(path)
    return target[4:] if os.name == "nt" and target.startswith("\\\\?\\") else target


POSIX_MODES = "POSIX file modes and umask: Windows keeps only a read-only bit (st_mode is 0o666 or 0o444)"
