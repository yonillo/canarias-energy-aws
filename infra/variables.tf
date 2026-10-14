variable "aws_region" {
  description = "Región de AWS donde desplegar la infraestructura (Irlanda por cercanía y disponibilidad)"
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Entorno de despliegue (dev, prod)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Nombre base del proyecto para etiquetado y recursos"
  type        = string
  default     = "canarias-energy-calima"
}
