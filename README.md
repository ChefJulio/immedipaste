# ImmediPaste

Lightweight screenshot tool that captures a screen region (or full screen) and immediately copies it to your clipboard -- ready to paste. Screenshots are also saved to disk.

Works on **Windows**, **macOS**, and **Linux**.

## Features

- **Region capture** -- drag to select any area across all monitors
- **Fullscreen capture** -- grab the entire screen instantly
- **Instant clipboard** -- screenshot is copied the moment you release
- **System tray** -- runs quietly in the background
- **Configurable hotkeys** -- change shortcuts via the settings dialog
- **Cross-monitor** -- works across multiple displays
- **Format selection** -- save as jpg (default), png, or webp

## Hotkeys

| Action | Default |
|---|---|
| Region capture | `Ctrl+Alt+Shift+S` |
| Fullscreen capture | `Ctrl+Alt+Shift+D` |

Inside the region overlay:
- **Drag** to select an area
- **Enter / Space** to capture the full screen
- **Escape / Right-click** to cancel

## Installation

```
pip install -r requirements.txt
```

### Platform requirements

| Platform | Requirements |
|---|---|
| **Windows** | Python 3.10+, Windows 10/11 |
| **macOS** | Python 3.10+, tkinter (`brew install python-tk`) |
| **Linux** | Python 3.10+, tkinter, one of: `xclip`, `xsel`, or `wl-copy` |

Linux clipboard setup:
```bash
# X11
sudo apt install xclip
# or Wayland
sudo apt install wl-clipboard
```

## Usage

```
python main.py
```

The app starts in the system tray. Use the hotkeys or right-click the tray icon for options.

## Configuration

Settings are stored in `config.json` and can be edited via the tray menu **Settings** option:

```json
{
  "save_folder": "~/OneDrive/Pictures/Screenshots",
  "hotkey_region": "<ctrl>+<alt>+<shift>+s",
  "hotkey_fullscreen": "<ctrl>+<alt>+<shift>+d",
  "format": "jpg",
  "filename_prefix": "immedipaste"
}
```

## License

MIT
