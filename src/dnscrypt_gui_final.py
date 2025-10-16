import sys
import subprocess
import importlib
import platform
import threading
import traceback
import requests
import json
import os
import shutil
import tarfile
import zipfile
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QTextEdit, QMessageBox, QHBoxLayout,
    QInputDialog
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QTextCursor
from PyQt5.QtCore import pyqtSignal, QObject
from PyQt5 import sip

# 注册自定义类型

if __name__ == "__main__":
    # 注册QTextCursor，保证多线程信号队列正确传递
    sip.register_metatype("QTextCursor<QTextCursor>")
    
    app = QApplication(sys.argv)
    # 你的主窗口
    window = DNSCryptGui()
    window.show()
    sys.exit(app.exec_())

# --------- 依赖检测与安装 ---------
def run_cmd(cmd):
    try:
        r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e:
        return False, str(e)

def ensure_package(pkg):
    try:
        importlib.import_module(pkg)
        return True
    except ImportError:
        # 仅pip安装作为备用，推荐预装或用系统包管理器安装
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
        return True

def ensure_dependencies():
    for p in ['PyQt5', 'requests']:
        if not ensure_package(p):
            print(f"依赖 {p} 安装失败")
            sys.exit(1)

ensure_dependencies()

# --------- 代理管理 ---------
class ProxyManager:
    def __init__(self, parent):
        self.parent = parent
        # 优先使用指定有效代理列表
        self.proxy_list = [
            {"name": "GitHubProxy", "prefix": "https://gh-proxy.com/"},
            {"name": "FastGit", "prefix": "https://gh.jasonzeng.dev/"},
            {"name": "pipers", "prefix": "https://proxy.pipers.cn/"},
            {"name": "gitmirror", "prefix": "https://hub.gitmirror.com/"},
            {"name": "dgithub", "prefix": "https://dgithub.xyz/"}
        ]
        self.current_proxy = None

    def test_proxy(self, prefix):
        test_url = prefix + "https://api.github.com/repos/DNSCrypt/dnscrypt-proxy/releases/latest"
        try:
            r = requests.get(test_url, timeout=7)
            return r.status_code == 200
        except:
            return False

    def auto_detect(self):
        for p in self.proxy_list:
            if self.test_proxy(p["prefix"]):
                self.current_proxy = p["prefix"]
                self.parent.log(f"自动选用代理：{p['name']}")
                return True
        return self.manual_input()

    def manual_input(self):
        text, ok = QInputDialog.getText(self.parent, "输入代理前缀", "自动检测失败，请输入代理前缀（如：https://gh-proxy.com/）:")
        if ok and text.strip():
            if self.test_proxy(text.strip()):
                self.current_proxy = text.strip()
                self.parent.log(f"手动设置代理为：{text.strip()}")
                return True
            self.parent.log("代理测试失败，请重试")
            QMessageBox.warning(self.parent, "无效代理", "代理测试失败，请重试")
            return self.manual_input()
        else:
            self.parent.log("未设置有效代理")
            QMessageBox.warning(self.parent, "代理设置", "未设置代理，可能影响下载速度")
            return False

# --------- 动态服务器加载（多地址顺序尝试） ---------
SERVER_LIST_URLS = [
    "https://download.dnscrypt.info/resolvers-list/v3/public-resolvers.md",
    "https://raw.githubusercontent.com/DNSCrypt/dnscrypt-resolvers/master/v3/public-resolvers.md",
    "https://dnscrypt.info/resolvers-list/v3/public-resolvers.md"
]

def fetch_server_list(proxy_prefix):
    for url in SERVER_LIST_URLS:
        try:
            use_url = proxy_prefix + url if proxy_prefix else url
            r = requests.get(use_url, timeout=10)
            if r.status_code == 200:
                js = r.json()
                servers = js.get("resolvers", [])
                if servers:
                    return servers
        except:
            continue
    return []

