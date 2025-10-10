# nchnroutes

为 BIRD 路由器生成非中国大陆路由规则的 Python 工具，实现 OSPF 智能分流。

## 功能特性

- ✅ **iwik.org 数据源** - 使用 iwik.org 提供的高质量中国 IP 数据（MikroTik 格式）
- ✅ **IPv4/IPv6 双栈支持** - 完整支持 IPv4 和 IPv6 智能分流
- ✅ **配置文件管理** - 使用 INI 格式统一管理所有配置
- ✅ **灵活的保留网段** - 支持通过配置文件自定义 IPv4/IPv6 保留网段
- ✅ **自定义排除网段** - 支持添加特定 IP 段不进行分流
- ✅ **路径集中管理** - 所有文件路径统一配置，易于维护
- ✅ **树形网段减法算法** - 高效的网段排除算法，生成最优路由规则
- ✅ **数据异常检测** - 自动检测加载的网段数量是否异常

## 快速开始

### 1. 下载数据文件
```bash
# 使用 Makefile 下载最新数据（推荐）
make produce

# 或手动下载
curl -o cn_ipv4_list.txt "http://www.iwik.org/ipcountry/mikrotik/CN"
curl -o cn_ipv6_list.txt "http://www.iwik.org/ipcountry/mikrotik_ipv6/CN"
curl -o ipv4-address-space.csv "https://www.iana.org/assignments/ipv4-address-space/ipv4-address-space.csv"
```

### 2. 配置下一跳
编辑 `config.ini` 配置文件，设置默认下一跳接口：
```ini
[网络配置]
default_next_hop = eth0  # 修改为你的实际接口名
```

### 3. 生成路由规则
```bash
# 使用默认配置文件（config.ini）
python3 produce.py

# 指定自定义配置文件
python3 produce.py --config /path/to/custom_config.ini
```

### 4. 部署到 BIRD
```bash
# 复制生成的路由文件到 BIRD 配置目录
sudo cp routes4.conf /etc/bird/routes4.conf
sudo cp routes6.conf /etc/bird/routes6.conf

# 重新加载 BIRD 配置
sudo birdc configure
```

## 配置文件说明

编辑 `config.ini` 来自定义配置。

### 路径配置
```ini
[路径配置]
# IANA IPv4 地址空间分配表
ipv4_address_space = ipv4-address-space.csv

# 输出文件路径
routes4_output = routes4.conf
routes6_output = routes6.conf

# iwik.org 数据文件路径（由 Makefile 自动下载）
china_ipv4_file = cn_ipv4_list.txt
china_ipv6_file = cn_ipv6_list.txt
```

### 网络配置
```ini
[网络配置]
# 默认下一跳（接口名或 IP 地址）
# 这是生成的路由规则中 via 后面的参数
default_next_hop = eth0
```

### 保留网段配置

保留网段是指**不会被路由到旁路由**的特殊地址，会直接从主路由出去。

#### IPv4 保留网段
```ini
[保留网段IPv4]
# RFC 1918 私有地址
private_a = 10.0.0.0/8
private_b_alt = 172.24.0.0/13  # 避免与 Cloudflare 冲突
private_c = 192.168.0.0/16

# 特殊用途地址
loopback = 127.0.0.0/8        # 回环地址
link_local = 169.254.0.0/16   # 链路本地地址
multicast = 224.0.0.0/4       # 组播地址
reserved = 240.0.0.0/4        # 保留地址
cgn = 100.64.0.0/10          # 运营商级 NAT

# 自定义内网段（示例：光猫网段）
modem_network = 192.168.1.0/24
```

#### IPv6 保留网段
```ini
[保留网段IPv6]
# RFC 标准保留地址（如需要可取消注释）
# loopback = ::1/128           # 回环地址
# link_local = fe80::/10       # 链路本地地址
# multicast = ff00::/8         # 组播地址

# 自定义内网 IPv6 地址
# internal_network = fd00::/8  # ULA 地址
```

#### 自定义排除网段
```ini
[自定义排除]
# 在这里添加您想要直接从主路由出去的特定 IP 或网段
# 支持 IPv4 和 IPv6
special_server_ipv4 = 140.234.45.58/32
special_server_ipv6 = 2603:245:245:2828:245:95f3:9385:5501/128
# company_network = 203.0.113.0/24
```

### 配置说明

