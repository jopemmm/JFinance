"""
Inicialização do Firebase Admin SDK para o J-Finance.
Carrega credenciais das variáveis de ambiente (nunca de arquivo JSON em produção).
"""

import os
import firebase_admin
from firebase_admin import credentials, firestore, auth


def initialize_firebase():
    """
    Inicializa o Firebase Admin SDK usando variáveis de ambiente.
    Funciona tanto em desenvolvimento local quanto no Railway.
    """
    # Verifica se já está inicializado
    if firebase_admin._apps:
        return firestore.client(), auth

    # Carrega as credenciais das variáveis de ambiente
    project_id = os.getenv("FIREBASE_PROJECT_ID")
    private_key_id = os.getenv("FIREBASE_PRIVATE_KEY_ID")
    private_key = os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n")
    client_email = os.getenv("FIREBASE_CLIENT_EMAIL")
    client_id = os.getenv("FIREBASE_CLIENT_ID")

    # Verifica se todas as credenciais estão presentes
    credenciais_faltantes = []
    if not project_id:
        credenciais_faltantes.append("FIREBASE_PROJECT_ID")
    if not private_key_id:
        credenciais_faltantes.append("FIREBASE_PRIVATE_KEY_ID")
    if not private_key or private_key == "\n":
        credenciais_faltantes.append("FIREBASE_PRIVATE_KEY")
    if not client_email:
        credenciais_faltantes.append("FIREBASE_CLIENT_EMAIL")
    if not client_id:
        credenciais_faltantes.append("FIREBASE_CLIENT_ID")

    if credenciais_faltantes:
        print("=" * 60)
        print("ERRO: Credenciais do Firebase não configuradas!")
        print("=" * 60)
        print("\nAs seguintes variáveis de ambiente estão faltando:")
        for cred in credenciais_faltantes:
            print(f"  - {cred}")
        print("\nConfigure essas variáveis no arquivo .env (local) ou no")
        print("dashboard do Railway (produção).")
        print("=" * 60)
        raise ValueError(
            f"Credenciais do Firebase faltando: {', '.join(credenciais_faltantes)}"
        )

    # Cria o objeto de credenciais
    cred_dict = {
        "type": "service_account",
        "project_id": project_id,
        "private_key_id": private_key_id,
        "private_key": private_key,
        "client_email": client_email,
        "client_id": client_id,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{client_email.replace('@', '%40')}",
        "universe_domain": "googleapis.com"
    }

    # Inicializa o Firebase
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)

    print("Firebase Admin SDK inicializado com sucesso!")

    return firestore.client(), auth


# Inicializa e exporta os clientes
db, auth_client = initialize_firebase()
