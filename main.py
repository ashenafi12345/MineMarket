from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from database import Base, engine
from routers import auth,products,users


Base.metadata.create_all(bind=engine)

app = FastAPI()

app.include_router(auth.router)
app.include_router(products.router)                 
app.include_router(users.router)                 



# Serve uploaded files
app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads"
)
