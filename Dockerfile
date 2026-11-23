FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg openssl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY ohrwurm ohrwurm
ENV DATEN=/daten MUSIK=/musik LAND=de
ENTRYPOINT ["python3", "-m", "ohrwurm"]
CMD ["--help"]
