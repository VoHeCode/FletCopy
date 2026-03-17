#!/usr/bin/env python3

import flet as ft
import asyncio
import hashlib
import os
import sys
import threading
import shutil
from pathlib import Path
import time as _time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MB = 1024 * 1024
BUF_SIZE = 16 * MB
CHECKSUM_BUF = 8 * MB
OS_BUFFER = 128 * 1024
WINDOW_SIZE = 10
PROGRESS_THRESHOLD = 200 * MB
WINDOW_HEIGHT = 450
WINDOW_WIDTH = 640
COL_STOP = ft.Colors.RED
COL_GO = ft.Colors.GREEN
COL_ATTENTION = ft.Colors.ORANGE


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------
class AppState:
    """Shared runtime state passed to producer and worker coroutines."""
    __slots__ = (
        "running", "cancelled", "orig_src", "orig_dst", "found_cnt",
        "copied_cnt", "written_mb", "read_total_mb", "current_write_mb",
        "last_ui_upd", "top10", "run_tasks", "start_time", "total_capacity_gb",
        "mobile_detected"
    )

    def __init__(self, initial_src=""):
        self.running = False
        self.cancelled = False
        self.orig_src = initial_src
        self.orig_dst = ""
        self.found_cnt = 0
        self.copied_cnt = 0
        self.written_mb = 0.0
        self.read_total_mb = 0.0
        self.current_write_mb = 0.0
        self.last_ui_upd = 0.0
        self.top10 = [""] * WINDOW_SIZE
        self.run_tasks = []
        self.start_time = 0.0
        self.total_capacity_gb = 100.0
        self.mobile_detected = False


# ---------------------------------------------------------------------------
# High-Performance Functions
# ---------------------------------------------------------------------------
def get_md5_checksum(path: Path) -> str:
    """Return the MD5 hex digest of a file, read in large chunks for performance."""
    h = hashlib.md5()
    with open(path, "rb", buffering=OS_BUFFER) as f:
        while True:
            chunk = f.read(CHECKSUM_BUF)
            if not chunk: break
            h.update(chunk)
    return h.hexdigest()


async def verify_checksum(src_path: Path, dst_tmp: Path) -> bool:
    """Compare MD5 checksums of source and destination; returns True if identical."""
    src_sum = await asyncio.to_thread(get_md5_checksum, src_path)
    dst_sum = await asyncio.to_thread(get_md5_checksum, dst_tmp)
    return src_sum == dst_sum


def delete_file(filename):
    try:
        p = Path(filename)
        if p.exists(): os.remove(p)
        return True
    except (OSError, PermissionError):
        return False


