import sys
import subprocess
import importlib
import time
import requests
import os
import threading
from datetime import datetime
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QTextEdit, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox
)
from PyQt5.QtCore import Qt

# 自动安装依赖模块
def ensure_package(pkg_name):
    try:
        importlib.import_module(pkg_name)
    except ImportError:
        print(f"{pkg_name} 未检测到，自动安装中...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])
        print(f"{pkg_name} 安装完成，请重启程序。")
        sys.exit(0)

def ensure_dependencies():
    for pkg in ["PyQt5", "requests"]:
        ensure_package(pkg)

ensure_dependencies()

# Proxy管理器，包含多个代理自动检测与手动输入支持
class ProxyManager:
    def __init__(self, ui_parent: QWidget):
        self.ui_parent = ui_parent
        self.proxy_list = [
            {"name": "GitHubProxy", "prefix": "https://ghproxy.com/"},
            {"name": "FastGit", "prefix": "https://hub.fastgit.org/"},
            {"name": "CNPMJS", "prefix": "https://github.com.cnpmjs.org/"}
        ]
        self.current_proxy_prefix = None

    def test_proxy(self, proxy_prefix):
        test_url = "https://api.github.com/repos/jedisct1/dnscrypt-proxy/releases/latest"
        proxied_url = proxy_prefix + test_url
        try:
            resp = requests.get(proxied_url, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def auto_select_proxy(self):
        for proxy in self.proxy_list:
            if self.test_proxy(proxy["prefix"]):
                self.current_proxy_prefix = proxy["prefix"]
                self.ui_parent.log(f"自动选择有效代理: {proxy['name']}")
                return True
        # 所有检测失败，弹窗输入
        return self.manual_proxy_input()

    def manual_proxy_input(self):
        text, ok = QInputDialog.getText(self.ui_parent, "手动输入代理",
                                        "自动检测代理失败，请输入代理前缀（例如：https://ghproxy.com/）:")
        if ok and text.strip():
            if self.test_proxy(text.strip()):
                self.current_proxy_prefix = text.strip()
                self.ui_parent.log(f"手动设置代理为: {text.strip()}")
                return True
            else:
                QMessageBox.warning(self.ui_parent, "代理无效", "手动输入的代理不可用，请重试。")
                return self.manual_proxy_input()
        else:
            QMessageBox.warning(self.ui_parent, "操作取消", "未设置有效代理，可能影响下载速度。")
            return False

# 配置文件写入和校验
def write_server_names(config_path, server_names):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("server_names"):
                new_lines.append('server_names = ["' + '","'.join(server_names) + '"]\n')
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append('server_names = ["' + '","'.join(server_names) + '"]\n')
        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True, None
    except Exception as e:
        return False, str(e)

def validate_config_file(config_path):
    if not os.path.exists(config_path):
        return False, "配置文件不存在"
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()
    if "server_names" not in content:
        return False, "配置文件缺少server_names字段"
    return True, None

def detect_dnscrypt_config_path():
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

# 动态加载服务器列表（示范：https://some_online_source/api/servers.json）
def fetch_servers(proxy_prefix=None):
    url = "https://some_online_source/api/servers.json"  # 注意替换为有效地址
    headers = {"User-Agent": "dnscrypt-proxy-gui"}
    try:
        if proxy_prefix:
            url = proxy_prefix + url
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json()
        return []
    except Exception:
        return []

# 主界面客户端
class DNSCryptGui(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DNSCrypt GUI 客户端")
        self.resize(1100, 750)

        self.config_path = detect_dnscrypt_config_path()
        self.proxy_manager = ProxyManager(self)

        # 本地服务器列表，优先用在线源
        self.servers = []
        self.manual_server = None  # 手动指定服务器
        self.init_ui()

        # 启动线程自动设置代理和加载服务器
        threading.Thread(target=self.setup_proxy_and_load_servers, daemon=True).start()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # 手动服务器输入
        manual_layout = QHBoxLayout()
        self.manual_server_input = QLineEdit()
        self.manual_server_input.setPlaceholderText("手动输入服务器，格式 host:port ，优先级最高")
        manual_apply_btn = QPushButton("应用手动服务器")
        manual_apply_btn.clicked.connect(self.apply_manual_server)
        manual_layout.addWidget(QLabel("手动服务器:"))
        manual_layout.addWidget(self.manual_server_input)
        manual_layout.addWidget(manual_apply_btn)
        main_layout.addLayout(manual_layout)

        # 服务器列表显示
        server_layout = QVBoxLayout()
        self.server_list = QListWidget()
        self.server_list.setSelectionMode(QListWidget.MultiSelection)
        server_layout.addWidget(QLabel("自动获取的可用服务器"))
        server_layout.addWidget(self.server_list)
        main_layout.addLayout(server_layout)

        apply_btn = QPushButton("应用选择服务器配置（自动模式）")
        apply_btn.clicked.connect(self.apply_selected_servers)
        main_layout.addWidget(apply_btn)

        # 服务控制按钮
        service_layout = QHBoxLayout()
        start_btn = QPushButton("启动服务")
        stop_btn = QPushButton("停止服务")
        restart_btn = QPushButton("重启服务")
        start_btn.clicked.connect(self.start_service)
        stop_btn.clicked.connect(self.stop_service)
        restart_btn.clicked.connect(self.restart_service)
        service_layout.addWidget(start_btn)
        service_layout.addWidget(stop_btn)
        service_layout.addWidget(restart_btn)
        main_layout.addLayout(service_layout)

        # 日志窗口
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(self.log_text, stretch=2)

        self.setLayout(main_layout)

    def log(self, msg):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{timestamp}] {msg}")
        print(msg)  # 可替换为文件日志等其他实现

    def setup_proxy_and_load_servers(self):
        self.log("开始自动检测并选择GitHub代理...")
        if not self.proxy_manager.auto_select_proxy():
            self.log("代理自动检测失败，未启用代理。")
        # 优先使用代理获取服务器列表
        self.servers = fetch_servers(self.proxy_manager.current_proxy_prefix)
        if not self.servers:
            self.log("在线获取服务器列表失败，使用本地备份服务器。")
            self.servers = [
                {"name": "cloudflare", "address": "one.one.one.one:53", "region": "Global"},
                {"name": "dnscrypt.eu-nl", "address": "dnscrypt-eu.privacydns.org:443", "region": "EU"},
                {"name": "quad9", "address": "dns.quad9.net:443", "region": "Global"},
            ]
        self.log(f"加载服务器共计 {len(self.servers)} 个。")
        self.populate_server_list()

    def populate_server_list(self):
        self.server_list.clear()
        for s in self.servers:
            item = QListWidgetItem(f"{s['name']} ({s.get('region','N/A')}) - {s['address']}")
            item.setData(Qt.UserRole, s)
            item.setSelected(True)
            self.server_list.addItem(item)

    def apply_manual_server(self):
        server = self.manual_server_input.text().strip()
        if not server:
            QMessageBox.warning(self, "输入错误", "请输入合法的服务器地址，如 host:port 。")
            return
        self.manual_server = server
        self.log(f"已设置手动服务器：{server}")
        success = self.apply_server_config([{"name": "manual", "address": server}])
        if success:
            QMessageBox.information(self, "成功", f"已应用手动服务器：{server}")
        else:
            QMessageBox.warning(self, "失败", "应用手动服务器失败，将尝试自动模式。")
            self.manual_server = None

    def apply_selected_servers(self):
        selected_servers = []
        for i in range(self.server_list.count()):
            item = self.server_list.item(i)
            if item.isSelected():
                data = item.data(Qt.UserRole)
                selected_servers.append(data)
        if not selected_servers:
            QMessageBox.warning(self, "配置错误", "请至少选择一个服务器！")
            self.log("未选择服务器，无法配置。")
            return
        self.manual_server = None  # 清除手动服务器
        success = self.apply_server_config(selected_servers)
        if success:
            QMessageBox.information(self, "成功", "服务器配置已应用，请重启dnscrypt-proxy使改动生效。")
        else:
            QMessageBox.warning(self, "失败", "服务器配置应用失败。")

    def apply_server_config(self, server_list):
        if not self.config_path:
            self.log("未找到dnscrypt-proxy配置文件路径，无法写入！")
            return False
        try:
            server_names = [s["name"] for s in server_list if "name" in s]
            success, err = write_server_names(self.config_path, server_names)
            if success:
                self.log(f"写入服务器配置成功：{server_names}")
                return True
            else:
                self.log(f"写入服务器配置失败：{err}")
                return False
        except Exception as e:
            self.log(f"应用服务器配置异常：{e}")
            return False

    # 服务控制相关示范代码，根据你的dnscrypt-proxy路径和启动命令调整
    def start_service(self):
        service_cmd = ["systemctl", "start", "dnscrypt-proxy"]
        self.run_service_command(service_cmd, "启动")

    def stop_service(self):
        service_cmd = ["systemctl", "stop", "dnscrypt-proxy"]
        self.run_service_command(service_cmd, "停止")

    def restart_service(self):
        service_cmd = ["systemctl", "restart", "dnscrypt-proxy"]
        self.run_service_command(service_cmd, "重启")

    def run_service_command(self, cmd, action_name):
        try:
            subprocess.run(cmd, check=True)
            self.log(f"服务{action_name}成功")
            QMessageBox.information(self, "服务控制", f"服务{action_name}成功！")
        except subprocess.CalledProcessError as e:
            self.log(f"服务{action_name}失败: {e}")
            QMessageBox.critical(self, "服务控制错误", f"服务{action_name}失败: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DNSCryptGui()
    window.show()
    sys.exit(app.exec_())
