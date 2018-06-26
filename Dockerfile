FROM python:2.7

COPY requirements.txt requirements.txt
COPY stats.py stats.py

RUN pip install -r requirements.txt

EXPOSE 8080
ENTRYPOINT ["python2", "stats.py", "8080"]
