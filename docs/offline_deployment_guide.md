# RAG 系统内网离线部署指南

## 概述

本指南适用于在**无外网访问**的 Ubuntu 18.04 环境中部署 RAG 知识管理平台。

**部署架构**：
- 后端：Python 3.10.14 + FastAPI（端口 8000）
- 前端：Next.js 14+ 生产构建（端口 3000）
- 向量数据库：Qdrant（本地文件存储）
- 依赖模型：FastEmbed 稀疏向量模型（本地）

**关键约束**：
- 内网环境无法访问 PyPI、npm、HuggingFace
- 需要提前在有网环境准备所有依赖
- SiliconFlow API（Embedding/Reranker）需要外网访问或内网代理

---

## 阶段一：准备工作（有网环境 - Windows）

### 1.1 克隆代码

```bash
git clone https://github.com/without7091/RAG.git
cd RAG
```

### 1.2 准备 Python 环境和依赖

#### 下载 Python 3.10.14 离线安装包

访问 https://www.python.org/downloads/release/python-31014/
下载：`Python-3.10.14.tgz`（Linux 源码包）

#### 下载 uv 工具（推荐）

本项目使用 **uv** 作为依赖管理工具（比 pip 快 10-100 倍）。

```bash
# 下载 uv Linux 版本
# 访问 https://github.com/astral-sh/uv/releases
# 下载 uv-x86_64-unknown-linux-gnu.tar.gz

# 或使用 curl（有网环境）
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 打包 Python 依赖（使用 uv）

```bash
cd backend

# 方式1：导出完整依赖锁（推荐）
# uv.lock 已存在，直接使用
uv export --frozen --no-hashes -o requirements.txt

# 方式2：从 pyproject.toml 生成
uv pip compile pyproject.toml -o requirements.txt

# 下载所有依赖包（Linux 平台）
uv pip download \
  --python-platform linux \
  --python-version 3.10 \
  -r requirements.txt \
  -o ../offline_packages/python_wheels

# 同时下载 local-sparse 可选依赖（FastEmbed）
uv pip download \
  --python-platform linux \
  --python-version 3.10 \
  --extra local-sparse \
  -r requirements.txt \
  -o ../offline_packages/python_wheels
```

**备选方案（使用 pip）**：
```bash
pip download -r requirements.txt \
  --platform manylinux2014_x86_64 \
  --only-binary=:all: \
  -d ./python_packages
```

### 1.3 准备 FastEmbed 模型文件

FastEmbed 需要从 HuggingFace 下载稀疏向量模型。

```python
# 在有网环境运行此脚本下载模型
from fastembed import SparseTextEmbedding

# 下载模型到本地
model = SparseTextEmbedding(model_name="Qdrant/bm42-all-minilm-l6-v2-attentions")
# 模型会缓存到 ~/.cache/fastembed/ 或 FASTEMBED_CACHE_PATH
```

**手动下载**：
```bash
# 创建模型目录
mkdir -p fastembed_models

# 从 HuggingFace 下载模型文件
# https://huggingface.co/Qdrant/bm42-all-minilm-l6-v2-attentions
# 下载所有文件到 fastembed_models/bm42-all-minilm-l6-v2-attentions/
```

### 1.4 准备 Node.js 环境和依赖

#### 下载 Node.js 离线安装包

访问 https://nodejs.org/
下载：`node-v20.x.x-linux-x64.tar.xz`（推荐 LTS 版本）

#### 打包前端依赖

```bash
cd frontend

# 安装依赖并缓存
npm install

# 打包 node_modules（方式1：直接压缩）
tar -czf node_modules.tar.gz node_modules/

# 方式2：使用 npm pack（更可靠）
npm pack --pack-destination=../offline_packages
```

**推荐方式**：使用 `npm ci` 的离线缓存
```bash
# 生成 package-lock.json
npm install

# 下载所有依赖到本地缓存
npm ci --cache ./npm_cache --prefer-offline

