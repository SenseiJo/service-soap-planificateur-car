# Dockerfile pour le service SOAP Python
FROM python:3.11-slim

WORKDIR /app

# Installer les dépendances système pour lxml
RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copier les fichiers de dépendances
COPY requirements.txt ./

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY main.py ./

# Exposer le port
EXPOSE 8000

# Démarrer le service
CMD ["python", "main.py"]
