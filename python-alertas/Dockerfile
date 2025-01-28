
FROM python:3.9-slim

RUN apt update -y
RUN apt upgrade -y

RUN apt-get install -y libgl1-mesa-glx
RUN apt-get install -y libglib2.0-0
RUN pip install kafka-python influxdb-client

WORKDIR /scripts

COPY ./scripts /scripts

CMD ["python", "-u", "alertas.py"]