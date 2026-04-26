import os
import requests
from kilo.server.auth.jwt import create_access_token

token = create_access_token({
    "sub": "dba4cea8-bf3a-4468-9b67-67262d642711",
    "email": "switch_test@example.com",
    "role": "USER"
})
print("Token:", token)

res = requests.get(
    "http://localhost:8080/api/auth/me",
    headers={"Authorization": f"Bearer {token}"}
)
print("Status:", res.status_code)
print("Response text length:", len(res.text))
print("Response:", res.text)
