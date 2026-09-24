import json
import socket
import subprocess
import sys
import time

import litelm

QEMU_CMD = [
    'qemu-system-x86_64',
    '-machine', 'q35,accel=kvm',
    '-cpu', 'host',
    '-smp', '2',
    '-m', '3G',
    '-drive', 'file=openbot.qcow2,if=virtio,cache=writeback',
    '-nic', 'user,model=virtio-net-pci,hostfwd=tcp::2222-:22',
    '-device', 'virtio-vga',
    '-display', 'gtk',
    '-device', 'virtio-tablet-pci',
]

qemu_proc = None

def wait_for_ssh(timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if qemu_proc.poll() is not None:
            return False
        try:
            with socket.create_connection(('127.0.0.1', 2222), timeout=2) as s:
                if s.recv(16).startswith(b'SSH-'):
                    return True
        except OSError:
            pass
        time.sleep(2)
    return False

def start_vm():
    global qemu_proc
    if qemu_proc and qemu_proc.poll() is None:
        return 'VM already running.'
    with open('qemu.log', 'w') as log:
        qemu_proc = subprocess.Popen(QEMU_CMD, stdout=log, stderr=log)
    time.sleep(1)
    if qemu_proc.poll() is not None:
        qemu_proc = None
        return 'VM failed to start:\n' + open('qemu.log').read()
    if not wait_for_ssh():
        if qemu_proc.poll() is not None:
            qemu_proc = None
            return 'VM failed to start:\n' + open('qemu.log').read()
        return 'VM did not finish booting within 120s (still running).'
    return 'VM started (boot complete).'

def stop_vm():
    global qemu_proc
    if not qemu_proc or qemu_proc.poll() is not None:
        qemu_proc = None
        return 'VM not running.'
    qemu_proc.terminate()
    try:
        qemu_proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        qemu_proc.kill()
        qemu_proc.wait()
    return 'VM stopped.'

SSH_CMD = [
    'ssh', '-p', '2222', '-i', 'openbot_key',
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'UserKnownHostsFile=/dev/null',
    '-o', 'BatchMode=yes',
    '-o', 'LogLevel=ERROR',
    'alpine@127.0.0.1',
]

def run_command(command):
    try:
        proc = subprocess.run(SSH_CMD + [command], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise Exception('timed out after 30s')
    output = (proc.stdout + proc.stderr).strip() or '(no output)'
    if proc.returncode == 255:
        return f'Error: ssh failed (VM not running?): {output}'
    return f'exit={proc.returncode}\n{output}'

TOOLS = [
    {'type': 'function', 'function': {
        'name': 'start',
        'description': 'Start the OpenBot virtual machine.',
        'parameters': {'type': 'object', 'properties': {}},
    }},
    {'type': 'function', 'function': {
        'name': 'stop',
        'description': 'Stop the OpenBot virtual machine.',
        'parameters': {'type': 'object', 'properties': {}},
    }},
    {'type': 'function', 'function': {
        'name': 'run',
        'description': 'Execute a shell command in the VM.',
        'parameters': {
            'type': 'object',
            'properties': {'command': {'type': 'string', 'description': 'Shell command to execute'}},
            'required': ['command'],
        },
    }},
]

HANDLERS = {
    'start': start_vm,
    'stop': stop_vm,
    'run': run_command,
}

SYSTEM = '''You are OpenBot: agent that has control over the Virtual Machine (VM).
Use the start and stop tools to manage the VM.
Use the run tool to execute shell commands in the VM.'''

messages = [
    {'role': 'system', 'content': SYSTEM},
]

BRIGHT_CYAN = '\033[96m'
DARK_GREEN = '\033[2m\033[32m'
BRIGHT_GREEN = '\033[92m'
DARK_RED = '\033[2m\033[31m'
GRAY = '\033[90m'
RESET = '\033[0m'

pending = ' '.join(sys.argv[1:]).strip() or None

while True:
    content = pending or input('>>> ').strip()
    pending = None
    if not content:
        continue
    messages.append({'role': 'user', 'content': content})
    for _ in range(10):
        stream = litelm.completion(
            'openrouter/glm-5.3-flash',
            messages=messages,
            tools=TOOLS,
            stream=True,
        )
        chunks = []
        streamed = False
        prev_kind = None
        for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, 'reasoning', None)
                if reasoning:
                    if prev_kind not in (None, 'reasoning'):
                        print()
                    print(f'{GRAY}{reasoning}{RESET}', end='', flush=True)
                    streamed = True
                    prev_kind = 'reasoning'
                if delta and delta.content:
                    if prev_kind not in (None, 'content'):
                        print()
                    print(f'{BRIGHT_CYAN}{delta.content}{RESET}', end='', flush=True)
                    streamed = True
                    prev_kind = 'content'
            chunks.append(chunk)
        if streamed:
            print()
        response = litelm.stream_chunk_builder(chunks)
        message = response.choices[0].message
        if not message.tool_calls:
            break
        for tc in message.tool_calls:
            print(f'{BRIGHT_GREEN}{tc.function.name}({tc.function.arguments}){RESET}', flush=True)
        messages.append({
            'role': 'assistant',
            'content': message.content or '',
            'tool_calls': [
                {'id': tc.id, 'type': 'function', 'function': {'name': tc.function.name, 'arguments': tc.function.arguments}}
                for tc in message.tool_calls
            ],
        })
        for tc in message.tool_calls:
            error = False
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError as exc:
                result = f'Error: invalid arguments: {exc}'
                error = True
            else:
                try:
                    result = HANDLERS[tc.function.name](**args)
                except KeyError:
                    result = f'Unknown tool: {tc.function.name}'
                    error = True
                except Exception as exc:
                    result = f'Error: {exc}'
                    error = True
            color = DARK_RED if error else DARK_GREEN
            print(f'{color}{result}{RESET}', flush=True)
            messages.append({'role': 'tool', 'tool_call_id': tc.id, 'content': result})
