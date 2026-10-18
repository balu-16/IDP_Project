"""Run application checks only after the detached FiQA batch has finished."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
STATE = SELF.parent / 'verification.json'
LOG = SELF.parent / 'verification_supervisor.log'
FIQA = ROOT / 'research/runs/accuracy_v3_redundancy_fiqa_full_execution.json'
PYTHON = ROOT / 'backend/.venv/bin/python'


def utc():
    return datetime.now(timezone.utc).isoformat()


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write((json.dumps(payload, indent=2) + '\n').encode())
        handle.flush()
        os.fsync(handle.fileno())
        temporary = handle.name
    os.replace(temporary, path)


def sources():
    paths = {SELF, ROOT / 'backend/main.py', ROOT / 'backend/requirements.txt',
        ROOT / 'frontend/package.json', ROOT / 'frontend/tests/retrieval.test.ts',
        ROOT / 'frontend/src/pages/Chat.tsx', ROOT / 'frontend/src/components/ChatBubble.tsx',
        ROOT / 'frontend/src/lib/contracts.ts', ROOT / 'frontend/src/lib/retrieval.ts'}
    for directory in ('backend/services', 'backend/services/gas_selector', 'backend/routes', 'backend/tests'):
        paths.update((ROOT / directory).glob('*.py'))
    paths.add(ROOT / 'backend/services/gas_selector/ORIGINS.json')
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def alive(pid):
    try:
        command = Path(f'/proc/{pid}/cmdline').read_bytes()
        return b'launch_fiqa_full_test.py' in command and b'--supervise' in command
    except OSError:
        return False


def update_plan(state):
    path = ROOT / 'plan.md'
    start, end = '<!-- APPLICATION_GAS_CHECKS_START -->', '<!-- APPLICATION_GAS_CHECKS_END -->'
    content = path.read_text()
    if content.count(start) != 1 or content.count(end) != 1:
        return
    lines = [start, f"Application verification status: **{state['status']}** ({utc()}).",
        'Detailed results: `build/application_gas/verification.json`; per-check logs are beside it.']
    for name, item in state.get('checks', {}).items():
        lines.append(f"- {name}: {item['status']} (exit {item.get('returncode', 'pending')}).")
    if state.get('error'):
        lines.append(f"Unresolved: {state['error']}")
    lines.append(end)
    prefix, rest = content.split(start)
    _, suffix = rest.split(end)
    path.write_text(prefix + '\n'.join(lines) + suffix)


def worker(resume):
    with (SELF.parent / '.verification.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text())
        state.update(pid=os.getpid(), status='waiting_for_fiqa', updated_utc=utc())
        write(STATE, state)
        child, stopped = None, False
        def stop(signum, frame):
            nonlocal stopped
            stopped = True
            if child is not None and child.poll() is None:
                child.send_signal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        try:
            while True:
                if stopped:
                    raise InterruptedError('Application checks interrupted')
                fiqa = json.loads(FIQA.read_text())
                if fiqa['status'] in ('completed', 'gate_failed') and not alive(fiqa.get('supervisor_pid')):
                    break
                if fiqa['status'] in ('failed', 'interrupted') and not alive(fiqa.get('supervisor_pid')):
                    raise RuntimeError('FiQA did not finish; resume FiQA before application verification')
                time.sleep(15)
            if sources() != state['sources']:
                raise ValueError('Application sources changed while waiting; checks were not run')
            state.update(status='running', started_checks_utc=utc(), fiqa_status=fiqa['status'])
            write(STATE, state)
            commands = (
                ('backend_regressions', ROOT / 'backend', [str(PYTHON), '-m', 'unittest', 'discover', '-s', 'tests', '-v'], {}),
                ('frontend_contracts', ROOT / 'frontend', ['npm', 'run', 'test:retrieval'], {}),
                ('typescript', ROOT / 'frontend', ['node_modules/.bin/tsc', '--noEmit', '-p', 'tsconfig.app.json'], {}),
                ('frontend_lint', ROOT / 'frontend', ['npm', 'run', 'lint'], {}),
                ('frontend_build', ROOT / 'frontend', ['npm', 'run', 'build'], {}),
                ('local_l6_smoke', ROOT / 'backend', [str(PYTHON), '-m', 'unittest', 'discover', '-s', 'tests',
                    '-p', 'test_l6_gas.py', '-k', 'LocalL6Smoke', '-v'], {'QUBIT_TEST_L6': '1'}))
            for name, cwd, command, extra in commands:
                if stopped:
                    raise InterruptedError('Application checks interrupted')
                if sources() != state['sources']:
                    raise ValueError('Application sources changed during verification')
                prior = state['checks'].get(name)
                if prior and prior['status'] == 'passed':
                    continue
                log = SELF.parent / f'{name}.log'
                item = {'status': 'running', 'started_utc': utc(), 'command': command, 'log': str(log)}
                state['checks'][name] = item
                write(STATE, state)
                print(f'{utc()} START {name}', flush=True)
                env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1',
                    TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false',
                    OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2', **extra)
                with log.open('a') as handle:
                    handle.write(f'\n{utc()} {command!r}\n')
                    handle.flush()
                    child = subprocess.Popen(command, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL)
                    if stopped:
                        child.terminate()
                    code = child.wait(timeout=300)
                    child = None
                item.update(status='passed' if code == 0 else 'failed', returncode=code, ended_utc=utc())
                write(STATE, state)
                if code != 0:
                    raise RuntimeError(f'{name} failed; inspect {log.relative_to(ROOT)}')
            if sources() != state['sources']:
                raise ValueError('Application sources changed before checks completed')
            state.update(status='passed', completed_utc=utc())
            write(STATE, state)
            update_plan(state)
            return 0
        except BaseException as exc:
            if child is not None and child.poll() is None:
                child.terminate()
                child.wait()
            state.update(status='interrupted' if isinstance(exc, (KeyboardInterrupt, InterruptedError)) else 'failed',
                         error=f'{type(exc).__name__}: {exc}', updated_utc=utc())
            write(STATE, state)
            update_plan(state)
            print(state['error'], flush=True)
            return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.worker:
        return worker(args.resume)
    if STATE.exists():
        if not args.resume:
            raise ValueError('Application verification exists; use --resume')
        state = json.loads(STATE.read_text())
        try:
            command = Path(f"/proc/{state.get('pid')}/cmdline").read_bytes()
        except OSError:
            command = b''
        if str(SELF).encode() in command and b'--worker' in command:
            raise ValueError('Application verification is already waiting/running')
        if sources() != state['sources']:
            raise ValueError('Source identity changed; run the documented checks manually after reviewing changes')
    else:
        state = {'schema': 'application-gas-verification-v1', 'status': 'queued',
                 'created_utc': utc(), 'checks': {}, 'sources': sources(), 'wait_for': str(FIQA)}
    write(STATE, state)
    with LOG.open('ab', buffering=0) as log:
        command = [str(PYTHON), '-u', str(SELF), '--worker']
        if args.resume:
            command.append('--resume')
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
    print(json.dumps({'verification_pid': process.pid, 'state': str(STATE), 'log': str(LOG)}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(1)