def cleanup_empty_directories(path: Path):
    if not path.is_dir(): return
    for d in sorted(path.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()
            except OSError:
                pass


def cleanup_parent_directories(f: Path):
    parent = f.parent
    while parent and parent != parent.parent and parent != Path(f.anchor):
        try:
            parent.rmdir()
            parent = parent.parent
        except OSError:
            break


# ---------------------------------------------------------------------------
# Producer & Worker
# ---------------------------------------------------------------------------
async def producer(src_list, queue, state: AppState, on_found, on_unreadable):
    """Walk source paths recursively and enqueue readable files for workers."""
    async def _async_glob(root: Path):
        loop = asyncio.get_event_loop()
        q = asyncio.Queue()

        def _walk():
            for dirpath, _, filenames in os.walk(root):
                for name in filenames:
                    loop.call_soon_threadsafe(q.put_nowait, Path(dirpath) / name)
            loop.call_soon_threadsafe(q.put_nowait, None)

        threading.Thread(target=_walk, daemon=True).start()
        while True:
            file_item = await q.get()
            if file_item is None: break
            yield file_item

    for s_path in src_list:
        if state.cancelled: break
        if s_path.is_file():
            if os.access(s_path, os.R_OK):
                await on_found(s_path)
                await queue.put(s_path)
            else:
                await on_unreadable(s_path)
        elif s_path.is_dir():
            async for f_item in _async_glob(s_path):
                if state.cancelled: break
                if os.access(f_item, os.R_OK):
                    await on_found(f_item)
                    await queue.put(f_item)
                else:
                    await on_unreadable(f_item)
    for _ in range(WINDOW_SIZE): await queue.put(None)


async def worker(queue, get_destination, do_checksum, move_mode, state: AppState, on_progress, on_done, on_error,
                 on_msg, worker_id=0):
    """
    Copy files from queue to destination.
    Uses temp file + atomic rename on normal filesystems.
    On MTP targets: skips metadata ops (copy only by size), single direct copy.
    """
    while True:
        f_path = await queue.get()
        if f_path is None: break
        target_path = get_destination(f_path)

        try:
            f_stat = f_path.stat()
            f_size = f_stat.st_size

            if target_path.exists():
                t_stat = target_path.stat()
                # MTP does not provide reliable mtime — skip based on size only
                size_match = t_stat.st_size == f_size
                mtime_match = abs(t_stat.st_mtime - f_stat.st_mtime) < 0.1
                if size_match and (state.mobile_detected or mtime_match):
                    await on_done(f"{target_path.name} (skipped)", f_size)
                    if move_mode:
                        delete_file(f_path)
                        await asyncio.to_thread(cleanup_parent_directories, f_path)
                    continue

            target_path.parent.mkdir(parents=True, exist_ok=True)

            if state.mobile_detected:
                await asyncio.to_thread(shutil.copyfile, str(f_path), str(target_path))
            else:
                temp_dst = Path(str(target_path) + ".tmp")
                state.top10[worker_id] = str(temp_dst)
                try:
                    watcher = None
                    if f_size >= PROGRESS_THRESHOLD:
                        await on_progress(target_path.name, 0)
                        watcher = asyncio.create_task(progress_watcher(temp_dst, f_size, target_path.name, on_progress))

                    await asyncio.to_thread(shutil.copy2, f_path, temp_dst)
                    if watcher: watcher.cancel()

                    if state.cancelled: continue
                    if do_checksum:
                        if not await verify_checksum(f_path, temp_dst):
                            await on_msg(target_path.name, "Checksum mismatch")
                            delete_file(temp_dst)
                            continue
                    os.replace(temp_dst, target_path)
                except OSError as e:
                    if e.errno in (38, 95):
                        delete_file(temp_dst)  # cleanup before switching to direct copy
                        state.mobile_detected = True
                        await on_msg(target_path.name, "MTP/Error 95: Switching to direct copy")
                        await asyncio.to_thread(shutil.copyfile, str(f_path), str(target_path))
                    else:
                        raise e

            if move_mode and not state.cancelled:
                delete_file(f_path)
                await asyncio.to_thread(cleanup_parent_directories, f_path)
            await on_done(target_path.name, f_size)
        except (OSError, IOError) as exc:
            await on_error(target_path.name, str(exc))
            break


async def progress_watcher(temp_dst: Path, total: int, name: str, on_progress):
    """Poll temp file size every 200 ms and report copy progress as percentage."""
    for _ in range(20):
        if temp_dst.exists(): break
        await asyncio.sleep(0.1)
    while True:
        await asyncio.sleep(0.2)
        try:
            current = os.path.getsize(temp_dst)
            pct = min(current / total * 100, 99)
            await on_progress(name, pct, current / MB)
            if current >= total: break
        except OSError:
            break


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
async def main(page: ft.Page):
    """Flet entry point — builds the UI and wires copy/move logic."""
    page.title = "FletCopy"
    page.padding = 20
    page.window.width = WINDOW_WIDTH
    page.window.height = WINDOW_HEIGHT

    raw_args = sys.argv[1:]
    initial_move = any(a.lower() in ("remove", "-remove") for a in raw_args)
    paths = [p for p in raw_args if p.lower() not in ("remove", "-remove")]

    source_val = paths[0] if len(paths) >= 1 else ""
    state = AppState(initial_src=source_val)

    src_field = ft.TextField(label="Source", value=state.orig_src, expand=True, read_only=True)
    dst_field = ft.TextField(label="Destination", expand=True, read_only=True)
    move_check = ft.Checkbox(label="Move Files", value=initial_move)
    checksum_check = ft.Checkbox(label="Verify Checksum", value=False)
    counter_text = ft.Text("")
    status_text = ft.Text("")
    speed_text = ft.Text("")

    usage_slider = ft.Slider(min=0, max=100, value=0, disabled=True, expand=True, active_color=ft.Colors.BLUE)
    min_label = ft.Text("0 GB", size=10)
    max_label = ft.Text("? GB", size=10)
    current_label = ft.Text("Free Space: select destination", size=12, weight=ft.FontWeight.BOLD)

    def show_notification(text, color=None):
        page.overlay[:] = [c for c in page.overlay if not isinstance(c, ft.SnackBar)]
        page.overlay.append(ft.SnackBar(ft.Text(text), open=True, bgcolor=color))
        page.update()

    async def update_disk_info(path_str):
        if not path_str: return
        try:
            usage = shutil.disk_usage(path_str)
            state.total_capacity_gb = usage.total / (1024 ** 3)
            free_gb = usage.free / (1024 ** 3)
            usage_slider.max = state.total_capacity_gb
            usage_slider.value = free_gb
            max_label.value = f"{state.total_capacity_gb:.0f} GB"
            current_label.value = f"Free: {free_gb:.1f} GB"

            if free_gb < 2:
                usage_slider.thumb_color = usage_slider.active_color = COL_STOP
            elif free_gb < 10:
                usage_slider.thumb_color = usage_slider.active_color = COL_ATTENTION
            else:
                usage_slider.thumb_color = usage_slider.active_color = COL_GO
        except Exception:
            pass
        page.update()

    async def _debounced_ui_update():
        now = _time.monotonic()
        if now - state.last_ui_upd >= 0.3:
            state.last_ui_upd = now
            elapsed = now - state.start_time
            if elapsed > 0:
                speed = (state.written_mb + state.current_write_mb) / elapsed
                speed_text.value = f"Speed: {speed:.1f} MB/s"
            page.update()

    async def handle_file_found(f_info):
        state.found_cnt += 1
        state.read_total_mb += f_info.stat().st_size / MB
        counter_text.value = f"Found: {state.found_cnt}  Copied: {state.copied_cnt}"
        await _debounced_ui_update()

    async def handle_unreadable(f):
        show_notification(f"Unreadable: {f.name}")

    async def handle_progress(name, pct, cur_mb=None):
        total_written = state.written_mb + (cur_mb if cur_mb is not None else state.current_write_mb)
        status_text.value = f"{total_written:.0f} / {state.read_total_mb:.0f} MB | {name} ({pct:.0f}%)"
        if cur_mb is not None: state.current_write_mb = cur_mb
        await _debounced_ui_update()

    async def handle_done(name, f_size=0):
        state.copied_cnt += 1
        state.written_mb += f_size / MB
        state.current_write_mb = 0.0
        status_text.value = f"{state.written_mb:.0f} / {state.read_total_mb:.0f} MB | {name}"
        counter_text.value = f"Found: {state.found_cnt}  Copied: {state.copied_cnt}"
        await update_disk_info(dst_field.value)
        page.update()

    async def handle_error(name, msg):
        show_notification(f"{name}: {msg}", COL_STOP)

    async def handle_msg(name, msg):
        show_notification(f"{name}: {msg}", COL_ATTENTION)

    def cancel_operation(e):
        state.cancelled = True
        for t in state.run_tasks: t.cancel()
        show_notification("Cancelled")

    async def pick_source(e):
        p = await ft.FilePicker().get_directory_path()
        if p: src_field.value = p; page.update()

    async def pick_destination(e):
        p = await ft.FilePicker().get_directory_path()
        if p: dst_field.value = p; await update_disk_info(p)

    async def start_copy_process(e):
        dst_val = (dst_field.value or "").strip()
        if not dst_val: show_notification("Select destination"); return
        sources = [Path(p.strip()) for p in src_field.value.splitlines() if p.strip()]
        if not sources: return

        # MTP/Mobile Erkennung
        state.mobile_detected = any(x in dst_val.lower() for x in ["mtp", "gvfs", "/run/user"])

        state.running, state.cancelled = True, False
        state.found_cnt, state.copied_cnt, state.written_mb, state.read_total_mb = 0, 0, 0.0, 0.0
        state.start_time, state.run_tasks = _time.monotonic(), []

        start_btn.disabled = pick_src_btn.disabled = pick_dst_btn.disabled = True
        cancel_btn.visible = True
        counter_text.value, speed_text.value = "Scanning...", "Speed: 0.0 MB/s"
        page.update()

        try:
            def get_destination_path(f_in):
                if len(sources) == 1 and sources[0].is_dir():
                    return Path(dst_val) / Path(sources[0].name) / f_in.relative_to(sources[0])
                return Path(dst_val) / f_in.name

            queue = asyncio.Queue(maxsize=WINDOW_SIZE * 2)
            prod_task = asyncio.create_task(producer(sources, queue, state, handle_file_found, handle_unreadable))

            # Reduzierte Worker-Anzahl für Handys zur Stabilitätsverbesserung
            num_workers = 1 if state.mobile_detected else WINDOW_SIZE
            worker_tasks = [
                asyncio.create_task(worker(queue, get_destination_path, checksum_check.value, move_check.value, state,
                                           handle_progress, handle_done, handle_error, handle_msg, i)) for i in
                range(num_workers)]

            state.run_tasks.extend([prod_task, *worker_tasks])
            await prod_task
            await asyncio.gather(*worker_tasks, return_exceptions=True)

        finally:
            state.running, cancel_btn.visible = False, False
            start_btn.disabled = pick_src_btn.disabled = pick_dst_btn.disabled = False
            if move_check.value and not state.cancelled:
                for s in sources:
                    if s.is_dir(): await asyncio.to_thread(cleanup_empty_directories, s)
            for p_tmp in state.top10:
                if p_tmp: delete_file(p_tmp)
            if not state.cancelled: show_notification("Finished", COL_GO)
            page.update()

    pick_src_btn = ft.TextButton("Select", on_click=pick_source)
    pick_dst_btn = ft.TextButton("Select", on_click=pick_destination)
    start_btn = ft.TextButton("Start", on_click=start_copy_process)
    cancel_btn = ft.TextButton("Cancel", visible=False, on_click=cancel_operation)

    page.add(ft.Column([
        ft.Row([src_field, pick_src_btn]),
        ft.Row([dst_field, pick_dst_btn]),
        ft.Row([move_check, checksum_check]),
        ft.Column([
            current_label,
            ft.Row([min_label, usage_slider, max_label], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=5),
        ft.Row([start_btn, cancel_btn]),
        ft.Divider(),
        ft.Row([counter_text, speed_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        status_text
    ], spacing=15, expand=True))


if __name__ == "__main__":
    ft.run(main)