# --------- dnscrypt-proxy 下载安装 ---------
class DNSCryptInstaller:
    def __init__(self, parent, proxy_prefix=None):
        self.parent = parent
        self.proxy_prefix = proxy_prefix
    
    def get_releases(self):
        url = "https://api.github.com/repos/DNSCrypt/dnscrypt-proxy/releases"
        if self.proxy_prefix:
            url = self.proxy_prefix + url
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self.parent.log(f"获取版本列表失败: {e}")
            return []

    def select_asset_url(self, release):
        system = platform.system()
        arch_map = {
            "x86_64": "linux_amd64",
            "amd64": "linux_amd64",
            "aarch64": "linux_arm64",
            "arm64": "linux_arm64",
            "armv7l": "linux_arm"
        }
        arch = arch_map.get(platform.machine().lower())
        if system == "Windows": arch = "windows_amd64"
        elif system == "Darwin": arch = "darwin_amd64"
        if not arch:
            raise RuntimeError("不支持的CPU架构")
        assets = release.get("assets", [])
        for asset in assets:
            name = asset.get("name", "")
            if system == "Windows" and name.endswith(".zip") and arch in name:
                return asset["browser_download_url"]
            elif system in ("Linux", "Darwin") and name.endswith(".tar.gz") and arch in name:
                return asset["browser_download_url"]
        return None

    def download_and_install(self):
        releases = self.get_releases()
        if not releases:
            self.parent.log("无法获得任何发行版本信息")
            QMessageBox.critical(self.parent, "错误", "获取dnscrypt-proxy版本列表失败。")
            return
        # 从最新到旧版本遍历尝试下载
        for release in releases:
            tag_name = release.get("tag_name", "")
            self.parent.log(f"尝试下载版本：{tag_name}")
            url = self.select_asset_url(release)
            if not url:
                self.parent.log(f"版本 {tag_name} 无适合的下载包，跳过")
                continue
            try:
                tmp_dir = Path.home() / ".dnscrypt_proxy_tmp"
                tmp_dir.mkdir(exist_ok=True)
                file_name = url.split("/")[-1]
                archive_path = tmp_dir / file_name
                if not archive_path.exists():
                    download_url = self.proxy_prefix + url if self.proxy_prefix else url
                    self.parent.log(f"下载文件：{download_url}")
                    with requests.get(download_url, stream=True, timeout=60) as r:
                        r.raise_for_status()
                        with open(archive_path, "wb") as f:
                            shutil.copyfileobj(r.raw, f)
                install_dir = Path.home() / "dnscrypt-proxy"
                if install_dir.exists():
                    shutil.rmtree(install_dir)
                install_dir.mkdir()
                self.parent.log(f"解压文件到：{install_dir}")
                if archive_path.suffix == ".zip":
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        zip_ref.extractall(install_dir)
                else:
                    with tarfile.open(archive_path, 'r:gz') as tar_ref:
                        tar_ref.extractall(install_dir)
                bin_path = next(install_dir.glob("dnscrypt-proxy*"))
                if platform.system() in ("Linux", "Darwin"):
                    bin_path.chmod(0o755)
                self.parent.log(f"版本 {tag_name} 安装成功，路径：{bin_path}")
                QMessageBox.information(self.parent, "安装成功", f"dnscrypt-proxy {tag_name} 安装完成")
                return
            except Exception:
                self.parent.log(f"版本 {tag_name} 下载或安装失败，尝试回退到旧版本")
                self.parent.log(traceback.format_exc())
                continue
        # 全部失败后提示
        self.parent.log("所有尝试的版本下载失败")
        QMessageBox.critical(self.parent, "错误", "所有尝试的dnscrypt-proxy版本下载失败，请检查网络或代理设置")



    def extract(self, archive, outdir):
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive, 'r') as zip_ref:
                zip_ref.extractall(outdir)
        else:
            with tarfile.open(archive, "r:gz") as tar_ref:
                tar_ref.extractall(outdir)

    def chmod_exec(self, path):
        if platform.system() in ("Linux", "Darwin"):
            path.chmod(0o755)

    def install(self):
        try:
            self.parent.log("获取最新版本信息...")
            release = self.get_latest()
            url = self.select_asset_url(release)
            self.parent.log(f"下载包链接：{url}")
            tmpdir = Path.home() / ".dnscrypt_installer_tmp"
            tmpdir.mkdir(exist_ok=True)
            fname = url.split("/")[-1]
            archpath = tmpdir / fname
            if not archpath.exists():
                self.parent.log("开始下载...")
                self.download(url, archpath)
                self.parent.log("下载完成")
            inst_dir = Path.home() / "dnscrypt-proxy"
            if inst_dir.exists():
                shutil.rmtree(inst_dir)
            inst_dir.mkdir()
            self.parent.log("解压中...")
            self.extract(archpath, inst_dir)
            binfile = next(inst_dir.glob("dnscrypt-proxy*"))
            self.chmod_exec(binfile)
            self.parent.log(f"安装成功，目录：{inst_dir}")
            QMessageBox.information(self.parent, "安装成功", f"dnscrypt-proxy安装完成至{inst_dir}")
        except Exception as e:
            self.parent.log(f"安装失败: {e}")
            tb = traceback.format_exc()
            self.parent.log(tb)
            QMessageBox.critical(self.parent, "安装失败", f"dnscrypt-proxy安装失败: {e}")

# --------- 服务器配置写入 ---------
def write_server_names(config_path, server_names):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        found = False
        newlines = []
        for line in lines:
            if line.strip().startswith("server_names"):
                newlines.append('server_names = ["' + '","'.join(server_names) + '"]\n')
                found = True
            else:
                newlines.append(line)
        if not found:
            newlines.append('server_names = ["' + '","'.join(server_names) + '"]\n')
        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(newlines)
        return True, None
    except Exception as e:
        return False, str(e)

