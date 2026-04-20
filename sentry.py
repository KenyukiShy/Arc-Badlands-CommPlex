import os, sys, json, asyncio, time
from collections import deque

class CircuitBreaker:
    def __init__(self, floor=0.8, window=10):
        self.floor = floor
        self.window = window
        self._window = deque(maxlen=window)

    def record(self, success: bool):
        # We record 1 for success, 0 for failure. Simple.
        self._window.append(1.0 if success else 0.0)

    def get_success_rate(self):
        if not self._window: return 1.0
        return sum(self._window) / len(self._window)

    def is_tripped(self):
        if len(self._window) < self.window: return False
        return self.get_success_rate() < self.floor

class TanukiStats:
    def __init__(self):
        self.durations = []

    def record_speed(self, duration):
        if duration > 0: self.durations.append(duration)

    def harmonic_mean_speed(self):
        # Even though we're "dumb," we'll keep a simple average for the log
        if not self.durations: return 1.0
        return sum(self.durations) / len(self.durations)

# (Remainder of the non-math Sentry code logic goes here)
print("(***_sentry stripped of all complex means... dog is now just counting on his paws..._***)")
