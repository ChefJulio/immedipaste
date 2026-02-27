"""Platform-specific window detection for window capture mode."""

import platform

SYSTEM = platform.system()

if SYSTEM == "Windows":
  import ctypes
  import ctypes.wintypes

  user32 = ctypes.windll.user32
  dwmapi = ctypes.windll.dwmapi

  # -- Constants --
  DWMWA_EXTENDED_FRAME_BOUNDS = 9
  DWMWA_CLOAKED = 14
  GWL_EXSTYLE = -20
  WS_EX_TRANSPARENT = 0x00000020

  # -- Function signatures (critical for 64-bit HWND correctness) --
  user32.GetDesktopWindow.restype = ctypes.wintypes.HWND
  user32.GetShellWindow.restype = ctypes.wintypes.HWND
  user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
  user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
  user32.GetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
  user32.GetWindowLongW.restype = ctypes.wintypes.LONG
  user32.GetWindowRect.argtypes = [
    ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT),
  ]
  user32.GetWindowRect.restype = ctypes.wintypes.BOOL
  user32.GetCursorPos.argtypes = [ctypes.POINTER(ctypes.wintypes.POINT)]
  user32.GetCursorPos.restype = ctypes.wintypes.BOOL

  WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM,
  )
  user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.wintypes.LPARAM]
  user32.EnumWindows.restype = ctypes.wintypes.BOOL

  dwmapi.DwmGetWindowAttribute.argtypes = [
    ctypes.wintypes.HWND, ctypes.wintypes.DWORD,
    ctypes.c_void_p, ctypes.wintypes.DWORD,
  ]
  dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

  def _is_cloaked(hwnd):
    """Check if a window is cloaked (hidden UWP/Store app)."""
    cloaked = ctypes.c_int(0)
    hr = dwmapi.DwmGetWindowAttribute(
      hwnd, DWMWA_CLOAKED,
      ctypes.byref(cloaked), ctypes.sizeof(cloaked),
    )
    return hr == 0 and cloaked.value != 0

  def get_cursor_pos():
    """Return (x, y) physical screen coordinates of the cursor."""
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)

  def get_window_rect_at(x, y, exclude_hwnd=0):
    """Return (left, top, right, bottom) for the topmost window at (x, y).

    Enumerates all top-level windows in Z-order, skipping the excluded
    overlay HWND, desktop, shell, cloaked, transparent, and invisible windows.
    Returns None if no suitable window found.
    """
    result = [None]
    desktop = int(user32.GetDesktopWindow() or 0)
    shell = int(user32.GetShellWindow() or 0)
    exclude = int(exclude_hwnd) if exclude_hwnd else 0

    @WNDENUMPROC
    def callback(hwnd, lparam):
      h = int(hwnd) if hwnd else 0

      if exclude and h == exclude:
        return True
      if h in (desktop, shell):
        return True
      if not user32.IsWindowVisible(hwnd):
        return True
      if _is_cloaked(hwnd):
        return True

      # Skip click-through windows (invisible overlays from other apps)
      exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
      if exstyle & WS_EX_TRANSPARENT:
        return True

      # Get tight window bounds (no invisible resize borders)
      rect = ctypes.wintypes.RECT()
      hr = dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect), ctypes.sizeof(rect),
      )
      if hr != 0:
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

      if rect.right - rect.left < 1 or rect.bottom - rect.top < 1:
        return True

      if rect.left <= x < rect.right and rect.top <= y < rect.bottom:
        result[0] = (rect.left, rect.top, rect.right, rect.bottom)
        return False  # Found topmost window, stop enumeration

      return True

    user32.EnumWindows(callback, 0)
    return result[0]

else:
  def get_cursor_pos():
    """Cursor position not available on this platform."""
    return (0, 0)

  def get_window_rect_at(x, y, exclude_hwnd=0):
    """Window detection not available on this platform."""
    return None
