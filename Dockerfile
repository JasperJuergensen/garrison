FROM python:3.10-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY ./garrison/ ./garrison/

COPY ./entrypoint.sh /entrypoint.sh
CMD "/entrypoint.sh"
