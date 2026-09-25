import base64
import io
import json
import os
import socket
import subprocess
import sys
import time
import litelm
from PIL import Image

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
    '-qmp', 'unix:/tmp/openbot-qmp.sock,server,nowait',
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

def wait_for_gui(timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if qemu_proc.poll() is not None:
            return False
        proc = subprocess.run(
            SSH_CMD + ['test -S /tmp/.X11-unix/X0 && pgrep -x xfwm4'],
            capture_output=True, timeout=10)
        if proc.returncode == 0:
            return True
        time.sleep(3)
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
    if not wait_for_gui():
        if qemu_proc.poll() is not None:
            qemu_proc = None
            return 'VM failed to start:\n' + open('qemu.log').read()
        return 'VM booted, but GUI is not up yet (still running; check the GTK window).'
    return 'VM started (GUI up).'

def stop_vm():
    global qemu_proc
    if not qemu_proc or qemu_proc.poll() is not None:
        qemu_proc = None
        return 'VM not running.'
    try:
        subprocess.run(SSH_CMD + ['sudo poweroff'], capture_output=True, text=True, timeout=10)
    except Exception:
        pass
    try:
        qemu_proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
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

QMP_SOCK = '/tmp/openbot-qmp.sock'

def qmp_screendump():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(QMP_SOCK)
    f = s.makefile('rw')
    def reply():
        while True:
            msg = json.loads(f.readline())
            if 'event' not in msg:
                return msg
    json.loads(f.readline())
    f.write('{"execute":"qmp_capabilities"}\n'); f.flush()
    reply()
    f.write('{"execute":"screendump","arguments":{"filename":"screen.ppm"}}\n'); f.flush()
    result = reply()
    f.close()
    s.close()
    if 'error' in result:
        raise Exception(f"QMP: {result['error'].get('desc')}")

def screenshot():
    if not qemu_proc or qemu_proc.poll() is not None:
        raise Exception('VM not running')
    qmp_screendump()
    img = Image.open('screen.ppm')
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    os.remove('screen.ppm')
    return f'VM screenshot captured ({img.width}x{img.height}).', base64.b64encode(buf.getvalue()).decode()

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
    {'type': 'function', 'function': {
        'name': 'screenshot',
        'description': 'Capture the VM display and attach it as an image.',
        'parameters': {'type': 'object', 'properties': {}},
    }},
]

HANDLERS = {
    'start': start_vm,
    'stop': stop_vm,
    'run': run_command,
    'screenshot': screenshot,
}

SYSTEM = '''You are OpenBot: agent that controls a Virtual Machine (VM) with a graphical desktop.
The VM runs Alpine Linux with an XFCE desktop (taskbar, file manager) and firefox; commands execute as user "alpine" via ash (busybox shell, not bash) with passwordless sudo available.
The display is fixed at 1024x768 and never changes; screenshot pixel coordinates map exactly to xdotool coordinates.
Use the start and stop tools to manage the VM.
Use the run tool to execute shell commands in the VM.
Use the screenshot tool to see the VM display.
You can browse the web with a graphical browser: run("launch firefox <url>") opens firefox on the desktop; take a screenshot to see the page and interact by running commands. Close apps with: run("pkill firefox").
Control the GUI with xdotool.
If you need something only the user can provide, stop and ask instead of guessing.
Ask when you hit: a login or sign-up page, a password or one-time code, a CAPTCHA, payment or purchase confirmation, legal terms or cookie consent to accept, sending anything on the user's behalf (email, message, post), an irreversible or destructive action (deleting files, wiping state), installing packages or making system-wide changes, anything the user must physically do (plug in a security key, press a button on a device), or a task too ambiguous to act on.
Never invent credentials, guess passwords, or attempt to bypass a CAPTCHA.
To ask: reply with a plain message and no tool calls. Say what you need, why, and where you got stuck.
Batch every question into one message, and keep working autonomously when you are not blocked.'''

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
    while True:
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
            image_b64 = None
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
            if isinstance(result, tuple):
                result, image_b64 = result
            color = DARK_RED if error else DARK_GREEN
            print(f'{color}{result}{RESET}', flush=True)
            messages.append({'role': 'tool', 'tool_call_id': tc.id, 'content': result})
            if image_b64:
                messages.append({'role': 'user', 'content': [
                    {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{image_b64}'}},
                    {'type': 'text', 'text': 'VM screenshot (attached).'},
                ]})
