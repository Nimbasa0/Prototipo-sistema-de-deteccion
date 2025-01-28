
FROM python:3.9-slim

RUN apt update -y
RUN apt upgrade -y

RUN apt-get install -y libgl1-mesa-glx
RUN apt-get install -y libglib2.0-0
RUN pip install kafka-python
RUN pip install pillow
RUN apt install ffmpeg -y
RUN pip install numpy

WORKDIR /scripts

COPY ./scripts /scripts

CMD ["python", "transmision.py"]