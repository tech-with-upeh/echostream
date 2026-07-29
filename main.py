from fastapi import FastAPI
from app.database import engine, Base
from app.routers import auth

# Automatically migrate tables on local start
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Production Ready Modular API")

# Include the partitioned router paths
app.include_router(auth.router)

@app.get("/")
def health_check():
    return {"status": "healthy"}
