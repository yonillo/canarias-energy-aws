# ⚡ Canarias Energy & Calima Real-Time Monitor (AWS Serverless Data Lake)

![AWS](https://img.shields.io/badge/AWS-Serverless-orange?style=for-the-badge&logo=amazon-aws&logoColor=white)
![Terraform](https://img.shields.io/badge/Terraform-Infrastructure%20as%20Code-purple?style=for-the-badge&logo=terraform&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12%2F3.13-blue?style=for-the-badge&logo=python&logoColor=white)
![Architecture](https://img.shields.io/badge/Architecture-Event--Driven-success?style=for-the-badge)

Plataforma desatendida y nativa en la nube diseñada para monitorizar en tiempo real el impacto de fenómenos meteorológicos extremos (como la **calima** y variaciones en los **alisios**) sobre los 6 sistemas eléctricos aislados de las Islas Canarias. 

El proyecto implementa una arquitectura **Serverless Event-Driven** combinada con un **Data Lake Medallion**, desplegada íntegramente mediante **Infraestructura como Código (IaC)**.

---

## 🏛️ Arquitectura del Sistema

El pipeline se ejecuta de forma automática cada 15 minutos sin requerir servidores ociosos (*Pay-as-you-go* absoluto):

```mermaid
graph TD
    A[Amazon EventBridge Scheduler] -->|Dispara cada 15m| B[AWS Lambda Ingestion Engine]
    B -->|Consulta APIs Externas| C1[Open-Meteo Air Quality / CAMS<br/>PM10, PM2.5, Polvo Sahariano]
    B -->|Consulta APIs Externas| C2[Open-Meteo Forecast<br/>Viento 80m & Radiación Solar]
    B -->|Consulta Oficial| C3[Red Eléctrica / REData<br/>Mix Energético Insular]
    B -->|Escribe Estado Actual| D[(Amazon DynamoDB<br/>Hot Path / Baja Latencia)]
    B -->|Escribe Archivo NDJSON| E[(Amazon S3 Data Lake<br/>Cold Path / Particionado Hive)]
    E -->|Consulta SQL Analítica| F[Amazon Athena & AWS Glue]
