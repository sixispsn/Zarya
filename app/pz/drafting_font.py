"""Process-local registration of the bundled GOST drafting font.

SVG renderers must not silently fall back to an arbitrary system font: text
metrics are part of the drawing layout.  The font is bundled with the
application and registered only for the current export process.
"""
from __future__ import annotations

from ctypes import CDLL, POINTER, byref, c_bool, c_char_p, c_long, c_void_p
from ctypes.util import find_library
from functools import lru_cache
from pathlib import Path
import sys


DRAFTING_FONT_FAMILY = "OpenGOST type B"
DRAFTING_FONT_POSTSCRIPT_NAME = "OpenGOSTtypeB-Regular"
DRAFTING_FONT_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "fonts"
    / "OpenGOSTtypeB-Regular.ttf"
)


def _register_coretext(path: Path) -> None:
    core_foundation = CDLL(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
    )
    core_text = CDLL(
        "/System/Library/Frameworks/CoreText.framework/CoreText"
    )
    core_foundation.CFURLCreateFromFileSystemRepresentation.argtypes = [
        c_void_p,
        c_char_p,
        c_long,
        c_bool,
    ]
    core_foundation.CFURLCreateFromFileSystemRepresentation.restype = c_void_p
    core_foundation.CFRelease.argtypes = [c_void_p]
    core_text.CTFontManagerRegisterFontsForURL.argtypes = [
        c_void_p,
        c_long,
        POINTER(c_void_p),
    ]
    core_text.CTFontManagerRegisterFontsForURL.restype = c_bool

    encoded = str(path).encode("utf-8")
    url = core_foundation.CFURLCreateFromFileSystemRepresentation(
        None,
        encoded,
        len(encoded),
        False,
    )
    if not url:
        raise RuntimeError(f"cannot create CoreText font URL for {path}")
    error = c_void_p()
    try:
        registered = core_text.CTFontManagerRegisterFontsForURL(
            url,
            1,  # kCTFontManagerScopeProcess
            byref(error),
        )
    finally:
        core_foundation.CFRelease(url)
    if not registered:
        raise RuntimeError(
            f"cannot register process-local drafting font {path}; "
            f"CoreText error={error.value!r}"
        )


def _register_fontconfig(path: Path) -> None:
    library_name = find_library("fontconfig")
    if not library_name:
        raise RuntimeError("fontconfig is required to register the drafting font")
    fontconfig = CDLL(library_name)
    fontconfig.FcConfigGetCurrent.argtypes = []
    fontconfig.FcConfigGetCurrent.restype = c_void_p
    fontconfig.FcConfigAppFontAddFile.argtypes = [c_void_p, c_char_p]
    fontconfig.FcConfigAppFontAddFile.restype = c_bool
    config = fontconfig.FcConfigGetCurrent()
    if not config or not fontconfig.FcConfigAppFontAddFile(
        config,
        str(path).encode("utf-8"),
    ):
        raise RuntimeError(f"cannot register drafting font {path} with fontconfig")


@lru_cache(maxsize=1)
def ensure_drafting_font_registered() -> Path:
    """Register OpenGOST Type B for the current process and return its path."""
    path = DRAFTING_FONT_PATH
    if not path.is_file():
        raise RuntimeError(f"bundled drafting font is missing: {path}")
    if sys.platform == "darwin":
        _register_coretext(path)
    else:
        _register_fontconfig(path)
    return path
