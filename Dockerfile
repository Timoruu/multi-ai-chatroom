# 多模型聊天室 —— 最小镜像
# ⚠️ 本机没有 Docker，本文件未经实测；如构建失败先确认基础镜像 Python ≥ 3.10
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# 依赖单独一层，改代码不必重装
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# run.py 检测到 PORT 会自动监听 0.0.0.0
ENV PORT=8765
ENV NO_BROWSER=1
EXPOSE 8765

# data/ 必须挂卷，否则重启丢聊天记录
VOLUME ["/app/data"]

CMD ["python", "run.py"]
