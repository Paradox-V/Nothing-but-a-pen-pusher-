"""部署脚本：上传新模块到服务器并重启 gunicorn + scheduler

配置通过环境变量读取，不再硬编码凭据：
  DEPLOY_HOST     - 服务器地址
  DEPLOY_USER     - SSH 用户名
  DEPLOY_SSH_KEY_PATH - SSH 私钥路径（推荐）

也可通过 .env 文件配置（python-dotenv）
"""
import os
import time
import paramiko

# 从环境变量读取配置
HOST = os.environ.get("DEPLOY_HOST", "")
USER = os.environ.get("DEPLOY_USER", "ubuntu")
SSH_KEY_PATH = os.environ.get("DEPLOY_SSH_KEY_PATH", os.path.expanduser("~/.ssh/id_rsa"))
REMOTE_BASE = "/opt/news_aggregator"
LOCAL_BASE = os.path.dirname(os.path.abspath(__file__))

FILES = [
    # 应用入口
    "app.py",
    "scheduler.py",
    "config.yaml",
    # 依赖
    "requirements.txt",
    # 工具模块
    "utils/__init__.py",
    "utils/auth.py",
    "utils/config.py",
    "utils/crawl_trigger.py",
    "utils/scheduler_client.py",
    "utils/url_security.py",
    "utils/time.py",
    # AI 模块
    "ai/__init__.py",
    "ai/client.py",
    "ai/config.py",
    "ai/filter.py",
    "ai/analyzer.py",
    # 数据模块
    "modules/__init__.py",
    "modules/news/__init__.py",
    "modules/news/routes.py",
    "modules/news/db.py",
    "modules/news/aggregator.py",
    "modules/news/vector.py",
    "modules/hotlist/__init__.py",
    "modules/hotlist/routes.py",
    "modules/hotlist/db.py",
    "modules/hotlist/fetcher.py",
    "modules/hotlist/vector.py",
    "modules/rss/__init__.py",
    "modules/rss/routes.py",
    "modules/rss/db.py",
    "modules/rss/fetcher.py",
    "modules/rss/parser.py",
    "modules/rss/discover.py",
    "modules/rss/vector.py",
    "modules/topic/__init__.py",
    "modules/topic/routes.py",
    "modules/topic/service.py",
    "modules/topic/title_gen.py",
    "modules/creator/__init__.py",
    "modules/creator/routes.py",
    "modules/creator/framework.py",
    "modules/creator/article.py",
    "modules/creator/image_gen.py",
    "modules/creator/db.py",
    "modules/chat/__init__.py",
    "modules/chat/routes.py",
    "modules/chat/service.py",
    "modules/chat/db.py",
    # 归档模块
    "modules/archive/__init__.py",
    "modules/archive/manager.py",
    "modules/archive/routes.py",
]


def ssh_exec(ssh, cmd, sudo=False):
    """执行命令，支持 sudo"""
    if sudo:
        cmd = f"sudo {cmd}"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    return stdout.read().decode(), stderr.read().decode()


def main():
    if not HOST:
        print("错误: 请设置环境变量 DEPLOY_HOST")
        print("  export DEPLOY_HOST=your_server_ip")
        print("  或创建 .env 文件（参考 .env.example）")
        return

    ssh = paramiko.SSHClient()
    # 使用 known_hosts 验证，防止 MITM
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

    # 在 /tmp 创建临时上传目录
    TMP_DIR = "/tmp/news_deploy"
    ssh_exec(ssh, f"rm -rf {TMP_DIR} && mkdir -p {TMP_DIR}")

    # 用 SFTP 上传到 /tmp
    sftp = ssh.open_sftp()

    # 上传后端文件
    for f in FILES:
        local_path = os.path.join(LOCAL_BASE, f)
        if not os.path.exists(local_path):
            print(f"  跳过: {f}")
            continue
        remote_dir = os.path.dirname(f).replace("\\", "/")
        if remote_dir:
            ssh_exec(ssh, f"mkdir -p {TMP_DIR}/{remote_dir}")
        tmp_remote = f"{TMP_DIR}/{f}".replace("\\", "/")
        print(f"  上传: {f}")
        sftp.put(local_path, tmp_remote)

    # 上传前端构建产物
    frontend_dist = os.path.join(LOCAL_BASE, "frontend_dist")
    if os.path.isdir(frontend_dist):
        print("上传前端构建产物...")
        for root, dirs, files_to_upload in os.walk(frontend_dist):
            for fname in files_to_upload:
                local_file = os.path.join(root, fname)
                rel_path = os.path.relpath(local_file, LOCAL_BASE).replace("\\", "/")
                remote_dir = os.path.dirname(rel_path).replace("\\", "/")
                if remote_dir:
                    ssh_exec(ssh, f"mkdir -p {TMP_DIR}/{remote_dir}")
                print(f"  上传: {rel_path}")
                sftp.put(local_file, f"{TMP_DIR}/{rel_path}")

    sftp.close()

    # sudo 复制到目标目录
    print("复制文件到目标目录...")
    for f in FILES:
        remote_dir = os.path.dirname(f).replace("\\", "/")
        if remote_dir:
            ssh_exec(ssh, f"mkdir -p {REMOTE_BASE}/{remote_dir}", sudo=True)
        ssh_exec(ssh, f"cp {TMP_DIR}/{f} {REMOTE_BASE}/{f}", sudo=True)
        print(f"  已部署: {f}")

    # 复制前端构建产物
    if os.path.isdir(frontend_dist):
        ssh_exec(ssh, f"mkdir -p {REMOTE_BASE}/frontend_dist/assets", sudo=True)
        ssh_exec(ssh, f"cp -r {TMP_DIR}/frontend_dist/* {REMOTE_BASE}/frontend_dist/", sudo=True)
        print("  已部署: frontend_dist/")

    # 清理临时文件
    ssh_exec(ssh, f"rm -rf {TMP_DIR}")

    # 安装依赖
    print("检查依赖...")
    out, err = ssh_exec(ssh, f"cd {REMOTE_BASE} && pip install -r requirements.txt -q 2>&1 | tail -3")
    if out.strip():
        print(f"  {out.strip()}")

    # 通过 systemctl 重启服务
    print("重启 news-viewer (gunicorn)...")
    out, err = ssh_exec(ssh, "systemctl restart news-viewer", sudo=True)
    if err.strip():
        print(f"  warning: {err.strip()}")
    time.sleep(3)

    print("重启 news-scheduler...")
    out, err = ssh_exec(ssh, "systemctl restart news-scheduler", sudo=True)
    if err.strip():
        print(f"  warning: {err.strip()}")
    time.sleep(3)

    # 验证
    out, _ = ssh_exec(ssh, "curl -s http://localhost:5000/api/status")
    print(f"状态: {out[:300]}")

    out, _ = ssh_exec(ssh, "systemctl is-active news-viewer")
    print(f"news-viewer: {out.strip()}")

    out, _ = ssh_exec(ssh, "systemctl is-active news-scheduler")
    print(f"news-scheduler: {out.strip()}")

    # 检查新模块 API
    out, _ = ssh_exec(ssh, "curl -s http://localhost:5000/api/topic/industries")
    print(f"选题行业API: {out[:200]}")

    ssh.close()
    print("\n部署完成!")


if __name__ == "__main__":
    # 尝试加载 .env 文件
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    main()
