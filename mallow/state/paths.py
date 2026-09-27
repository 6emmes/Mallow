from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
MALLOW_DIR = PACKAGE_DIR.parent

UNIT_CLASSES = PACKAGE_DIR / "data" / "unit_classes.csv"
MODEL = MALLOW_DIR / "models" / "winprob_public.skops"

STATE_CSV_NAME = "state.csv"
PREDICTION_NAME = "prediction.txt"

USERDATA_ENV = "MALLOW_USERDATA"
DEFAULT_USERDATA_LEAF = "Command and Conquer Generals Zero Hour Data"
REGISTRY_SUBKEY = (r"SOFTWARE\Electronic Arts\EA Games"
                   r"\Command and Conquer Generals Zero Hour")
USERDATA_LEAF_VALUE = "UserDataLeafName"


def _windows_documents_dir() -> Path | None:
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
    documents = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                     (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C,
                                          0x85, 0x48, 0x03, 0x69, 0xC7))

    get_path = ctypes.WinDLL("shell32").SHGetKnownFolderPath
    get_path.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                         ctypes.POINTER(ctypes.c_void_p)]
    get_path.restype = ctypes.c_long            # HRESULT
    free = ctypes.WinDLL("ole32").CoTaskMemFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None

    out = ctypes.c_void_p()
    if get_path(ctypes.byref(documents), 0, None, ctypes.byref(out)) != 0:
        return None
    try:
        return Path(ctypes.wstring_at(out)) if out.value else None
    finally:
        free(out)


def _documents_dir() -> Path:
    known = _windows_documents_dir() if sys.platform == "win32" else None
    return known if known is not None else Path.home() / "Documents"


def _userdata_leaf() -> str:
    if sys.platform != "win32":
        return DEFAULT_USERDATA_LEAF

    import winreg
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, REGISTRY_SUBKEY) as key:
                value, _ = winreg.QueryValueEx(key, USERDATA_LEAF_VALUE)
        except OSError:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
    return DEFAULT_USERDATA_LEAF


def user_data_dir() -> Path:
    override = os.environ.get(USERDATA_ENV)
    if override:
        return Path(override).expanduser()
    return _documents_dir() / _userdata_leaf()


USERDATA = user_data_dir()
STATE_CSV = USERDATA / STATE_CSV_NAME
PREDICTION_TXT = USERDATA / PREDICTION_NAME
