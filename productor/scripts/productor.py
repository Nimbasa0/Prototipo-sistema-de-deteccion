import threading
import queue
import time
import cv2
from datetime import datetime
from kafka import KafkaProducer
import json
import base64
from ultralytics import YOLO
import dask
from dask.distributed import Client
import torch 
from torchvision import transforms


def imagen_a_base64(image):
    #Transforma imagen en base 64 para el JSON
    _, buffer = cv2.imencode('.jpg', image)
    imagen_bytes = buffer.tobytes()
    imagen_base64 = base64.b64encode(imagen_bytes).decode('utf-8')
    return imagen_base64


def enviar_json_a_kafka(json_data, topic_name, producer):
    #Envío de los JSON a Kafka
    producer.send(topic_name, value=json_data)
    print(f"JSON enviado a Kafka, tópico: {topic_name}", flush=True)

#Relacionador de topicos con los cam ID (Para asignar los frames al correspondiente tópico)
topico_a_cam_id = {
    "transmision_cam1": 1,
    "transmision_cam2": 2,
    "transmision_cam3": 3
}

#Uso de GPU
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print(f"Utilizando el dispositivo: {device}")

#modelo YOLO
model = YOLO('best.pt')  
model.to(device) 

#COMENTARIO: Es posible que para mejorar la precisión en la detección de objetos en las imagenes haya que cambiar la forma de extraer los 
# frames y ajustarlos a YOLO. Actualmente se adaptan los frames extraidos con openCV a las caracteristicas necesarias para aplicar YOLO, lo
#que altera el color de las imágenes.


def ajustar_frame_para_yolo(frame_resized):
   #Requisitos de YOLO de caracteristicas de la imagen (RGB) - Altera el color de las imágenes
    frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
    frame_rgb = frame_rgb.astype('float32') / 255.0  
    transform = transforms.Compose([
        transforms.ToTensor(),  
    ])
    
    frame_tensor = transform(frame_rgb)   
    frame_tensor = frame_tensor.unsqueeze(0).to(device) 
    return frame_tensor



