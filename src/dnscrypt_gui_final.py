import sys
import subprocess
import importlib
import time
import requests
import os
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QTextEdit, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox
)
from PyQt5.QtCore import Qt

# 依赖自动安装模块
def ensure_package(pkg_name):
    try:
        importlib.import_module(pkg_name)
    except ImportError:
        print(f"{pkg_name} 未检测到，正在自动安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name])
        print(f"{pkg_name} 安装完成，请重启程序。")
        sys.exit(0)

def ensure_dependencies():
    for pkg in ["PyQt5", "requests"]:
        ensure_package(pkg)

ensure_dependencies()

# 代理测试函数
def test_proxy(proxy, test_url="https://raw.githubusercontent.com/github/gitignore/main/README.md"):
    if proxy.get("host") == "direct":
        proxies = None
    else:
        proxy_str = f"{proxy['type']}://{proxy['host']}:{proxy['port']}"
        proxies = {"http": proxy_str, "https": proxy_str}
    start = time.time()
    try:
        resp = requests.get(test_url, proxies=proxies, timeout=8, headers={"User-Agent":"proxy-test"})
        latency = int((time.time() - start) * 1000)
        return resp.status_code == 200, latency
    except Exception:
        return False, None

# 配置文件写入与校验
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

# 自动检测dnscrypt-proxy配置路径
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

# 主要GUI客户端
class DNSCryptGui(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DNSCrypt GUI 客户端")
        self.resize(1000, 700)

        self.config_path = detect_dnscrypt_config_path()

        self.servers = [
            {"name": "cloudflare", "address": "one.one.one.one:53", "region": "Global"},
            {"name": "dnscrypt.eu-nl", "address": "dnscrypt-eu.privacydns.org:443", "region": "EU"},
            {"name": "quad9", "address": "dns.quad9.net:443", "region": "Global"}
        ]
        self.github_proxies = [
            {"name": "直连", "type": "http", "host": "direct", "port": 0},
            {"name": "GitHub-CNPMJS", "type": "http", "host": "github.com.cnpmjs.org", "port": 80},
            {"name": "FastGit", "type": "http", "host": "hub.fastgit.org", "port": 443}
        ]
        self.active_proxy = self.github_proxies[0]

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # 服务器选择区
        server_layout = QVBoxLayout()
        server_layout.addWidget(QLabel("选择DNSCrypt服务器（可多选）"))
        self.server_list = QListWidget()
        self.server_list.setSelectionMode(QListWidget.MultiSelection)
        for s in self.servers:
            item = QListWidgetItem(f"{s['name']} ({s['region']}) - {s['address']}")
            item.setData(Qt.UserRole, s)
            self.server_list.addItem(item)
        server_layout.addWidget(self.server_list)

        apply_btn = QPushButton("应用服务器配置")
        apply_btn.clicked.connect(self.apply_config)
        server_layout.addWidget(apply_btn)

        main_layout.addLayout(server_layout)

        # 代理管理区
        proxy_layout = QVBoxLayout()
        proxy_layout.addWidget(QLabel("GitHub 加速代理"))
        self.proxy_combo = QComboBox()
        for p in self.github_proxies:
            self.proxy_combo.addItem(p["name"])
        proxy_layout.addWidget(self.proxy_combo)

        test_proxy_btn = QPushButton("测试当前代理连通性")
        test_proxy_btn.clicked.connect(self.test_current_proxy)
        proxy_layout.addWidget(test_proxy_btn)

        main_layout.addLayout(proxy_layout)

        # 日志显示
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(self.log_text, stretch=2)

        self.setLayout(main_layout)

    def log(self, msg):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{now}] {msg}")

    def apply_config(self):
        selected = []
        for i in range(self.server_list.count()):
            item = self.server_list.item(i)
            if item.isSelected():
                data = item.data(Qt.UserRole)
                selected.append(data["name"])
        if not selected:
            self.log("未选择任何服务器，配置应用失败。")
            QMessageBox.warning(self, "配置错误", "请至少选择一个服务器。")
            return
        if not self.config_path:
            self.log("未检测到dnscrypt-proxy主配置文件路径，配置失败。")
            QMessageBox.critical(self, "文件错误", "无法检测到dnscrypt-proxy配置文件。")
            return
        success, err = write_server_names(self.config_path, selected)
        if success:
            self.log(f"成功写入服务器列表: {selected}")
            QMessageBox.information(self, "成功", "服务器配置已更新，请重启dnscrypt-proxy使其生效。")
        else:
            self.log(f"写入失败: {err}")
            QMessageBox.critical(self, "写入失败", f"写入配置时发生错误：{err}")

    def test_current_proxy(self):
        idx = self.proxy_combo.currentIndex()
        proxy = self.github_proxies[idx]
        self.log(f"开始测试代理：{proxy['name']}")
        success, latency = test_proxy(proxy)
        if success:
            self.log(f"代理 {proxy['name']} 可用，延迟 {latency} ms")
            QMessageBox.information(self, "代理测试", f"代理 {proxy['name']} 测试成功，延迟 {latency} 毫秒。")
        else:
            self.log(f"代理 {proxy['name']} 不可用或连接超时")
            QMessageBox.warning(self, "代理测试", f"代理 {proxy['name']} 测试失败，请检查网络或代理设置。")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DNSCryptGui()
    window.show()
    sys.exit(app.exec_())
