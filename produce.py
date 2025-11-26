#!/usr/bin/env python3
"""
nchnroutes - 生成非中国大陆路由规则
用于BIRD路由器的OSPF智能分流配置

优化说明:
1. 使用 collapse_addresses 合并输入网段，减少计算量
2. IPv4 根节点使用字典索引，实现 O(1) 查找
3. 并行处理 IPv4 和 IPv6 路由生成
"""

import argparse
import csv
import logging
import re
import configparser
import time
from pathlib import Path
from ipaddress import IPv4Network, IPv6Network, collapse_addresses
from concurrent.futures import ThreadPoolExecutor
from typing import List, Set, Dict, Optional, Union, Type

# 类型别名
IPNetwork = Union[IPv4Network, IPv6Network]

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
    __slots__ = ('cidr', 'child', 'dead')

    def __init__(self, cidr: IPNetwork):
        self.cidr = cidr
        self.child: List['NetworkNode'] = []
        self.dead = False

    def __repr__(self):
        return f"<NetworkNode {self.cidr} dead={self.dead}>"

class RouteGenerator:
    """路由生成器类"""

    def __init__(self, config_file: Union[str, Path] = DEFAULT_CONFIG_FILE):
        self.config_file = Path(config_file)
        self.next_hop: str = "eth0"
        self.reserved_ipv4: List[IPv4Network] = []
        self.reserved_ipv6: List[IPv6Network] = []
        self.config: Optional[configparser.ConfigParser] = None
        self.paths: Dict[str, Path] = {}

        self._load_config_paths()
        self._load_reserved_networks()

    def _load_config_paths(self):
        """加载路径配置"""
        # 默认路径
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
        reserved_v4_set = set()
        reserved_v6_set = set()

        if not self.config_file.exists():
            logging.error(f"配置文件不存在: {self.config_file}")
            self._load_default_reserved(reserved_v4_set)
        else:
            try:
                self.config = configparser.ConfigParser()
                self.config.read(self.config_file, encoding='utf-8')

                # 加载网络配置
                if self.config.has_section(ConfigKeys.SECTION_NETWORK):
                    self.next_hop = self.config.get(
                        ConfigKeys.SECTION_NETWORK, 
                        ConfigKeys.KEY_NEXT_HOP, 
                        fallback="eth0"
                    ).strip()
                    logging.info(f"下一跳: {self.next_hop}")

                # 加载各部分配置
                self._load_network_section(ConfigKeys.SECTION_RESERVED_V4, IPv4Network, reserved_v4_set)
                self._load_network_section(ConfigKeys.SECTION_RESERVED_V6, IPv6Network, reserved_v6_set)
                
                # 加载自定义排除
                if self.config.has_section(ConfigKeys.SECTION_CUSTOM_EXCLUDE):
                    for key, value in self.config.items(ConfigKeys.SECTION_CUSTOM_EXCLUDE):
                        network_str = value.strip()
                        if not network_str:
                            continue
                        try:
                            if ':' in network_str:
                                reserved_v6_set.add(IPv6Network(network_str))
                            else:
                                reserved_v4_set.add(IPv4Network(network_str))
                        except ValueError as e:
                            logging.warning(f"自定义网段格式错误 {key}={network_str}: {e}")

            except Exception as e:
                logging.error(f"无法读取配置文件: {e}")
                self._load_default_reserved(reserved_v4_set)

        # 预先合并保留网段，减少后续计算
        self.reserved_ipv4 = list(collapse_addresses(reserved_v4_set))
        self.reserved_ipv6 = list(collapse_addresses(reserved_v6_set))
        logging.info(f"配置加载完成: 保留IPv4={len(self.reserved_ipv4)} (合并后), 保留IPv6={len(self.reserved_ipv6)} (合并后)")

    def _load_network_section(self, section_name: str, NetworkClass: Type[IPNetwork], target_set: Set[IPNetwork]):
        """加载指定配置节的网段"""
        if self.config and self.config.has_section(section_name):
            for key, value in self.config.items(section_name):
                network_str = value.strip()
                if network_str:
                    try:
                        target_set.add(NetworkClass(network_str))
                    except ValueError as e:
                        logging.warning(f"{section_name}格式错误 {key}={network_str}: {e}")

    def _load_default_reserved(self, target_set: Set[IPv4Network]):
        """加载默认保留网段"""
        default_ipv4 = [
            '0.0.0.0/8', '10.0.0.0/8', '127.0.0.0/8', '169.254.0.0/16',
            '172.24.0.0/13', '192.0.0.0/29', '192.168.0.0/16',
            '224.0.0.0/4', '240.0.0.0/4', '100.64.0.0/10'
        ]
        for network_str in default_ipv4:
            target_set.add(IPv4Network(network_str))
        logging.info(f"使用默认下一跳: {self.next_hop}")

    def _dump_bird_routes(self, nodes: List[NetworkNode], output_file):
        """递归写入BIRD路由规则"""
        # 使用栈替代递归以防止深度过深（虽然通常不会），并略微提高性能
        stack = list(reversed(nodes))
        while stack:
            node = stack.pop()
            if node.dead:
                continue
            
            if node.child:
                stack.extend(reversed(node.child))
            else:
                output_file.write(f'route {node.cidr} via "{self.next_hop}";\n')

    def _subtract_network(self, node: NetworkNode, network_to_subtract: IPNetwork) -> bool:
        """
        从节点中减去指定网段
        返回 True 如果该节点被完全移除（dead）
        """
        if node.dead:
            return True
            
        # 情况1: 完全匹配，标记为死节点
        if node.cidr == network_to_subtract:
            node.dead = True
            return True
            
        # 情况2: 待减网段是当前节点的子网
        if network_to_subtract.subnet_of(node.cidr):
            if not node.child:
                # 如果没有子节点，进行拆分
                # address_exclude 返回的是排除后的剩余网段
                node.child = [NetworkNode(subnet) for subnet in node.cidr.address_exclude(network_to_subtract)]
                # 这里的逻辑是：address_exclude 已经把 network_to_subtract 挖掉了
                # 所以生成的子节点里已经不包含 network_to_subtract 了，不需要再递归处理
                # 除非我们是在处理重叠的排除网段（比如先排除了一个大的，又来一个小的），
                # 但由于我们已经做了 collapse_addresses，理论上输入网段是不重叠的。
                # 为了保险起见（防止 address_exclude 行为差异），或者处理更复杂的重叠情况：
                # 实际上 address_exclude 已经完成了"减法"。
                return False
            else:
                # 如果已有子节点，递归传递给子节点处理
                # 过滤掉已经 dead 的子节点
                new_children = []
                for child in node.child:
                    if not self._subtract_network(child, network_to_subtract):
                        new_children.append(child)
                node.child = new_children
                
                # 如果所有子节点都死了，父节点也死了
                if not node.child:
                    node.dead = True
                    return True
        
        # 情况3: 待减网段与当前节点无交集，或当前节点是待减网段的子网（已被 collapse 处理掉，或者在根节点筛选时已排除）
        return False

    def _process_subtraction(self, root_nodes: List[NetworkNode], networks_to_subtract: List[IPNetwork], is_ipv4: bool):
        """执行网段减法"""
        if is_ipv4:
            # IPv4 优化：建立索引
            # 根节点通常是 /8，我们可以用第一个八位组作为 key
            # 这样可以将 O(N) 的查找降低到 O(1)
            node_map = {}
            for node in root_nodes:
                # 获取第一个八位组
                first_octet = int(str(node.cidr.network_address).split('.')[0])
                if first_octet not in node_map:
                    node_map[first_octet] = []
                node_map[first_octet].append(node)
            
            for net in networks_to_subtract:
                # 找到对应的根节点
                first_octet = int(str(net.network_address).split('.')[0])
                if first_octet in node_map:
                    for node in node_map[first_octet]:
                        if net.subnet_of(node.cidr) or node.cidr == net:
                            self._subtract_network(node, net)
                            # 一个网段通常只属于一个根节点（除非根节点有重叠，IANA分配表通常无重叠）
                            # 但为了安全，不 break，或者确认无重叠后 break
                            break 
        else:
            # IPv6 只有一个根节点 2000::/3，直接遍历
            for net in networks_to_subtract:
                for node in root_nodes:
                    if net.subnet_of(node.cidr) or node.cidr == net:
                        self._subtract_network(node, net)

    def _get_ipv4_root_nodes(self) -> List[NetworkNode]:
        """从CSV文件加载IPv4根网段"""
        ipv4_root = []
        ipv4_space_file = self.paths['ipv4_address_space']
        try:
            with open(ipv4_space_file, newline='') as f:
                f.readline() # Skip header
                reader = csv.reader(f, quoting=csv.QUOTE_MINIMAL)
                for row in reader:
                    if len(row) >= 6 and row[5] in ("ALLOCATED", "LEGACY"):
                        block = row[0]
                        # 构造 /8 网段
                        cidr_str = f"{int(block[:3])}.0.0.0/8"
                        try:
                            ipv4_root.append(NetworkNode(IPv4Network(cidr_str)))
                        except ValueError as e:
                            logging.warning(f"IPv4根网段格式错误 {cidr_str}: {e}")
        except FileNotFoundError:
            logging.warning(f"{ipv4_space_file} 不存在，使用全局地址空间")
            return [NetworkNode(IPv4Network('0.0.0.0/0'))]
        return ipv4_root

    def _parse_iwik_format(self, content: str) -> List[str]:
        """解析iwik.org的MikroTik格式数据"""
        pattern = r'add address=([\d.:a-fA-F/]+)\s+list=CN'
        return [m.group(1).strip() for m in re.finditer(pattern, content) if m.group(1).strip()]

    def _load_china_networks(self, ipv4: bool = True) -> List[IPNetwork]:
        """加载中国IP网段并合并"""
        networks = []
        data_file = self.paths['china_ipv4_file' if ipv4 else 'china_ipv6_file']
        NetworkClass = IPv4Network if ipv4 else IPv6Network

        try:
            with open(data_file, 'r') as f:
                network_strings = self._parse_iwik_format(f.read())
            
            raw_networks = []
            for network_str in network_strings:
                try:
                    raw_networks.append(NetworkClass(network_str))
                except ValueError:
                    pass
            
            # 关键优化：合并网段
            # collapse_addresses 会自动合并相邻和包含的网段
            # 例如 1.1.1.0/24 和 1.1.0.0/24 会合并为 1.1.0.0/23
            networks = list(collapse_addresses(raw_networks))
            
            logging.info(f"  中国{'IPv4' if ipv4 else 'IPv6'}: 原始 {len(raw_networks)} -> 合并后 {len(networks)}")
            
        except FileNotFoundError:
            logging.error(f"文件不存在: {data_file}")
        except Exception as e:
            logging.error(f"读取失败: {e}")

        if len(networks) < 100:
            logging.warning(f"网段数量异常少({len(networks)})")

        return networks

    def _generate_routes_for_protocol(self, ip_version: int):
        """为指定的IP版本生成路由规则"""
        start_time = time.time()
        if ip_version == 4:
            proto_name = "IPv4"
            root_nodes = self._get_ipv4_root_nodes()
            china_networks = self._load_china_networks(ipv4=True)
            reserved_networks = self.reserved_ipv4
            output_path = self.paths['routes4_output']
        else:
            proto_name = "IPv6"
            root_nodes = [NetworkNode(IPV6_UNICAST)]
            china_networks = self._load_china_networks(ipv4=False)
            reserved_networks = self.reserved_ipv6
            output_path = self.paths['routes6_output']

        logging.info(f"[{proto_name}] 开始生成...")
        logging.info(f"[{proto_name}] 根网段: {len(root_nodes)}")

        # 合并所有需要排除的网段
        all_subtracts = china_networks + reserved_networks
        # 再次合并，确保中国IP和保留IP之间的重叠也被处理
        all_subtracts = list(collapse_addresses(all_subtracts))
        
        logging.info(f"[{proto_name}] 需排除网段总数: {len(all_subtracts)}")

        self._process_subtraction(root_nodes, all_subtracts, ip_version == 4)

        with open(output_path, 'w') as f:
            self._dump_bird_routes(root_nodes, f)
            
        duration = time.time() - start_time
        logging.info(f"[{proto_name}] 生成完成，耗时 {duration:.2f}秒 -> {output_path}")

    def generate_routes(self):
        """主生成函数，并行执行"""
        logging.info("开始生成路由规则 (并行模式)...")
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            future4 = executor.submit(self._generate_routes_for_protocol, 4)
            future6 = executor.submit(self._generate_routes_for_protocol, 6)
            
            future4.result()
            future6.result()
            
        total_time = time.time() - start_time
        logging.info(f"全部完成! 总耗时: {total_time:.2f}秒")

def main():
    """主函数"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    parser = argparse.ArgumentParser(description='生成非中国大陆路由规则')
    parser.add_argument('--config', default=DEFAULT_CONFIG_FILE,
                        help=f'配置文件路径 (默认: {DEFAULT_CONFIG_FILE})')
    args = parser.parse_args()

    logging.info("=" * 60)
    logging.info("  nchnroutes 路由生成器 (Optimized)")
    logging.info("=" * 60)
    
    generator = RouteGenerator(args.config)
    generator.generate_routes()

    logging.info("=" * 60)

if __name__ == "__main__":
    main()
