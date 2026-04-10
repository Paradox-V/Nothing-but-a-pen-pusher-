"""远程重启 gunicorn 服务

配置通过环境变量读取：
  DEPLOY_HOST     - 服务器地址
  DEPLOY_USER     - SSH 用户名
  DEPLOY_SSH_KEY_PATH - SSH 私钥路径
"""
import os
import time


def main():
    import paramiko

    HOST = os.environ.get("DEPLOY_HOST", "")
    USER = os.environ.get("DEPLOY_USER", "ubuntu")
    SSH_KEY_PATH = os.environ.get("DEPLOY_SSH_KEY_PATH", os.path.expanduser("~/.ssh/id_rsa"))

    if not HOST:
        print("错误: 请设置环境变量 DEPLOY_HOST")
        print("  export DEPLOY_HOST=your_server_ip")
        print("  或创建 .env 文件（参考 .env.example）")
        return

    ssh = paramiko.SSHClient()
    known_hosts = os.path.expanduser("~/.ssh/known_hosts")
    if os.path.exists(known_hosts):
        ssh.load_host_keys(known_hosts)
    ssh.set_missing_host_key_policy(paramiko.RejectPolicy())

    print(f"连接 {HOST}...")
    try:
        ssh.connect(HOST, username=USER, key_filename=SSH_KEY_PATH)
    except paramiko.AuthenticationException:
        print(f"SSH Key 认证失败，请检查密钥: {SSH_KEY_PATH}")
        return
    except Exception as e:
        print(f"连接失败: {e}")
        return

    def run(cmd):
        transport = ssh.get_transport()
        channel = transport.open_session()
        channel.settimeout(10)
        channel.exec_command(cmd)
        try:
            out = channel.makefile('r').read()
        except Exception:
            out = ''
        try:
            err = channel.makefile_stderr('r').read()
        except Exception:
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


if __name__ == "__main__":
    # 尝试加载 .env 文件
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    main()
