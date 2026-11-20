"""ImagePrefetcher: downloads card/deck images to the on-disk cache in the
background, so they're already local by the time a grid shows them
(the grids themselves only request images for cells actually on
screen). Pure download — decoding still happens in ui.image_loader when
a cell is painted, which is fast once the file is on disk.

Uses plain daemon threads rather than the shared QThreadPool, so a long
prefetch never starves on-screen image loads or other background tasks,
and never keeps the app from closing.
"""

import queue
import threading

from image_cache import get_image_path


class ImagePrefetcher:
    def __init__(self, workers: int = 6):
        """workers: number of concurrent downloads."""
        self._workers = workers
        self._stop = threading.Event()

    def start(self, items):
        """Cancels any prefetch still running and starts a new one.
        items: (url, cache_name) pairs, downloaded in order; already-
        cached ones are skipped instantly by get_image_path."""
        self._stop.set()
        self._stop = threading.Event()

        todo = queue.Queue()
        for item in items:
            todo.put(item)
        for _ in range(self._workers):
            threading.Thread(target=self._work, args=(todo, self._stop), daemon=True).start()

    def stop(self):
        """Cancels the running prefetch (in-flight downloads finish)."""
        self._stop.set()

    @staticmethod
    def _work(todo: queue.Queue, stop: threading.Event):
        while not stop.is_set():
            try:
                url, cache_name = todo.get_nowait()
            except queue.Empty:
                return
            get_image_path(url, cache_name)
