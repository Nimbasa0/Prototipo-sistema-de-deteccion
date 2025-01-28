#Este codigo se encarga de estar enviando constantemente el último frame hacía el servidor RTSP
#Comienza enviando una imagen en negro, luego a medida que recibe los frames Kafka, los acomoda en la imagen y continúa con la transmisión
from kafka import KafkaConsumer
import logging
import base64
from PIL import Image
from io import BytesIO
import subprocess
import numpy as np
import time
from datetime import datetime
from kafka.errors import KafkaError, NoBrokersAvailable


#Para este codigo estaba probando usar un logger en vez de directamente print
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


#Definición de algunas variables para los consumidores Kafka
bootstrap_servers = 'broker:29092'
topics = ['transmision_cam1', 'transmision_cam2', 'transmision_cam3']
group_id = 'frames'
#URL y FPS del stream RTSP generado
rtsp_url = 'rtsp://rtsp-server:8554/mystream' 
fps = 10 


#Configuración de los consumidores de Kafka
def crear_consumer_kafka(bootstrap_servers, topics, group_id, retries=10, delay=5):
    for attempt in range(retries):
        try:
            consumer = KafkaConsumer(
                *topics,
                bootstrap_servers=bootstrap_servers,
                group_id=group_id,
                auto_offset_reset='latest',
                enable_auto_commit=False,
                consumer_timeout_ms=1000
            )
            print(f"Conexión a Kafka exitosa en el intento {attempt + 1}")
            return consumer
        except NoBrokersAvailable as e:
            print(f"Error de conexion a Kafka: {e}. Reintentando en {delay} segundos...")
            time.sleep(delay)
        except KafkaError as e:
            print(f"Error en Kafka: {e}. reintentando en {delay} segundos...")
            time.sleep(delay)
    
    print("No se pudo conectar a Kafka después de varios intentos.")
    return None



# Configuración de FFmpeg para enviar el video hacía el servidor RTSP
ffmpeg_cmd = [
    'ffmpeg',
    '-y',
    '-f', 'rawvideo',
    '-pix_fmt', 'bgr24',
    '-s', '1280x720',
    '-r', str(fps),
    '-i', '-', 
    '-c:v', 'libx264',
    '-preset', 'ultrafast',
    '-crf', '28',
    '-b:v', '500k',
    '-g', '10',
    '-f', 'rtsp',
    '-rtsp_transport', 'udp',
    '-max_interleave_delta', '100M',
    '-x264-params', 'slice-max-size=1460',
    '-loglevel', 'debug',
    '-tune', 'zerolatency',
    rtsp_url
]

#Inicio del proceso de FFmpeg
ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

#un contador de paquetes para la visualización en terminal
packet_count = 1


ultimo_frame = None

#Función de envio del último frame al servidor RTSP
def enviar_ultimo_frame(ultimo_frame, fps):
    if ultimo_frame is not None:
        for _ in range(int(fps)): 
            ffmpeg_process.stdin.write(ultimo_frame)
            ffmpeg_process.stdin.flush()
            time.sleep(1 / fps)  

#Lista de frames
frames = {'transmision_cam1': None,'transmision_cam2': None,'transmision_cam3': None}

#Junte de las tres imagenes con cajas de detección en una sola

def crear_frame_compuesto(frames):
    #Imagen de 1280x720 en negro
    compuesto = np.zeros((720, 1280, 3), dtype=np.uint8)  

    #Asignando un cuarto de la imagen al último frame de cada topico
    if frames['transmision_cam1'] is not None:
        compuesto[0:360, 0:640] = frames['transmision_cam1']
    if frames['transmision_cam2'] is not None:
        compuesto[0:360, 640:1280] = frames['transmision_cam2']
    if frames['transmision_cam3'] is not None:
        compuesto[360:720, 0:640] = frames['transmision_cam3']
    return compuesto.tobytes()

#Redimensión de imagen para que entren en el espacio
def resize_image(image, size=(640, 360)):
    return image.resize(size) 

#Creación de los consumidores e inicio del consumo
consumer = crear_consumer_kafka(bootstrap_servers, topics, group_id)
if not consumer:
    logger.error("No se pudo conectar a Kafka, terminando el proceso.")
    exit(1)    
try:
    logger.info('Iniciando consumo de mensajes...')
    while True:  
        message = consumer.poll(timeout_ms=1000) 
        #Se obtienen los mensajes de los topicos, se desempaquetan hasta obtener el JSON y 
        # se guardan los campos de frame_id, timestamp y base64_data en variables
        if message:
            for topic_partition, messages in message.items():
                topic = topic_partition.topic
                for msg in messages:         
                    message_value = msg.value.decode('utf-8') 
                    try:
                        message_json = eval(message_value) 
                        frame_id = message_json.get('frame_id')  
                        timestamp = message_json.get('timestamp')  
                        base64_data = message_json.get('frame_base64') 
                        #Se decodifica el frame desde base64 y se reconstruye la imagen, luego se redimensiona para ajustarla a la imagen
                    #compuesta
                        if base64_data:
                            image_data = base64.b64decode(base64_data)
                            image = Image.open(BytesIO(image_data))
                            image = resize_image(image, size=(640, 360))

                           #Se pasa a arreglo numpy para añadir a la imagen compuesta
                            image_np = np.array(image)
                            image_np = image_np[:, :, ::-1]  
                            frames[topic] = image_np  
                            #Se añaden los frames al frame compuesto 
                            compuesto_frame = crear_frame_compuesto(frames)

                            #Se envía el frame compuesto hacía el servidor RTSP mediante FFmpeg
                            ffmpeg_process.stdin.write(compuesto_frame)
                            ffmpeg_process.stdin.flush()
                            logger.info(f'Paquete {packet_count} recibido de {topic}')
                            logger.info(f'Frame ID: {frame_id}, Timestamp: {timestamp}')
                        else:
                            logger.warning(f'Paquete {packet_count} recibido de {topic} pero no contiene datos.')   
                    except Exception as e:
                        logger.error(f'Error procesndo el paquete {packet_count}: {e}') 
                    packet_count += 1
        else:
            #Se mantiene enviando el último frame compuesto si no se reciben nuevos. Así, si hay inestabilidad en el envío de los frame
            #al menos, el envío al servidor RTSP no se va a acabar, así una vez la conexión vuelva, el stream seguirá con normalidad   
            enviar_ultimo_frame(crear_frame_compuesto(frames), fps)
finally:
    #Se cierran los consumidores Kafka y el proceso de FFmpeg
    consumer.close()
    ffmpeg_process.stdin.close()
    ffmpeg_process.wait()
    logger.info('Consumidor cerrado y proceso ffmpeg terminado.')
