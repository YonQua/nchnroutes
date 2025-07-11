#!/usr/bin/env python3
"""
nchnroutes - 生成非中国大陆路由规则
用于BIRD路由器的OSPF智能分流配置

重构版本特性：
- 支持外部配置文件
- 完整的中文注释
- 更好的代码结构
- 错误处理和日志
"""

import argparse
import csv
import os
import math
import subprocess
import configparser
from ipaddress import IPv4Network, IPv6Network
from typing import List, Set

# 全局常量
IPV6_UNICAST = IPv6Network('2000::/3')  # 全球单播IPv6地址空间
DEFAULT_CONFIG_FILE = "config.ini"

class NetworkNode:
    """网络节点类，用于构建路由树结构"""

    def __init__(self, cidr):
        self.cidr = cidr
        self.child = []
        self.dead = False

    def __repr__(self):
        return f"<NetworkNode {self.cidr}>"

class DataDownloader:
    """数据文件下载管理器"""

    def __init__(self, config: configparser.ConfigParser):
        self.config = config
        self.auto_download = config.getboolean('下载配置', 'auto_download', fallback=True)
        self.timeout = config.getint('下载配置', 'download_timeout', fallback=30)

    def _is_file_usable(self, filepath: str) -> bool:
        """检查文件是否可用（存在且非空）"""
        return os.path.exists(filepath) and os.path.getsize(filepath) > 0

    def _download_file(self, url: str, filepath: str) -> bool:
        """下载文件，使用curl命令，单次尝试"""
        try:
            print(f"正在下载 {filepath}...")
            print(f"URL: {url}")

            # 使用curl下载，设置User-Agent和超时
            cmd = [
                'curl',
                '-L',  # 跟随重定向
                '-f',  # 失败时返回错误码
                '-s',  # 静默模式
                '--connect-timeout', str(self.timeout),
                '--max-time', str(self.timeout * 2),
                '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
                '-o', filepath,
                url
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                # 检查下载的文件大小
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    print(f"✅ 下载完成: {filepath} ({os.path.getsize(filepath)} 字节)")
                    return True
                else:
                    print(f"❌ 下载的文件为空: {filepath}")
            else:
                print(f"❌ curl下载失败: {result.stderr}")

        except Exception as e:
            print(f"❌ 下载出错: {e}")

        return False

    def ensure_data_files(self) -> bool:
        """确保数据文件可用 - 简化逻辑：先下载，失败了用旧文件"""
        if not self.auto_download:
            print("自动下载已禁用")
            return self._check_files_exist()

        files_to_download = [
            ("delegated-apnic-latest", self.config.get('数据源URL', 'apnic_url')),
            ("china_ip_list.txt", self._get_china_ip_url())
        ]

        for filename, url in files_to_download:
            if url:
                print(f"尝试下载最新的 {filename}...")
                if self._download_file(url, filename):
                    print(f"✅ 下载成功: {filename}")
                else:
                    if self._is_file_usable(filename):
                        print(f"⚠️  下载失败，使用本地旧文件: {filename}")
                    else:
                        print(f"❌ 下载失败且无可用本地文件: {filename}")
                        return False
            else:
                print(f"❌ 无法获取 {filename} 的下载URL")
                if not self._is_file_usable(filename):
                    return False

        return True

    def _get_china_ip_url(self) -> str:
        """获取中国IP列表的URL"""
        china_source = self.config.get('数据源URL', 'china_ip_source', fallback='mayaxcn')
        china_url_key = f'china_ip_{china_source}'
        return self.config.get('数据源URL', china_url_key, fallback='')

    def _check_files_exist(self) -> bool:
        """检查必要的数据文件是否存在且可用"""
        files_to_check = ["delegated-apnic-latest", "china_ip_list.txt"]

        for filename in files_to_check:
            if self._is_file_usable(filename):
                print(f"✅ 找到可用文件: {filename}")
            else:
                print(f"❌ 缺少可用文件: {filename}")
                return False

        return True

class RouteGenerator:
    """路由生成器类"""
    
    def __init__(self, next_hop: str, exclude_networks: List[str] = None):
        self.next_hop = next_hop
        self.reserved_ipv4 = set()
        self.reserved_ipv6 = set()
        self.config_file = DEFAULT_CONFIG_FILE  # 默认配置文件
        self.config = None  # 配置对象
        self.downloader = None  # 下载管理器

        # 加载保留网段配置
        self._load_reserved_networks()

        # 添加命令行指定的排除网段
        if exclude_networks:
            self._add_exclude_networks(exclude_networks)
    
    def _load_reserved_networks(self):
        """从INI配置文件加载保留网段"""
        config_path = self.config_file

        if not os.path.exists(config_path):
            print(f"警告: 配置文件 {config_path} 不存在，使用默认保留网段")
            self._load_default_reserved()
            return

        try:
            self.config = configparser.ConfigParser()
            self.config.read(config_path, encoding='utf-8')

            # 初始化下载管理器
            self.downloader = DataDownloader(self.config)

            config = self.config  # 保持向后兼容

            # 加载IPv4保留网段
            if config.has_section('保留网段IPv4'):
                for key, value in config.items('保留网段IPv4'):
                    network_str = value.strip()
                    if network_str:
                        try:
                            network = IPv4Network(network_str)
                            self.reserved_ipv4.add(network)
                            print(f"加载IPv4保留网段: {network} ({key})")
                        except ValueError as e:
                            print(f"警告: IPv4网段格式错误 {key}={network_str}: {e}")

            # 加载IPv6保留网段
            if config.has_section('保留网段IPv6'):
                for key, value in config.items('保留网段IPv6'):
                    network_str = value.strip()
                    if network_str:
                        try:
                            network = IPv6Network(network_str)
                            self.reserved_ipv6.add(network)
                            print(f"加载IPv6保留网段: {network} ({key})")
                        except ValueError as e:
                            print(f"警告: IPv6网段格式错误 {key}={network_str}: {e}")

            # 加载自定义排除网段
            if config.has_section('自定义排除'):
                for key, value in config.items('自定义排除'):
                    network_str = value.strip()
                    if network_str:
                        try:
                            if ':' in network_str:
                                network = IPv6Network(network_str)
                                self.reserved_ipv6.add(network)
                                print(f"加载自定义IPv6排除: {network} ({key})")
                            else:
                                network = IPv4Network(network_str)
                                self.reserved_ipv4.add(network)
                                print(f"加载自定义IPv4排除: {network} ({key})")
                        except ValueError as e:
                            print(f"警告: 自定义网段格式错误 {key}={network_str}: {e}")

            # 从网络配置中读取下一跳设置（如果命令行没有指定的话）
            if config.has_section('网络配置') and config.has_option('网络配置', 'default_next_hop'):
                config_next_hop = config.get('网络配置', 'default_next_hop').strip()
                if config_next_hop and self.next_hop == "ens192":  # 如果还是默认值
                    self.next_hop = config_next_hop
                    print(f"从配置文件读取下一跳: {self.next_hop}")

        except Exception as e:
            print(f"错误: 无法读取配置文件 {config_path}: {e}")
            print("使用默认保留网段")
            self._load_default_reserved()
    
    def _load_default_reserved(self):
        """加载默认的保留网段（备用方案）"""
        default_ipv4 = [
            '0.0.0.0/8', '10.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16',
            '172.24.0.0/13', '192.0.0.0/29', '192.168.0.0/16',
            '224.0.0.0/4', '240.0.0.0/4', '100.64.0.0/10'
        ]
        
        for network_str in default_ipv4:
            self.reserved_ipv4.add(IPv4Network(network_str))
    
    def _add_exclude_networks(self, exclude_networks: List[str]):
        """添加命令行指定的排除网段"""
        for network_str in exclude_networks:
            try:
                if ':' in network_str:
                    network = IPv6Network(network_str)
                    self.reserved_ipv6.add(network)
                else:
                    network = IPv4Network(network_str)
                    self.reserved_ipv4.add(network)
                print(f"添加排除网段: {network}")
            except ValueError as e:
                print(f"警告: 排除网段格式错误: {network_str} - {e}")
    
    def _dump_bird_routes(self, nodes: List[NetworkNode], output_file):
        """将路由节点写入BIRD配置文件"""
        for node in nodes:
            if len(node.child) > 0:
                self._dump_bird_routes(node.child, output_file)
            elif not node.dead:
                output_file.write(f'route {node.cidr} via "{self.next_hop}";\n')
    
    def _subtract_networks(self, root_nodes: List[NetworkNode], subtract_networks: Set):
        """从根节点中减去指定的网段（递归实现）"""
        for network_to_subtract in subtract_networks:
            for node in root_nodes:
                if node.cidr == network_to_subtract:
                    node.dead = True
                    break
                elif node.cidr.supernet_of(network_to_subtract):
                    if len(node.child) > 0:
                        # 如果已有子节点，递归处理子节点
                        self._subtract_networks(node.child, {network_to_subtract})
                    else:
                        # 创建子网段，排除要减去的网段
                        node.child = [
                            NetworkNode(subnet)
                            for subnet in node.cidr.address_exclude(network_to_subtract)
                        ]
                    break
    
    def generate_routes(self):
        """生成路由规则文件"""
        print("开始生成路由规则...")

        # 确保数据文件存在且未过期
        if self.downloader:
            print("\n=== 检查和下载数据文件 ===")
            if not self.downloader.ensure_data_files():
                print("警告: 部分数据文件下载失败，可能影响路由生成质量")
            print()

        # 生成IPv4路由
        self._generate_ipv4_routes()

        # 生成IPv6路由
        self._generate_ipv6_routes()

        print("路由规则生成完成!")
        print("生成的文件:")
        print("  - routes4.conf (IPv4路由)")
        print("  - routes6.conf (IPv6路由)")
    
    def _generate_ipv4_routes(self):
        """生成IPv4路由规则"""
        print("正在生成IPv4路由...")

        # 从IPv4地址空间CSV文件读取分配信息
        ipv4_root = []

        try:
            with open("ipv4-address-space.csv", newline='') as f:
                f.readline()  # 跳过标题行
                reader = csv.reader(f, quoting=csv.QUOTE_MINIMAL)

                for row in reader:
                    if len(row) >= 6 and (row[5] == "ALLOCATED" or row[5] == "LEGACY"):
                        block = row[0]
                        # 构建CIDR格式: 如 "001/8" -> "1.0.0.0/8"
                        cidr = f"{block[:3].lstrip('0') or '0'}.0.0.0{block[-2:]}"
                        try:
                            network = IPv4Network(cidr)
                            ipv4_root.append(NetworkNode(network))
                            print(f"添加IPv4根网段: {network}")
                        except ValueError as e:
                            print(f"警告: IPv4根网段格式错误 {cidr}: {e}")

        except FileNotFoundError:
            print("警告: ipv4-address-space.csv 文件不存在，使用默认IPv4地址空间")
            # 使用默认的IPv4地址空间 (0.0.0.0/0)
            ipv4_root = [NetworkNode(IPv4Network('0.0.0.0/0'))]

        print(f"IPv4根网段总数: {len(ipv4_root)}")

        # 减去中国IP段
        china_ipv4 = self._load_china_networks(ipv4=True)
        self._subtract_networks(ipv4_root, china_ipv4)

        # 减去保留网段
        self._subtract_networks(ipv4_root, self.reserved_ipv4)

        # 写入IPv4路由文件
        with open("routes4.conf", 'w') as f:
            self._dump_bird_routes(ipv4_root, f)

        print(f"IPv4路由生成完成，共处理 {len(ipv4_root)} 个根网段")
    
    def _generate_ipv6_routes(self):
        """生成IPv6路由规则"""
        print("正在生成IPv6路由...")
        
        # IPv6使用全球单播地址空间作为起点
        ipv6_root = [NetworkNode(IPV6_UNICAST)]
        
        # 减去保留网段
        self._subtract_networks(ipv6_root, self.reserved_ipv6)
        
        # 减去中国IPv6段
        china_ipv6 = self._load_china_networks(ipv4=False)
        self._subtract_networks(ipv6_root, china_ipv6)
        
        # 写入IPv6路由文件
        with open("routes6.conf", 'w') as f:
            self._dump_bird_routes(ipv6_root, f)
        
        print("IPv6路由生成完成")
    
    def _load_china_networks(self, ipv4: bool = True) -> Set:
        """加载中国IP网段"""
        china_networks = set()

        print(f"加载中国{'IPv4' if ipv4 else 'IPv6'}网段...")

        # 从APNIC数据加载中国IP段
        try:
            with open("delegated-apnic-latest", 'r') as f:
                for line in f:
                    if ipv4 and "apnic|CN|ipv4|" in line:
                        # 解析IPv4段: apnic|CN|ipv4|1.2.3.0|256|20100101|allocated
                        parts = line.split("|")
                        if len(parts) >= 5:
                            ip_start = parts[3]
                            ip_count = int(parts[4])
                            # 计算CIDR前缀长度
                            prefix_len = 32 - int(math.log2(ip_count))
                            cidr = f"{ip_start}/{prefix_len}"
                            try:
                                network = IPv4Network(cidr)
                                china_networks.add(network)
                            except ValueError as e:
                                print(f"警告: APNIC IPv4网段格式错误 {cidr}: {e}")

                    elif not ipv4 and "apnic|CN|ipv6|" in line:
                        # 解析IPv6段: apnic|CN|ipv6|2001:db8::|64|20100101|allocated
                        parts = line.split("|")
                        if len(parts) >= 5:
                            ipv6_prefix = parts[3]
                            prefix_len = parts[4]
                            cidr = f"{ipv6_prefix}/{prefix_len}"
                            try:
                                network = IPv6Network(cidr)
                                china_networks.add(network)
                            except ValueError as e:
                                print(f"警告: APNIC IPv6网段格式错误 {cidr}: {e}")

        except FileNotFoundError:
            print("警告: delegated-apnic-latest 文件不存在，跳过APNIC数据")
        except Exception as e:
            print(f"警告: 读取APNIC数据时出错: {e}")

        # 对于IPv4，还可以从china_ip_list.txt加载额外的中国IP段
        if ipv4:
            try:
                with open("china_ip_list.txt", 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            try:
                                network = IPv4Network(line)
                                china_networks.add(network)
                            except ValueError as e:
                                print(f"警告: china_ip_list IPv4网段格式错误 {line}: {e}")

            except FileNotFoundError:
                print("警告: china_ip_list.txt 文件不存在，跳过额外的中国IP数据")
            except Exception as e:
                print(f"警告: 读取china_ip_list.txt时出错: {e}")

        print(f"成功加载 {len(china_networks)} 个中国{'IPv4' if ipv4 else 'IPv6'}网段")
        return china_networks

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='生成非中国大陆路由规则，用于BIRD路由器OSPF分流')
    parser.add_argument('--exclude', metavar='CIDR', type=str, nargs='*',
                        help='要排除的IPv4/IPv6网段，CIDR格式')
    parser.add_argument('--next', default="ens192", metavar="INTERFACE_OR_IP",
                        help='非中国IP的下一跳，通常是隧道接口名或IP地址 (默认: ens192)')
    parser.add_argument('--config', default=DEFAULT_CONFIG_FILE,
                        help=f'配置文件路径 (默认: {DEFAULT_CONFIG_FILE})')

    args = parser.parse_args()

    print("=== nchnroutes 路由生成器 (重构版) ===")
    print(f"下一跳设置: {args.next}")
    print(f"配置文件: {args.config}")

    # 创建路由生成器并生成路由
    generator = RouteGenerator(args.next, args.exclude)
    generator.config_file = args.config  # 传递配置文件路径
    generator.generate_routes()

if __name__ == "__main__":
    main()
