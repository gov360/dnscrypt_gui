import sys
import os
import subprocess
import json
import time
import requests
from datetime import datetime

# 自动修复pip缺失函数
def ensure_pip():
    try:
        import pip
        return True
    except ImportError:
        print("pip未安装，尝试自动安装pip...")
        try:
            import urllib.request
            get_pip_url = "https://bootstrap.pypa.io/get-pip.py"
            install_script = "get-pip.py"
            if not os.path.exists(install_script):
                print(f"正在下载 {get_pip_url} ...")
                urllib.request.urlretrieve(get_pip_url, install_script)
            print("开始执行 get-pip.py 安装 pip ...")
            subprocess.check_call([sys.executable, install_script])
            os.remove(install_script)
            return True
        except Exception as e:
            print(f"自动安装pip失败：{e}")
            return False

# 自动安装PyQt5和requests依赖
def ensure_dependencies():
    if not ensure_pip():
        print("请手动安装pip后重试。")
        sys.exit(1)
    try:
        import PyQt5
        import requests
    except ImportError:
        print("缺少依赖，自动安装 PyQt5 和 requests ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyqt5", "requests"])
        print("依赖安装完成，请重新启动程序。")
        sys.exit(0)

ensure_dependencies()

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QTextEdit, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox
)
from PyQt5.QtCore import Qt

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

def backup_config(path):
    import shutil
    if os.path.exists(path):
        bak_path = path + ".bak." + datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy(path, bak_path)

def write_server_names(path, server_names):
    try:
        with open(path, 'r', encoding='utf-8') as f:
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
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        return True, None
    except Exception as e:
        return False, str(e)

def test_proxy(proxy, test_url):
    proxies = {}
    ptype = proxy.get("type", "http")
    host = proxy.get("host")
    port = proxy.get("port", 0)
    if host == "direct":
        proxies = None
    else:
        proxy_str = f"{ptype}://{host}:{port}"
        proxies = {"http": proxy_str, "https": proxy_str}
    start = time.time()
    try:
        response = requests.get(test_url, proxies=proxies, timeout=8, headers={"User-Agent":"dnscrypt-proxy-gui-test"})
        latency = int((time.time() - start) * 1000)
        if response.status_code == 200:
            return True, latency
        else:
            return False, latency
    except Exception:
        latency = int((time.time() - start) * 1000)
        return False, latency

