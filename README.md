# ImmedIPaste

Lightweight Windows screenshot tool that captures a screen region (or full screen) and immediately copies it to your clipboard -- ready to paste. Screenshots are also saved to disk.

## Features

- **Region capture** -- drag to select any area across all monitors
- **Fullscreen capture** -- grab the entire screen instantly
- **Instant clipboard** -- screenshot is copied the moment you release
- **System tray** -- runs quietly in the background
- **Configurable hotkeys** -- change shortcuts via the settings dialog
- **Cross-monitor** -- works across multiple displays

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

### Requirements

- Python 3.10+
- Windows 10/11

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
  "format": "png",
  "filename_prefix": "immedipaste"
}
```

## License

MIT
