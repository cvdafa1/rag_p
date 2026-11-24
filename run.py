import uvicorn
from app.config import config

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=config.service.host,
        port=config.service.port,
        reload=True,
    )
    