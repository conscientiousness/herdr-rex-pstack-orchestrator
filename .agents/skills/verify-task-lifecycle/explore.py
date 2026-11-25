"""Bounded schedule exploration of the installed source tree. See SKILL.md."""

import argparse
import importlib.util
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from threading import local
from types import SimpleNamespace

from scheduler import Schedule

SCRIPTS = Path(__file__).resolve().parents[3] / 'skills/agent-workers/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('workers', SCRIPTS / 'agent-workers.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
core, rex = w.core, w.rex
write_json, state_lock = w.write_json, w.task_state_lock
TASK, OFFLINE = 't-000001', 't-000002'
OWNER = {'pid': 7, 'name': 'pi'}
BASE = '2030-01-01T00:00:00Z'
LATER = '2030-01-01T00:00:01Z'
NOW = 1893456060


@dataclass(frozen=True)
class Case:
    name: str
    actors: tuple[str, ...]
    bound: int = 0  # Switches away from an actor that could keep running.
    backend: str = 'core'
    state: str = 'running'
    submission: str = 'sent'
    native: str | None = 'working'
    saw_working: bool = True
    result: str = 'stable'
    ack: bool = True


def cases():
    for backend in ('core', 'rex'):
        unsent = dict(backend=backend, state='start_failed', submission='not_sent',
                      native='idle', saw_working=False, result='missing')
        yield Case(f'{backend}-recheck', ('recheck',), **dict(unsent, native='working'))
        yield Case(f'{backend}-uncertain', ('recheck', 'submit', 'worker-finish'), 2,
                   **dict(unsent, state='not_started', submission='unknown', native='working'))
        yield Case(f'{backend}-uncertain-nonce', ('nonce-recheck',),
                   **dict(unsent, state='not_started', submission='unknown', native='working', result='invalid'))
        for outcome in ('sent', 'unknown'):
            yield Case(f'{backend}-resend-{outcome}', ('submit',), backend=backend,
                       state='not_started', submission=outcome, native='idle',
                       saw_working=False, result='missing')
        yield Case(f'{backend}-recovery', ('recheck', 'submit', 'retry'), 2, ack=False, **unsent)
        yield Case(f'{backend}-close', ('submit', 'close'), 2, **unsent)
        yield Case(f'{backend}-run', ('run', 'worker-finish', 'wait'), 2,
                   **dict(unsent, state='starting'))
        yield Case(f'{backend}-observers', ('wait', 'recheck', 'worker-finish'), 2, backend)
        yield Case(f'{backend}-exit', ('wait', 'worker-exit'), 1, backend)
        yield Case(f'{backend}-resume', ('wait', 'worker-resume'), 1, backend, native=None)
        for status in ('working', 'blocked', 'error', 'idle', 'done', None):
            yield Case(f'{backend}-delivery-{status}', ('wait',), backend=backend, native=status,
                       saw_working=status != 'idle')
        for result in ('fresh', 'fresh-file', 'invalid', 'missing'):
            yield Case(f'{backend}-file-{result}', ('wait',), backend=backend, native=None, result=result)
        yield Case(f'{backend}-unobserved', ('wait',), backend=backend, native=None, saw_working=False)
    yield Case('batch', ('batch',), native='done')
    yield Case('batch-recheck', ('batch-recheck',), native='done')


