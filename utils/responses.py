def ok(data=None, mensaje="OK"):
    return {
        "success": True,
        "mensaje": mensaje,
        "data": data
    }, 200

def error(mensaje="Error", code=400):
    return {
        "success": False,
        "mensaje": mensaje
    }, code
