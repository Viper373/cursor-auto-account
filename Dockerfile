FROM python:3.9-slim

WORKDIR /app

# 安装 Chrome 和依赖（用于 DrissionPage）
# 说明：在某些环境 libgconf-2-4 在新发行版中已被移除，故不再依赖它。
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list && \
    sed -i 's/security.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list && \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      wget \
      gnupg \
      unzip \
      xvfb \
      libxi6 \
      socat \
      libnss3 \
      libxss1 \
      libgbm1 \
      fonts-liberation \
      xdg-utils \
      ca-certificates \
    ; \
    # 下载并安装 chrome deb，使用 dpkg 安装然后修复依赖
    wget -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb; \
    dpkg -i /tmp/google-chrome.deb || apt-get -f install -y; \
    rm -f /tmp/google-chrome.deb; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /tmp/*

# 复制项目文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建模板目录和截图目录
RUN mkdir -p templates screenshots

# 暴露端口
EXPOSE 8001 9223

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8001
ENV DEBUG=false

# 创建启动脚本
COPY start.sh /start.sh
RUN chmod +x /start.sh

# 启动服务
CMD ["/start.sh"]