def procesar_stream(rtsp_url, nombre_topico):
    #Configuración del productor Kafka
    producer = KafkaProducer(bootstrap_servers='broker:29092',
                             value_serializer=lambda v: json.dumps(v).encode('utf-8'))
    
    
    cap = cv2.VideoCapture(rtsp_url)
    
    #Frames que se toman por segundo de la transmisión original
    fps_limit = 10  
    frame_interval = 1.0 / fps_limit
    frame_count = 0 

    #se identifica el cam ID
    cam_id = topico_a_cam_id.get(nombre_topico, 0)

    #se hace la cola de frames de 1, así se toma el más actual siempre
    frame_queue = queue.Queue(maxsize=1)

    # Variable donde se guarda la última detección con su respectivo cam_id y timestamp para usarlo más adelante
    ultima_deteccion = {"cam_id": cam_id, "timestamp": None, "detecciones": []}
    
    def leer_frames():
        #Lectura de frames según la cola
        nonlocal frame_count
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                print(f"No se pudo leer el frame del stream {rtsp_url}. Saliendo...")
                break
           
            frame_resized = cv2.resize(frame, (640, 640))
           
            if not frame_queue.full():
                frame_queue.put(frame_resized)
            else:
               
                frame_queue.get()
                frame_queue.put(frame_resized)
            time.sleep(0)  

    
    def procesar_frame():
        #Procesamiento de frames (Funcionamiento principal)
        nonlocal frame_count
        while cap.isOpened():
            if not frame_queue.empty():
                #Obtención del frame redimensionado
                frame_resized = frame_queue.get()
                timestamp = datetime.now().isoformat()
                start_time = time.time()
                #Aplicación del ajuste al frame para poder utilizarse con YOLO
                frame_tensor = ajustar_frame_para_yolo(frame_resized)
                #Aplicación YOLO
                results = model(frame_tensor)  
                result = results[0]

                ########Envío de resultados de detección escritos

                #Extraer resultados de detecciones
                #Clases: 0=log ; 1=person ; 2=helmet ; 3=truck
                detecciones = []
                for box in result.boxes:
                    clase = int(box.cls.cpu().numpy())
                    confianza = float(box.conf.cpu().numpy())
                    coordenadas = box.xyxy.cpu().numpy().tolist()
                    detecciones.append({
                        "clase": clase,
                        "confianza": confianza,
                        "coordenadas": coordenadas
                    })

                #Actualización de la última detección para enviar a el contenedor de detecciones
                ultima_deteccion.update({"timestamp": timestamp, "detecciones": detecciones})
                ######Envio de imagenes con cajas de detección


                #Reajuste de colores y transformación frame con cajas de detección a base64
                frame_resized2 = result.plot() 
                frame_pa_json = cv2.cvtColor(frame_resized2, cv2.COLOR_RGB2BGR)
                frame_base64 = imagen_a_base64(frame_pa_json)

                #JSON utilizado para la transmisión en vivo
                frame_data = {
                    "cam_id": cam_id,
                    "timestamp": timestamp,
                    "frame_base64": frame_base64,
                    "frame_id": frame_count + 1  
                }

                #Envio de JSON con frame con cajas de detección a Kafka
                enviar_json_a_kafka(frame_data, nombre_topico, producer)
                print(f'Frame {frame_count + 1} enviado a Kafka desde {rtsp_url} con timestamp {timestamp}', flush=True)

                frame_count += 1
                elapsed_time = time.time() - start_time
                
                sleep_time = max(0, frame_interval - elapsed_time)
                time.sleep(sleep_time)
                del frame_resized2
                del frame_base64 
                del frame_tensor
                torch.cuda.empty_cache() 

    #Definición de la función que envía las detecciones al contenedor de alertas
    def enviar_detecciones():
        while cap.isOpened():
            if ultima_deteccion["timestamp"]:
                enviar_json_a_kafka(ultima_deteccion, "detecciones", producer)
                print(f"Última detección enviada: {ultima_deteccion}")
            #Ajuste del tiempo entre envío de la información para las alertas (actualmente 2 segundos)
            time.sleep(2)

    #Se crean tres hilos, dos para leer y procesar todo lo que tiene que ver con el frame y otro hilo para las detecciones
    hilo_lectura_frame = threading.Thread(target=leer_frames)
    hilo_procesamiento_frame = threading.Thread(target=procesar_frame)
    hilo_detecciones = threading.Thread(target=enviar_detecciones)
    #Se inician los hilos
    hilo_lectura_frame.start()
    hilo_procesamiento_frame.start()
    hilo_detecciones.start()

    #Espera a la finalización de los hilos
    hilo_lectura_frame.join()
    hilo_procesamiento_frame.join()
    hilo_detecciones.join()
    #Cierre de OpenCV y Kafka
    cap.release()
    producer.close()

#Lista de streams RTSP
# stream de prueba para cuando las cámaras están apagadas: http://142.0.109.159/axis-cgi/mjpg/video.cgi
# cam 1: rtsp://129.222.172.5:2525/Streaming/Channels/102
# cam 2: rtsp://129.222.172.5:1500/Streaming/Channels/102
# cam 3: rtsp://129.222.172.5:10554/Streaming/Channels/102
streams = [
    {"url": "rtsp://admin:test1122@129.222.172.5:10554/Streaming/Channels/102", "topic": "transmision_cam1"},
    {"url": "rtsp://admin:test1122@129.222.172.5:1500/Streaming/Channels/102", "topic": "transmision_cam2"},
    {"url": "rtsp://admin:test1122@129.222.172.5:2525/Streaming/Channels/102", "topic": "transmision_cam3"}
]


if __name__ == '__main__':
    #Inicio de Dask
    client = Client()

    futures = []
    for stream in streams:
        future = dask.delayed(procesar_stream)(stream["url"], stream["topic"])
        futures.append(future)

    dask.compute(*futures)

    client.close()