# 打包缓存
tar -czf npm_cache.tar.gz npm_cache/
```

### 1.5 整理传输包

创建传输目录结构：
```
RAG_offline_deploy/
├── code/                          # 项目代码
│   └── RAG/
├── runtime/
│   ├── Python-3.10.14.tgz        # Python 源码
│   ├── node-v20.x.x-linux-x64.tar.xz
│   └── uv-x86_64-unknown-linux-gnu.tar.gz  # uv 工具
├── dependencies/
│   ├── python_wheels/            # Python wheels（uv 下载）
│   ├── npm_cache.tar.gz          # npm 缓存
│   └── fastembed_models/         # FastEmbed 模型
└── scripts/
    └── deploy.sh                 # 部署脚本
```

---

## 阶段二：传输到内网 Ubuntu

### 2.1 传输方式

- U盘拷贝
- 内网文件服务器
- scp（如果内网可达）

```bash
# 示例：scp 传输
scp -r RAG_offline_deploy/ user@ubuntu-server:/home/user/
```

---

## 阶段三：Ubuntu 18.04 内网部署

### 3.1 安装系统依赖

```bash
# 更新包管理器（如果有内网镜像源）
sudo apt update

# 安装编译 Python 所需的依赖
sudo apt install -y \
  build-essential \
  libssl-dev \
  zlib1g-dev \
  libncurses5-dev \
  libncursesw5-dev \
  libreadline-dev \
  libsqlite3-dev \
  libgdbm-dev \
  libdb5.3-dev \
  libbz2-dev \
  libexpat1-dev \
  liblzma-dev \
  tk-dev \
  libffi-dev
```

**如果无法 apt install**：需要提前下载 .deb 包
```bash
# 在有网环境下载
apt download build-essential libssl-dev zlib1g-dev ...
# 传输到内网后安装
sudo dpkg -i *.deb
```

### 3.2 安装 Python 3.10.14

```bash
cd /home/user/RAG_offline_deploy/runtime

# 解压
tar -xzf Python-3.10.14.tgz
cd Python-3.10.14

# 编译安装
./configure --enable-optimizations --prefix=/usr/local/python3.10
make -j$(nproc)
sudo make altinstall

# 验证
/usr/local/python3.10/bin/python3.10 --version

# 创建软链接
sudo ln -s /usr/local/python3.10/bin/python3.10 /usr/local/bin/python3.10
sudo ln -s /usr/local/python3.10/bin/pip3.10 /usr/local/bin/pip3.10
```

### 3.3 安装 Node.js

```bash
cd /home/user/RAG_offline_deploy/runtime

# 解压
tar -xJf node-v20.x.x-linux-x64.tar.xz

# 移动到系统目录
sudo mv node-v20.x.x-linux-x64 /usr/local/nodejs

# 配置环境变量
echo 'export PATH=/usr/local/nodejs/bin:$PATH' >> ~/.bashrc
source ~/.bashrc

# 验证
node --version
npm --version
```

### 3.4 部署后端

```bash
cd /home/user/RAG_offline_deploy/code/RAG/backend

# 安装 uv 工具
cd /home/user/RAG_offline_deploy/runtime
tar -xzf uv-x86_64-unknown-linux-gnu.tar.gz
sudo mv uv /usr/local/bin/
uv --version

# 返回后端目录
cd /home/user/RAG_offline_deploy/code/RAG/backend

# 使用 uv 创建虚拟环境
uv venv --python 3.10

# 激活虚拟环境
source .venv/bin/activate

# 离线安装依赖（从本地 wheels）
uv pip install \
  --no-index \
  --find-links /home/user/RAG_offline_deploy/dependencies/python_wheels \
  -e ".[local-sparse]"

# 或使用 pip 安装（备选）
# pip install --no-index --find-links=/home/user/RAG_offline_deploy/dependencies/python_wheels -e ".[local-sparse]"

# 配置 FastEmbed 模型路径
export FASTEMBED_CACHE_PATH=/home/user/RAG_offline_deploy/dependencies/fastembed_models

# 创建 .env 文件
cat > .env << EOF
# SiliconFlow API（需要外网访问或代理）
SILICONFLOW_API_KEY=your_api_key_here
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1

