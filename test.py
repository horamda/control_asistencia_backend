import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

try:
    cnx = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        connection_timeout=int(os.getenv("DB_CONN_TIMEOUT", 5))
    )
    print("CONECTO OK")
except Exception as e:
    print("ERROR:", e)
