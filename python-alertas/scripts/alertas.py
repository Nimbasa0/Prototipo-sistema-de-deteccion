from kafka import KafkaConsumer
from influxdb_client import InfluxDBClient, Point, WritePrecision
import time
import json
from datetime import datetime
from influxdb_client.client.write_api import SYNCHRONOUS


# Configuración del topico de Kafka
bootstrap_servers = 'broker:29092'
topic = 'detecciones'
group_id = 'deteccion'

# Configuración de InfluxDB (se puede cambiar con el archivo 'variables.env' en la carpeta conf)
INFLUXDB_URL = "http://influxdb:8086"  
INFLUXDB_TOKEN = "token44"            
INFLUXDB_ORG = "org"       
INFLUXDB_BUCKET = "bucket1"  


# Inicio cliente de InfluxDB
influx_client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)


# Mapeo de clases a texto (Quitar o agregar clases para las correspondientes alertas)
#Clases del modelo YOLO: 0=log ; 1=person ; 2=helmet ; 3=truck
CLASES = {
    0: "log",
    1: "person",
    2: "helmet",
    3: "truck",  
}

#Inicio del Kafka consumer y configuración

def inicio_kafka_consumer(bootstrap_servers, topic, group_id, retries=10, delay=5):
    for attempt in range(retries):
        try:
            consumer = KafkaConsumer(
                topic,
                bootstrap_servers=bootstrap_servers,
                group_id=group_id,
                auto_offset_reset='latest',
                enable_auto_commit=False,
            )
            print(f"Conexión a Kafka exitosa en el intento {attempt + 1}")
            return consumer
        except Exception as e:
            print(f"Error de conexión a Kafka: {e}. Reintentando en {delay} segundos...")
            time.sleep(delay)
    print("No se pudo conectar a Kafka después de varios intentos.")
    return None


#Función para enviar la alerta hacía InfluxDB

def enviar_a_influxdb(cam_id, timestamp, resumen):
    try:
        #Texto que se va a mostrar en el log de Grafana
        texto = f"Resumen de detecciones para la cámara '{cam_id}' con timestamp '{timestamp}': {resumen}"
        #Forma de enviar el dato hacia InfluxDB
        point = (
            Point("deteccion")
            .field("mensaje", texto)
            .time(datetime.utcnow(), WritePrecision.NS)
        )
        write_api.write(bucket=INFLUXDB_BUCKET, org=INFLUXDB_ORG, record=point)
        print(f"Datos enviados a InfluxDB: {texto}")
    except Exception as e:
        print(f"Error al enviar datos a InfluxDB: {e}")


#Función que procesa el mensaje recibido de Kafka, obteniendo las detecciones del JSON que se generaba en el contenedor productor
def procesar_mensaje(message):
    json_de_kafka = None

    try:
        #Obteniendo los datos del JSON
        message_value = message.value
        json_de_kafka = json.loads(message_value)
        #Guardando los campos del objeto JSON en variables
        cam_id = json_de_kafka.get("cam_id")
        timestamp = json_de_kafka.get("timestamp")
        detecciones = json_de_kafka.get("detecciones", [])
        #Para revisar
        print(detecciones)

        if not detecciones:
            print(f"No se encontraron detecciones en el frame con timestamp {timestamp} y cam_id {cam_id}")
        else:
            # Función para contar los objetos de cada clase
            conteo_clases = {}
            for deteccion in detecciones:
                clase_id = deteccion.get("clase")
                clase_texto = CLASES.get(clase_id, f"Clase-{clase_id}")
                conteo_clases[clase_texto] = conteo_clases.get(clase_texto, 0) + 1

            # Función para generar el mensaje resumen que se envía a Grafana, especificando el número de objetos detectados en la imagen
            partes_resumen = []
            for clase, cantidad in conteo_clases.items():
                if cantidad == 1:
                    partes_resumen.append(f"un objeto '{clase}'")
                else:
                    partes_resumen.append(f"{cantidad} objetos '{clase}'")

            #Unión de los mensajes de detecciones.
            resumen = " - ".join(partes_resumen)

            # Envio del mensaje a InfluxDB
            enviar_a_influxdb(cam_id, timestamp, resumen)
            print(f"Resumen de detecciones: {resumen}")

    except json.JSONDecodeError:
        print(f"Mensaje no válido recibido: {message.value}")
    except KeyError as e:
        print(f"Error de formato en el mensaje, falta clave: {e}")
    except Exception as e:
        print(f"Error inesperado al procesar el mensaje: {str(e)}")

    return json_de_kafka

#Función para comenzar el consumo de mensajes
def consumo_de_mensajes(consumer):
    try:
        print('Iniciando consumo de mensajes...')
        for message in consumer:
            json_de_kafka = procesar_mensaje(message)
            if json_de_kafka:
                print("Mensaje procesado exitosamente.")
            else:
                print("Error al procesar el mensaje.")
    except Exception as e:
        print(f"Error inesperado al consumir mensajes: {str(e)}")
    finally:
        consumer.close()
        print("Consumidor cerrado.")


# Inicio del consumidor de Kafka y el procesamiento de los JSON

consumer = inicio_kafka_consumer(bootstrap_servers, topic, group_id)
if consumer:
    consumo_de_mensajes(consumer)
else:
    print("No se pudo conectar al tópico 'detecciones'.")
