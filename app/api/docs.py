from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, ORJSONResponse

from app.cw.config import config

router = APIRouter()


@router.get("/redoc", response_class=HTMLResponse)
def custom_redoc():
    if config.get("DEBUG").lower() != "true":  # type: ignore
        return HTMLResponse(status_code=404, content="Not found")

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WalletCast Demo API - ReDoc</title>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
        <style>
            body {
                margin: 0;
                padding: 0;
            }
        </style>
    </head>
    <body>
        <redoc spec-url="./openapi.json"></redoc>
        <script src="https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js"></script>
    </body>
    </html>
    """
    return HTMLResponse(html_content)


@router.get("/docs", response_class=HTMLResponse)
def custom_docs():
    if config.get("DEBUG").lower() != "true":  # type: ignore
        return HTMLResponse(status_code=404, content="Not found")

    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>WalletCast Demo API - Swagger UI</title>
        <meta charset="utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
        <style>
            body {
                margin: 0;
                padding: 0;
            }
        </style>
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
        <script>
            window.onload = function() {
                window.ui = SwaggerUIBundle({
                    url: './openapi.json',
                    dom_id: '#swagger-ui',
                    deepLinking: true,
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIStandalonePreset
                    ],
                    plugins: [
                        SwaggerUIBundle.plugins.DownloadUrl
                    ],
                    layout: "StandaloneLayout"
                });
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(html_content)


@router.get("/openapi.json", response_class=ORJSONResponse)
def custom_openapi(request: Request):
    if config.get("DEBUG").lower() != "true":  # type: ignore
        return HTMLResponse(status_code=404, content="Not found")

    return ORJSONResponse(content=request.app.openapi())
