# FletCopy

A fast, lightweight file copy and move utility built with [Flet](https://flet.dev/) (Python/Flutter).
Designed for desktop use on Linux, with full support for MTP-mounted Android devices.

---

## Features

- Copy or move files and directories with a simple GUI
- Parallel copying with up to 10 concurrent workers
- Atomic writes via temporary file and rename — no partial files on the destination
- Optional MD5 checksum verification after each file
- Smart-skip: files already present at the destination are skipped if size and modification time match
- MTP/mobile device support: automatically detects MTP-mounted paths and switches to a compatible copy method
- Live progress display including speed (MB/s), file count, and free disk space on the destination
- Clean cancellation at any point, with automatic cleanup of temporary files

---

## Requirements

- Python 3.10 or newer
- [Flet](https://flet.dev/) — `pip install flet`

---

## Usage

Start the application directly:

```
python main.py
```

FletCopy can also be launched from a file manager such as Thunar as a custom action.
Pass the source path as the first argument. To enable move mode automatically, add `remove` or `-remove`:

```
python main.py /path/to/source -remove
```

---

## MTP / Android Devices

When the destination path contains `mtp`, `gvfs`, or `/run/user`, FletCopy automatically:

- Reduces the worker count to 1 for stability
- Uses direct file copy instead of the temp-file approach (avoids Error 95)
- Skips files based on size only, since MTP does not provide reliable modification timestamps

If a copy attempt unexpectedly returns Error 95 mid-run, FletCopy switches to MTP mode on the fly
and retries from that point onward.

---

## Options

| Option | Description |
|---|---|
| Move Files | Delete source files after successful copy |
| Verify Checksum | MD5 comparison of source and destination after each file |

---

## Architecture

The copy engine uses an async producer/worker model.
A single producer walks the source tree and enqueues files.
Up to 10 worker coroutines consume the queue in parallel, each writing to a `.tmp` file
before an atomic `os.replace()` into the final destination.
A progress watcher task polls the temp file size every 200 ms for large files.

All blocking I/O runs via `asyncio.to_thread` to keep the UI responsive.

---

## License

MIT