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
import re
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



class RouteGenerator:
    """路由生成器类"""
    
    def __init__(self, next_hop: str, config_file: str = DEFAULT_CONFIG_FILE, exclude_networks: List[str] = None):
        self.next_hop = next_hop
        self.reserved_ipv4 = set()
        self.reserved_ipv6 = set()
        self.config_file = config_file
        self.config = None  # 配置对象
        self.paths = {}  # 存储路径配置

        # 加载配置和路径
        self._load_config_paths()
        self._load_reserved_networks()

        # 添加命令行指定的排除网段
        if exclude_networks:
            self._add_exclude_networks(exclude_networks)

    def _load_config_paths(self):
        """集中加载所有路径配置"""
        # 设置默认路径
        self.paths = {
            'ipv4_address_space': 'ipv4-address-space.csv',
            'routes4_output': 'routes4.conf',
            'routes6_output': 'routes6.conf',
            'china_ipv4_file': 'cn_ipv4_list.txt',
            'china_ipv6_file': 'cn_ipv6_list.txt',
            'delegated_apnic': 'delegated-apnic-latest'
        }

        # 从配置文件覆盖默认值
        if os.path.exists(self.config_file):
            try:
                config = configparser.ConfigParser()
                config.read(self.config_file, encoding='utf-8')
                if config.has_section('路径配置'):
                    for key in self.paths:
                        if config.has_option('路径配置', key):
                            self.paths[key] = config.get('路径配置', key)
            except Exception as e:
                print(f"警告: 读取路径配置时出错: {e}")

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

            # 从网络配置中读取下一跳设置（如果命令行使用的是默认值）
            if config.has_section('网络配置') and config.has_option('网络配置', 'default_next_hop'):
                config_next_hop = config.get('网络配置', 'default_next_hop').strip()
                # 检查是否使用了argparse的默认值（通过比较来判断）
                parser_default = "ens192"  # 与main()函数中argparse的默认值保持一致
                if config_next_hop and self.next_hop == parser_default:
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
        print("使用本地数据文件进行路由生成...")

        # 生成IPv4路由
        self._generate_ipv4_routes()

        # 生成IPv6路由
        self._generate_ipv6_routes()

        print("路由规则生成完成!")
        print("生成的文件:")
        print("  - routes4.conf (IPv4路由)")
        print("  - routes6.conf (IPv6路由)")
    
    def _generate_ipv4_routes(self):
        """生成IPv4路由规则 - 参考原始nchnroutes逻辑"""
        print("正在生成IPv4路由...")

        # 从IPv4地址空间CSV文件读取分配信息
        ipv4_root = []

        ipv4_space_file = self.paths['ipv4_address_space']
        try:
            with open(ipv4_space_file, newline='') as f:
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
                        except ValueError as e:
                            print(f"警告: IPv4根网段格式错误 {cidr}: {e}")

        except FileNotFoundError:
            print(f"警告: {ipv4_space_file} 文件不存在，使用默认IPv4地址空间")
            # 使用默认的IPv4地址空间 (0.0.0.0/0)
            ipv4_root = [NetworkNode(IPv4Network('0.0.0.0/0'))]

        print(f"IPv4根网段总数: {len(ipv4_root)}")

        # 关键修复：按正确顺序处理
        # 1. 先减去中国IP段（最重要）
        china_ipv4 = self._load_china_networks(ipv4=True)
        print(f"开始减去 {len(china_ipv4)} 个中国IPv4网段...")
        self._subtract_networks(ipv4_root, china_ipv4)

        # 2. 再减去保留网段（包含自定义排除）
        print(f"开始减去 {len(self.reserved_ipv4)} 个保留/排除IPv4网段...")
        self._subtract_networks(ipv4_root, self.reserved_ipv4)

        # 写入IPv4路由文件
        routes_file = self.paths['routes4_output']
        with open(routes_file, 'w') as f:
            self._dump_bird_routes(ipv4_root, f)

        print(f"IPv4路由生成完成，共处理 {len(ipv4_root)} 个根网段")
    
    def _generate_ipv6_routes(self):
        """生成IPv6路由规则"""
        print("正在生成IPv6路由...")

        # IPv6使用全球单播地址空间作为起点
        ipv6_root = [NetworkNode(IPV6_UNICAST)]
        print(f"IPv6根网段: {IPV6_UNICAST}")

        # 减去中国IPv6段
        china_ipv6 = self._load_china_networks(ipv4=False)
        if china_ipv6:
            print(f"开始减去 {len(china_ipv6)} 个中国IPv6网段...")
            self._subtract_networks(ipv6_root, china_ipv6)
        else:
            print("未找到中国IPv6网段，跳过减法操作")

        # 减去保留IPv6段
        if self.reserved_ipv6:
            print(f"开始减去 {len(self.reserved_ipv6)} 个保留IPv6网段...")
            self._subtract_networks(ipv6_root, self.reserved_ipv6)

        # 写入IPv6路由文件
        routes6_file = self.paths['routes6_output']
        with open(routes6_file, 'w') as f:
            self._dump_bird_routes(ipv6_root, f)

        print("IPv6路由生成完成")
    


    def _parse_iwik_format(self, content: str) -> List[str]:
        """解析iwik.org的MikroTik格式数据，使用正则表达式提高鲁棒性"""
        networks = []
        # 匹配 MikroTik 格式：add address=IP/CIDR list=CN
        pattern = r'add address=([\d.:a-fA-F/]+)\s+list=CN'

        for match in re.finditer(pattern, content):
            network = match.group(1).strip()
            if network:
                networks.append(network)

        return networks

    def _load_china_networks(self, ipv4: bool = True) -> Set:
        """加载中国IP网段 - 支持iwik.org和APNIC数据源"""
        china_networks = set()

        print(f"加载中国{'IPv4' if ipv4 else 'IPv6'}网段（简化版）...")

        if ipv4:
            # 1. 从iwik数据加载IPv4
            iwik_file = self.paths['china_ipv4_file']
            iwik_count = 0
            try:
                with open(iwik_file, 'r') as f:
                    content = f.read()
                network_strings = self._parse_iwik_format(content)
                for network_str in network_strings:
                    try:
                        network = IPv4Network(network_str)
                        china_networks.add(network)
                        iwik_count += 1
                    except ValueError as e:
                        print(f"警告: iwik IPv4格式错误 {network_str}: {e}")
                print(f"从iwik数据加载了 {iwik_count} 个IPv4网段")
            except FileNotFoundError:
                print(f"警告: {iwik_file} 不存在，请运行 make download")
            except Exception as e:
                print(f"警告: 读取iwik IPv4数据出错: {e}")

            # 2. 如果iwik数据不足，尝试APNIC备用数据
            if iwik_count == 0:
                print("⚠️  iwik IPv4数据不可用，尝试APNIC备用数据...")
                apnic_file = self.paths['delegated_apnic']
                apnic_count = 0
                try:
                    with open(apnic_file, 'r') as f:
                        for line in f:
                            if "apnic|CN|ipv4|" in line:
                                parts = line.split("|")
                                if len(parts) >= 5:
                                    try:
                                        ip_start = parts[3]
                                        ip_count = int(parts[4])
                                        prefix_len = 32 - int(math.log2(ip_count))
                                        cidr = f"{ip_start}/{prefix_len}"
                                        network = IPv4Network(cidr)
                                        china_networks.add(network)
                                        apnic_count += 1
                                    except (ValueError, OverflowError) as e:
                                        print(f"警告: APNIC IPv4格式错误 {line.strip()}: {e}")
                    print(f"从APNIC备用数据加载了 {apnic_count} 个CN IPv4网段")
                except FileNotFoundError:
                    print(f"❌ 错误: {apnic_file} 也不存在，请运行 make download")
                except Exception as e:
                    print(f"❌ 错误: 读取APNIC数据失败: {e}")

                if apnic_count == 0:
                    print("❌ 错误: 无法从任何数据源加载IPv4数据")
                    print("请运行: make download")

        else:  # IPv6
            # 1. 从iwik数据加载IPv6
            iwik_file = self.paths['china_ipv6_file']
            iwik_count = 0
            try:
                with open(iwik_file, 'r') as f:
                    content = f.read()
                network_strings = self._parse_iwik_format(content)
                for network_str in network_strings:
                    try:
                        network = IPv6Network(network_str)
                        china_networks.add(network)
                        iwik_count += 1
                    except ValueError as e:
                        print(f"警告: iwik IPv6格式错误 {network_str}: {e}")
                print(f"从iwik数据加载了 {iwik_count} 个IPv6网段")
            except FileNotFoundError:
                print(f"警告: {iwik_file} 不存在，请运行 make download")
            except Exception as e:
                print(f"警告: 读取iwik IPv6数据出错: {e}")

            # 2. 如果iwik数据不足，报告错误
            if iwik_count == 0:
                print("❌ 错误: 无法加载iwik IPv6数据，请确保已下载 cn_ipv6_list.txt")
                print("下载命令: make download 或 make cn_ipv6_list.txt")

        print(f"总共加载 {len(china_networks)} 个中国{'IPv4' if ipv4 else 'IPv6'}网段")
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
    generator = RouteGenerator(args.next, args.config, args.exclude)
    generator.generate_routes()

if __name__ == "__main__":
    main()
