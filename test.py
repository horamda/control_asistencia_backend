from dotenv import load_dotenv

from db import DatabaseConfigError, get_raw_connection, init_orm

load_dotenv()

try:
    init_orm()
    cnx = get_raw_connection()
    print("CONECTO OK")
    cnx.close()
except DatabaseConfigError as e:
    print("ERROR:", e)
except Exception as e:
    print("ERROR:", e)