class World:
    def __init__(self, case, schedule):
        self.case = case
        self.s = schedule
        self.native = case.native
        self.ended = case.native == 'done'
        self.turn = int(self.ended or case.native in ('blocked', 'error') or
                        (case.native is None and case.saw_working))
        self.gone = False
        self.sends = int(case.submission in ('unknown', 'sent'))
        self.result = case.result
        self.clock = 0.0
        self.last = {}
        self.task_ids = {}
        self.command = local()
        self.failures = {}
        self.fallback_reads = {}
        self.lines = []
        self.locked = False
        self.seed(TASK, case.state, case.submission)
        if case.name.startswith('batch'):
            self.seed(OFFLINE, 'blocked', 'sent')
        self.put_result(case.result)
        w.core = SimpleNamespace(validate=core.validate, CoreError=core.CoreError, status=core.status,
                                 ready=self.ready, get=self.get, call=self.call, close=self.close)
        w.rex = SimpleNamespace(validate=rex.validate, RexError=rex.RexError, get=self.get,
                                send=self.rex_send, close=self.close)
        w.agent_index = self.agent_index
        w.notify = self.notify
        w.emit = self.emit
        w.write_json = self.write
        w.task_state_lock = self.lock
        w.time = SimpleNamespace(time=lambda: NOW, monotonic=lambda: self.clock, sleep=self.sleep)
        self.s.trace.append(f'seed: {case.backend} {case.state}/{case.submission}, '
                            f'native={self.native}, sends={self.sends}, result={case.result}')

    def seed(self, task_id, state, submission):
        directory = w.task_dir(task_id)
        directory.mkdir(parents=True)
        agent = 'horch-' + task_id[2:]
        task = dict(task_id=task_id, nonce=task_id, harness='pi', agent=agent, worker='fixture',
                    created_at=w.iso_now(), pane_id=agent, result_path=str(directory / 'result.json'))
        if self.case.backend == 'core':
            binding = dict(kind='core', executable='/fixture/core', session='fixture', core_id='core',
                           endpoint='/fixture/core.sock', env={}, terminal=agent, name=agent, nonce=task_id)
        else:
            uuid = '00000000-0000-0000-0000-000000000001'
            binding = dict(kind='rex', executable='/fixture/rex', host_id='host', instance_id='instance',
                           endpoint='unix:///fixture/rex.sock', block='block:' + uuid, window='window:' + uuid,
                           session='session:' + uuid, label=f'{agent}-{task_id}', harness='pi')
            task.update(workspace_id=binding['session'], pane_id=binding['block'])
        task['backend'] = binding
        self.task_ids[binding.get('terminal') or binding['block']] = task_id
        initial = dict(w.default_state(), state=state, submission=submission, saw_working=self.case.saw_working)
        if submission != 'not_sent':
            initial['startup_ready'] = True
            if self.case.backend == 'core':
                initial['baseline_seq'] = 0
            else:
                initial.update(baseline_status_at=BASE, baseline_status_owner=OWNER)
        write_json(directory / 'task.json', task)
        write_json(directory / 'state.json', initial)
        self.last[task_id] = initial

    def put_result(self, kind):
        if kind == 'missing':
            return
        directory = w.task_dir(TASK)
        output = directory / 'answer.txt'
        output.write_text('answer\n')
        result = directory / 'result.json'
        write_json(result, dict(task_id=TASK, nonce='wrong' if kind == 'invalid' else TASK,
                                status='completed', summary='answer', files=[output.name], question=None))
        for path, fresh in ((output, kind == 'fresh-file'), (result, kind == 'fresh')):
            stamp = NOW if fresh else NOW - 16
            os.utime(path, (stamp, stamp))
        self.result = kind

    def step(self):
        if self.locked:
            raise RuntimeError('scheduler point inside task_state_lock; inspect the new transaction')
        self.s.point()

    @contextmanager
    def lock(self, directory):
        self.step()
        with state_lock(directory):
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

    def fail(self, prop, why):
        self.failures.setdefault(prop, [*self.s.trace, why])

    def write(self, path, value):
        write_json(path, value)
        if path.name != 'state.json':
            return
        task_id = path.parent.name
        before = self.last[task_id]
        self.last[task_id] = value.copy()
        state, sub, closed = value['state'], value['submission'], value['closed']
        self.s.record(f'write {task_id} {state}/{sub} closed={closed}')
        wait = self.command.wait
        valid_result = task_id == TASK and self.result not in ('missing', 'invalid')
        if wait is not None:
            if wait.recheck and before['submission'] == 'not_sent' and (sub == 'sent' or state == 'running'):
                self.fail('P2', 'recheck promoted not_sent')
            if before['submission'] == 'unknown' and sub == 'sent' and not valid_result:
                self.fail('P2', f'wait promoted unknown to sent without a nonce-bound result for {task_id}')
        if (before['closed'] and not closed) or (before['state'] == 'done' and state != 'done'):
            self.fail('P3', 'done or closed reverted')
        if state == 'done' and before['state'] != 'done':
            cause = value['settled_by']
            if cause == 'result_file':
                # Keep the settling waiter's observations for checks at close and delivery.
                reads = self.command.null_reads
                self.fallback_reads[task_id] = reads
                eligible = (sub == 'sent' and value['saw_working'] and self.result == 'stable'
                            and reads.get(task_id, 0) > 0)
            else:
                eligible = cause == 'native' and self.ended and self.native not in ('working', 'blocked', 'error')
            if not valid_result or not eligible:
                self.fail('P4', f'settled_by={cause} with native={self.native}, ended={self.ended}, result={self.result}')

    def check_confirmation(self, task_id):
        reads = self.fallback_reads.get(task_id)
        if reads is not None and reads.get(task_id, 0) < 2:
            self.fail('P4', f'result_file for {task_id} lacks a second live null-status observation')

    def emit(self, line):
        if 'error' in line:
            self.s.record(line['error'])
        if 'summary' not in line:
            return
        self.lines.append(line)
        self.s.record(f"wait_line {line['task_id']} {line['state']} summary={line['summary']}")
        if line['summary'] is not None:
            task_id = line['task_id']
            if line['state'] != 'done' or self.last[task_id]['state'] != 'done':
                self.fail('P4', 'delivered without durable done')
            elif task_id in self.fallback_reads:
                self.check_confirmation(task_id)
            elif self.native in ('working', 'blocked', 'error'):
                self.fail('P4', f'delivered while native={self.native}')

    def snapshot(self):
        if self.gone:
            return None
        if self.case.backend == 'core':
            return dict(state='live', reported=self.native is not None, turn=self.turn,
                        status={'state': self.native} if self.native else None)
        return dict(state='live', status=self.native, owner=OWNER if self.native else None,
                    updated_at=(LATER if self.native != 'idle' else BASE) if self.native else None)

    def get(self, binding):
        self.step()
        task_id = self.task_ids[binding.get('terminal') or binding['block']]
        if task_id == OFFLINE:
            self.s.record(f'core.get {OFFLINE} -> endpoint unavailable')
            raise core.CoreError('endpoint unavailable')
        self.s.record(f'{self.case.backend}.get -> {"gone" if self.gone else self.native}')
        if self.command.wait is not None:
            reads = self.command.null_reads
            reads[task_id] = reads.get(task_id, 0) + 1 if not self.gone and self.native is None else 0
        return self.snapshot()

    def ready(self, binding, seconds):
        self.step()
        self.s.record(f'core.ready -> {"gone" if self.gone else self.native}')
        if self.gone or self.native != 'idle':
            raise core.CoreError('no idle terminal')
        return self.snapshot()

    def accepted(self, text):
        if str(w.task_dir(TASK) / 'brief.md') not in text:
            raise ValueError('unexpected send payload')
        self.sends += 1
        self.s.record(f'{self.case.backend}.send brief.md -> accepted #{self.sends}')
        if self.sends > 1:
            self.fail('P1', 'brief pointer delivered twice')
        self.ended = False
        if self.case.ack:
            self.native = 'working'

    def call(self, binding, method, **params):
        self.step()
        if method != 'terminal.send' or params['if'] != 'idle':
            raise ValueError(f'unmodeled core.call: {method}')
        if self.gone or self.native != 'idle':
            raise core.CoreError('terminal not idle')
        self.accepted(params['text'])
        return {'started': self.case.ack}

    def rex_send(self, binding, text, baseline):
        self.step()
        if self.snapshot() != baseline:
            raise rex.RexError('worker changed before paste', 'not_sent')
        self.accepted(text)

    def close(self, binding):
        self.step()
        task_id = self.task_ids[binding.get('terminal') or binding['block']]
        self.s.record(f'{self.case.backend}.close {task_id} (native={self.native}) -> gone')
        if self.command.close_id != task_id and self.last[task_id]['state'] != 'done':
            self.fail('P6', f'closed {task_id} without durable done or an explicit close for it')
        self.check_confirmation(task_id)
        self.gone, self.native = True, None
        return {'terminal' if self.case.backend == 'core' else 'block': 'closed'}

    def agent_index(self):
        self.step()
        return {}

    def notify(self, *args):
        self.step()

    def sleep(self, seconds):
        self.step()
        # No further ACK in the no-ack fixture unless another actor intervenes.
        self.clock += max(seconds, 90)

    def worker(self, action):
        if self.gone or not self.sends:
            return
        if action == 'worker-finish':
            self.put_result('fresh')
            self.s.record('write result.json')
            self.step()
            if self.gone:
                return
            self.turn += 1
            self.ended = True
            self.native = 'done'
        elif action == 'worker-exit':
            self.gone, self.native = True, None
        else:
            self.native = 'working'
        self.s.record(f'native -> {"gone" if self.gone else self.native}')

    def act(self, name):
        self.command.wait = None
        self.command.close_id = None
        self.command.null_reads = {}
        args = SimpleNamespace(task_id=TASK)
        if name.startswith('worker-'):
            self.worker(name)
        elif name == 'run':
            directory = w.task_dir(TASK)
            submit = w.submit_core_task if self.case.backend == 'core' else w.submit_rex_task
            submit(directory, w.load_task(directory, TASK), w.load_state(directory))
        elif name in ('submit', 'retry'):
            try:
                w.cmd_submit(args)
            except SystemExit as exc:
                if exc.code != 1 or not self.s.trace[-1].endswith(': submission_unsafe'):
                    raise
        elif name == 'close':
            self.command.close_id = args.task_id
            w.cmd_close(args)
        else:
            batch = name.startswith('batch')
            args = SimpleNamespace(task_ids=[OFFLINE, TASK] if batch else [TASK], recheck='recheck' in name,
                                   config=str(SCRIPTS.parent / 'references/workers.example.toml'),
                                   all=batch, max_seconds=0)
            self.command.wait = args
            try:
                w.cmd_wait(args)
            except core.CoreError as exc:
                if not batch or str(exc) != 'endpoint unavailable':
                    raise
                if not args.recheck:
                    self.fail('P5', f'batch aborted; {TASK} still {self.last[TASK]["state"]}')
                return
            if batch and args.recheck:
                self.fail('P5', f'explicit recheck of {OFFLINE} returned without its endpoint error')
            elif batch and not any(line['task_id'] == TASK and line['state'] == 'done'
                                   and line['summary'] == 'answer' for line in self.lines):
                self.fail('P5', 'healthy summary missing from batch')