class DNSCryptGui(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DNSCrypt + GitHub代理管理")
        self.setGeometry(200, 200, 1100, 700)

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

        self.config_path = detect_dnscrypt_config_path()

        self.init_ui()
        self.load_config()
        self.refresh_ui()

    def init_ui(self):
        main_layout = QVBoxLayout()
        btn_layout = QHBoxLayout()

        self.update_server_btn = QPushButton("更新服务器列表")
        self.update_server_btn.clicked.connect(self.update_server_list)
        btn_layout.addWidget(self.update_server_btn)

        self.apply_server_btn = QPushButton("应用选中的服务器")
        self.apply_server_btn.clicked.connect(self.apply_selected_servers)
        btn_layout.addWidget(self.apply_server_btn)

        self.export_config_btn = QPushButton("导出配置")
        self.export_config_btn.clicked.connect(self.export_config)
        btn_layout.addWidget(self.export_config_btn)

        self.import_config_btn = QPushButton("导入配置")
        self.import_config_btn.clicked.connect(self.import_config)
        btn_layout.addWidget(self.import_config_btn)

        main_layout.addLayout(btn_layout)
        
        mid_layout = QHBoxLayout()

        server_layout = QVBoxLayout()
        server_layout.addWidget(QLabel("可选DNS服务器(多选)"))
        self.server_list_widget = QListWidget()
        self.server_list_widget.setSelectionMode(QListWidget.MultiSelection)
        server_layout.addWidget(self.server_list_widget)
        mid_layout.addLayout(server_layout, 2)

        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("GitHub 加速代理（选择）"))
        self.github_proxy_combo = QComboBox()
        for p in self.github_proxies:
            self.github_proxy_combo.addItem(p["name"])
        right_layout.addWidget(self.github_proxy_combo)

        self.proxy_test_btn = QPushButton("测试选中代理")
        self.proxy_test_btn.clicked.connect(self.test_github_proxy)
        right_layout.addWidget(self.proxy_test_btn)

        right_layout.addWidget(QLabel("手动添加代理"))
        manual_form = QHBoxLayout()
        self.man_proxy_type = QComboBox()
        self.man_proxy_type.addItems(["http", "socks"])
        manual_form.addWidget(QLabel("类型"))
        manual_form.addWidget(self.man_proxy_type)
        self.man_proxy_host = QLineEdit()
        self.man_proxy_host.setPlaceholderText("地址 Host")
        manual_form.addWidget(self.man_proxy_host)
        self.man_proxy_port = QLineEdit()
        self.man_proxy_port.setPlaceholderText("端口 Port")
        manual_form.addWidget(self.man_proxy_port)
        right_layout.addLayout(manual_form)

        manual_auth = QHBoxLayout()
        self.man_proxy_user = QLineEdit()
        self.man_proxy_user.setPlaceholderText("用户名")
        manual_auth.addWidget(self.man_proxy_user)
        self.man_proxy_pass = QLineEdit()
        self.man_proxy_pass.setPlaceholderText("密码")
        self.man_proxy_pass.setEchoMode(QLineEdit.Password)
        manual_auth.addWidget(self.man_proxy_pass)
        right_layout.addLayout(manual_auth)

        self.man_proxy_add_btn = QPushButton("添加并测试代理")
        self.man_proxy_add_btn.clicked.connect(self.add_manual_proxy)
        right_layout.addWidget(self.man_proxy_add_btn)

        self.proxy_status_label = QLabel("当前代理：直连")
        right_layout.addWidget(self.proxy_status_label)

        right_layout.addWidget(QLabel("日志输出"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        right_layout.addWidget(self.log_text, 3)

        mid_layout.addLayout(right_layout, 3)
        main_layout.addLayout(mid_layout)
        self.setLayout(main_layout)

    def log(self, msg):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.append(f"[{now}] {msg}")

    def load_config(self):
        if os.path.exists("config.json"):
            try:
                with open("config.json", "r") as f:
                    config = json.load(f)
                self.servers = config.get("servers", self.servers)
                self.github_proxies = config.get("proxy", self.github_proxies)
                self.active_proxy = config.get("active_proxy", self.active_proxy)
            except Exception as e:
                self.log(f"加载配置异常：{e}")

    def save_config(self):
        config = {
            "servers": self.servers,
            "proxy": self.github_proxies,
            "active_proxy": self.active_proxy
        }
        try:
            with open("config.json", "w") as f:
                json.dump(config, f, indent=2)
            self.log("配置已保存至 config.json")
        except Exception as e:
            self.log(f"保存配置失败：{e}")

    def refresh_ui(self):
        self.server_list_widget.clear()
        for s in self.servers:
            item = QListWidgetItem(f"{s['name']} ({s['region']}) - {s['address']}")
            item.setData(Qt.UserRole, s)
            self.server_list_widget.addItem(item)

        self.github_proxy_combo.clear()
        for p in self.github_proxies:
            self.github_proxy_combo.addItem(p["name"])
        idx = 0
        for i, p in enumerate(self.github_proxies):
            if p["name"] == self.active_proxy["name"]:
                idx = i
                break
        self.github_proxy_combo.setCurrentIndex(idx)

        self.proxy_status_label.setText(f"当前代理：{self.active_proxy['name']}")

    def update_server_list(self):
        self.log("服务器列表更新暂未实现")

    def apply_selected_servers(self):
        selected = []
        for i in range(self.server_list_widget.count()):
            item = self.server_list_widget.item(i)
            if item.isSelected():
                s = item.data(Qt.UserRole)
                selected.append(s["name"])
        if not selected:
            QMessageBox.information(self, "提示", "请选择至少一个服务器。")
            return
        if not self.config_path:
            self.config_path = detect_dnscrypt_config_path()
            if not self.config_path:
                QMessageBox.critical(self, "错误", "无法检测到主配置文件路径，请手动指定")
                return
        backup_config(self.config_path)
        ok, err = write_server_names(self.config_path, selected)
        if ok:
            self.log(f"成功写入服务器列表：{selected}")
            QMessageBox.information(self, "成功", "配置写入成功，重启dnscrypt-proxy使其生效。")
        else:
            self.log(f"写入失败：{err}")
            QMessageBox.critical(self, "错误", f"写入失败：{err}")

    def export_config(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "导出配置", "config.json", "JSON 文件 (*.json)")
        if path:
            try:
                with open("config.json", "r") as fsrc, open(path, "w") as fdst:
                    fdst.write(fsrc.read())
                self.log(f"配置导出成功：{path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导出失败：{e}")

    def import_config(self):
        from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "导入配置", "", "JSON 文件 (*.json)")
        if path:
            try:
                with open(path, "r") as f:
                    config = json.load(f)
                self.servers = config.get("servers", self.servers)
                self.github_proxies = config.get("proxy", self.github_proxies)
                self.active_proxy = config.get("active_proxy", self.active_proxy)
                self.save_config()
                self.refresh_ui()
                self.log(f"配置导入自：{path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"导入失败：{e}")

    def test_github_proxy(self):
        idx = self.github_proxy_combo.currentIndex()
        proxy = self.github_proxies[idx]
        self.log(f"开始测试代理：{proxy['name']}")
        test_url = "https://raw.githubusercontent.com/github/gitignore/main/README.md"
        success, latency = test_proxy(proxy, test_url)
        if success:
            self.log(f"代理 {proxy['name']} 可用，延迟 {latency} ms")
            self.active_proxy = proxy
            self.save_config()
            self.proxy_status_label.setText(f"当前代理：{proxy['name']}")
        else:
            self.log(f"代理 {proxy['name']} 不可用")

    def add_manual_proxy(self):
        ptype = self.man_proxy_type.currentText()
        host = self.man_proxy_host.text().strip()
        port_text = self.man_proxy_port.text().strip()
        username = self.man_proxy_user.text().strip()
        password = self.man_proxy_pass.text().strip()
        if not host or not port_text.isdigit():
            QMessageBox.warning(self, "输入错误", "请输入正确的代理地址和端口")
            return
        port = int(port_text)
        name = f"{ptype}://{host}:{port}"
        for p in self.github_proxies:
            if p["name"] == name:
                QMessageBox.information(self, "提示", "该代理已经存在。")
                return
        proxy = {
            "name": name, "type": ptype, "host": host, "port": port,
            "username": username, "password": password
        }
        self.github_proxies.append(proxy)
        self.github_proxy_combo.addItem(name)
        self.log(f"已添加手动代理 {name}")
        success, latency = test_proxy(proxy, "https://raw.githubusercontent.com/github/gitignore/main/README.md")
        if success:
            self.log(f"手动代理可用，延迟 {latency} ms")
            self.active_proxy = proxy
            self.save_config()
            self.proxy_status_label.setText(f"当前代理：{name}")
        else:
            self.log(f"手动代理不可用")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DNSCryptGui()
    window.show()
    sys.exit(app.exec_())
