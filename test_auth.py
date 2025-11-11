from authentication import verify_user

# Test authentication with username "Alex" and password "ajm2l2"
username = "Alex"
password = "ajm2l2"

print(f"Testando autenticação para usuário: {username}")
result = verify_user(username, password)

if result:
    print("✅ Autenticação bem-sucedida!")
    print(f"Dados do usuário: {result}")
else:
    print("❌ Falha na autenticação. Verifique o usuário e senha.")
