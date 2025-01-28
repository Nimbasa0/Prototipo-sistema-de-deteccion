##Sistema de detección para cámaras RTSP
Este sistema es una arquitectura que toma las transmisiones en vivo de cámaras de seguridad mediante protocolo RTSP, aplicandoles un modelo de detección de objetos YOLO pre-entrenado a las imágenes a medida que se van consumiendo. Los resultados de detección se entregan de dos formas: 
- Mediante una transmisión en vivo RTSP con las imágenes originales presentando las cajas de detección respectivas.
- Y mediante un sistema de alertas que entrega un mensaje escrito una vez se detecta un objeto de interés en las imágenes de las cámaras.

La visualización de estos resultados es accesible mediante Grafana. El sistema completo es hospedado en contenedores individuales de Docker. A continuación, se presenta el esquema general de la arquitectura:

###Arquitectura del sistema de detección
![](https://github.com/Nimbasa0/Prototipo-sistema-de-deteccion/images/esquema_general.jpg)

Cada bloque de la imagen representa un contenedor Docker ejecutandose. Estas etapas o secciones son:

####Etapa de ingesta de imágenes y aplicación del modelo de detección

La primera sección es compuesta por un único contendor encargado de ejecutar el algoritmo de python ***productor.py*** encargado de la extracción de imágenes de las transmisiones RTSP  de las cámaras y de la aplicación del modelo YOLO para la posterior obtención de los respectivos resultados para cada fuente de datos. De forma especifica, el código realiza las tareas de obtención de imagen y aplicación del modelo YOLO de forma paralela para cada cámara gracias a la libreria Dask. 
Posterior a la obtención de resultados mediante el modelo de detección, se realiza el empaquetado de estos en objetos JSON que son enviados hacía Kafka, siendo tres tópicos encargados de recibir los JSON con las imágenes con cajas de detección y uno solo encargado de recibir los JSON con los datos de detección escritos.

####Etapa de transmisión de datos

Como se mencionó, la transmisión de los datos entre contenedores se realiza gracias a Apache Kafka. Este sistema se hospeda en dos contenedores, uno que aloja el broker de Kafka encargado del almacenamiento de los mensajes y la configuración de tópicos, y otro contenedor dispuesto para Apache Zookeeper, servicio encargado de coordinar los procesos distribuidos para Kafka. Un esquema de la comunicación del productor con el consumidor mediante los tópicos se puede ver en la siguiente figura:

![](https://github.com/Nimbasa0/Prototipo-sistema-de-deteccion/images/esquema_transmision.jpg)

####Etapa de transmisión de video en vivo

Una de las formas de visualización de los resultados obtenidos mediante la detección de objetos es la de un video en vivo que muestra las imágenes originales de las cámaras con las cajas de detección aplicadas encima, esto se obtiene gracias al sistema compuesto por un total de dos contenedores. El primer contenedor se encarga de ejecutar el algoritmo de python ***transmision.py***, este código se encarga de consumir los objetos JSON desde los tres tópicos de Kafka que contienen las imágenes resultado de la aplicación del modelo YOLO para cada cámara, posteriormente se encarga de desempaquetar y reconstruir dichas imagenes para posteriormente enviarlas hacia un servidor RTSP que está hospedado en el segundo contenedor de este sistema. Esta transmisión RTSP es en vivo y es accesible mediante su dirección o por otra parte, mediante un dashboard ya configurado en Grafana. Un esquema de esta etapa se ve a continuación:

![](https://github.com/Nimbasa0/Prototipo-sistema-de-deteccion/images/esquema_vivo.jpg)

####Etapa de alertas de detección

La otra forma de visualizar resultados con este sistema es mediante un registro de detecciones que va especificando los objetos detectados en las imagenes de las cámaras en un periodo de tiempo definido por el usuario. Para lgorar esto, la etapa de alertas de detección se compone de dos contenedores, uno encargado de ejecutar el algoritmo de Python ***alertas.py***, código que se encarga de la obtención de los objetos JSON que contaban con los resultados de detección escritos desde el tópico de Kafka referido a las alertas, una vez el JSON es consumido, el algoritmo se encarga de extraer los objetos detectados para cada imágen respectiva de cada cámara para luego generar un mensaje que entrega los objetos detectados especificando el instante de tiempo de la imagen y la cámara a la cual corresponde, dicho mensaje es enviado y almacenado en una base de datos de Influxdb, servicio hospedado en el segundo contenedor de esta etapa. El  registro de estos mensajes es visible a través de un dashboard de Grafana ya configurado para consumir los datos guardados en Influxdb.

####Etapa de visualización
Como se mencionó anteriormente, tanto la visualización de la transmisión RTSP en vivo de las imágenes con cajas de detección como el registro de alertas puede ser visto a través de dashboards ya configurados en Grafana. Para la realización de este servicio se utilizaron dos contenedores, en uno se hospeda el software de Grafana, mientras que el otro es un plugin que necesita Grafana para poder reproducir videos.



