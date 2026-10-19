# 参数录入服务镜像
FROM docker.m.daocloud.io/python:3.13-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /srv/app

# 先只拷依赖清单, 让依赖层可以被缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再拷代码
COPY app ./app
COPY templates ./templates
COPY static ./static

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
