#!/usr/bin/env python3
"""
nchnroutes - 生成非中国大陆路由规则
用于BIRD路由器的OSPF智能分流配置
"""

import argparse
import csv
import logging
import re
import configparser
from pathlib import Path
from ipaddress import IPv4Network, IPv6Network

# 配置常量
class ConfigKeys:
    """配置文件的节名和键名"""
    SECTION_PATHS = '路径配置'
    SECTION_NETWORK = '网络配置'
    SECTION_RESERVED_V4 = '保留网段IPv4'
    SECTION_RESERVED_V6 = '保留网段IPv6'
    SECTION_CUSTOM_EXCLUDE = '自定义排除'
    KEY_NEXT_HOP = 'default_next_hop'

# 全局常量
IPV6_UNICAST = IPv6Network('2000::/3')
DEFAULT_CONFIG_FILE = Path("config.ini")

class NetworkNode:
    """网络节点类，用于构建路由树结构"""

    def __init__(self, cidr, parent=None):
        self.cidr = cidr
        self.child = []
        self.dead = False
        self.parent = parent

    def __repr__(self):
        return f"<NetworkNode {self.cidr}>"


class RouteGenerator:
    """路由生成器类"""

    def __init__(self, config_file: str | Path = DEFAULT_CONFIG_FILE):
        self.config_file = Path(config_file)
        self.next_hop = None
        self.reserved_ipv4 = set()
        self.reserved_ipv6 = set()
        self.config = None
        self.paths = {}

        self._load_config_paths()
        self._load_reserved_networks()

    def _load_config_paths(self):
        """加载路径配置"""
        self.paths = {
            'ipv4_address_space': Path('ipv4-address-space.csv'),
            'routes4_output': Path('routes4.conf'),
            'routes6_output': Path('routes6.conf'),
            'china_ipv4_file': Path('cn_ipv4_list.txt'),
            'china_ipv6_file': Path('cn_ipv6_list.txt'),
        }

        if self.config_file.exists():
            try:
                config = configparser.ConfigParser()
                config.read(self.config_file, encoding='utf-8')
                if config.has_section(ConfigKeys.SECTION_PATHS):
                    for key in self.paths:
                        if config.has_option(ConfigKeys.SECTION_PATHS, key):
                            self.paths[key] = Path(config.get(ConfigKeys.SECTION_PATHS, key))
            except Exception as e:
                logging.warning(f"读取路径配置出错: {e}")

    def _load_reserved_networks(self):
        """加载保留网段和网络配置"""
        if not self.config_file.exists():
            logging.error(f"配置文件不存在: {self.config_file}")
            self._load_default_reserved()
            return

        try:
            self.config = configparser.ConfigParser()
            self.config.read(self.config_file, encoding='utf-8')

            # 加载网络配置
            if self.config.has_section(ConfigKeys.SECTION_NETWORK):
                if self.config.has_option(ConfigKeys.SECTION_NETWORK, ConfigKeys.KEY_NEXT_HOP):
                    self.next_hop = self.config.get(ConfigKeys.SECTION_NETWORK, ConfigKeys.KEY_NEXT_HOP).strip()
                    logging.info(f"下一跳: {self.next_hop}")
                else:
                    self.next_hop = "eth0"
                    logging.warning(f"缺少下一跳配置，使用默认: {self.next_hop}")
            else:
                self.next_hop = "eth0"
                logging.warning(f"缺少网络配置段，使用默认下一跳: {self.next_hop}")

            # 加载IPv4保留网段
            self._load_network_section(ConfigKeys.SECTION_RESERVED_V4, IPv4Network, self.reserved_ipv4)

            # 加载IPv6保留网段
            self._load_network_section(ConfigKeys.SECTION_RESERVED_V6, IPv6Network, self.reserved_ipv6)

            # 加载自定义排除网段
            if self.config.has_section(ConfigKeys.SECTION_CUSTOM_EXCLUDE):
                for key, value in self.config.items(ConfigKeys.SECTION_CUSTOM_EXCLUDE):
                    network_str = value.strip()
                    if network_str:
                        try:
                            network = IPv6Network(network_str) if ':' in network_str else IPv4Network(network_str)
                            target_set = self.reserved_ipv6 if ':' in network_str else self.reserved_ipv4
                            target_set.add(network)
                        except ValueError as e:
                            logging.warning(f"自定义网段格式错误 {key}={network_str}: {e}")

            logging.info(f"配置加载完成: IPv4={len(self.reserved_ipv4)}, IPv6={len(self.reserved_ipv6)}")

        except Exception as e:
            logging.error(f"无法读取配置文件: {e}")
            self._load_default_reserved()

    def _load_network_section(self, section_name: str, NetworkClass, target_set: set):
        """加载指定配置节的网段"""
        if self.config.has_section(section_name):
            for key, value in self.config.items(section_name):
                network_str = value.strip()
                if network_str:
                    try:
                        target_set.add(NetworkClass(network_str))
                    except ValueError as e:
                        logging.warning(f"{section_name}格式错误 {key}={network_str}: {e}")

    def _load_default_reserved(self):
        """加载默认保留网段"""
        default_ipv4 = [
            '0.0.0.0/8', '10.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16',
            '172.24.0.0/13', '192.0.0.0/29', '192.168.0.0/16',
            '224.0.0.0/4', '240.0.0.0/4', '100.64.0.0/10'
        ]
        for network_str in default_ipv4:
            self.reserved_ipv4.add(IPv4Network(network_str))

        if self.next_hop is None:
            self.next_hop = "eth0"
            logging.info(f"使用默认下一跳: {self.next_hop}")

    def _dump_bird_routes(self, nodes: list[NetworkNode], output_file):
        """将路由节点写入BIRD配置文件"""
        for node in nodes:
            if node.child:
                self._dump_bird_routes(node.child, output_file)
            elif not node.dead:
                output_file.write(f'route {node.cidr} via "{self.next_hop}";\n')

    def _subtract_networks(self, root_nodes: list[NetworkNode], subtract_networks):
        """从根节点中减去指定的网段"""
        for network_to_subtract in subtract_networks:
            for node in root_nodes:
                if node.cidr == network_to_subtract:
                    node.dead = True
                    break
                if node.cidr.supernet_of(network_to_subtract):
                    if node.child:
                        self._subtract_networks(node.child, (network_to_subtract,))
                    else:
                        node.child = [
                            NetworkNode(subnet, parent=node)
                            for subnet in node.cidr.address_exclude(network_to_subtract)
                        ]
                    break

    def generate_routes(self):
        """生成路由规则文件"""
        self._generate_routes_for_protocol(ip_version=4)
        self._generate_routes_for_protocol(ip_version=6)
        logging.info("✓ 路由规则生成完成")
        logging.info(f"  - {self.paths['routes4_output']}")
        logging.info(f"  - {self.paths['routes6_output']}")

    def _get_ipv4_root_nodes(self) -> list[NetworkNode]:
        """从CSV文件加载IPv4根网段"""
        ipv4_root = []
        ipv4_space_file = self.paths['ipv4_address_space']
        try:
            with open(ipv4_space_file, newline='') as f:
                f.readline()
                reader = csv.reader(f, quoting=csv.QUOTE_MINIMAL)
                for row in reader:
                    if len(row) >= 6 and row[5] in ("ALLOCATED", "LEGACY"):
                        block = row[0]
                        cidr = f"{block[:3].lstrip('0') or '0'}.0.0.0{block[-2:]}"
                        try:
                            ipv4_root.append(NetworkNode(IPv4Network(cidr)))
                        except ValueError as e:
                            logging.warning(f"IPv4根网段格式错误 {cidr}: {e}")
        except FileNotFoundError:
            logging.warning(f"{ipv4_space_file} 不存在，使用全局地址空间")
            return [NetworkNode(IPv4Network('0.0.0.0/0'))]
        return ipv4_root

    def _generate_routes_for_protocol(self, ip_version: int):
        """为指定的IP版本生成路由规则"""
        if ip_version == 4:
            proto_name = "IPv4"
            root_nodes = self._get_ipv4_root_nodes()
            china_networks = self._load_china_networks(ipv4=True)
            reserved_networks = self.reserved_ipv4
            output_path = self.paths['routes4_output']
        elif ip_version == 6:
            proto_name = "IPv6"
            root_nodes = [NetworkNode(IPV6_UNICAST)]
            china_networks = self._load_china_networks(ipv4=False)
            reserved_networks = self.reserved_ipv6
            output_path = self.paths['routes6_output']
        else:
            raise ValueError("IP版本必须是4或6")

        logging.info(f"正在生成{proto_name}路由...")
        logging.info(f"  根网段: {len(root_nodes)}")

        if china_networks:
            logging.info(f"  减去中国IP: {len(china_networks)} 个")
            self._subtract_networks(root_nodes, china_networks)

        if reserved_networks:
            logging.info(f"  减去保留IP: {len(reserved_networks)} 个")
            self._subtract_networks(root_nodes, reserved_networks)

        with open(output_path, 'w') as f:
            self._dump_bird_routes(root_nodes, f)
        logging.info(f"  ✓ {proto_name}路由已写入")

    def _parse_iwik_format(self, content: str) -> list[str]:
        """解析iwik.org的MikroTik格式数据"""
        pattern = r'add address=([\d.:a-fA-F/]+)\s+list=CN'
        return [m.group(1).strip() for m in re.finditer(pattern, content) if m.group(1).strip()]

    def _load_china_networks(self, ipv4: bool = True) -> set:
        """加载中国IP网段"""
        china_networks = set()
        data_file = self.paths['china_ipv4_file' if ipv4 else 'china_ipv6_file']
        NetworkClass = IPv4Network if ipv4 else IPv6Network

        try:
            with open(data_file, 'r') as f:
                network_strings = self._parse_iwik_format(f.read())
            for network_str in network_strings:
                try:
                    china_networks.add(NetworkClass(network_str))
                except ValueError:
                    pass
            logging.info(f"  中国{'IPv4' if ipv4 else 'IPv6'}: {len(china_networks)} 个")
        except FileNotFoundError:
            logging.error(f"文件不存在: {data_file}")
        except Exception as e:
            logging.error(f"读取失败: {e}")

        if len(china_networks) < 100:
            logging.warning(f"网段数量异常少({len(china_networks)})")

        return china_networks


def main():
    """主函数"""
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )

    parser = argparse.ArgumentParser(description='生成非中国大陆路由规则')
    parser.add_argument('--config', default=DEFAULT_CONFIG_FILE,
                        help=f'配置文件路径 (默认: {DEFAULT_CONFIG_FILE})')
    args = parser.parse_args()

    logging.info("=" * 60)
    logging.info("  nchnroutes 路由生成器")
    logging.info("=" * 60)
    logging.info(f"配置文件: {args.config}\n")

    generator = RouteGenerator(args.config)
    generator.generate_routes()

    logging.info("\n" + "=" * 60)

if __name__ == "__main__":
    main()