def detect_config_path():
    candidates = [
        "/etc/dnscrypt-proxy/dnscrypt-proxy.toml",
        "/usr/local/etc/dnscrypt-proxy/dnscrypt-proxy.toml",
        "/etc/dnscrypt-proxy.toml",
        "/usr/local/dnscrypt-proxy/dnscrypt-proxy.toml",
        "/opt/dnscrypt-proxy/dnscrypt-proxy.toml",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None

# --------- 服务控制 ---------
def run_cmd(cmd):
    try:
        r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e:
        return False, str(e)

# --------- UI主体 ---------
class DNSCryptGui(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DNSCrypt GUI客户端")
        self.resize(1000, 700)
        self.config_path = detect_config_path()
        self.proxy_manager = ProxyManager(self)
        self.manual_server = None
        self.servers = []
        self.installer = DNSCryptInstaller(self)
        self.init_ui()
        threading.Thread(target=self.startup_tasks, daemon=True).start()

    def init_ui(self):
        layout = QVBoxLayout()
        self.manual_in = QLineEdit()
        self.manual_in.setPlaceholderText("手动输入服务器host:port，优先级最高")
        manual_btn = QPushButton("应用手动服务器")
        manual_btn.clicked.connect(self.apply_manual_server)
        manual_layout = QHBoxLayout()
        manual_layout.addWidget(self.manual_in)
        manual_layout.addWidget(manual_btn)
        layout.addLayout(manual_layout)

        layout.addWidget(QLabel("在线服务器列表（多选）"))
        self.server_list = QListWidget()
        self.server_list.setSelectionMode(QListWidget.MultiSelection)
        layout.addWidget(self.server_list)

        apply_auto_btn = QPushButton("应用自动服务器配置")
        apply_auto_btn.clicked.connect(self.apply_auto_servers)
        layout.addWidget(apply_auto_btn)

        self.install_btn = QPushButton("下载并安装最新dnscrypt-proxy")
        self.install_btn.clicked.connect(self.install_dnscrypt_proxy)
        layout.addWidget(self.install_btn)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("启动服务")
        self.stop_btn = QPushButton("停止服务")
        self.restart_btn = QPushButton("重启服务")
        self.start_btn.clicked.connect(lambda:self.run_service("start"))
        self.stop_btn.clicked.connect(lambda:self.run_service("stop"))
        self.restart_btn.clicked.connect(lambda:self.run_service("restart"))
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.restart_btn)
        layout.addLayout(btn_layout)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text, stretch=1)
        self.setLayout(layout)

    def log(self,msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{ts}] {msg}")
        print(msg)

    def startup_tasks(self):
        try:
            self.log("自动检测代理...")
            if not self.proxy_manager.auto_detect():
                self.log("代理检测失败，未使用代理，下载可能不稳定")
                self.installer.proxy_prefix = None
            else:
                self.installer.proxy_prefix = self.proxy_manager.current_proxy

            self.log("获取服务器列表，多地址尝试...")
            servers = fetch_server_list(self.installer.proxy_prefix)
            if not servers:
                self.log("所有地址尝试失败，使用本地备份服务器")
                servers = [
                    {"name": "cloudflare", "address": "one.one.one.one:53"},
                    {"name": "dnscrypt.eu-nl", "address": "dnscrypt-eu.privacydns.org:443"},
                    {"name": "quad9", "address": "dns.quad9.net:443"},
                ]
            self.servers = servers
            self.populate_serverlist()
        except Exception as e:
            self.log(f"启动异常: {e}")
            self.log(traceback.format_exc())

    def populate_serverlist(self):
        self.server_list.clear()
        for s in self.servers:
            item = QListWidgetItem(f"{s['name']} - {s['address']}")
            item.setData(Qt.UserRole,s)
            item.setSelected(True)
            self.server_list.addItem(item)

    def apply_manual_server(self):
        srv = self.manual_in.text().strip()
        if not srv:
            QMessageBox.warning(self, "警告", "请输入有效服务器地址")
            return
        self.manual_server = srv
        self.log(f"应用手动服务器: {srv}")
        success, err = write_server_names(self.config_path, [srv])
        if success:
            QMessageBox.information(self, "成功", "手动服务器配置应用成功")
        else:
            QMessageBox.critical(self, "失败", f"写入失败: {err}")

    def apply_auto_servers(self):
        selected = [
            self.server_list.item(i).data(Qt.UserRole)['name']
            for i in range(self.server_list.count())
            if self.server_list.item(i).isSelected()
        ]
        if not selected:
            QMessageBox.warning(self, "警告", "请至少选择一个服务器")
            return
        self.manual_server = None
        self.log(f"应用自动服务器: {selected}")
        success, err = write_server_names(self.config_path, selected)
        if success:
            QMessageBox.information(self, "成功", "自动服务器配置应用成功")
        else:
            QMessageBox.critical(self, "失败", f"写入失败: {err}")

    def install_dnscrypt_proxy(self):
        def _install():
            self.install_btn.setEnabled(False)
            try:
                self.installer.install()
            finally:
                self.install_btn.setEnabled(True)
        threading.Thread(target=_install, daemon=True).start()

    def run_service(self, action):
        ok, out = run_cmd(f"sudo systemctl {action} dnscrypt-proxy")
        if ok:
            self.log(f"服务{action}成功")
            QMessageBox.information(self, "通知", f"服务{action}成功")
        else:
            self.log(f"服务{action}失败: {out}")
            QMessageBox.warning(self, "错误", f"服务{action}失败: {out}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    gui = DNSCryptGui()
    gui.show()
    sys.exit(app.exec_())
