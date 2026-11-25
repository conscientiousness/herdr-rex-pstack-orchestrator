"""Replay a choice prefix, then take the first eligible actor at each fork."""

from queue import SimpleQueue
from threading import Event, Thread, current_thread


class Schedule:
    def __init__(self):
        self.gates = {}
        self.parked = SimpleQueue()
        self.trace = []

    def record(self, event):
        self.trace.append(f"{current_thread().name}: {event}")

    def point(self):
        name = current_thread().name
        self.parked.put((name, False, None))
        self.gates[name].wait()
        self.gates[name].clear()

    def run(self, actors, prefix, bound):
        def actor(action):
            error = None
            try:
                self.point()
                action()
            except BaseException as exc:
                error = exc
            finally:
                self.parked.put((current_thread().name, True, error))

        pending = list(actors)
        threads = []
        for name, action in actors.items():
            self.gates[name] = Event()
            thread = Thread(target=actor, args=(action,), name=name, daemon=True)
            threads.append(thread)
            thread.start()
            parked = self.parked.get()
            if parked != (name, False, None):
                raise RuntimeError(f'actor failed to park: {parked}')

        path = []
        forks = []
        previous = None
        switches = 0
        while pending:
            choices = list(pending)
            if previous in pending:
                choices.remove(previous)
                choices.insert(0, previous)
                if switches == bound:
                    choices = [previous]
            if len(path) < len(prefix):
                chosen = prefix[len(path)]
                if chosen not in choices:
                    raise ValueError(f"prefix diverged at {path}: {chosen} outside {choices}")
            else:
                chosen = choices[0]
                forks.extend(tuple([*path, other]) for other in reversed(choices[1:]))
            switches += previous in pending and previous != chosen
            path.append(chosen)
            self.gates[chosen].set()
            name, finished, error = self.parked.get()
            assert name == chosen
            if error is not None:
                raise error
            if finished:
                pending.remove(chosen)
            previous = chosen
        if len(prefix) > len(path):
            raise ValueError("prefix extends past the end of the schedule")
        for thread in threads:
            thread.join()
        return path, forks