def explore(case, replay):
    stack = [replay or ()]
    witnesses = {}
    count = 0
    while stack:
        prefix = stack.pop()
        with tempfile.TemporaryDirectory() as tmp:
            os.environ['XDG_STATE_HOME'] = tmp
            schedule = Schedule()
            world = World(case, schedule)
            path, forks = schedule.run({a: partial(world.act, a) for a in case.actors}, prefix, case.bound)
            for task_id in world.fallback_reads:
                world.check_confirmation(task_id)
            if replay is None:
                stack.extend(forks)
            for prop, trace in world.failures.items():
                if prop not in witnesses or len(trace) < len(witnesses[prop][0]):
                    witnesses[prop] = trace, path
        count += 1
    print(f'{case.name}: {count} schedules; {", ".join(witnesses) or "pass"}')
    for prop, (trace, path) in witnesses.items():
        print(f'  {prop} --case {case.name} --schedule {",".join(path)}')
        for event in trace:
            print(f'    {event}')
    return count, bool(witnesses)


def main():
    catalog = {case.name: case for case in cases()}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=catalog)
    parser.add_argument('--schedule', help='replay the comma-separated actor choices for one case')
    args = parser.parse_args()
    if args.schedule and not args.case:
        parser.error('--schedule requires --case')
    started = time.monotonic()
    counts = [explore(case, args.schedule.split(',') if args.schedule else None)
              for case in ([catalog[args.case]] if args.case else catalog.values())]
    failures = sum(failed for _, failed in counts)
    print(f'{sum(n for n, _ in counts)} schedules, {failures}/{len(counts)} cases with findings, '
          f'{time.monotonic() - started:.2f}s')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
