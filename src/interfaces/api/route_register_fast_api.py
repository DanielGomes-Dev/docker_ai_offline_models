import json
import traceback

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from src.application.contracts.base_routes import RouteRegisterInterface


class RouteRegisterFastApi(RouteRegisterInterface):
    def __init__(self):
        self.router = APIRouter()

    def execute(self, prefix, route, method, callback):
        full_route = f"{prefix}{route}"

        if method == "POST":
            print(f"Registrando Rota POST: {full_route}")

            @self.router.post(full_route)
            async def execute_post(request: Request):
                try:
                    body = await request.json()
                    return await callback(body)
                except HTTPException:
                    raise
                except Exception as e:  # noqa: BLE001
                    print(f"❌ Erro na rota {full_route}")
                    print(traceback.format_exc())
                    raise HTTPException(status_code=500, detail=str(e))

        elif method == "POST_FILE":
            print(f"Registrando Rota POST FILE: {full_route}")

            @self.router.post(full_route)
            async def execute_post_file(request: Request, file: UploadFile = File(...)):
                try:
                    form = await request.form()
                    payload = {
                        "file": file,
                        "body": json.loads(form.get("payload") or "{}"),
                    }
                    return await callback(payload)
                except HTTPException:
                    raise
                except Exception as e:  # noqa: BLE001
                    print(f"❌ Erro na rota {full_route}")
                    print(traceback.format_exc())
                    raise HTTPException(status_code=500, detail=str(e))

        else:
            raise ValueError(f"Método HTTP não suportado: {method}")