**保留网段 vs 中国网段**：
- **保留网段** - 不应该被路由的特殊地址（如回环、组播、私有地址等），在配置文件中定义
- **中国网段** - 应该直连而不走旁路由的地址，由 iwik.org 数据源自动提供（约 6,000+ IPv4 网段，11,000+ IPv6 网段）

**重要提示**：
- ✅ 中国 IP 网段**自动**从 iwik.org 数据加载，无需手动配置
- ⚙️ 如需排除特定 IP 不进行分流，添加到 `[自定义排除]` 节即可
- 🔧 如果发现数据源遗漏了某些中国 IP，建议向 iwik.org 反馈

## 输出文件

生成的路由规则文件：

- **`routes4.conf`** - IPv4 路由规则（BIRD 格式）
  - 约 17,000 条路由
  - 格式示例：`route 1.0.0.0/8 via "eth0";`

- **`routes6.conf`** - IPv6 路由规则（BIRD 格式）
  - 约 43,000 条路由
  - 格式示例：`route 2400::/6 via "eth0";`

## BIRD 路由器配置

### 在 BIRD 配置中引入路由规则

编辑 BIRD 配置文件（通常是 `/etc/bird/bird.conf`）：

```
protocol static {
    ipv4;
    # 引入生成的 IPv4 路由规则
    include "/etc/bird/routes4.conf";
}

protocol static {
    ipv6;
    # 引入生成的 IPv6 路由规则
    include "/etc/bird/routes6.conf";
}
```

### 部署流程

```bash
# 1. 生成路由规则
python3 produce.py

# 2. 复制到 BIRD 配置目录
sudo cp routes4.conf /etc/bird/routes4.conf
sudo cp routes6.conf /etc/bird/routes6.conf

# 3. 重新加载 BIRD 配置
sudo birdc configure

# 4. 验证 BIRD 状态
sudo birdc show protocols
sudo birdc show route protocol static1 | head -20
```

## 自动化更新

### 使用 Makefile 一键更新

Makefile 提供了自动化的更新流程：

```bash
# 一键更新：拉取代码、下载数据、生成路由、部署到 BIRD
make produce
```

Makefile 会执行以下操作：
1. `git pull` - 更新代码
2. 下载最新的中国 IP 数据（iwik.org）
3. 生成路由规则（routes4.conf 和 routes6.conf）
4. 复制到 BIRD 配置目录
5. 重新加载 BIRD 配置


## 工作原理

### 核心算法：网段减法树

程序使用树形结构实现高效的网段排除算法：

1. **构建根节点**
   - IPv4: 从 `ipv4-address-space.csv` 读取 IANA 分配的根网段（/8 级别）
   - IPv6: 使用全球单播地址 `2000::/3`

2. **加载排除网段**
   - 从 iwik.org 加载中国 IP 网段（MikroTik 格式）
   - 从配置文件加载保留网段和自定义排除网段

3. **执行网段减法**
   - 对每个需要排除的网段，在树中找到其父网段
   - 如果完全匹配，标记为死节点（不输出）
   - 如果是父网段的子网，执行 `address_exclude()` 拆分为多个子网

4. **生成 BIRD 路由**
   - 遍历树结构，跳过死节点
   - 输出叶子节点为 BIRD 路由规则

### 数据源

- **IPv4 根网段**: IANA IPv4 地址空间分配表
- **中国 IP 数据**: iwik.org（MikroTik 格式）
  - IPv4: 约 6,000+ 网段
  - IPv6: 约 11,000+ 网段

### 分流效果

生成的路由规则实现以下分流逻辑：

- ✅ **中国 IP** → 直接从主路由出去（不经过旁路由）
- ✅ **保留网段** → 直接从主路由出去（私有地址、回环等）
- ✅ **国外 IP** → 通过 BIRD 路由到旁路由（via 指定的接口）

**验证关键 IP**：
- `223.5.5.5`（阿里 DNS）→ 直连，不在路由表中
- `8.8.8.8`（Google DNS）→ 经过旁路由

## 项目文件结构

```
nchnroutes/
├── produce.py              # 主路由生成脚本
├── config.ini              # 配置文件
├── Makefile                # 自动化构建脚本
│
├── 数据文件（由 Makefile 下载）
│   ├── cn_ipv4_list.txt         # 中国 IPv4 网段（iwik.org）
│   ├── cn_ipv6_list.txt         # 中国 IPv6 网段（iwik.org）
│   └── ipv4-address-space.csv   # IANA IPv4 地址空间
│
└── 输出文件（由 produce.py 生成）
    ├── routes4.conf        # IPv4 路由规则（BIRD 格式）
    └── routes6.conf        # IPv6 路由规则（BIRD 格式）
```