# Qdrant 本地存储
QDRANT_PATH=./qdrant_local_storage

# 服务配置
HOST=0.0.0.0
PORT=8000

# FastEmbed 模型路径
FASTEMBED_CACHE_PATH=/home/user/RAG_offline_deploy/dependencies/fastembed_models
EOF

# 启动后端（测试）
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3.5 部署前端

```bash
cd /home/user/RAG_offline_deploy/code/RAG/frontend

# 解压 npm 缓存
tar -xzf /home/user/RAG_offline_deploy/dependencies/npm_cache.tar.gz

# 离线安装依赖
npm ci --cache ./npm_cache --offline --prefer-offline

# 配置环境变量
cat > .env.local << EOF
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
EOF

# 构建生产版本
npm run build

# 启动生产服务器
npm run start
```

---

## 阶段四：生产环境配置

### 4.1 使用 systemd 管理服务

#### 后端服务

```bash
sudo nano /etc/systemd/system/rag-backend.service
```

```ini
[Unit]
Description=RAG Backend API Service
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/home/user/RAG_offline_deploy/code/RAG/backend
Environment="PATH=/home/user/RAG_offline_deploy/code/RAG/backend/venv/bin"
Environment="FASTEMBED_CACHE_PATH=/home/user/RAG_offline_deploy/dependencies/fastembed_models"
ExecStart=/home/user/RAG_offline_deploy/code/RAG/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable rag-backend
sudo systemctl start rag-backend
sudo systemctl status rag-backend
```

#### 前端服务

```bash
sudo nano /etc/systemd/system/rag-frontend.service
```

```ini
[Unit]
Description=RAG Frontend Service
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/home/user/RAG_offline_deploy/code/RAG/frontend
Environment="PATH=/usr/local/nodejs/bin:/usr/bin:/bin"
ExecStart=/usr/local/nodejs/bin/npm run start
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable rag-frontend
sudo systemctl start rag-frontend
sudo systemctl status rag-frontend
```

### 4.2 配置 Nginx 反向代理（可选）

```bash
sudo apt install nginx  # 或使用离线 .deb 包
```

```nginx
# /etc/nginx/sites-available/rag
server {
    listen 80;
    server_name your_domain_or_ip;

    # 前端
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    # 后端 API
    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/rag /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 阶段五：验证部署

### 5.1 健康检查

```bash
# 后端健康检查
curl http://localhost:8000/health

# 前端访问
curl http://localhost:3000
```

### 5.2 功能测试

1. 访问前端：`http://server_ip:3000`
2. 创建知识库
3. 上传测试文档
4. 执行检索测试

---

## 常见问题

### Q1: SiliconFlow API 无法访问（内网无外网）

**解决方案**：
- 配置内网 HTTP 代理
- 或在内网部署自己的 Embedding/Reranker 服务（需要 GPU）

### Q2: FastEmbed 模型加载失败

检查环境变量：
```bash
export FASTEMBED_CACHE_PATH=/path/to/fastembed_models
```

### Q3: Python 编译失败

确保安装了所有编译依赖，特别是 `libssl-dev` 和 `libffi-dev`

### Q4: npm 离线安装失败

使用 `npm ci` 而不是 `npm install`，并确保 `package-lock.json` 存在

---

## 本地虚拟机模拟测试

### 创建断网 Ubuntu 虚拟机

1. 使用 VirtualBox/VMware 创建 Ubuntu 18.04 虚拟机
2. 网络设置：
   - 方式1：禁用网络适配器
   - 方式2：设置为"仅主机(Host-Only)"网络
3. 通过共享文件夹传输部署包

### 测试流程

```bash
# 1. 验证无网络
ping 8.8.8.8  # 应该失败

# 2. 按照上述步骤部署

# 3. 验证服务
systemctl status rag-backend
systemctl status rag-frontend
```

---

## 附录：自动化部署脚本

见 `scripts/deploy.sh`（待创建）

---

**文档版本**: v1.0
**更新日期**: 2026-03-04
**适用版本**: RAG v2.0.0
