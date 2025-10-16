import unittest
import tempfile
import os
import shutil

# 用于写入配置文件中的server_names字段的函数（示例）
def write_server_names(path, server_names):
    try:
        with open(path, "r", encoding="utf-8") as f:
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
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return True, None
    except Exception as e:
        return False, str(e)

# 用于检测配置文件格式及内容的简单函数示例
def validate_config_file(path):
    if not os.path.exists(path):
        return False, "配置文件不存在"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if "server_names" not in content:
            return False, "配置文件缺少server_names字段"
        # 此处还可以添加更多语法和格式校验
        return True, None
    except Exception as e:
        return False, str(e)

class TestConfigFile(unittest.TestCase):
    def setUp(self):
        # 创建临时目录及模拟配置文件
        self.temp_dir = tempfile.mkdtemp()
        self.config_file = os.path.join(self.temp_dir, "dnscrypt-proxy.toml")
        sample_content = (
            "listen_addresses = ['127.0.0.1:53']\n"
            "server_names = ['oldserver']\n"
            "bootstrap_resolvers = ['8.8.8.8:53']\n"
        )
        with open(self.config_file, "w", encoding="utf-8") as f:
            f.write(sample_content)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_write_server_names_success(self):
        new_servers = ["server1", "server2"]
        success, err = write_server_names(self.config_file, new_servers)
        self.assertTrue(success)
        self.assertIsNone(err)
        with open(self.config_file, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('server_names = ["server1","server2"]', content)

    def test_write_server_names_file_missing(self):
        bad_path = os.path.join(self.temp_dir, "missing.toml")
        success, err = write_server_names(bad_path, ["a"])
        self.assertFalse(success)
        self.assertIsNotNone(err)

    def test_validate_config_file_success(self):
        valid, msg = validate_config_file(self.config_file)
        self.assertTrue(valid)
        self.assertIsNone(msg)

    def test_validate_config_file_missing(self):
        missing_path = os.path.join(self.temp_dir, "notexist.toml")
        valid, msg = validate_config_file(missing_path)
        self.assertFalse(valid)
        self.assertEqual(msg, "配置文件不存在")

    def test_validate_config_file_no_server_names(self):
        # 写入不包含 server_names 的配置
        bad_config = os.path.join(self.temp_dir, "bad.toml")
        with open(bad_config, "w", encoding="utf-8") as f:
            f.write("listen_addresses=['127.0.0.1:53']\n")
        valid, msg = validate_config_file(bad_config)
        self.assertFalse(valid)
        self.assertEqual(msg, "配置文件缺少server_names字段")

if __name__ == "__main__":
    unittest.main()
