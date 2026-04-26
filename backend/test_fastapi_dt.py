from fastapi.encoders import jsonable_encoder
from datetime import datetime
print(jsonable_encoder({"created_at": datetime.now()}))
