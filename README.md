# nchnroutes

为RouterOS OSPF智能分流生成非中国大陆路由规则的Python工具。

## 功能特性

- ✅ **iwik.org数据源** - 使用iwik.org提供的高质量中国IP数据
- ✅ **IPv4/IPv6双栈支持** - 完整支持IPv4和IPv6智能分流
- ✅ **配置文件管理** - 使用INI格式统一管理所有配置
- ✅ **自定义排除** - 支持添加特定IP段不进行分流
- ✅ **备用数据源** - iwik数据不可用时自动回退到APNIC数据
- ✅ **路径集中管理** - 所有文件路径统一配置，易于维护
- ✅ **验证工具** - 独立的路由验证脚本确保生成质量

## 快速开始

### 1. 下载数据文件
```bash
# 使用Makefile下载最新数据（推荐）
make download

# 或手动下载
curl -o cn_ipv4_list.txt "http://www.iwik.org/ipcountry/mikrotik/CN"
curl -o cn_ipv6_list.txt "http://www.iwik.org/ipcountry/mikrotik_ipv6/CN"
curl -o delegated-apnic-latest "https://ftp.apnic.net/stats/apnic/delegated-apnic-latest"
```

### 2. 生成路由规则
```bash
# 基本使用
python3 produce.py

# 指定自定义配置文件
python3 produce.py --config config.ini

# 添加自定义排除网段
python3 produce.py --exclude 8.8.8.8/32 1.1.1.1/32

# 指定下一跳接口
python3 produce.py --next ens192
```

### 3. 验证生成结果
```bash
# 验证路由质量
python3 verify_routes.py

# 检查关键IP是否正确排除（如223.5.5.5）
python3 verify_routes.py --ipv4 routes4.conf --ipv6 routes6.conf
```

## 配置文件

编辑 `config.ini` 来自定义配置：

### 路径配置
```ini
[路径配置]
# 数据文件路径
ipv4_address_space = ipv4-address-space.csv
delegated_apnic = delegated-apnic-latest

# 输出文件路径
routes4_output = routes4.conf
routes6_output = routes6.conf

# iwik.org数据文件路径（由Makefile下载）
china_ipv4_file = cn_ipv4_list.txt
china_ipv6_file = cn_ipv6_list.txt
```

### 网络配置
```ini
[网络配置]
# 默认下一跳接口（如果命令行未指定）
default_next_hop = ens192
```

### 自定义保留网段
```ini
[保留网段IPv4]
# RFC 1918 私有地址
private_a = 10.0.0.0/8
private_b_alt = 172.24.0.0/13  # 避免与Cloudflare冲突
private_c = 192.168.0.0/16

# 自定义内网段
modem_network = 192.168.1.0/24

[保留网段IPv6]
# IPv6特殊地址（RFC标准保留地址）
loopback = ::1/128
link_local = fe80::/10
multicast = ff00::/8
unspecified = ::/128
documentation = 2001:db8::/32

# 内网IPv6地址（如果有的话）
# internal_network = fd00::/8  # 示例：ULA地址

[自定义排除IPv6]
# 特殊服务器或不希望分流的IPv6地址
# special_server = 2001:db8::1/128
```

### 重要说明

**中国IPv6网段处理**：
- ✅ **自动处理** - 脚本通过iwik.org数据自动加载中国IPv6网段（约11,000个）
- ❌ **不要手动配置** - 不需要在配置文件中手动添加中国IPv6网段
- 🔧 **如需补充** - 如果发现遗漏的中国IPv6网段，建议向iwik.org反馈

**保留网段 vs 中国网段**：
- **保留网段** - 不应该被路由的特殊地址（如回环、组播等）
- **中国网段** - 应该直连而不走旁路由的地址（由数据源自动提供）

## 生成的文件

- `routes4.conf` - IPv4路由规则（BIRD格式，约17,000条路由）
- `routes6.conf` - IPv6路由规则（BIRD格式，约43,000条路由）

## 部署到BIRD

生成的文件可直接用于BIRD路由器：
```bash
# 1. 验证生成的路由
python3 verify_routes.py

# 2. 复制到BIRD配置目录
sudo cp routes4.conf /etc/bird/routes4.conf
sudo cp routes6.conf /etc/bird/routes6.conf

# 3. 重新加载BIRD配置
sudo birdc configure

# 4. 验证BIRD状态
sudo birdc show protocols static1
sudo birdc show route protocol static1 | head -10
```

## 自动化更新

### 使用Makefile
```bash
# 更新数据并重新生成路由
make update

# 只下载数据
make download

# 只生成路由
make generate
```

### 使用cron定时任务
```bash
# 每天凌晨2点更新路由规则
0 2 * * * cd /path/to/nchnroutes && make update && sudo cp routes*.conf /etc/bird/ && sudo birdc configure
```

## 工作原理

### 路由生成流程
1. **构建全球IP地址空间** - 从`ipv4-address-space.csv`读取IANA分配的IPv4根网段
2. **加载中国IP数据** - 优先使用iwik.org数据，备用APNIC数据
3. **网段减法运算** - 从全球地址空间中减去中国IP段和保留网段
4. **生成BIRD路由** - 输出标准BIRD格式的静态路由配置

### 数据源优先级
- **IPv4**: iwik.org → APNIC备用数据
- **IPv6**: iwik.org → 手动配置的主要ISP网段

### 智能分流效果
- **中国IP** → 直接从RouterOS出去（不经过旁路由）
- **国外IP** → 通过BIRD路由到旁路由处理
- **关键验证**: 223.5.5.5（阿里DNS）直连，不走旁路由

## 项目文件

### 核心脚本
- `produce.py` - 主路由生成脚本
- `verify_routes.py` - 路由验证工具
- `config.ini` - 统一配置文件

### 数据文件
- `cn_ipv4_list.txt` - 中国IPv4网段（iwik.org格式）
- `cn_ipv6_list.txt` - 中国IPv6网段（iwik.org格式）
- `delegated-apnic-latest` - APNIC官方数据（备用）
- `ipv4-address-space.csv` - IANA IPv4地址空间分配

### 输出文件
- `routes4.conf` - IPv4路由规则（BIRD格式）
- `routes6.conf` - IPv6路由规则（BIRD格式）

## 故障排除

### 常见问题

**Q: 223.5.5.5仍然走旁路由？**
```bash
# 检查路由生成是否正确
grep "route 223.0\|route 223.5" routes4.conf
# 应该没有输出，如果有输出说明配置有问题

# 验证路由
python3 verify_routes.py
```

**Q: IPv6无法分流？**
```bash
# 检查IPv6数据是否加载
python3 produce.py | grep "IPv6网段"
# 应该显示加载了11000+个IPv6网段

# 检查IPv6路由数量
wc -l routes6.conf
# 应该有40000+条路由
```

**Q: 数据下载失败？**
```bash
# 手动下载数据
curl -o cn_ipv4_list.txt "http://www.iwik.org/ipcountry/mikrotik/CN"
curl -o cn_ipv6_list.txt "http://www.iwik.org/ipcountry/mikrotik_ipv6/CN"

# 检查文件内容
head -5 cn_ipv4_list.txt
# 应该看到 :do { add address=... list=CN } 格式
```

## 版本历史

- **v2.0** - 使用iwik.org数据源，完整IPv6支持，代码重构优化
- **v1.0** - 基础版本，使用GitHub数据源
