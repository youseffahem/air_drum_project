"""Reversible one-frame-in-flight shared-memory perception experiment.

The parent waits for the current delivered frame before publishing another. No prefetch,
frame interpolation, asynchronous prediction or future frame access is permitted.
"""

from __future__ import annotations

import multiprocessing as mp
import time
from contextlib import contextmanager
from multiprocessing.shared_memory import SharedMemory
from unittest.mock import patch

import numpy as np


def worker(cfg, connection):
    from _p16 import resources

    from spacedrums.app.main import HANDS, Perception
    from spacedrums.capture import Roi
    from spacedrums.contracts import FrameSample, FrameView, HandId

    perception, memory = None, None
    try:
        perception = Perception(cfg)
        connection.send(("ready", None))
        while True:
            message = connection.recv()
            if message is None:
                connection.send(("closed", {**resources(), "process_cpu_s": time.process_time()}))
                break
            name, shape, record = message
            if memory is None:
                memory = SharedMemory(name=name)
            pixels = np.ndarray(shape, np.uint8, buffer=memory.buf)
            sample = FrameSample.from_dict(record)
            roi = Roi.from_rect(sample.roi_px)
            frame = FrameView(sample, pixels[roi.y : roi.y1, roi.x : roi.x1], pixels)
            cpu = time.process_time()
            start = time.perf_counter()
            detected = perception.landmarker.detect(frame)
            hands_s = time.perf_counter() - start
            out = {}
            start = time.perf_counter()
            for hand in HANDS:
                observation = detected.left if hand is HandId.LEFT else detected.right
                stick = perception.estimator.estimate(frame, observation)
                out[hand] = observation, stick
                perception.last_analyses[hand] = perception.estimator.last_analysis
            stick_s = time.perf_counter() - start
            connection.send(
                (
                    "frame",
                    (
                        sample.frame_id,
                        out,
                        perception.last_analyses,
                        {"hands": hands_s, "stick": stick_s},
                        time.process_time() - cpu,
                    ),
                )
            )
    except BaseException as exc:
        connection.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        if perception is not None:
            perception.close()
        if memory is not None:
            memory.close()
        connection.close()


class Bridge:
    def __init__(self, cfg):
        context = mp.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=worker, args=(cfg, child), name="phase16-perception")
        self.memory = None
        self.stats = {"worker_compute_cpu_s": 0.0, "frames": 0, "final_resources": None}
        self.process.start()
        child.close()
        try:
            self.receive("ready", 30)
        except BaseException:
            self.close()
            raise

    def receive(self, expected, timeout=10):
        if not self.connection.poll(timeout):
            raise TimeoutError("perception worker exceeded bounded wait")
        kind, value = self.connection.recv()
        if kind != expected:
            raise RuntimeError(f"perception worker {kind}: {value}")
        return value

    def frame(self, view):
        if view.full is None or view.full.dtype != np.uint8:
            raise ValueError("process experiment requires original full BGR uint8 frames")
        if self.memory is None:
            self.shape = view.full.shape
            self.memory = SharedMemory(create=True, size=view.full.nbytes)
        if view.full.shape != self.shape:
            raise ValueError("camera shape changed during shared-memory experiment")
        np.copyto(np.ndarray(self.shape, np.uint8, buffer=self.memory.buf), view.full)
        self.connection.send((self.memory.name, self.shape, view.sample.to_dict()))
        frame_id, observations, analyses, stages, cpu_s = self.receive("frame")
        if frame_id != view.sample.frame_id:
            raise AssertionError("worker returned another delivered frame")
        self.stats["worker_compute_cpu_s"] += cpu_s
        self.stats["frames"] += 1
        return observations, analyses, stages

    def close(self):
        try:
            if self.process.is_alive():
                self.connection.send(None)
                self.stats["final_resources"] = self.receive("closed", 10)
        except (EOFError, OSError, RuntimeError, TimeoutError):
            pass
        finally:
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)
            self.connection.close()
            if self.memory is not None:
                self.memory.close()
                self.memory.unlink()
                self.memory = None


@contextmanager
def process_perception():
    from spacedrums.app.main import Perception

    def initialize(self, cfg):
        self.bridge = Bridge(cfg)
        self.last_analyses = {}
        self.last_hands = None
        self.worker_stage_s = {}

    def call(self, view):
        observations, self.last_analyses, self.worker_stage_s = self.bridge.frame(view)
        return observations

    with (
        patch.object(Perception, "__init__", initialize),
        patch.object(Perception, "__call__", call),
        patch.object(Perception, "close", lambda self: self.bridge.close()),
    ):
        yield
