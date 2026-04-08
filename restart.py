import paramiko, time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('49.232.239.68', username='ubuntu', password='Dyp1213812138')

def run(cmd):
    transport = ssh.get_transport()
    channel = transport.open_session()
    channel.settimeout(10)
    channel.exec_command(cmd)
    try:
        out = channel.makefile('r').read()
    except:
        out = ''
    try:
        err = channel.makefile_stderr('r').read()
    except:
        err = ''
    channel.close()
    return out, err

# 1. Kill gunicorn
run('pkill -f gunicorn || true')
time.sleep(1)
out, _ = run('pgrep -f gunicorn')
if out.strip():
    run('pkill -9 -f gunicorn')
    time.sleep(1)
print('Killed old processes')

# 2. Write a startup script on server
script = """#!/bin/bash
cd /opt/news_aggregator
/home/ubuntu/.local/bin/gunicorn -k gthread --threads 4 --workers 1 --bind 0.0.0.0:5000 --timeout 120 app:app > /tmp/gunicorn.log 2>&1 &
"""
run(f"echo '{script}' > /tmp/start_gunicorn.sh && chmod +x /tmp/start_gunicorn.sh")

# 3. Execute startup script in background
transport = ssh.get_transport()
channel = transport.open_session()
channel.exec_command('/tmp/start_gunicorn.sh')
channel.close()
time.sleep(4)

# 4. Verify
out, _ = run('ps aux | grep gunicorn | grep -v grep')
print(f'Processes:\n{out}')

out, _ = run('cat /tmp/gunicorn.log | tail -10')
print(f'Log:\n{out}')

out, _ = run('curl -s http://localhost:5000/api/status')
print(f'Status:\n{out[:300]}')

out, _ = run('curl -s http://localhost:5000/api/topic/industries')
print(f'Industries:\n{out[:200]}')

ssh.close()
print('Done')
