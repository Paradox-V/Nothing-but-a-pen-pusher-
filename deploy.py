"""部署脚本：上传新模块到服务器并重启 gunicorn"""
import os
import time
import paramiko

HOST = "49.232.239.68"
USER = "ubuntu"
PASS = "Dyp1213812138"
REMOTE_BASE = "/opt/news_aggregator"
LOCAL_BASE = r"C:\Users\35368\Desktop\信源汇总 - 副本"

FILES = [
    "app.py",
    "config.yaml",
    "templates/index.html",
    "modules/topic/__init__.py",
    "modules/topic/service.py",
    "modules/topic/title_gen.py",
    "modules/topic/routes.py",
    "modules/creator/__init__.py",
    "modules/creator/framework.py",
    "modules/creator/article.py",
    "modules/creator/image_gen.py",
    "modules/creator/routes.py",
]


def ssh_exec(ssh, cmd, sudo=False):
    """执行命令，支持 sudo"""
    if sudo:
        cmd = f"echo '{PASS}' | sudo -S {cmd}"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    return stdout.read().decode(), stderr.read().decode()


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"连接 {HOST}...")
    ssh.connect(HOST, username=USER, password=PASS)

    # 在 /tmp 创建临时上传目录
    TMP_DIR = "/tmp/news_deploy"
    ssh_exec(ssh, f"rm -rf {TMP_DIR} && mkdir -p {TMP_DIR}")

    # 用 SFTP 上传到 /tmp
    sftp = ssh.open_sftp()
    for f in FILES:
        local_path = os.path.join(LOCAL_BASE, f)
        if not os.path.exists(local_path):
            print(f"  跳过: {f}")
            continue

        # 确保远程子目录存在
        remote_dir = os.path.dirname(f).replace("\\", "/")
        if remote_dir:
            ssh_exec(ssh, f"mkdir -p {TMP_DIR}/{remote_dir}")

        tmp_remote = f"{TMP_DIR}/{f}".replace("\\", "/")
        print(f"  上传: {f}")
        sftp.put(local_path, tmp_remote)

    sftp.close()

    # sudo 复制到目标目录
    print("复制文件到目标目录...")
    for f in FILES:
        remote_dir = os.path.dirname(f).replace("\\", "/")
        if remote_dir:
            ssh_exec(ssh, f"mkdir -p {REMOTE_BASE}/{remote_dir}", sudo=True)
        ssh_exec(ssh, f"cp {TMP_DIR}/{f} {REMOTE_BASE}/{f}", sudo=True)
        print(f"  已部署: {f}")

    # 清理临时文件
    ssh_exec(ssh, f"rm -rf {TMP_DIR}")

    # 安装依赖
    print("检查依赖...")
    out, err = ssh_exec(ssh, "pip install litellm httpx -q 2>&1 | tail -3")
    if out.strip():
        print(f"  {out.strip()}")

    # 重启 gunicorn
    print("重启 gunicorn...")
    ssh_exec(ssh, "pkill -f 'gunicorn.*app:app'", sudo=True)
    time.sleep(2)
    # 用 ubuntu 用户启动 gunicorn
    ssh.exec_command(
        f"cd {REMOTE_BASE} && nohup gunicorn --workers 1 --threads 4 "
        "--bind 0.0.0.0:5000 --timeout 120 app:app > /tmp/gunicorn.log 2>&1 &"
    )
    time.sleep(3)

    # 验证
    out, _ = ssh_exec(ssh, "curl -s http://localhost:5000/api/status")
    print(f"状态: {out[:300]}")

    out, _ = ssh_exec(ssh, "ps aux | grep 'gunicorn.*app:app' | grep -v grep")
    print(f"进程:\n{out}")

    # 检查新模块 API
    out, _ = ssh_exec(ssh, "curl -s http://localhost:5000/api/topic/industries")
    print(f"选题行业API: {out[:200]}")

    ssh.close()
    print("\n部署完成!")


if __name__ == "__main__":
    main()