### 核心模块说明

**produce.py** - 路由生成器
- `RouteGenerator` 类：核心路由生成逻辑
- `NetworkNode` 类：网段树形结构
- `_parse_iwik_format()` 方法：解析 MikroTik 格式数据
- `_subtract_networks()` 方法：网段减法算法
- `_dump_bird_routes()` 方法：输出 BIRD 路由规则

**config.ini** - 配置文件
- `[路径配置]`：数据文件和输出文件路径
- `[网络配置]`：下一跳等网络参数
- `[保留网段IPv4]`：IPv4 保留网段
- `[保留网段IPv6]`：IPv6 保留网段
- `[自定义排除]`：自定义排除网段

## 技术细节

### 依赖项

- **Python 3.7+**
- **标准库模块**：
  - `ipaddress` - IP 地址和网段处理
  - `configparser` - INI 配置文件解析
  - `csv` - CSV 文件读取
  - `re` - 正则表达式（解析 MikroTik 格式）
  - `argparse` - 命令行参数解析
  - `logging` - 日志输出

无需安装第三方依赖，开箱即用。

### 性能优化

- **树形结构**：使用树形节点避免重复计算
- **懒惰拆分**：只在必要时才拆分网段
- **死节点标记**：避免输出被完全排除的网段
- **CSV 直接读取**：跳过 pandas，减少内存占用

### 数据格式

**iwik.org MikroTik 格式**：
```
:do {
add address=1.0.1.0/24 list=CN
add address=1.0.2.0/23 list=CN
...
} on-error={}
```

**BIRD 路由格式**：
```
route 1.0.0.0/8 via "eth0";
route 2.0.0.0/8 via "eth0";
...
```

## 常见问题（FAQ）

**Q: 为什么选择 iwik.org 而不是 APNIC？**
- iwik.org 数据更新及时，格式简洁
- 直接提供 MikroTik 格式，便于解析
- IPv6 数据完整，包含所有主要 ISP 网段

**Q: 是否支持白名单模式（只路由中国 IP）？**
- 当前版本仅支持黑名单模式（排除中国 IP）
- 白名单模式可以通过反转逻辑实现，但需要修改代码

**Q: 生成的路由会占用多少内存？**
- IPv4 约 17,000 条路由，占用约 2-3 MB 内存
- IPv6 约 43,000 条路由，占用约 5-8 MB 内存
- BIRD 加载后总内存占用通常小于 50 MB

**Q: 多久需要更新一次路由数据？**
- 建议每周更新一次（`cron` 定时任务）
- IP 分配变化不频繁，每月更新也可以
- 重大网络调整后建议立即更新

## 版本历史

### v2.0（当前版本）
- ✨ 使用 iwik.org 数据源
- ✨ 完整的 IPv6 支持
- ✨ 代码重构为面向对象架构
- ✨ 树形网段减法算法
- ✨ 灵活的配置文件系统
- ✨ MikroTik 格式解析
- 🐛 修复 IPv6 网段加载问题

### v1.0
- 🎉 初始版本
- ✅ 基础 IPv4 路由生成
- ✅ APNIC 数据源

## 许可证

本项目采用 MIT 许可证。详见 LICENSE 文件。

## 贡献

欢迎提交 Issue 和 Pull Request！

### 贡献指南
1. Fork 本仓库
2. 创建特性分支（`git checkout -b feature/amazing-feature`）
3. 提交更改（`git commit -m 'Add amazing feature'`）
4. 推送到分支（`git push origin feature/amazing-feature`）
5. 打开 Pull Request

## 致谢

- [iwik.org](http://www.iwik.org/) - 提供高质量的 IP 地址数据
- [IANA](https://www.iana.org/) - IPv4 地址空间分配数据
- BIRD 项目 - 强大的路由软件

## 相关链接

- **BIRD 官网**: https://bird.network.cz/
- **iwik.org 数据源**: http://www.iwik.org/ipcountry/
- **IANA IPv4 地址空间**: https://www.iana.org/assignments/ipv4-address-space/

---

**最后更新**: 2025-10-10
