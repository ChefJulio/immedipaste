# ImmediPaste

Capture any region of your screen and have it on your clipboard instantly -- no extra steps, just capture and paste. Screenshots are also saved to disk.

Works on **Windows**, **macOS**, and **Linux**.

## Download

Grab the latest build from [Releases](https://github.com/ChefJulio/immedipaste/releases/latest):

| Platform | Download |
|---|---|
| **Windows** | `ImmediPaste-windows.exe` |
| **macOS** | `ImmediPaste-macos` |
| **Linux** | `ImmediPaste-linux` |

## Features

- **Instant clipboard** -- screenshot is on your clipboard the moment you finish capturing
- **Region capture** -- drag to select any area across all monitors
- **Fullscreen capture** -- grab the entire screen with a hotkey
- **System tray** -- runs quietly in the background
- **Live settings** -- change hotkeys, save folder, and format without restarting
- **Cross-monitor** -- works across multiple displays
- **Format selection** -- save as jpg (default), png, or webp
- **Single instance** -- prevents duplicate processes from running

## Hotkeys

| Action | Default |
|---|---|
| Region capture | `Ctrl+Alt+Shift+S` |
| Fullscreen capture | `Ctrl+Alt+Shift+D` |

Inside the region overlay:
- **Drag** to select an area
- **Enter / Space** to capture the full screen
- **Escape / Right-click** to cancel

## Running from source

```
pip install -r requirements.txt
python main.py
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

## Configuration

Settings are stored in `config.json` (auto-created on first run) and can be edited via the tray menu **Settings** option:

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
