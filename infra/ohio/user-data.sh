#!/bin/bash
# User data das instancias ECS (executado uma vez, no primeiro boot).
# Diz ao agente do ECS em qual cluster registrar a instancia; sem isso
# ela entraria no cluster "default".
echo "ECS_CLUSTER=__PREFIXO__-cluster" >> /etc/ecs/ecs.config
