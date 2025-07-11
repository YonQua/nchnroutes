# nchnroutes - 重构版

为RouterOS OSPF智能分流生成非中国大陆路由规则。

## 功能特性

- ✅ **自动下载数据** - 自动获取最新的IP地址分配数据
- ✅ **配置文件管理** - 使用INI格式统一管理所有配置
- ✅ **自定义排除** - 支持添加特定IP不进行分流
- ✅ **容错处理** - 下载失败时自动使用本地旧文件
- ✅ **完整中文注释** - 代码易读易维护

## 使用方法

### 基本使用
```bash
python3 produce_refactored.py
```

### 命令行选项
```bash
python3 produce_refactored.py --help
python3 produce_refactored.py --config custom.ini
python3 produce_refactored.py --exclude 8.8.8.8/32 1.1.1.1/32
```

## 配置文件

编辑 `config.ini` 来自定义配置：

### 添加自定义排除IP
在 `[自定义排除]` 部分添加：
```ini
[自定义排除]
special_server = 140.245.45.58/32
dns_server = 8.8.8.8/32
company_network = 203.0.113.0/24
```

### 修改下载源
在 `[数据源URL]` 部分修改：
```ini
[数据源URL]
china_ip_source = mayaxcn
china_ip_mayaxcn = https://example.com/new-source.txt
```

## 生成的文件

- `routes4.conf` - IPv4路由规则（用于BIRD配置）
- `routes6.conf` - IPv6路由规则（用于BIRD配置）

## 用于BIRD配置

生成的文件可直接用于BIRD路由器：
```bash
# 复制到BIRD配置目录
sudo cp routes4.conf /etc/bird/routes4.conf
sudo cp routes6.conf /etc/bird/routes6.conf

# 重新加载BIRD配置
sudo birdc configure
```

## 定时更新

建议设置cron定时任务：
```bash
# 每天凌晨2点更新路由规则
0 2 * * * cd /path/to/nchnroutes && python3 produce_refactored.py
```

## 工作原理

1. **构建全球IP地址空间** - 从ipv4-address-space.csv读取全球IPv4分配
2. **减去中国IP段** - 从APNIC数据和china_ip_list.txt获取中国IP
3. **减去内网/保留IP段** - 排除私有网络、组播等不需要分流的网段
4. **生成路由规则** - 输出BIRD格式的静态路由配置

## 文件说明

- `produce_refactored.py` - 主脚本（重构版）
- `config.ini` - 统一配置文件
- `ipv4-address-space.csv` - IPv4地址空间数据
- `delegated-apnic-latest` - APNIC官方数据（自动下载）
- `china_ip_list.txt` - 中国IP列表（自动下载）
