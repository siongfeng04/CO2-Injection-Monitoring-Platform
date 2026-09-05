from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv(
	"DATABASE_URL",
	"postgresql+psycopg2://postgres:<your_password>@localhost:5432/co2_injection_db",
)
SECRET_KEY = os.getenv("SECRET_KEY", "secret")
ENV = os.getenv("ENV", "production")
